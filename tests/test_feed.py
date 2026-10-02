"""Offline unit tests — no network.

Covers the normalization helpers, the fit-score, filter_and_rank, and the
CLI argument parsing, using in-memory fixtures.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout

import pytest

from remote_jobs_api import feed
from remote_jobs_api.feed import Job, _clean, _h, _match_score, filter_and_rank, SOURCES, _canonical_published


# --- helpers -------------------------------------------------------------

def _job(**kw) -> Job:
    base = dict(id="x", title="Senior Backend Developer", company="Acme",
                url="https://example.com/j/x", source="test")
    base.update(kw)
    return Job(**base)


# --- _clean --------------------------------------------------------------

def test_clean_strips_tags_and_whitespace():
    assert _clean("<b>  Hello </b>\n  World ") == "Hello World"


def test_clean_unescapes_entities():
    assert _clean("A &amp; B") == "A & B"


def test_clean_empty():
    assert _clean("") == ""
    assert _clean(None) == ""


# --- _h deterministic hash -----------------------------------------------

def test_hash_stable_and_short():
    a = _h("hello")
    b = _h("hello")
    assert a == b
    assert len(a) == 16


def test_hash_differs():
    assert _h("a") != _h("b")


# --- Job.to_dict lean schema --------------------------------------------

def test_to_dict_has_core_fields():
    d = _job().to_dict()
    for k in ("id", "title", "company", "url", "location", "salary",
              "category", "tags", "published", "source"):
        assert k in d


def test_to_dict_truncates_description():
    d = _job(description="x" * 2000).to_dict()
    assert len(d["description"]) <= 500


# --- _match_score --------------------------------------------------------

def test_score_title_hit_higher_than_body():
    title_hit = _job(title="Python Backend", description="")
    body_hit = _job(title="Designer", description="we use python a lot")
    assert _match_score(title_hit, ["python"]) > _match_score(body_hit, ["python"])


def test_score_bounds():
    assert _match_score(_job(), []) == 50
    assert 0 <= _match_score(_job(title="Python Python Python"), ["python"]) <= 100


def test_score_case_insensitive():
    assert _match_score(_job(title="PYTHON"), ["python"]) >= 40


# --- filter_and_rank -----------------------------------------------------

def test_filter_source():
    a = _job(id="a", source="remotive")
    b = _job(id="b", source="wwr")
    out = filter_and_rank([a, b], source="wwr")
    assert [d["id"] for d in out] == ["b"]


def test_filter_min_score():
    high = _job(id="high", title="Python Senior")
    low = _job(id="low", title="Designer")
    out = filter_and_rank([high, low], skills=["python"], min_score=40)
    assert all(d["fit_score"] >= 40 for d in out)


def test_rank_best_fit_first():
    # A job matching TWO distinct skills outranks one matching only one.
    # (Repeating a single skill does not raise the score — each skill counts once.)
    a = _job(id="a", title="Python Developer")
    b = _job(id="b", title="Senior Python Engineer", tags=["api"])
    out = filter_and_rank([a, b], skills=["python", "api"])
    assert out[0]["id"] == "b"
    assert out[0]["fit_score"] > out[1]["fit_score"]


def test_filter_no_skills_fit_score_null():
    # Without skills there is no notion of fit: fit_score must be null,
    # NOT a fake constant (the old behaviour returned 50 for every job).
    out = filter_and_rank([_job(id="a"), _job(id="b", title="Other")])
    assert out, "expected jobs back"
    assert all(d["fit_score"] is None for d in out)


def test_filter_with_skills_fit_score_int():
    # With skills, fit_score is a real int (not null) and varies by match.
    a = _job(id="a", title="Python Developer")
    b = _job(id="b", title="Growth Designer")
    out = filter_and_rank([a, b], skills=["python"])
    assert all(isinstance(d["fit_score"], int) for d in out)
    by_id = {d["id"]: d["fit_score"] for d in out}
    assert by_id["a"] > by_id["b"]  # title hit > no hit


def test_filter_dedupe_same_title_company_source():
    # Boards repost; identical title+company+source is one job, not two.
    a = _job(id="a", title="Backend Dev", company="Acme", source="wwr")
    b = _job(id="b", title="Backend Dev", company="Acme", source="wwr")
    c = _job(id="c", title="Backend Dev", company="Acme", source="remotive")  # different source = kept
    out = filter_and_rank([a, b, c])
    ids = {d["id"] for d in out}
    assert len(ids) == 2
    # b (exact dup of a within same source) is dropped; c (different source) kept
    assert "b" not in ids
    assert "c" in ids


# --- parse_salary --------------------------------------------------------

def _ps(text: str):
    """parse_salary, asserting a dict (type-narrowed)."""
    p = feed.parse_salary(text)
    assert p is not None, f"expected a parsed salary from {text!r}"
    return p


def test_parse_salary_range_with_currency():
    p = _ps("USD 220,000-260,000 / yearly")
    assert p == {"min": 220000, "max": 260000, "currency": "USD", "period": "year"}


def test_parse_salary_dollar_sign_usd():
    p = _ps("$80,000-$250,000")
    assert p["currency"] == "USD"
    assert p["min"] == 80000 and p["max"] == 250000
    assert p["period"] is None  # unstated


def test_parse_salary_k_suffix():
    p = _ps("$90k - $105k")
    assert p["min"] == 90000 and p["max"] == 105000


def test_parse_salary_no_currency_code():
    # '130,000-170,000 / yearly' has a period but no currency symbol
    p = _ps("130,000-170,000 / yearly")
    assert p["currency"] is None
    assert p["period"] == "year"
    assert p["min"] == 130000 and p["max"] == 170000


def test_parse_salary_hourly():
    p = _ps("USD 84-106 / hourly")
    assert p["period"] == "hour"
    assert p["min"] == 84 and p["max"] == 106


def test_parse_salary_monthly():
    p = _ps("USD 500-600 / monthly")
    assert p["period"] == "month"


def test_parse_salary_empty_or_none():
    assert feed.parse_salary("") is None
    assert feed.parse_salary("No salary listed") is None
    assert feed.parse_salary("   ") is None


# --- min_salary filter ---------------------------------------------------

def test_filter_min_salary_excludes_below_and_missing():
    # Distinct titles so the dedupe (title+company+source) does not collapse them.
    a = _job(id="a", title="Senior Python Engineer", salary="USD 200,000 / yearly")
    b = _job(id="b", title="Junior Python Engineer", salary="USD 50,000 / yearly")
    c = _job(id="c", title="Intern Python Engineer", salary="")  # no parseable salary
    out = filter_and_rank([a, b, c], min_salary=100000)
    ids = {d["id"] for d in out}
    assert "a" in ids      # 200k >= 100k
    assert "b" not in ids  # 50k < 100k
    assert "c" not in ids  # no salary -> excluded when filter active


def test_filter_min_salary_off_returns_all_with_salary():
    # Distinct titles so the dedupe (title+company+source) does not collapse them.
    a = _job(id="a", title="Senior Python Engineer", salary="USD 200,000 / yearly")
    c = _job(id="c", title="Junior Python Engineer", salary="")
    out = filter_and_rank([a, c])  # no min_salary -> keep everything
    assert {d["id"] for d in out} == {"a", "c"}


def test_filter_min_salary_uses_floor_not_top_of_range():
    # The documented contract (README / web.py / index.html) is "Filter on the
    # floor with ?min_salary=". A job whose TOP of range meets the floor but whose
    # FLOOR is below it must be excluded. Regression: the filter used salary_max
    # (top of range), so "USD 90,000-120,000" was wrongly kept at min_salary=100k.
    below = _job(id="below", title="Mid Python Engineer",
                 salary="USD 90,000-120,000 / yearly")   # floor 90k < 100k, top 120k
    above = _job(id="above", title="Staff Python Engineer",
                 salary="USD 110,000-150,000 / yearly")  # floor 110k >= 100k
    exact = _job(id="exact", title="Sr Python Engineer",
                 salary="USD 100,000-140,000 / yearly")  # floor exactly 100k
    out = filter_and_rank([below, above, exact], min_salary=100000)
    ids = {d["id"] for d in out}
    assert "below" not in ids   # floor 90k is below the requested floor -> excluded
    assert "above" in ids       # floor 110k meets it -> kept
    assert "exact" in ids       # floor exactly at it -> kept (>=)


def test_to_dict_exposes_structured_salary():
    d = _job(id="a", salary="EUR 109,000-128,000 / yearly").to_dict()
    assert d["salary_min"] == 109000
    assert d["salary_max"] == 128000
    assert d["salary_currency"] == "EUR"
    assert d["salary_period"] == "year"


# --- sources registry ----------------------------------------------------

def test_sources_known():
    assert set(SOURCES) == {"remotive", "remoteok", "jobicy", "wwr", "hn"}


# --- _canonical_published (schema consistency) ----------------------------

def test_canonical_published_iso_passthrough():
    # ISO-8601 (remotive/remoteok) -> canonical ISO-8601 UTC
    assert _canonical_published("2026-09-15T09:01:36Z") == "2026-09-15T09:01:36+00:00"

def test_canonical_published_rfc2822_normalized():
    # RFC-2822 (We Work Remotely) -> same canonical shape as ISO
    out = _canonical_published("Tue, 15 Sep 2026 09:01:36 +0000")
    assert out == "2026-09-15T09:01:36+00:00"

def test_canonical_published_nonutc_converted():
    # a non-UTC offset is normalized to UTC
    out = _canonical_published("2026-09-15T11:31:36+02:00")
    assert out == "2026-09-15T09:31:36+00:00"

def test_canonical_published_blank_and_garbage():
    assert _canonical_published("") == ""
    assert _canonical_published(None) == ""
    assert _canonical_published("not a date") == ""

def test_to_dict_published_is_single_format():
    # the public schema must expose ONE date format regardless of source
    d_iso = _job(published="2026-09-15T09:01:36Z").to_dict()
    d_rfc = _job(published="Tue, 15 Sep 2026 09:01:36 +0000").to_dict()
    d_blank = _job(published="").to_dict()
    assert d_iso["published"] == d_rfc["published"] == "2026-09-15T09:01:36+00:00"
    assert d_blank["published"] == ""


# --- CLI -----------------------------------------------------------------

def _run_cli(argv):
    from remote_jobs_api import cli
    buf = io.StringIO()
    with redirect_stdout(buf):
        # monkeypatch collect so the CLI stays offline
        orig = feed.collect
        feed.collect = lambda *a, **k: [
            _job(id="a", title="Python Backend", source="remotive"),
            _job(id="b", title="Growth Designer", source="wwr"),
        ]
        try:
            rc = cli.main(argv)
        finally:
            feed.collect = orig
    return rc, buf.getvalue()


def test_cli_json_output():
    rc, out = _run_cli(["--skills", "python", "--limit", "5"])
    assert rc == 0
    data = json.loads(out)
    assert data["count"] == 2
    assert data["jobs"][0]["fit_score"] >= 40


def test_cli_source_filter():
    rc, out = _run_cli(["--source", "wwr"])
    data = json.loads(out)
    assert all(j["source"] == "wwr" for j in data["jobs"])


def test_cli_csv_output():
    rc, out = _run_cli(["--format", "csv"])
    assert rc == 0
    lines = out.strip().splitlines()
    assert lines[0].startswith("id,")
    assert len(lines) == 3  # header + 2 rows


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
