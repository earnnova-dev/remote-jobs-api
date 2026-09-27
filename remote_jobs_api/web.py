"""Server-rendered web UI: landing page + login + account dashboard.

Stdlib-only. The page is a single self-contained HTML document (inline CSS,
no CDN) so the landing page can also be deployed as static on GitHub Pages if
desired, and the dashboard works with zero build step.
"""
from __future__ import annotations

import html
from typing import Optional

# Plan display metadata. Price strings are shown as a fallback; when Stripe
# price IDs are configured, real prices are injected by the caller.
PLANS = [
    {
        "id": "free",
        "name": "Free",
        "monthly": 0,
        "calls": "100 calls / month",
        "tagline": "For trying it out.",
        "cta": "Start free",
    },
    {
        "id": "pro",
        "name": "Pro",
        "monthly": 19,
        "calls": "10,000 calls / month",
        "tagline": "For professionals & small teams.",
        "cta": "Get Pro",
        "highlight": True,
    },
    {
        "id": "team",
        "name": "Team",
        "monthly": 49,
        "calls": "100,000 calls / month",
        "tagline": "For teams & job boards.",
        "cta": "Get Team",
    },
]


def _esc(v) -> str:
    return html.escape(str(v), quote=True)


def _base_css() -> str:
    return """
:root {
  --bg: #0b0f17; --bg2: #0f1522; --card: #121a2b; --border: #1f2a40;
  --text: #e6ebf4; --muted: #93a1b8; --accent: #4f8cff; --accent2: #6aa9ff;
  --good: #35c46a; --bad: #ff6b6b;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       background: var(--bg); color: var(--text); line-height: 1.55; }
a { color: var(--accent2); text-decoration: none; }
a:hover { text-decoration: underline; }
.wrap { max-width: 1040px; margin: 0 auto; padding: 0 20px; }
header { padding: 22px 0; border-bottom: 1px solid var(--border); background: var(--bg2); }
header .row { display: flex; align-items: center; justify-content: space-between; }
.logo { font-weight: 700; font-size: 18px; letter-spacing: .3px; }
.logo span { color: var(--accent2); }
.btn { display: inline-block; background: var(--accent); color: #fff; padding: 10px 18px; border-radius: 8px;
       border: 1px solid var(--accent); font-weight: 600; cursor: pointer; font-size: 14px; }
.btn:hover { background: var(--accent2); text-decoration: none; }
.btn-ghost { background: transparent; border: 1px solid var(--border); color: var(--text); }
.btn-ghost:hover { border-color: var(--accent); background: var(--card); }
.btn-danger { background: transparent; border: 1px solid var(--bad); color: var(--bad); }
.btn-danger:hover { background: rgba(255,107,107,.12); }
.hero { padding: 60px 0 40px; }
.hero h1 { font-size: 40px; margin: 0 0 14px; line-height: 1.15; }
.hero p.sub { font-size: 18px; color: var(--muted); max-width: 640px; margin: 0 0 26px; }
.pill { display: inline-block; background: var(--card); border: 1px solid var(--border); color: var(--muted);
        padding: 4px 12px; border-radius: 999px; font-size: 13px; margin-bottom: 18px; }
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; margin: 30px 0; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 22px; }
.card.hl { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.card h3 { margin: 0 0 4px; font-size: 18px; }
.card .price { font-size: 30px; font-weight: 700; margin: 10px 0 2px; }
.card .price small { font-size: 14px; color: var(--muted); font-weight: 500; }
.card ul { list-style: none; padding: 0; margin: 16px 0; color: var(--muted); font-size: 14px; }
.card ul li { padding: 5px 0; }
.card ul li::before { content: "✓ "; color: var(--good); }
.badge { display: inline-block; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 999px; }
.badge.free { background: #1c2740; color: var(--muted); }
.badge.pro  { background: #12331d; color: var(--good); }
.badge.team { background: #122a44; color: var(--accent2); }
.badge.past_due { background: #3a2c10; color: #ffb454; }
.badge.canceled { background: #3a1414; color: var(--bad); }
form.inline { display: flex; gap: 10px; flex-wrap: wrap; }
input { background: var(--bg2); border: 1px solid var(--border); color: var(--text); padding: 11px 13px;
        border-radius: 8px; font-size: 14px; width: 100%; }
input:focus { outline: none; border-color: var(--accent); }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.form-grid .full { grid-column: 1 / -1; }
label { font-size: 13px; color: var(--muted); display: block; margin-bottom: 6px; }
.error { color: var(--bad); font-size: 14px; margin: 10px 0; }
.success { color: var(--good); font-size: 14px; margin: 10px 0; }
.kv { display: grid; grid-template-columns: 180px 1fr; gap: 10px 16px; font-size: 14px; }
.kv .k { color: var(--muted); }
.code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; background: var(--bg2);
        border: 1px solid var(--border); padding: 3px 8px; border-radius: 6px; word-break: break-all; }
.table { width: 100%; border-collapse: collapse; font-size: 14px; }
.table th, .table td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); }
.table th { color: var(--muted); font-weight: 600; font-size: 13px; }
footer { border-top: 1px solid var(--border); margin-top: 50px; padding: 26px 0; color: var(--muted); font-size: 13px; }
.section { padding: 30px 0; }
.section h2 { font-size: 24px; margin: 0 0 16px; }
@media (max-width: 760px){ .grid, .form-grid { grid-template-columns: 1fr; } .hero h1 { font-size: 32px; } }
"""


