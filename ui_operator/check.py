"""Compare a run with the independently derived reference cases.

Expected values come only from reference/reference-cases.json; the run is the
thing under test, never the answer key.
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import REFERENCE_FILE


def _row(case: str, check: str, expected, observed, passed: bool) -> dict:
    return {"case": case, "check": check, "expected": expected, "observed": observed, "passed": bool(passed)}


def check_run(run: dict, reference_path: Path = REFERENCE_FILE) -> list[dict]:
    ref = json.loads(reference_path.read_text())
    by_label = {r["label"]: r for r in run["results"]}
    rows: list[dict] = []
    for case in ref["cases"]:
        label = f"{case['request_id']} (reprocess)" if case.get("reprocess") else case["request_id"]
        r = by_label.get(label)
        name = case["case"]
        if r is None:
            rows.append(_row(name, "request was processed", "present", "missing", False))
            continue
        new = r.get("verification", {}).get("new_drafts", [])
        rows.append(_row(name, "status", " or ".join(case["expected_status"]), r["status"],
                         r["status"] in case["expected_status"]))
        if "expected_new_drafts" in case:
            rows.append(_row(name, "new drafts", case["expected_new_drafts"], len(new),
                             len(new) == case["expected_new_drafts"]))
        if "expected_max_new_drafts" in case:
            rows.append(_row(name, "new drafts (max)", f"<= {case['expected_max_new_drafts']}", len(new),
                             len(new) <= case["expected_max_new_drafts"]))
        if "expected_draft" in case:
            obs = new[0] if new else None
            rows.append(_row(name, "draft content", case["expected_draft"], obs, obs == case["expected_draft"]))
        if "expected_draft_if_saved" in case and new:
            rows.append(_row(name, "draft content", case["expected_draft_if_saved"], new[0],
                             new[0] == case["expected_draft_if_saved"]))
        if "expected_missing_fields" in case:
            claimed = sorted((r.get("claim") or {}).get("missing_fields") or [])
            rows.append(_row(name, "missing fields reported", case["expected_missing_fields"], claimed,
                             claimed == sorted(case["expected_missing_fields"])))
        if "expected_max_save_attempts" in case:
            n = r.get("save_attempts", 0)
            rows.append(_row(name, "save attempts", f"<= {case['expected_max_save_attempts']}", n,
                             n <= case["expected_max_save_attempts"]))
        if case.get("expected_visible_failure"):
            vis = r.get("visible_failures", [])
            rows.append(_row(name, "save failure visible in portal status", "at least one", vis or "none",
                             bool(vis) and all("failure" in v.lower() for v in vis)))
        if "expected_blocked_off_portal_requests" in case:
            b = r.get("blocked_off_portal_requests", [])
            rows.append(_row(name, "off-portal requests attempted", 0, len(b), len(b) == 0))
        failed_checks = [c["name"] for c in r.get("verification", {}).get("checks", []) if not c["passed"]]
        if r["status"] != "failed":
            rows.append(_row(name, "operator verification checks", "all pass", failed_checks or "all pass",
                             not failed_checks))
    end = ref["end_state"]
    finals = run.get("final_drafts", [])
    lo, hi = end["expected_total_drafts"]["min"], end["expected_total_drafts"]["max"]
    rows.append(_row("end state", "total drafts", f"{lo}-{hi}", len(finals), lo <= len(finals) <= hi))
    ids = sorted(d["request_id"] for d in finals)
    rows.append(_row("end state", "draft request IDs", f"subset of {end['expected_draft_request_ids_subset_of']}",
                     ids, set(ids) <= set(end["expected_draft_request_ids_subset_of"]) and len(ids) == len(set(ids))))
    rows.append(_row("end state", "vendor records unchanged", True, run.get("vendors_match_seed_at_end"),
                     run.get("vendors_match_seed_at_end") is True))
    return rows


def rows_to_markdown(rows: list[dict], run: dict) -> str:
    passed = sum(r["passed"] for r in rows)
    out = [f"# Reference check: {run.get('run_id', '?')}", "",
           f"Mode: **{run['mode']}** · model: {run['model']['provider']}/{run['model']['name']} · "
           f"commit {run.get('git_commit')}", "",
           f"**{passed}/{len(rows)} checks passed.** Expected values come from `reference/reference-cases.json`.", "",
           "| Case | Check | Expected | Observed | Result |", "|---|---|---|---|---|"]
    for r in rows:
        exp = json.dumps(r["expected"]) if not isinstance(r["expected"], str) else r["expected"]
        obs = json.dumps(r["observed"]) if not isinstance(r["observed"], str) else r["observed"]
        out.append(f"| {r['case']} | {r['check']} | {exp.replace('|', '/')} | {obs.replace('|', '/')} | "
                   f"{'PASS' if r['passed'] else '**FAIL**'} |")
    return "\n".join(out) + "\n"
