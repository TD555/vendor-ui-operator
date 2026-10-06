"""Test doubles. NOT a model integration: these exist only to test the harness,
guard and verifier without network access. Every turn they produce is labelled
source="scripted-test-double" or "simulated-failure" in run records and reports.
"""
from __future__ import annotations

import re

from .model import ModelError, ModelTurn
from .requests_io import Request, load_seed, resolve_vendor


class ScriptedModel:
    """Follows the documented procedure deterministically, reading the page text it is given."""
    provider = "scripted"
    model = "rule-based test double"

    def __init__(self, requests: list[Request]):
        self.by_label = {r.label: r for r in requests}
        self.vendors = load_seed()["vendors"]
        self.context: dict = {}
        self._n = 0

    def params(self) -> dict:
        return {"note": "deterministic test double; not a model"}

    def _turn(self, name, args) -> ModelTurn:
        self._n += 1
        return ModelTurn(tool_name=name, args=args, tool_call_id=f"scripted-{self._n}",
                         source="scripted-test-double", provider=self.provider, model=self.model)

    def next_turn(self, system, transcript, tools) -> ModelTurn:
        req = self.by_label[self.context["request_label"]]
        last = transcript[-1]["text"]
        actions_done = [t["tool_call"] for t in transcript if t["role"] == "assistant"]
        res = resolve_vendor(req, self.vendors)
        if not actions_done:
            if req.missing_fields:
                return self._turn("finish", {"outcome": "needs_information", "reason": "required field empty",
                                             "missing_fields": req.missing_fields,
                                             "clarification_question": f"Please supply {', '.join(req.missing_fields)}."})
            if res.outcome != "ok":
                return self._turn("finish", {"outcome": res.outcome.replace("-", "_"), "reason": res.reason,
                                             "clarification_question": "Which vendor ID should change?"})
            return self._turn("select_option", {"ref": "vendor", "value": res.vendor_id, "reason": "select vendor"})
        plan = [("request", req.request_id)] + [(f, req.address[f]) for f in ("line1", "city", "postal_code", "country")]
        filled = {a["args"]["ref"] for a in actions_done if a["name"] == "fill_field"}
        for ref, value in plan:
            if ref not in filled:
                return self._turn("fill_field", {"ref": ref, "value": value, "reason": "copy request value"})
        saves = sum(1 for a in actions_done if a["name"] == "click_button")
        if f'"request_id": "{req.request_id}"' in last:
            return self._turn("finish", {"outcome": "draft_saved", "reason": "draft visible in Saved drafts"})
        if saves < 2:
            m = re.search(r"\[(\w+)\] \"[^\"]+\" \(submits the form\)", last)
            return self._turn("click_button", {"ref": m.group(1) if m else "?", "reason": "save draft"})
        return self._turn("finish", {"outcome": "failed", "reason": "save failed twice; no draft"})


class FailingModel:
    """Simulates an unavailable model API."""
    provider = "simulated"
    model = "unavailable"
    context: dict = {}

    def params(self) -> dict:
        return {"note": "simulated API outage"}

    def next_turn(self, *a, **k):
        raise ModelError("SIMULATED: connection refused")


class ListModel:
    """Returns a fixed list of (tool, args) turns; used for negative tests."""
    provider = "scripted"
    model = "fixed action list"

    def __init__(self, turns: list[tuple[str, dict]]):
        self.turns, self.i, self.context = list(turns), 0, {}

    def params(self) -> dict:
        return {}

    def next_turn(self, *a, **k) -> ModelTurn:
        if self.i >= len(self.turns):
            raise ModelError("fixed action list exhausted")
        name, args = self.turns[self.i]
        self.i += 1
        return ModelTurn(tool_name=name, args=args, tool_call_id=f"list-{self.i}",
                         source="scripted-test-double", provider=self.provider, model=self.model)