def landing(stripe_configured: bool = False, prices: Optional[dict] = None,
            sources=None) -> str:
    prices = prices or {}
    sources = sources or ["remotive", "remoteok", "jobicy", "wwr", "hn"]
    cards = []
    for p in PLANS:
        price = prices.get(p["id"], p["monthly"])
        hl = ' hl' if p.get("highlight") else ""
        if p["id"] == "free":
            cta = f'<a class="btn btn-ghost" href="/register">Create account</a>'
        else:
            cta = f'<a class="btn" href="/checkout/{p["id"]}">Buy {p["name"]}</a>'
        cards.append(f"""
        <div class="card{hl}">
          <h3>{p["name"]}</h3>
          <div class="price">${price}<small> / month</small></div>
          <div style="color:var(--muted);font-size:14px;margin-bottom:6px">{p["tagline"]}</div>
          <ul>
            <li>{p["calls"]}</li>
            <li>All 5 job boards</li>
            <li>Skills fit-scoring</li>
            <li>JSON &amp; CSV export</li>
          </ul>
          {cta}
        </div>""")

    stripe_note = ""
    if not stripe_configured:
        stripe_note = ('<p class="error" style="margin-top:20px;font-size:13px">'
                       'Stripe is not configured yet — checkout will complete once the payment provider is connected.</p>')

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Remote Jobs API — normalized remote job data</title>
<style>{_base_css()}</style></head><body>
<header><div class="wrap row">
  <div class="logo">Remote&nbsp;<span>Jobs&nbsp;API</span></div>
  <div><a class="btn btn-ghost" href="/login">Sign in</a>
       <a class="btn" href="/register" style="margin-left:8px">Get started</a></div>
</div></header>

<div class="wrap">
  <div class="hero">
    <div class="pill">Live · {len(sources)} job boards · 300+ listings updated every 5 minutes</div>
    <h1>One API for all remote jobs.</h1>
    <p class="sub">Normalized listings from Remotive, RemoteOK, Jobicy, We Work Remotely and Hacker News —
       with skills fit-scoring, JSON/CSV export and predictable API keys. Start free, upgrade in one click.</p>
    <a class="btn" href="/register">Create a free account →</a>
  </div>

  <div class="section">
    <h2>Pricing</h2>
    <div class="grid">{''.join(cards)}</div>
    {stripe_note}
  </div>

  <div class="section">
    <h2>How it works</h2>
    <div class="grid">
      <div class="card"><h3>1. Sign up</h3><div style="color:var(--muted);font-size:14px">Create an account with email + password. Your API key is generated instantly.</div></div>
      <div class="card"><h3>2. Call the API</h3><div style="color:var(--muted);font-size:14px"><code>GET /v1/jobs?skills=python,backend</code> with your Bearer key. Filter by source and score.</div></div>
      <div class="card"><h3>3. Scale up</h3><div style="color:var(--muted);font-size:14px">Upgrade with Stripe. Cancel anytime from your dashboard. No lock-in.</div></div>
    </div>
  </div>

  <div class="section">
    <h2>Example</h2>
