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


# Live-demo JS (kept out of the landing f-string: its object-literal braces
# would otherwise be parsed as Python expressions).
_DEMO_JS = r"""
<script>
(function(){
  var list=document.getElementById('demo-list'),
      status=document.getElementById('demo-status'),
      err=document.getElementById('demo-err'),
      copy=document.getElementById('demo-copy');
  var escMap={'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'};
  function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return escMap[c];});}
  function load(){
    var sk=document.getElementById('demo-skills').value.trim(),
        src=document.getElementById('demo-source').value;
    var q=new URLSearchParams();
    if(sk) q.set('skills',sk);
    if(src) q.set('source',src);
    q.set('limit','6');
    var url='/v1/jobs?'+q.toString();
    status.textContent='Loading\u2026'; err.style.display='none'; list.innerHTML='';
    fetch(url,{headers:{'Accept':'application/json'}}).then(function(r){
      if(!r.ok) throw new Error('HTTP '+r.status);
      return r.json();
    }).then(function(d){
      var n=(d.jobs||[]).length;
      status.textContent=n+' live jobs' + (sk?(' \u00b7 ranked by fit for "'+sk+'"'):'') + (src?(' \u00b7 source: '+src):'');
      if(!n){ status.textContent='No jobs matched \u2014 try fewer skills.'; return; }
      list.innerHTML=(d.jobs||[]).map(function(j){
        var score=(j.fit_score!=null)?' <span class="badge pro">fit '+j.fit_score+'</span>':'';
        var sal=j.salary? ' <span style="color:var(--muted);font-size:12px">\u00b7 '+esc(j.salary)+'</span>':'';
        return '<div style="border:1px solid var(--border);border-radius:10px;padding:12px 14px">'
          +'<div style="font-weight:600;font-size:15px">'+(j.fit_score!=null?'<span style="color:var(--muted);font-weight:400">['+j.fit_score+'] </span>':'')+esc(j.title)+' '+score+'</div>'
          +'<div style="color:var(--muted);font-size:13px;margin-top:2px">'+esc(j.company)+' \u00b7 '+esc(j.location||'Remote')+sal+'</div>'
          +'<a href="'+esc(j.url)+'" target="_blank" rel="noopener" style="font-size:13px">'+esc(j.source)+'</a></div>';
      }).join('');
      copy.style.visibility='visible';
      copy.onclick=function(){
        var base=location.origin+url;
        var cmd='curl -H "Authorization: Bearer ***" "'+base+'"';
        (navigator.clipboard?navigator.clipboard.writeText(cmd):Promise.reject()).then(function(){
          copy.textContent='Copied!'; setTimeout(function(){copy.textContent='Copy this curl';},1500);
        }).catch(function(){copy.textContent=cmd;});
      };
    }).catch(function(e){
      err.style.display='block';
      err.textContent='Could not load live jobs ('+e.message+'). The API may require a key or be rate-limited \u2014 see /docs.';
      status.textContent='';
    });
  }
  document.getElementById('demo-go').onclick=load;
  document.getElementById('demo-skills').addEventListener('keydown',function(e){if(e.key==='Enter')load();});
  document.getElementById('demo-source').onchange=load;
  load();
})();
</script>
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
<title>Remote Jobs API — one API for all remote jobs</title>
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
    <h2>Try it live</h2>
    <p style="color:var(--muted);margin:0 0 14px">This is the real API — no mock data. Type skills to rank by fit, or leave blank for the latest listings.</p>
    <div class="card" id="demo-card">
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px">
        <input id="demo-skills" placeholder="e.g. python, backend, remote" style="max-width:320px">
        <select id="demo-source" style="max-width:170px"><option value="">All boards</option>
          <option value="remotive">Remotive</option><option value="remoteok">RemoteOK</option>
          <option value="jobicy">Jobicy</option><option value="wwr">We Work Remotely</option>
          <option value="hn">Hacker News</option></select>
        <button class="btn" id="demo-go" type="button">Load jobs</button>
        <button class="btn btn-ghost" id="demo-copy" type="button" style="visibility:hidden">Copy this curl</button>
      </div>
      <div id="demo-status" style="color:var(--muted);font-size:13px;margin-bottom:10px">Loading…</div>
      <div id="demo-list" style="display:grid;gap:10px"></div>
      <div id="demo-err" class="error" style="display:none"></div>
    </div>
  </div>

  <div class="section">
    <h2>Example</h2>
<pre class="card" style="overflow:auto"><code>curl -H "Authorization: Bearer *** " \\
  "https://remote-jobs-api.tten.no/v1/jobs?skills=python,api&amp;limit=5"</code></pre>
    <p style="margin-top:14px;color:var(--muted);font-size:14px">Full reference: <a href="/docs">API docs</a> · <a href="/openapi.yaml">OpenAPI spec</a></p>
  </div>
</div>
{_DEMO_JS}
<footer><div class="wrap">© 2026 Remote Jobs API · <a href="/docs">Docs</a> · <a href="mailto:earnnova@tten.no">earnnova@tten.no</a></div></footer>
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
      <a href="/forgot">Forgot password?</a>
    </p>
    <p style="margin-top:10px;color:var(--muted);font-size:14px">
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


def forgot_page(error: str = "", ok: str = "") -> str:
    form = """
    <form method="post" action="/forgot">
      <label>Email</label>
      <input type="email" name="email" required autocomplete="email">
      <div style="margin-top:16px"><button class="btn" type="submit">Email me a reset link</button></div>
    </form>
    <p style="margin-top:16px;color:var(--muted);font-size:14px">
      <a href="/login">← Back to sign in</a>
    </p>"""
    body = f"""
