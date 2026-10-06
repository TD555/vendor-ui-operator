"""Static HTML run report: one page a reviewer can open without running anything."""
from __future__ import annotations

import json
from html import escape

from .config import ADDRESS_FIELDS

STATUS_LABEL = {"draft": "Verified draft", "needs-information": "Needs information",
                "unresolved": "Unresolved", "failed": "Failed", "already-drafted": "Already drafted"}

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1f21;--muted:#62666b;--line:#e2e2de;--ok:#1f7a4d;--okbg:#e6f4ec;
--warn:#8a5a00;--warnbg:#fbf1dc;--bad:#a8322d;--badbg:#fbe7e5;--info:#2a5d9f;--infobg:#e7eef9;--code:#f1f1ee}
@media (prefers-color-scheme:dark){:root{--bg:#141516;--card:#1d1f21;--ink:#e8e8e6;--muted:#9a9ea3;--line:#33363a;
--ok:#6fcf9b;--okbg:#18301f;--warn:#e8b866;--warnbg:#33290f;--bad:#f08a84;--badbg:#3a1a18;--info:#8fb6f0;--infobg:#17243a;--code:#26292c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 16px 60px}h1{font-size:24px;margin:0 0 4px}
.meta{color:var(--muted);font-size:13px}.meta code{font-size:12px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:20px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.tile b{display:block;font-size:26px;font-variant-numeric:tabular-nums}.tile span{color:var(--muted);font-size:13px}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 14px}.filters button{font:inherit;font-size:13px;border:1px solid var(--line);
background:var(--card);color:var(--ink);border-radius:999px;padding:4px 12px;cursor:pointer}.filters button[aria-pressed=true]{background:var(--ink);color:var(--bg)}
details.req{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:10px 0}
details.req>summary{cursor:pointer;padding:12px 14px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;list-style:none}
summary .id{font-weight:600;min-width:110px}summary .why{color:var(--muted);flex:1;min-width:200px}
.pill{font-size:12px;font-weight:600;border-radius:999px;padding:2px 10px;white-space:nowrap}
.s-draft,.s-already-drafted{background:var(--okbg);color:var(--ok)}.s-needs-information{background:var(--warnbg);color:var(--warn)}
.s-unresolved{background:var(--infobg);color:var(--info)}.s-failed{background:var(--badbg);color:var(--bad)}
.body{padding:0 14px 14px;border-top:1px solid var(--line)}h3{font-size:14px;margin:16px 0 6px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}td code,pre{background:var(--code);border-radius:4px}td code{padding:1px 4px}
pre{padding:10px;overflow:auto;font-size:12px;margin:0;white-space:pre-wrap;word-break:break-word}.rej{color:var(--bad)}.sim{color:var(--warn);font-weight:600}
.changed{background:var(--okbg)}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}.grid2>div{min-width:0}@media(max-width:700px){.grid2{grid-template-columns:1fr}}
.wrap{overflow-x:auto}
"""

JS = """
document.querySelectorAll('.filters button').forEach(b=>b.onclick=()=>{
 document.querySelectorAll('.filters button').forEach(x=>x.setAttribute('aria-pressed',x===b));
 const f=b.dataset.f;document.querySelectorAll('details.req').forEach(d=>d.hidden=!(f==='all'||d.dataset.s===f));});
"""


def _j(v) -> str:
    return escape(json.dumps(v, ensure_ascii=False))


def _before_after(r: dict) -> str:
    before = (r.get("vendor_before") or {}).get("address")
    new = r.get("verification", {}).get("new_drafts", [])
    after = new[0]["address"] if new else None
    if not before and not after:
        return "<p class='meta'>No vendor selected and no draft saved.</p>"
    rows = []
    for f in ADDRESS_FIELDS:
        b = (before or {}).get(f, "—")
        a = (after or {}).get(f, "—") if after else "—"
        cls = " class='changed'" if after and a != b else ""
        rows.append(f"<tr><td>{f}</td><td><code>{escape(str(b))}</code></td><td{cls}><code>{escape(str(a))}</code></td></tr>")
    vid = escape(str((r.get("vendor_before") or {}).get("vendor_id", "")))
    vname = escape(str((r.get("vendor_before") or {}).get("name", "")))
    return (f"<p class='meta'>Vendor {vid} {vname}: original record (unchanged) vs saved draft</p>"
            "<div class='wrap'><table><tr><th>Field</th><th>Original address</th><th>Draft</th></tr>"
            + "".join(rows) + "</table></div>")


def _steps(r: dict) -> str:
    rows = []
    events = {e.get("at_step"): e for e in r.get("harness_events", [])}
    if 0 in events:
        rows.append(f"<tr><td>0</td><td colspan=4 class='sim'>SIMULATED · {escape(events[0]['event'])}</td></tr>")
    for s in r.get("steps", []):
        if "error" in s:
            rows.append(f"<tr><td>{s['step']}</td><td colspan=4 class='rej'>{escape(s['error'])}</td></tr>")
            continue
        args = {k: v for k, v in s["args"].items() if k != "reason"}
        guard = s.get("guard", "")
        g = f"<span class='rej'>{escape(guard)}</span>" if guard.startswith("rejected") else escape(guard)
        ex = s.get("execution")
        exs = "" if ex is None else ("ok" if ex.get("ok") else f"<span class='rej'>{escape(ex.get('error', ''))}</span>")
        if s.get("save_attempt"):
            exs += f" · save #{s['save_attempt']}: <b>{escape(s['save_result'])}</b>"
        note = f"<br><span class='sim'>{escape(s['note'])}</span>" if s.get("note") else ""
        rows.append(f"<tr><td>{s['step']}</td><td><code>{escape(s['tool'])}</code><br><span class='meta'>"
                    f"{escape(s['args'].get('reason', ''))}</span>{note}</td><td><code>{_j(args)}</code></td>"
                    f"<td>{g}{'<br>' + exs if exs else ''}</td><td>{escape(s.get('status_after') or '')}</td></tr>")
        if s["step"] in events:
            rows.append(f"<tr><td></td><td colspan=4 class='sim'>SIMULATED · {escape(events[s['step']]['event'])}</td></tr>")
    if not rows:
        return "<p class='meta'>No model actions (handled before the agent loop).</p>"
    return ("<div class='wrap'><table><tr><th>#</th><th>Action</th><th>Arguments</th><th>Guard / result</th>"
            "<th>Portal status after</th></tr>" + "".join(rows) + "</table></div>")


def _checks(r: dict) -> str:
    cs = r.get("verification", {}).get("checks", [])
    if not cs:
        return ""
    rows = "".join(f"<tr><td>{'✓' if c['passed'] else '<span class=rej>✗</span>'}</td><td>{escape(c['name'])}</td>"
                   f"<td class='meta'>{escape(c.get('detail', ''))}</td></tr>" for c in cs)
    return f"<h3>Verification (code, after the run)</h3><div class='wrap'><table>{rows}</table></div>"


def render_report(run: dict, check_rows: list[dict] | None = None) -> str:
    s = run["summary"]["counts"]
    sources = sorted({st.get("source", "") for r in run["results"] for st in r.get("steps", []) if st.get("source")})
    src_note = ", ".join(sources) or "none"
    tiles = "".join(f"<div class='tile'><b>{s.get(k, 0)}</b><span>{v}</span></div>" for k, v in STATUS_LABEL.items())
    tiles += f"<div class='tile'><b>{run['summary']['guard_rejections']}</b><span>Actions rejected by guard</span></div>"
    filt = "<button data-f='all' aria-pressed='true'>All</button>" + "".join(
        f"<button data-f='{k}' aria-pressed='false'>{v}</button>" for k, v in STATUS_LABEL.items())
    cards = []
    for r in run["results"]:
        claim = r.get("claim") or {}
        extra = ""
        if claim.get("clarification_question"):
            extra += f"<p><b>Clarification draft:</b> {escape(claim['clarification_question'])}</p>"
        if claim.get("missing_fields"):
            extra += f"<p><b>Missing fields:</b> {escape(', '.join(claim['missing_fields']))}</p>"
        cards.append(f"""<details class='req' data-s='{r['status']}'><summary><span class='id'>{escape(r['label'])}</span>
<span class='pill s-{r['status']}'>{STATUS_LABEL.get(r['status'], r['status'])}</span>
<span class='why'>{escape(r.get('reason', ''))}</span><span class='meta'>{len(r.get('steps', []))} actions</span></summary>
<div class='body'>{extra}<div class='grid2'><div><h3>Request</h3><pre>{escape(json.dumps(r['request'], indent=2, ensure_ascii=False))}</pre></div>
<div><h3>Before / after</h3>{_before_after(r)}</div></div>
<h3>Actions</h3>{_steps(r)}{_checks(r)}
<p class='meta'>Model's final claim: <code>{_j(claim) if claim else 'none'}</code></p></div></details>""")
    check_html = ""
    if check_rows:
        passed = sum(c["passed"] for c in check_rows)
        rows = "".join(f"<tr><td>{escape(c['case'])}</td><td>{escape(c['check'])}</td><td><code>{_j(c['expected'])}</code></td>"
                       f"<td><code>{_j(c['observed'])}</code></td><td>{'PASS' if c['passed'] else '<b class=rej>FAIL</b>'}</td></tr>"
                       for c in check_rows)
        check_html = (f"<h2>Reference checks · {passed}/{len(check_rows)} passed</h2><p class='meta'>Expected values from "
                      "reference/reference-cases.json, derived by hand before the run.</p><div class='wrap'><table>"
                      "<tr><th>Case</th><th>Check</th><th>Expected</th><th>Observed</th><th></th></tr>" + rows + "</table></div>")
    m = run["model"]
    warn = ""
    if any(x != "live" for x in sources):
        warn = (f"<p class='tile'><b style='font-size:15px'>Response source: {escape(src_note)}</b>"
                "<span>replay = recorded real model responses; scripted-test-double = deterministic test code, "
                "not a model.</span></p>")
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Vendor Operator Run</title><style>{CSS}</style></head><body><main>
<h1>Vendor address operator · run report</h1>
<p class='meta'>Run <code>{escape(run.get('run_id', ''))}</code> · mode <b>{escape(run['mode'])}</b> · model {escape(m['provider'])}/{escape(str(m['name']))}
· response source: {escape(src_note)} · commit <code>{escape(run.get('git_commit', ''))}</code><br>
portal sha256 <code>{run['portal_sha256'][:12]}</code> · prompt sha256 <code>{run['prompt_sha256'][:12]}</code> ·
limits {escape(json.dumps(run['limits']))} · {escape(run['started_at'])} → {escape(run.get('finished_at', ''))}</p>
{warn}<div class='tiles'>{tiles}</div>
<p class='meta'>Final drafts in portal: {len(run.get('final_drafts', []))} · vendor records unchanged: {run.get('vendors_match_seed_at_end')}
· {escape(run.get('error', ''))}</p>
<div class='filters'>{filt}</div>{''.join(cards)}{check_html}
<p class='meta'>Five demonstration requests plus four added cases cannot establish reliability on other portals or requests.</p>
</main><script>{JS}</script></body></html>"""
