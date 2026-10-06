"""End-to-end tests in a real headless browser against the frozen portal.
All model turns here come from labelled test doubles, never from a live model."""
import json

import pytest

from ui_operator.agent import run_batch
from ui_operator.check import check_run
from ui_operator.model import Recorder, ReplayModel
from ui_operator.requests_io import _to_request, load_requests
from ui_operator.testing import FailingModel, ListModel, ScriptedModel

ADDR = {"line1": "42 Fiction Lane", "city": "Demo City", "postal_code": "00123", "country": "Exampleland"}


def by_label(run):
    return {r["label"]: r for r in run["results"]}


@pytest.fixture(scope="module")
def scripted_run():
    reqs = load_requests()
    return run_batch(reqs, ScriptedModel(reqs), "scripted-test-double", port=0)


def test_scripted_run_meets_every_reference_check(scripted_run):
    rows = check_run(scripted_run)
    assert [r for r in rows if not r["passed"]] == []


def test_simulated_failure_is_visible_and_retried_once(scripted_run):
    r5 = by_label(scripted_run)["R5"]
    assert r5["save_attempts"] == 2 and r5["visible_failures"] == ["Simulated save failure. Nothing saved."]
    assert any(e["simulated"] for e in r5["harness_events"])
    r9 = by_label(scripted_run)["R9"]
    assert r9["status"] == "failed" and r9["save_attempts"] == 2 and r9["verification"]["new_drafts"] == []


def test_fabricated_success_is_caught():
    """Model claims draft_saved without ever saving: verification must mark it failed."""
    req = _to_request({"request_id": "N1", "vendor_id": "V1", "address": ADDR})
    model = ListModel([("finish", {"outcome": "draft_saved", "reason": "trust me"})])
    run = run_batch([req], model, "negative-test", port=0)
    r = run["results"][0]
    assert r["status"] == "failed" and "did not find" in r["reason"]


def test_reset_and_wrong_vendor_are_rejected_and_nothing_changes():
    req = _to_request({"request_id": "N2", "vendor_id": "V1", "address": ADDR})
    model = ListModel([("click_button", {"ref": "reset", "reason": "x"}),
                       ("select_option", {"ref": "vendor", "value": "V2", "reason": "x"}),
                       ("fill_field", {"ref": "line1", "value": "Somewhere Else 1", "reason": "x"}),
                       ("finish", {"outcome": "failed", "reason": "gave up"})])
    run = run_batch([req], model, "negative-test", port=0)
    r = run["results"][0]
    assert [s["guard"].split(":")[0] for s in r["steps"][:3]] == ["rejected"] * 3
    assert r["status"] == "failed" and r["verification"]["new_drafts"] == []
    assert run["vendors_match_seed_at_end"]


def test_model_outage_fails_visibly_and_batch_continues():
    reqs = [_to_request({"request_id": f"N{i}", "vendor_id": "V1", "address": ADDR}) for i in (3, 4)]
    run = run_batch(reqs, FailingModel(), "simulated-outage", port=0)
    assert [r["status"] for r in run["results"]] == ["failed", "failed"]
    assert all("SIMULATED" in r["reason"] for r in run["results"])
    assert run["final_drafts"] == []


def test_step_limit_stops_the_loop():
    req = _to_request({"request_id": "N5", "vendor_id": "V1", "address": ADDR})
    model = ListModel([("select_option", {"ref": "vendor", "value": "V1", "reason": "x"})] * 20)
    run = run_batch([req], model, "negative-test", port=0)
    r = run["results"][0]
    assert r["status"] == "failed" and "step limit" in r["reason"] and len(r["steps"]) == 12


def test_record_then_replay_reproduces_outcomes(tmp_path):
    reqs = load_requests()
    calls = tmp_path / "model-calls.jsonl"
    rec = Recorder(ScriptedModel(reqs), calls)
    first = run_batch(reqs, rec, "record-test", port=0)
    replay = run_batch(load_requests(), ReplayModel(calls), "replay-test", port=0)
    assert [r["status"] for r in first["results"]] == [r["status"] for r in replay["results"]]
    steps = [s for r in replay["results"] for s in r["steps"]]
    assert steps and all(s["source"] == "replay" and not s["note"] for s in steps)   # no divergence
    assert len(calls.read_text().splitlines()) == len(steps)
    assert all(json.loads(l)["prompt_sha256"] for l in calls.read_text().splitlines())