<div class="wrap" style="max-width:440px;padding-top:60px">
  <h1 style="margin:0 0 6px">Reset your password</h1>
  <p style="color:var(--muted);font-size:14px;margin:0 0 18px">Enter the email you signed up with. We'll send a link to set a new password.</p>
  {f'<p class="error">{error}</p>' if error else ''}
  {f'<p class="success" style="word-break:break-all">{ok}</p>' if ok else ''}
  {form}
</div>"""
    return _shell("Reset password", body)


def reset_page(token: str, error: str = "", ok: str = "") -> str:
    form = f"""
    <form method="post" action="/reset">
      <input type="hidden" name="token" value="{token}">
      <label>New password (min 8 chars)</label>
      <input type="password" name="password" required minlength="8" autocomplete="new-password">
      <label>Confirm new password</label>
      <input type="password" name="confirm" required minlength="8" autocomplete="new-password">
      <div style="margin-top:16px"><button class="btn" type="submit">Set new password</button></div>
    </form>
    <p style="margin-top:16px;color:var(--muted);font-size:14px">
      <a href="/forgot">← Request a new link</a>
    </p>"""
    body = f"""
<div class="wrap" style="max-width:440px;padding-top:60px">
  <h1 style="margin:0 0 6px">Choose a new password</h1>
  <p style="color:var(--muted);font-size:14px;margin:0 0 18px">Pick a strong password you don't use elsewhere.</p>
  {f'<p class="error">{error}</p>' if error else ''}
  {f'<p class="success">{ok}</p>' if ok else ''}
  {form}
</div>"""
    return _shell("New password", body)


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


def checkout_page(plan_id: str, prices: Optional[dict] = None, email: str = "") -> str:
    plan = next((p for p in PLANS if p["id"] == plan_id), None)
    if plan is None:
        return _shell("Plan not found", '<div class="wrap"><p>Unknown plan.</p><a href="/">← back</a></div>')
    price = (prices or {}).get(plan_id, plan["monthly"])
    if email:
        # Logged in: pre-fill the email, no need to retype it.
        email_field = (
            f'<input type="email" name="email" required value="{_esc(email)}" '
            f'autocomplete="email" readonly tabindex="-1" '
            f'style="background:var(--bg);color:var(--muted)">'
        )
    else:
        email_field = '<input type="email" name="email" required autocomplete="email">'
    body = f"""
<div class="wrap" style="max-width:440px;padding-top:60px">
  <h1 style="margin:0 0 6px">Checkout — {plan["name"]}</h1>
  <p style="color:var(--muted);font-size:14px">
    ${price} / month · {plan["calls"].lower()} · cancel anytime.
  </p>
  <div class="card">
    <form method="post" action="/checkout/{plan_id}">
      <label>Email</label>
      {email_field}
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


