# Remote Jobs API

**Live, normalized remote-job data across 5 boards — one clean endpoint, one schema.**

Stop scraping Remotive / RemoteOK / We Work Remotely / Jobicy / Hacker News
yourself. This API pulls them, normalizes every listing into a single
schema, dedupes, and hands you structured JSON (or CSV) — with an optional
**0-100 skill fit-score** for ranking.

Built for:
- Job boards & aggregator sites
- Recruiter and ATS tooling
- Lead-gen and market research
- **AI agents** that need structured job data in one call

## Why it's different
- **One schema, every board.** No per-board adapters on your side.
- **No session scraping.** Reads public job-board endpoints — your data never
  leaves their servers, no browser, no account.
- **Self-hostable.** Stdlib-only Python (zero dependencies). Run it on a
  laptop, a $5 VPS, or containerize it with the included Dockerfile.
- **Deterministic fit scoring.** No hidden LLM, no black box — reproducible
  ranking you can reason about and unit-test.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Status + live job count |
| GET | `/v1/jobs/sources` | Available boards |
| GET | `/v1/jobs` | Normalized job listings |

### GET /v1/jobs

Query params:

| Param | Type | Notes |
|-------|------|-------|
| `skills` | string | Comma-separated keywords → adds `fit_score`, ranks best-first |
| `source` | string | `remotive` / `remoteok` / `jobicy` / `wwr` / `hn` |
| `limit` | int | 1-500 (default 50) |
| `min_score` | int | 0-100, filter by fit (needs `skills`) |
| `format` | string | `json` (default) or `csv` |

### Example

```bash
curl "https://<your-host>/v1/jobs?skills=python,backend,api&limit=3"
```

```json
{
  "count": 3,
  "generated_at": 1790433192,
  "jobs": [
    {
      "id": "94516b10164d3c70",
      "title": "Senior Backend Developer (Python)",
      "company": "Proxify AB",
      "url": "https://weworkremotely.com/remote-jobs/proxify-ab-senior-backend-developer-python-10",
      "location": "Anywhere in the World",
      "category": "Back-End Programming",
      "source": "wwr",
      "published": "Tue, 15 Sep 2026 09:01:36 +0000",
      "fit_score": 80
    }
  ]
}
```

## Run it yourself

Zero runtime dependencies — it's pure Python stdlib.

**Option A — CLI (query the feed directly, no server needed):**

```bash
pip install remote-jobs-api
remote-jobs-api --skills python,api --limit 5
remote-jobs-api --source wwr --format csv
remote-jobs-api --help
```

**Option B — HTTP API server (self-host):**

```bash
pip install remote-jobs-api
remote-jobs-api --serve --port 8321        # or: python -m remote_jobs_api.server
```

Or from source / Docker:

```bash
git clone https://github.com/earnnova-dev/remote-jobs-api
cd remote-jobs-api
python3 -m remote_jobs_api.server          # listens on :8321
```

```bash
docker build -t remote-jobs-api .
docker run -p 8321:8321 remote-jobs-api
```

Env vars:
- `PORT` (default `8321`)
- `RJA_CACHE_TTL` (default `300` s) — how long to cache upstream fetches

## Testing

Offline unit tests (no network): `python -m pytest`.

## Pricing (indicative, for a hosted tier)

| Plan | Price | Includes |
|------|-------|----------|
| **Free** | $0 | 100 calls/mo, all boards, 50 results/req |
| **Pro** | $19/mo | 10k calls/mo, CSV, min_score, higher limits |
| **Team** | $49/mo | 100k calls/mo, SLA, webhooks (soon) |

> Self-hosted = free, MIT. The paid tier is the hosted, always-on,
> high-rate-limit version — the same engine, managed for you.

## Related product

Want alerts instead of a data endpoint? **GigWatch** is a self-hosted gig watcher
that monitors the same live feeds, filters by your skills, and pings you
(console, email, or Slack) only when a new matching gig appears.

- Repo: https://github.com/earnnova-dev/gigwatch
- Install: `pip install gigwatch-nova`

## License

MIT. See [LICENSE](LICENSE).

## Data & compliance

This API only reads public, no-auth job-board endpoints and returns data
exactly as those boards publish it. It does not store your personal data,
does not scrape authenticated sessions, and does not resell any board's
proprietary content beyond what is publicly viewable.
