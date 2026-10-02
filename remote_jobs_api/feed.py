"""Remote-Jobs Data API — normalized feed layer.

Stdlib-only. Pulls live remote-job listings from public job-board endpoints
that require no auth, normalizes them into ONE schema, and exposes them for
the HTTP API. This is the same feed engine as GigWatch, repackaged as a data
product.

Public sources (no key, no account):
  - remotive   https://remotive.com/api/remote-jobs
  - remoteok   https://remoteok.com/api
  - jobicy     https://jobicy.com/api/v2/remote-jobs
  - wwr        https://weworkremotely.com/remote-jobs.rss
  - hn         HN "Who is Hiring?" (Algolia, monthly megathread)
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict, field
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (compatible; RemoteJobsAPI/1.0)"

SOURCES = ["remotive", "remoteok", "jobicy", "wwr", "hn"]


@dataclass
class Job:
    id: str
    title: str
    company: str = ""
    url: str = ""
    location: str = ""
    salary: str = ""
    category: str = ""
    tags: List[str] = field(default_factory=list)
    published: str = ""
    source: str = ""
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # keep the public schema lean and stable
        sal = _salary_struct(d["salary"])
        return {
            "id": d["id"],
            "title": d["title"],
            "company": d["company"],
            "url": d["url"],
            "location": d["location"],
            "salary": d["salary"],
            # structured salary (machine-filterable). null when the board gives none.
            "salary_min": sal["min"],
            "salary_max": sal["max"],
            "salary_currency": sal["currency"],
            "salary_period": sal["period"],
            "category": d["category"],
            "tags": d["tags"],
            "published": _canonical_published(d["published"]),
            "source": d["source"],
            "description": d["description"][:500],
        }


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _clean(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _repair_mojibake(text: str) -> str:
    """Repair common UTF-8-as-Latin-1 text returned by legacy feeds."""
    if not text:
        return ""
    try:
        repaired = text.encode("latin-1").decode("utf-8")
        # Only accept the repair when it removes mojibake markers.
        if repaired != text and sum(text.count(c) for c in "ÃÂ�") > 0:
            return repaired
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return text


def _h(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:16]


_SAL_CURRENCY_RE = re.compile(
    r"\b(USD|EUR|GBP|CAD|AUD|NZD|CHF|CZK|PLN|INR|SEK|NOK|DKK|JPY|BRL|MXN|SGD|HKD|ZAR|AED|SAR|ILS|PHP|IDR|THB|KRW|CNY|VND)\b",
    re.I,
)


def parse_salary(text: str) -> Optional[Dict[str, Any]]:
    """Parse a messy salary string into structured fields.

    Returns {min, max, currency, period} (any field may be None) or None if
    the string carries no numeric salary. Handles the formats the boards
    actually emit:
        'USD 220,000-260,000 / yearly'
        '$90k - $105k'
        'CZK 700,600-700,600 / yearly'
        '130,000-170,000 / yearly'   (no currency)
        '$80,000-$250,000'
        'USD 84-106 / hourly'
    """
    if not text or not text.strip():
        return None
    t = text.strip()
    tl = t.lower()

    currency = None
    m = _SAL_CURRENCY_RE.search(t)
    if m:
        currency = m.group(1).upper()
    elif "$" in t:
        currency = "USD"

    period = None
    if re.search(r"\bper\s*(year|annum)\b|/\s*(year|annum|yr|yrs)\b|\b(yearly|annually|annual)\b|/y\b|/yr\b", tl):
        period = "year"
    elif re.search(r"\bper\s*month\b|/\s*(month|mo|mos|m)\b|\bmonthly\b|/m\b", tl):
        period = "month"
    elif re.search(r"\bper\s*hour\b|/\s*(hour|hr|h)\b|\bhourly\b|/h\b", tl):
        period = "hour"
    elif re.search(r"\bper\s*week\b|/\s*(week|wk|wks)\b|\bweekly\b", tl):
        period = "week"
    elif re.search(r"\bper\s*day\b|/\s*(day|d)\b|\bdaily\b", tl):
        period = "day"

    # numbers with optional 'k' multiplier
    nums = re.findall(r"(\d[\d,]*)(k)?", t, re.I)
    vals = []
    for n, k in nums:
        try:
            v = float(n.replace(",", ""))
        except ValueError:
            continue
        if k:
            v *= 1000.0
        vals.append(v)
    if not vals:
        return None
    lo, hi = min(vals), max(vals)
    # clean float->int when whole
    def _num(x):
        return int(x) if float(x).is_integer() else x
    return {"min": _num(lo), "max": _num(hi), "currency": currency, "period": period}


def _salary_struct(salary_text: str) -> Dict[str, Any]:
    """Convenience: parse_salary + stable key set (all four keys always present)."""
    p = parse_salary(salary_text) or {}
    return {
        "min": p.get("min"),
        "max": p.get("max"),
        "currency": p.get("currency"),
        "period": p.get("period"),
    }


def fetch_remotive(limit: Optional[int] = None) -> List[Job]:
    data = json.loads(_get("https://remotive.com/api/remote-jobs").decode("utf-8"))
    out = []
    for raw in data.get("jobs", []):
        out.append(Job(
            id=str(raw.get("id")),
            title=_clean(raw.get("title", "")),
            company=_clean(raw.get("company_name", "")),
            url=raw.get("url", ""),
            location=_clean(raw.get("candidate_required_location", "")),
            salary=_clean(raw.get("salary", "")),
            category=_clean(raw.get("category", "")),
            tags=[_clean(t) for t in raw.get("tags", []) if t],
            published=raw.get("publication_date", ""),
            source="remotive",
            description=_clean(raw.get("description", "")),
        ))
    return out[:limit] if limit else out


def fetch_remoteok(limit: Optional[int] = None) -> List[Job]:
    data = json.loads(_get("https://remoteok.com/api").decode("utf-8", "replace"))
    out = []
    for raw in data:
        if not isinstance(raw, dict) or not raw.get("position"):
            continue
        lo, hi = raw.get("salary_min"), raw.get("salary_max")
        salary = ""
        if lo and hi:
            salary = f"${int(lo):,}-${int(hi):,}"
        elif lo or hi:
            salary = f"${int(lo or hi):,}"
        out.append(Job(
            id=str(raw.get("id") or _h(raw.get("url", ""))),
            title=_repair_mojibake(_clean(raw.get("position", ""))),
            company=_repair_mojibake(_clean(raw.get("company", ""))),
            url=raw.get("url", ""),
            location=_repair_mojibake(_clean(raw.get("location", ""))),
            salary=salary,
            tags=[_clean(t) for t in raw.get("tags", []) if t],
            published=raw.get("date", ""),
            source="remoteok",
            description=_clean(raw.get("description", "")),
        ))
    out = [j for j in out if j.id and j.title]
    return out[:limit] if limit else out


def fetch_jobicy(limit: Optional[int] = None) -> List[Job]:
    n = limit or 50
    data = json.loads(_get(f"https://jobicy.com/api/v2/remote-jobs?count={n}").decode("utf-8", "replace"))
    out = []
    for raw in data.get("jobs", []):
        if not isinstance(raw, dict):
            continue
        title = _clean(raw.get("jobTitle") or "")
        if not title:
            continue
        tags = []
        for k in ("jobIndustry", "jobType"):
            v = raw.get(k) or []
            if isinstance(v, list):
                tags.extend(str(t) for t in v)
        loc = " / ".join(p for p in (raw.get("jobGeo") or "", raw.get("jobLevel") or "") if p)
        sal = ""
        sal_min = raw.get("salaryMin")
        sal_max = raw.get("salaryMax")
        currency = str(raw.get("salaryCurrency") or "").strip()
        period = str(raw.get("salaryPeriod") or "").strip().strip("/").strip()
        try:
            if sal_min is not None and sal_max is not None:
                sal = f"{currency} {int(float(sal_min)):,}-{int(float(sal_max)):,}".strip()
            elif sal_min is not None or sal_max is not None:
                sal = f"{currency} {int(float(sal_min if sal_min is not None else sal_max)):,}".strip()
        except (TypeError, ValueError):
            sal = _clean(str(raw.get("salary") or ""))
        if period:
            sal = f"{sal} / {period}" if sal else period
        out.append(Job(
            id=str(raw.get("id") or _h(raw.get("url", ""))),
            title=title,
            company=_clean(raw.get("companyName") or ""),
            url=raw.get("url", ""),
            location=loc,
            salary=sal,
            tags=tags,
            published=raw.get("pubDate") or "",
            source="jobicy",
            description=_clean((raw.get("jobExcerpt") or "")[:300]),
        ))
    out = [j for j in out if j.id and j.title]
    return out[:limit] if limit else out


def fetch_wwr(limit: Optional[int] = None) -> List[Job]:
    root = ET.fromstring(_get("https://weworkremotely.com/remote-jobs.rss").decode("utf-8", "replace"))
    out = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        company = ""
        if ": " in title:
            company, title = (p.strip() for p in title.split(": ", 1))
        out.append(Job(
            id=_h(link or title),
            title=title,
            company=company,
            url=link,
            category=_clean(it.findtext("category") or ""),
            location=_clean(it.findtext("region") or ""),
            published=(it.findtext("pubDate") or "").strip(),
            source="wwr",
            description=_clean(it.findtext("description") or ""),
        ))
    out = [j for j in out if j.id and j.title]
    return out[:limit] if limit else out


def fetch_hn(limit: Optional[int] = None) -> List[Job]:
    import time
    now = int(time.time())
    window = now - 35 * 86400
    res = json.loads(_get("https://hn.algolia.com/api/v1/search?%s" % urllib.parse.urlencode({
        "query": "who is hiring", "tags": "story",
        "numericFilters": f"created_at_i>={window}", "hitsPerPage": 20,
    })).decode("utf-8"))
    stories = []
    for h in res.get("hits", []):
        t = (h.get("title") or "").lower()
        if "who is hiring" not in t or "analysis" in t:
            continue
        if "who wants to be hired" in t or "show hn" in t:
            continue
        stories.append(h)
    out = []
    for story in stories:
        item = json.loads(_get(f"https://hn.algolia.com/api/v1/items/{story.get('objectID')}").decode("utf-8"))
        for ch in item.get("children", [])[:100]:
            cid = ch.get("id")
            base = f"https://news.ycombinator.com/item?id={cid}"
            raw = ch.get("text") or ""
            if not raw:
                continue
            # split on the RAW lines first (before any whitespace collapsing),
            # then clean each line individually.
            for line in raw.splitlines():
                s = _clean(line).lstrip("-*• \t").strip()
                if not s or len(s) > 120:
                    continue  # multi-sentence blocks are not single-job lines
                title = company = ""
                if "|" in s:
                    parts = [p.strip() for p in s.split("|")]
                    if len(parts) >= 2:
                        company, title = parts[0], parts[1]
                else:
                    m = re.match(r"^([A-Z][A-Za-z0-9&.'\-]{0,60}?)\s*(?:—|–|:|-)\s+(.{3,120})$", s)
                    if m:
                        company, title = m.group(1), m.group(2)
                if not title or len(title) < 3 or len(title) > 100:
                    continue
                if not company or company.lower() in ("http", "https", "i", "we", "a", "the"):
                    continue
                if "http" in title.lower():
                    continue  # title must not be a URL
                out.append(Job(
                    id=_h(f"{cid}|{title}"),
                    title=title, company=company, url=base,
                    source="hn", description=s[:300],
                ))
    out = [j for j in out if j.id and j.title]
    return out[:limit] if limit else out


_FETCHERS = {
    "remotive": fetch_remotive,
    "remoteok": fetch_remoteok,
    "jobicy": fetch_jobicy,
    "wwr": fetch_wwr,
    "hn": fetch_hn,
}


def _published_key(value: str) -> float:
    """Parse ISO-8601 and RFC-2822 feed dates into one sortable timestamp."""
    if not value:
        return 0.0
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _canonical_published(value: str) -> str:
    """Normalize a source's native date string into ONE canonical ISO-8601 UTC form.

    Boards return three different date formats (ISO-8601 from remotive/remoteok,
    RFC-2822 from We Work Remotely, blank from HN). The product contract is a
    single clean schema, so the public ``published`` field is normalized to
    ``YYYY-MM-DDTHH:MM:SS+00:00`` (UTC) when the timestamp can be parsed, and an
    empty string when the source provides none (or an unparseable one).
    """
    if not value or not value.strip():
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return ""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def collect(sources: Optional[List[str]] = None, limit: Optional[int] = None,
            per_source_limit: int = 100) -> List[Job]:
    """Fetch from the given sources (default: all), dedupe by URL, return flat list."""
    sources = sources or SOURCES
    seen: set = set()
    out: List[Job] = []
    for src in sources:
        fn = _FETCHERS.get(src)
        if not fn:
            continue
        try:
            for j in fn(limit=per_source_limit):
                key = j.url or j.id
                if key in seen:
                    continue
                seen.add(key)
                out.append(j)
        except Exception:
            # a flaky source should not break the whole API
            continue
    # sort by actual timestamp, because sources use ISO-8601, RFC-2822, or blank dates
    out.sort(key=lambda j: _published_key(j.published), reverse=True)
    return out[:limit] if limit else out


def _match_score(job: Job, skills: List[str]) -> int:
    """Deterministic 0-100 fit score: title hits weigh more than body hits."""
    if not skills:
        return 50
    title = job.title.lower()
    hay = job.haystack if hasattr(job, "haystack") else " ".join(
        [job.title, job.company, job.category, job.location, job.salary,
         " ".join(job.tags), job.description]).lower()
    score = 0.0
    for s in skills:
        s = s.lower().strip()
        if not s:
            continue
        if s in title:
            score += 40
        elif s in hay:
            score += 15
    return int(max(0, min(100, score)))


def filter_and_rank(jobs: List[Job], skills: Optional[List[str]] = None,
                    remote_only: bool = False, source: Optional[str] = None,
                    min_score: Optional[int] = None,
                    min_salary: Optional[float] = None) -> List[Dict[str, Any]]:
    out = []
    seen = set()
    has_skills = bool(skills)
    for j in jobs:
        if source and j.source != source:
            continue
        # Dedupe: same title + company + source is one job (boards repost).
        key = (j.title.lower(), j.company.lower(), j.source)
        if key in seen:
            continue
        seen.add(key)
        d = j.to_dict()
        # fit_score only exists when skills are supplied (matches the docs).
        # Without skills there is no notion of fit, so we emit null, not a fake 50.
        d["fit_score"] = _match_score(j, skills) if has_skills else None
        if min_score is not None and (d["fit_score"] is None or d["fit_score"] < min_score):
            continue
        # min_salary: keep only jobs whose parsed FLOOR (salary_min) meets it.
        # This matches the documented contract ("Filter on the floor with
        # ?min_salary="). Using the top of range (salary_max) would keep jobs
        # whose minimum pay is below the requested floor (e.g. "$90k-$120k"
        # wrongly surviving min_salary=100k). Jobs with no parseable salary are
        # excluded when the filter is active.
        if min_salary is not None:
            floor = d.get("salary_min")
            if floor is None or floor < min_salary:
                continue
        out.append(d)
    # best fit first (jobs without skills sort by fit=0), then newest
    out.sort(key=lambda d: ((d["fit_score"] or 0), d["published"]), reverse=True)
    return out
