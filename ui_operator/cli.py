"""Command line entry point.

  python -m ui_operator run                 live run with the configured model (records responses)
  python -m ui_operator run --scripted      harness test with the deterministic test double (no model)
  python -m ui_operator replay runs/<id>    re-run in the real browser using recorded responses (no API key)
  python -m ui_operator check  runs/<id>    compare a run with reference/reference-cases.json
  python -m ui_operator report runs/<id>    regenerate report.html
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .agent import run_batch
from .check import check_run, rows_to_markdown
from .config import DEFAULT_PROVIDER, MODEL_NAME, PORTAL_PORT, RUNS_DIR
from .model import ModelError, Recorder, ReplayModel, build_live_model
from .report import render_report
from .requests_io import load_requests


class _Unavailable:
    """Stand-in when the live model cannot be constructed; every call fails visibly."""
    provider = "unavailable"

    def __init__(self, provider: str, reason: str):
        self.model, self.reason, self.context = provider, reason, {}

    def params(self):
        return {"error": self.reason}

    def next_turn(self, *a, **k):
        raise ModelError(self.reason)


def _finish(run: dict, run_dir: Path) -> int:
    run["run_id"] = run_dir.name
    rows = check_run(run)
    run["reference_check"] = {"passed": sum(r["passed"] for r in rows), "total": len(rows)}
    (run_dir / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False))
    (run_dir / "check-results.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    (run_dir / "check-results.md").write_text(rows_to_markdown(rows, run))
    (run_dir / "report.html").write_text(render_report(run, rows))
    c = run["summary"]["counts"]
    print(f"\n{run_dir}\n  verified drafts {c['draft']} · needs-information {c['needs-information']} · "
          f"unresolved {c['unresolved']} · failed {c['failed']} · already-drafted {c['already-drafted']}")
    print(f"  reference checks: {run['reference_check']['passed']}/{run['reference_check']['total']} passed")
    print(f"  report: {run_dir / 'report.html'}")
    return 0 if run["reference_check"]["passed"] == run["reference_check"]["total"] else 1


def _select(reqs, only: str | None):
    if not only:
        return reqs
    wanted = {x.strip() for x in only.split(",")}
    return [r for r in reqs if r.request_id in wanted]


def cmd_run(a) -> int:
    reqs = _select(load_requests(), a.only)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if a.scripted:
        from .testing import ScriptedModel
        model, mode = ScriptedModel(reqs), "scripted-test-double"
        run_dir = RUNS_DIR / f"{stamp}-scripted"
        run_dir.mkdir(parents=True)
    else:
        mode = "live"
        run_dir = RUNS_DIR / f"{stamp}-live"
        run_dir.mkdir(parents=True)
        try:
            model = Recorder(build_live_model(a.provider, a.model or MODEL_NAME or None), run_dir / "model-calls.jsonl")
        except ModelError as exc:
            print(f"model unavailable: {exc}", file=sys.stderr)
            model = _Unavailable(a.provider, str(exc))
    print(f"Running {len(reqs)} requests ({mode}) ...")
    return _finish(run_batch(reqs, model, mode, headless=not a.headed, port=a.port), run_dir)


def cmd_replay(a) -> int:
    src = Path(a.run_dir)
    calls = src / "model-calls.jsonl"
    if not calls.exists():
        print(f"no recorded responses at {calls}", file=sys.stderr)
        return 2
    reqs = load_requests()
    run_dir = RUNS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-replay-of-{src.name}"
    run_dir.mkdir(parents=True)
    print(f"Replaying {calls} in a real browser (no model calls) ...")
    run = run_batch(reqs, ReplayModel(calls), f"replay of {src.name}", headless=not a.headed, port=a.port)
    run["replayed_from"] = str(src)
    return _finish(run, run_dir)


def cmd_check(a) -> int:
    run_dir = Path(a.run_dir)
    run = json.loads((run_dir / "run.json").read_text())
    rows = check_run(run)
    print(rows_to_markdown(rows, run))
    return 0 if all(r["passed"] for r in rows) else 1


def cmd_report(a) -> int:
    run_dir = Path(a.run_dir)
    run = json.loads((run_dir / "run.json").read_text())
    (run_dir / "report.html").write_text(render_report(run, check_run(run)))
    print(run_dir / "report.html")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m ui_operator", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--provider", default=DEFAULT_PROVIDER, choices=["anthropic", "openai"])
    r.add_argument("--model", default=None, help="model ID (default per provider, or MODEL_NAME)")
    r.add_argument("--only", help="comma-separated request IDs, e.g. R1,R5")
    r.add_argument("--scripted", action="store_true", help="use the deterministic test double instead of a model")
    for sp in (r, rp := sub.add_parser("replay")):
        sp.add_argument("--headed", action="store_true", help="show the browser window")
        sp.add_argument("--port", type=int, default=PORTAL_PORT)
    rp.add_argument("run_dir")
    sub.add_parser("check").add_argument("run_dir")
    sub.add_parser("report").add_argument("run_dir")
    a = p.parse_args(argv)
    return {"run": cmd_run, "replay": cmd_replay, "check": cmd_check, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
