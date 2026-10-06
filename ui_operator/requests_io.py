"""Load and validate change requests; resolve vendors deterministically from the seed.

The deterministic resolver is used twice: by the action guard (so the model cannot
select a vendor the rules do not allow) and by the verifier (so a saved draft is
checked against the vendor the rules require, not the vendor the model picked).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import ADDRESS_FIELDS, EXTRA_FILE, SEED_FILE


@dataclass
class Request:
    request_id: str
    raw: dict
    address: dict
    vendor_id: str | None = None
    vendor_name: str | None = None
    simulate: str | None = None
    reprocess: bool = False
    input_errors: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.request_id} (reprocess)" if self.reprocess else self.request_id

    @property
    def missing_fields(self) -> list[str]:
        return [f for f in ADDRESS_FIELDS if not str(self.address.get(f, "")).strip()]

    def model_view(self) -> dict:
        """What the model sees: the request as data, minus harness-only keys."""
        return {k: v for k, v in self.raw.items() if k not in ("simulate", "purpose")}


def validate_request(raw: dict) -> list[str]:
    errors = []
    if not isinstance(raw.get("request_id"), str) or not raw["request_id"].strip():
        errors.append("request_id missing or not a string")
    if not raw.get("vendor_id") and not raw.get("vendor_name"):
        errors.append("neither vendor_id nor vendor_name given")
    addr = raw.get("address")
    if not isinstance(addr, dict):
        errors.append("address missing or not an object")
    else:
        for f in ADDRESS_FIELDS:
            if f not in addr:
                errors.append(f"address.{f} key missing")
            elif not isinstance(addr[f], str):
                errors.append(f"address.{f} must be text (got {type(addr[f]).__name__})")
        extra = set(addr) - set(ADDRESS_FIELDS)
        if extra:
            errors.append(f"unexpected address keys: {sorted(extra)}")
    return errors


def _to_request(raw: dict, reprocess: bool = False) -> Request:
    errors = validate_request(raw)
    addr = raw.get("address") if isinstance(raw.get("address"), dict) else {}
    return Request(
        request_id=str(raw.get("request_id", "")).strip() or "<missing>",
        raw=raw,
        address={f: addr.get(f, "") for f in ADDRESS_FIELDS},
        vendor_id=raw.get("vendor_id"),
        vendor_name=raw.get("vendor_name"),
        simulate=raw.get("simulate"),
        reprocess=reprocess,
        input_errors=errors,
    )


def load_seed(path: Path = SEED_FILE) -> dict:
    return json.loads(path.read_text())


def load_requests(seed_path: Path = SEED_FILE, extra_path: Path | None = EXTRA_FILE) -> list[Request]:
    seed = load_seed(seed_path)
    reqs = [_to_request(r) for r in seed["requests"]]
    if extra_path and extra_path.exists():
        extra = json.loads(extra_path.read_text())
        reqs += [_to_request(r) for r in extra.get("requests", [])]
        by_id = {r.request_id: r for r in reqs}
        for rp in extra.get("reprocess", []):
            original = by_id.get(rp["request_id"])
            if original:
                reqs.append(_to_request(original.raw, reprocess=True))
    seen = set()
    for r in reqs:
        if not r.reprocess:
            if r.request_id in seen:
                r.input_errors.append("duplicate request_id in input files")
            seen.add(r.request_id)
    return reqs


def _norm(s: str) -> str:
    return " ".join(s.split()).casefold()


@dataclass
class Resolution:
    vendor_id: str | None
    outcome: str          # "ok" | "needs-information" | "unresolved"
    reason: str
    candidates: list[str] = field(default_factory=list)


def resolve_vendor(req: Request, vendors: list[dict]) -> Resolution:
    """Rule 1: exact vendor ID, or an exact (unambiguous) full name.

    Choice recorded in reference/derivation.md: a partial name is never accepted,
    even if it matches a single vendor; it becomes needs-information.
    """
    ids = {v["vendor_id"]: v for v in vendors}
    if req.vendor_id:
        if req.vendor_id in ids:
            return Resolution(req.vendor_id, "ok", f"exact vendor ID {req.vendor_id}")
        return Resolution(None, "unresolved", f"unknown vendor ID {req.vendor_id}")
    name = _norm(req.vendor_name or "")
    exact = [v["vendor_id"] for v in vendors if _norm(v["name"]) == name]
    if len(exact) == 1:
        return Resolution(exact[0], "ok", f"exact name match {exact[0]}")
    partial = [v["vendor_id"] for v in vendors if name and name in _norm(v["name"])]
    if len(exact) > 1 or len(partial) > 1:
        return Resolution(None, "needs-information",
                          f"name matches {len(exact) or len(partial)} vendors; vendor ID needed",
                          exact or partial)
    if len(partial) == 1:
        return Resolution(None, "needs-information",
                          "name is only a partial match; confirm vendor ID", partial)
    return Resolution(None, "unresolved", f"no vendor named {req.vendor_name!r}")
