"""Unit tests for request validation, vendor resolution and the action guard (no browser)."""
from ui_operator.actions import Guard
from ui_operator.requests_io import _to_request, load_requests, load_seed, resolve_vendor

VENDORS = load_seed()["vendors"]
ADDR = {"line1": "42 Fiction Lane", "city": "Demo City", "postal_code": "00123", "country": "Exampleland"}


def obs(select_value="", fields=None, drafts="[]"):
    fields = fields or {"request": "", "line1": "", "city": "", "postal_code": "", "country": ""}
    controls = [{"ref": "vendor", "label": "Vendor", "kind": "select", "value": select_value, "disabled": False,
                 "options": [{"value": "", "text": "Choose"}] + [{"value": v["vendor_id"], "text": v["name"]} for v in VENDORS]}]
    controls += [{"ref": k, "label": k, "kind": "text", "value": v, "disabled": False} for k, v in fields.items()]
    controls.append({"ref": "fail", "label": "Simulate failure on next save", "kind": "checkbox", "checked": False, "disabled": False})
    return {"controls": controls, "status": "",
            "buttons": [{"ref": "el1", "text": "Save draft", "submits_form": True},
                        {"ref": "reset", "text": "Reset fictional drafts", "submits_form": False}],
            "sections": [{"heading": "Saved drafts", "text": drafts}]}


def guard_for(raw):
    r = _to_request(raw)
    return Guard(r, resolve_vendor(r, VENDORS))


def test_seed_and_extra_requests_load_without_input_errors():
    reqs = load_requests()
    assert [r.label for r in reqs][-1] == "R1 (reprocess)"
    assert all(not r.input_errors for r in reqs)


def test_request_validation_rejects_non_text_postal_code():
    r = _to_request({"request_id": "X", "vendor_id": "V1", "address": {**ADDR, "postal_code": 123}})
    assert any("postal_code must be text" in e for e in r.input_errors)


def test_resolution_rules():
    res = lambda raw: resolve_vendor(_to_request({"request_id": "X", "address": ADDR, **raw}), VENDORS)
    assert res({"vendor_id": "V1"}).vendor_id == "V1"
    assert res({"vendor_id": "V999"}).outcome == "unresolved"
    amb = res({"vendor_name": "Northstar Supplies"})
    assert amb.outcome == "needs-information" and sorted(amb.candidates) == ["V2", "V3"]
    assert res({"vendor_name": "  northstar supplies WEST "}).vendor_id == "V3"
    assert res({"vendor_name": "Juniper"}).outcome == "needs-information"   # partial, single match: conservative
    assert res({"vendor_name": "Nobody Ltd"}).outcome == "unresolved"


def test_guard_blocks_wrong_vendor_and_ambiguous_selection():
    g = guard_for({"request_id": "R1", "vendor_id": "V1", "address": ADDR})
    assert not g.check("select_option", {"ref": "vendor", "value": "V2"}, obs())[0]
    assert g.check("select_option", {"ref": "vendor", "value": "V1"}, obs())[0]
    g2 = guard_for({"request_id": "R2", "vendor_name": "Northstar Supplies", "address": ADDR})
    ok, msg = g2.check("select_option", {"ref": "vendor", "value": "V2"}, obs())
    assert not ok and "unique vendor" in msg


def test_guard_blocks_invented_values_and_harness_controls():
    g = guard_for({"request_id": "R3", "vendor_id": "V4", "address": {**ADDR, "postal_code": ""}})
    assert not g.check("fill_field", {"ref": "postal_code", "value": "00400"}, obs())[0]   # copied original
    assert not g.check("fill_field", {"ref": "postal_code", "value": ""}, obs())[0]
    assert not g.check("fill_field", {"ref": "fail", "value": "on"}, obs())[0]           # checkbox
    assert not g.check("click_button", {"ref": "reset"}, obs())[0]
    assert not g.check("click_button", {"ref": "el1"}, obs("V4"))[0]                   # missing field


def test_guard_save_requires_exact_form_values_and_limits_retries():
    raw = {"request_id": "R1", "vendor_id": "V1", "address": ADDR}
    g = guard_for(raw)
    half = obs("V1", {"request": "R1", "line1": "1 Example Road", "city": "Demo City", "postal_code": "00123", "country": "Exampleland"})
    ok, msg = g.check("click_button", {"ref": "el1"}, half)
    assert not ok and "1 Example Road" in msg
    full = obs("V1", {"request": "R1", **ADDR})
    assert g.check("click_button", {"ref": "el1"}, full)[0]
    g.record_save(False)
    assert g.check("click_button", {"ref": "el1"}, full)[0]       # one retry allowed
    g.record_save(False)
    assert not g.check("click_button", {"ref": "el1"}, full)[0]   # no second retry


def test_guard_refuses_save_when_draft_already_listed():
    g = guard_for({"request_id": "R1", "vendor_id": "V1", "address": ADDR})
    drafts = '[{"request_id": "R1", "vendor_id": "V1", "address": {}}]'
    ok, msg = g.check("click_button", {"ref": "el1"}, obs("V1", {"request": "R1", **ADDR}, drafts))
    assert not ok and "already exists" in msg