<pre class="card" style="overflow:auto"><code>curl -H "Authorization: Bearer rja_live_… " \\
  "https://remote-jobs-api.tten.no/v1/jobs?skills=python,api&amp;limit=5"</code></pre>
  </div>
</div>
<footer><div class="wrap">© 2026 Remote Jobs API · <a href="mailto:earnnova@tten.no">earnnova@tten.no</a></div></footer>
</body></html>"""


def auth_page(title: str, error: str = "", ok: str = "") -> str:
    form = f"""
    <form method="post" action="/login">
      <label>Email</label>
      <input type="email" name="email" required autocomplete="email">
      <label>Password</label>
      <input type="password" name="password" required autocomplete="current-password">
      <div style="margin-top:16px"><button class="btn" type="submit">Sign in</button></div>
    </form>
    <p style="margin-top:16px;color:var(--muted);font-size:14px">
      New here? <a href="/register">Create an account</a>.
    </p>"""
    body = f"""
<div class="wrap" style="max-width:440px;padding-top:60px">
  <h1 style="margin:0 0 18px">{title}</h1>
  {f'<p class="error">{error}</p>' if error else ''}
  {f'<p class="success">{ok}</p>' if ok else ''}
  {form}
</div>"""
    return _shell("Sign in", body)


def register_page(title: str = "Create your account", error: str = "", ok: str = "") -> str:
    form = f"""
    <form method="post" action="/register">
      <div class="form-grid">
        <div class="full"><label>Email</label>
          <input type="email" name="email" required autocomplete="email"></div>
        <div class="full"><label>Password (min 8 chars)</label>
          <input type="password" name="password" required minlength="8" autocomplete="new-password"></div>
      </div>
      <div style="margin-top:16px"><button class="btn" type="submit">Create account</button></div>
    </form>
    <p style="margin-top:16px;color:var(--muted);font-size:14px">
      Already have an account? <a href="/login">Sign in</a>.
    </p>"""
    body = f"""
<div class="wrap" style="max-width:440px;padding-top:60px">
  <h1 style="margin:0 0 6px">{title}</h1>
  <p style="color:var(--muted);font-size:14px;margin:0 0 18px">Free plan includes 100 calls/month. Upgrade anytime.</p>
  {f'<p class="error">{error}</p>' if error else ''}
  {f'<p class="success">{ok}</p>' if ok else ''}
  {form}
</div>"""
    return _shell("Sign up", body)


def dashboard(user: dict, prices: Optional[dict] = None) -> str:
    plan = user.get("plan", "free")
    sub = user.get("sub_status", "none")
    email = user.get("email", "")
    api_key = user.get("api_key", "")
    calls = user.get("calls_this_month", 0)
    price = (prices or {}).get(plan, dict((p["id"], p["monthly"]) for p in PLANS).get(plan, 0))

    limit_map = {"free": 100, "pro": 10000, "team": 100000}
    limit = limit_map.get(plan, 0)
    usage_bar = ""
    if limit:
        pct = min(100, round(calls / limit * 100))
        usage_bar = f"""
        <div style="margin:10px 0 4px;height:8px;background:var(--bg2);border:1px solid var(--border);border-radius:6px;overflow:hidden">
          <div style="width:{pct}%;height:100%;background:var(--accent)"></div>
        </div>
        <div style="color:var(--muted);font-size:13px">{calls:,} / {limit:,} calls this month ({pct}%)</div>"""

    # Subscription actions
    sub_actions = ""
    if sub in ("active", "trialing"):
        sub_actions = f"""
        <div style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap">
          <a class="btn btn-ghost" href="/billing/portal">Manage billing</a>
          <a class="btn btn-danger" href="/billing/cancel">Cancel subscription</a>
        </div>"""
    elif sub == "canceled":
        sub_actions = f"""
        <div style="margin-top:14px"><a class="btn" href="/checkout/{plan}">Reactivate</a></div>"""
    else:
        sub_actions = f"""
        <div style="margin-top:14px"><a class="btn" href="/checkout/pro">Upgrade to Pro →</a></div>"""

    body = f"""
