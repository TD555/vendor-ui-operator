"""Tool definitions offered to the model, and the guard that validates every
requested action BEFORE it touches the browser.

The guard encodes the domain rules in code so a model mistake is caught and
recorded instead of executed. Rejections are returned to the model as tool
errors and count against the step limit.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

from .config import MAX_SAVE_ATTEMPTS
from .requests_io import Request, Resolution

OUTCOMES = ("draft_saved", "needs_information", "unresolved", "failed")

TOOLS = [
    {
        "name": "select_option",
        "description": "Choose an option in a <select> control on the portal page. Use the control's ref and the option value shown in the observation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Control ref from the observation, e.g. the value in [brackets]."},
                "value": {"type": "string", "description": "Option value to select."},
                "reason": {"type": "string", "description": "One short sentence: why this action."},
            },
            "required": ["ref", "value", "reason"],
        },
    },
    {
        "name": "fill_field",
        "description": "Replace the content of a text input on the portal page with an exact value taken from the request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "value": {"type": "string", "description": "Exact text from the request. Postal codes are text; keep leading zeros."},
                "reason": {"type": "string"},
            },
            "required": ["ref", "value", "reason"],
        },
    },
    {
        "name": "click_button",
        "description": "Click a button on the portal page by ref.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["ref", "reason"],
        },
    },
    {
        "name": "finish",
        "description": "End work on this request and report the outcome. Call exactly once, as the last action.",
        "input_schema": {
            "type": "object",
            "properties": {
                "outcome": {"type": "string", "enum": list(OUTCOMES)},
                "reason": {"type": "string", "description": "Concise reason a reviewer can act on."},
                "missing_fields": {"type": "array", "items": {"type": "string"},
                                   "description": "Required request fields that are empty, if any."},
                "clarification_question": {"type": "string",
                                           "description": "Question to send back to the requester, when information is needed."},
            },
            "required": ["outcome", "reason"],
        },
    },
]


def parse_drafts_section(obs: dict) -> list[dict] | None:
    for s in obs.get("sections", []):
        if s["heading"].strip().lower() == "saved drafts":
            try:
                return json.loads(s["text"] or "[]")
            except json.JSONDecodeError:
                return None
    return None


@dataclass
class Guard:
    request: Request
    resolution: Resolution
    save_attempts: int = 0
    save_results: list[str] = field(default_factory=list)   # "saved" | "not_saved"

    def _control(self, obs: dict, ref: str):
        for c in obs["controls"]:
            if c["ref"] == ref:
                return c
        return None

    def _button(self, obs: dict, ref: str):
        for b in obs["buttons"]:
            if b["ref"] == ref:
                return b
        return None

    def allowed_values(self) -> set[str]:
        vals = {self.request.request_id}
        vals |= {v for v in self.request.address.values() if str(v).strip()}
        return vals

    def check(self, name: str, args: dict, obs: dict) -> tuple[bool, str]:
        if name == "finish":
            if args.get("outcome") not in OUTCOMES:
                return False, f"outcome must be one of {OUTCOMES}"
            return True, "ok"
        if not isinstance(args.get("ref"), str):
            return False, "missing 'ref'"
        ref = args["ref"]

        if name == "select_option":
            c = self._control(obs, ref)
            if not c or c["kind"] != "select":
                return False, f"[{ref}] is not a select control on the current page"
            if args.get("value") not in {o["value"] for o in c["options"]}:
                return False, f"value {args.get('value')!r} is not an option of [{ref}]"
            if self.resolution.outcome != "ok":
                return False, f"policy: request does not identify a unique vendor ({self.resolution.reason}); do not select one"
            if args["value"] != self.resolution.vendor_id:
                return False, f"policy: request identifies {self.resolution.vendor_id}, not {args['value']}"
            return True, "ok"

        if name == "fill_field":
            c = self._control(obs, ref)
            if not c or c["kind"] != "text" or c.get("disabled"):
                return False, f"[{ref}] is not an editable text input on the current page"
            value = args.get("value")
            if not isinstance(value, str) or not value.strip():
                return False, "policy: empty values are never entered; required fields must come from the request"
            if value not in self.allowed_values():
                return False, f"policy: {value!r} is not a value from this request (no invented or altered values)"
            return True, "ok"

        if name == "click_button":
            b = self._button(obs, ref)
            if not b:
                return False, f"[{ref}] is not a button on the current page"
            if not b["submits_form"]:
                return False, f"policy: only the form's save button may be clicked; [{ref}] \"{b['text']}\" is not allowed"
            return self._check_save(obs)

        return False, f"unknown tool {name}"

    def _check_save(self, obs: dict) -> tuple[bool, str]:
        if self.request.missing_fields:
            return False, f"policy: required fields empty in request: {self.request.missing_fields}"
        if self.resolution.outcome != "ok":
            return False, f"policy: vendor not uniquely identified ({self.resolution.reason})"
        if self.save_attempts >= MAX_SAVE_ATTEMPTS:
            return False, f"policy: at most {MAX_SAVE_ATTEMPTS - 1} retry after a failed save"
        if self.save_results and self.save_results[-1] == "saved":
            return False, "policy: a draft was already saved for this request"
        drafts = parse_drafts_section(obs)
        if drafts is None:
            return False, "cannot read the Saved drafts section; inspect the page before saving"
        if any(d.get("request_id") == self.request.request_id for d in drafts):
            return False, "policy: a draft for this request ID already exists (no duplicates)"
        select = next((c for c in obs["controls"] if c["kind"] == "select"), None)
        if not select or select["value"] != self.resolution.vendor_id:
            return False, f"policy: selected vendor must be {self.resolution.vendor_id} before saving"
        form_values = Counter(c["value"] for c in obs["controls"] if c["kind"] == "text")
        wanted = Counter([self.request.request_id, *self.request.address.values()])
        if form_values != wanted:
            stray = sorted((form_values - wanted).elements())
            missing = sorted((wanted - form_values).elements())
            return False, f"policy: form values do not match the request (unexpected {stray}, not yet entered {missing})"
        return True, "ok"

    def record_save(self, saved: bool):
        self.save_attempts += 1
        self.save_results.append("saved" if saved else "not_saved")