def docs_page() -> str:
    body = """
<div class="wrap" style="max-width:840px;padding-top:40px">
  <h1 style="margin:0 0 6px">API documentation</h1>
  <p style="color:var(--muted);margin:0 0 24px">Base URL: <span class="code">https://remote-jobs-api.tten.no</span> · <a href="/openapi.yaml">OpenAPI 3.1 spec</a></p>

  <h2>Quickstart</h2>
  <p>1. <a href="/register">Create an account</a> — your API key is issued instantly and shown on your dashboard.</p>
  <p>2. Call the API with your key:</p>
<pre class="card" style="overflow:auto"><code>curl -H "Authorization: Bearer ***" \\
  "https://remote-jobs-api.tten.no/v1/jobs?skills=python,backend&amp;limit=5"</code></pre>

  <h2>Authentication</h2>
  <p>Send your key as a Bearer token in the <code>Authorization</code> header. Open mode is currently on, so <code>/v1/jobs</code> also works with no key (unlimited, unattributed). Paid keys carry monthly call quotas and usage tracking.</p>

  <h2>Endpoints</h2>
  <table class="table">
    <tr><th>Method</th><th>Path</th><th>Description</th></tr>
    <tr><td>GET</td><td><code>/health</code></td><td>Status + live job count + active sources</td></tr>
    <tr><td>GET</td><td><code>/v1/jobs/sources</code></td><td>Available job boards</td></tr>
    <tr><td>GET</td><td><code>/v1/jobs</code></td><td>Normalized job listings (JSON or CSV)</td></tr>
  </table>

  <h2>GET /v1/jobs — query parameters</h2>
  <table class="table">
    <tr><th>Param</th><th>Type</th><th>Notes</th></tr>
    <tr><td><code>skills</code></td><td>string</td><td>Comma-separated keywords. Adds a <code>fit_score</code> (0–100) to each job and ranks best-first.</td></tr>
    <tr><td><code>source</code></td><td>string</td><td><code>remotive</code> / <code>remoteok</code> / <code>jobicy</code> / <code>wwr</code> / <code>hn</code></td></tr>
    <tr><td><code>min_score</code></td><td>int</td><td>Only return jobs with <code>fit_score</code> ≥ N (requires <code>skills</code>).</td></tr>
    <tr><td><code>min_salary</code></td><td>int</td><td>Only return jobs whose parsed salary floor (<code>salary_min</code>) is ≥ N. Listings with no parsed salary are dropped. e.g. <code>min_salary=100000</code>.</td></tr>
    <tr><td><code>limit</code></td><td>int</td><td>1–500 (default 50).</td></tr>
    <tr><td><code>format</code></td><td>string</td><td><code>json</code> (default) or <code>csv</code>.</td></tr>
  </table>

  <h2>Response shape</h2>
<pre class="card" style="overflow:auto"><code>{
  "count": 5,
  "generated_at": 1790573039,
  "query": { "skills": ["python","backend"], "source": null, "min_score": null, "limit": 5 },
  "jobs": [
    {
      "id": "154115",
      "title": "Account Manager, Ada Accelerate",
      "company": "Ada",
      "url": "https://jobicy.com/jobs/154115-...",
      "location": "Canada / Director",
      "salary": "130,000-170,000 / yearly",
      "category": "",
      "tags": ["Customer Support & Success", "Full-Time"],
      "published": "2026-09-27T20:36:28+00:00",
      "source": "jobicy",
      "description": "About Us ...",
      "fit_score": 50
    }
  ]
}</code></pre>
  <p style="color:var(--muted);font-size:14px"><code>fit_score</code> is only present when <code>skills</code> is supplied. It is a deterministic keyword-overlap score (no LLM) — reproducible and unit-testable.</p>

  <h2>Rate limits &amp; plans</h2>
  <table class="table">
    <tr><th>Plan</th><th>Calls / month</th><th>Price</th></tr>
    <tr><td>Free</td><td>100</td><td>$0</td></tr>
    <tr><td>Pro</td><td>10,000</td><td>$19</td></tr>
    <tr><td>Team</td><td>100,000</td><td>$49</td></tr>
  </table>
  <p style="color:var(--muted);font-size:14px">Exceeding your monthly quota returns <code>429</code> with <code>{"error": "...", "retry": "next month"}</code>.</p>

  <h2>Error codes</h2>
  <table class="table">
    <tr><th>Code</th><th>Meaning</th></tr>
    <tr><td>400</td><td>Bad request (unknown source, limit out of range, min_score without skills)</td></tr>
    <tr><td>401</td><td>Missing or invalid API key (when key is required)</td></tr>
    <tr><td>429</td><td>Monthly quota exceeded</td></tr>
    <tr><td>5xx</td><td>Upstream board / server error — retry</td></tr>
  </table>

  <h2>Example: CSV export</h2>
<pre class="card" style="overflow:auto"><code>curl -H "Authorization: Bearer ***" \\
  "https://remote-jobs-api.tten.no/v1/jobs?skills=data,ml&amp;limit=100&amp;format=csv" -o jobs.csv</code></pre>

  <h2>Questions</h2>
  <p>Reach us at <a href="mailto:earnnova@tten.no">earnnova@tten.no</a>.</p>
</div>"""
    return _shell("API docs", body)