<div class="wrap">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:24px">
    <h1 style="margin:0;font-size:24px">Dashboard</h1>
    <form method="post" action="/logout" style="margin:0">
      <button class="btn btn-ghost" type="submit">Sign out</button>
    </form>
  </div>

  <div class="grid" style="grid-template-columns:1.3fr 1fr">
    <div class="card">
      <h3>Subscription</h3>
      <div style="margin:8px 0"><span class="badge {plan}">{plan.upper()}</span>
        <span style="margin-left:10px;color:var(--muted);font-size:14px">{sub.replace('_',' ')}</span></div>
      <div style="font-size:14px;color:var(--muted)">${price} / month · {limit_map.get(plan,0):,} calls</div>
      {sub_actions}
    </div>

    <div class="card">
      <h3>Usage</h3>
      {usage_bar or '<div style="color:var(--muted);font-size:14px">Unlimited plan</div>'}
    </div>
  </div>

  <div class="card" style="margin-top:18px">
    <h3>API key</h3>
    <div style="color:var(--muted);font-size:13px;margin-bottom:8px">Use this as a Bearer token on every API call.</div>
    <div class="code" style="display:block;padding:12px;margin:8px 0">{_esc(api_key) or '(no key yet)'}</div>
    <div style="font-size:13px;color:var(--muted)">
      Account: <span class="code">{_esc(email)}</span>
    </div>
  </div>
</div>"""
    return _shell("Dashboard", body)


def checkout_page(plan_id: str, prices: Optional[dict] = None) -> str:
    plan = next((p for p in PLANS if p["id"] == plan_id), None)
    if plan is None:
        return _shell("Plan not found", '<div class="wrap"><p>Unknown plan.</p><a href="/">← back</a></div>')
    price = (prices or {}).get(plan_id, plan["monthly"])
    body = f"""
<div class="wrap" style="max-width:440px;padding-top:60px">
  <h1 style="margin:0 0 6px">Checkout — {plan["name"]}</h1>
  <p style="color:var(--muted);font-size:14px">
    ${price} / month · {plan["calls"].lower()} · cancel anytime.
  </p>
  <div class="card">
    <form method="post" action="/checkout/{plan_id}">
      <label>Email</label>
      <input type="email" name="email" required autocomplete="email">
      <div style="margin-top:16px"><button class="btn" type="submit">Pay ${price} with Stripe</button></div>
    </form>
    <p style="margin-top:14px;color:var(--muted);font-size:13px">
      You'll be redirected to Stripe's secure checkout. After payment your plan is activated and
      your API key is upgraded automatically.
    </p>
  </div>
  <p style="margin-top:16px"><a href="/login">← Back to sign in</a></p>
</div>"""
    return _shell(f"Checkout — {plan['name']}", body)


def _shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Remote Jobs API</title>
<style>{_base_css()}</style></head><body>
<header><div class="wrap row"><div class="logo">Remote&nbsp;<span>Jobs&nbsp;API</span></div>
  <a href="/" class="btn btn-ghost">Home</a></div></header>
{body}
<footer><div class="wrap">© 2026 Remote Jobs API · <a href="mailto:earnnova@tten.no">earnnova@tten.no</a></div></footer>
</body></html>"""