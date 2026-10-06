"""Post-run verification in code. The final status of a request is decided here,
from observed application state, not from what the model claims."""
from __future__ import annotations

from .requests_io import Request, Resolution


def _check(name: str, passed: bool, detail: str = "") -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


def verify_request(*, request: Request, resolution: Resolution, claim: dict | None,
                   drafts_before: list[dict], stored_after: list[dict], rendered_after: list[dict],
                   vendors_after: list[dict], seed_vendors: list[dict],
                   blocked_requests: list[str], final_url: str, portal_url: str,
                   stop_reason: str | None) -> dict:
    rid = request.request_id
    new = [d for d in stored_after if d not in drafts_before]
    mine = [d for d in stored_after if d.get("request_id") == rid]
    checks = [
        _check("rendered draft list matches stored drafts", rendered_after == stored_after),
        _check("original vendor records unchanged", vendors_after == seed_vendors),
        _check("no draft created for another request", all(d.get("request_id") == rid for d in new),
               f"new drafts: {[d.get('request_id') for d in new]}"),
        _check("at most one draft for this request ID", len(mine) <= 1, f"{len(mine)} found"),
        _check("earlier drafts untouched", all(d in stored_after for d in drafts_before)),
        _check("stayed on the local portal", final_url.split("#")[0] == portal_url and not blocked_requests,
               f"blocked off-portal requests: {blocked_requests}" if blocked_requests else ""),
    ]
    integrity_ok = all(c["passed"] for c in checks)
    outcome = (claim or {}).get("outcome")

    if stop_reason:  # model error, step limit, browser error
        status, reason = "failed", stop_reason
        checks.append(_check("no draft saved by an incomplete run", not new, f"{len(new)} new"))
    elif outcome == "draft_saved":
        expected = {"request_id": rid, "vendor_id": resolution.vendor_id, "address": request.address}
        ok = resolution.outcome == "ok" and len(new) == 1 and new[0] == expected
        checks.append(_check("saved draft equals the request (vendor resolved independently)", ok,
                             f"expected {expected}; new drafts {new}"))
        status, reason = ("draft", "draft saved and verified") if ok else (
            "failed", "model reported a saved draft, but verification did not find the intended draft")
    elif outcome in ("needs_information", "unresolved"):
        checks.append(_check("no draft created", not new, f"{len(new)} new"))
        status = outcome.replace("_", "-")
        reason = (claim or {}).get("reason", "")
    elif outcome == "failed":
        checks.append(_check("no draft created", not new, f"{len(new)} new"))
        status, reason = "failed", (claim or {}).get("reason", "")
    else:
        status, reason = "failed", "run ended without a finish action"

    if not integrity_ok and status != "failed":
        status, reason = "failed", "integrity check failed: " + "; ".join(c["name"] for c in checks if not c["passed"])
    if not all(c["passed"] for c in checks) and status != "failed":
        status, reason = "failed", "verification check failed"
    return {"status": status, "reason": reason, "new_drafts": new, "checks": checks}
