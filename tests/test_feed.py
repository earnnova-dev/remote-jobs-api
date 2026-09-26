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
from remote_jobs_api.feed import Job, _clean, _h, _match_score, filter_and_rank, SOURCES


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


# --- sources registry ----------------------------------------------------

def test_sources_known():
    assert set(SOURCES) == {"remotive", "remoteok", "jobicy", "wwr", "hn"}


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
