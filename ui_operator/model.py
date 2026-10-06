"""Model adapters, a recorder for real responses, and a replayer.

Transcript format (provider-neutral), built by the agent:
  {"role": "user", "text": ...}
  {"role": "assistant", "text": ..., "tool_call": {"id", "name", "args"}}
  {"role": "tool", "id": ..., "text": ..., "is_error": bool}

Every adapter returns a ModelTurn. Recorded turns carry `source` so a reviewer can
tell a live call from a replayed one or a test double.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import (DEFAULT_MODELS, MODEL_MAX_RETRIES, MODEL_MAX_TOKENS,
                     MODEL_TEMPERATURE, MODEL_TIMEOUT_S)


class ModelError(RuntimeError):
    """Model unavailable, refused, or returned something unusable."""


@dataclass
class ModelTurn:
    tool_name: str
    args: dict
    tool_call_id: str
    text: str = ""
    source: str = "live"            # live | replay | scripted-test-double | simulated-failure
    provider: str = ""
    model: str = ""
    latency_ms: int = 0
    usage: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    prompt_sha256: str = ""
    note: str = ""


def prompt_digest(system: str, transcript: list[dict], tools: list[dict]) -> str:
    blob = json.dumps({"system": system, "transcript": transcript, "tools": tools}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


# --------------------------------------------------------------------------- Anthropic
class AnthropicModel:
    provider = "anthropic"

    def __init__(self, model: str | None = None):
        try:
            import anthropic
        except ImportError as exc:
            raise ModelError("anthropic SDK not installed (pip install -r requirements.txt)") from exc
        key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("MODEL_API_KEY")
        if not key:
            raise ModelError("no API key: set ANTHROPIC_API_KEY (or MODEL_API_KEY) or use `replay`")
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=key, timeout=MODEL_TIMEOUT_S, max_retries=MODEL_MAX_RETRIES)
        self.model = model or DEFAULT_MODELS["anthropic"]
        self.sdk_version = anthropic.__version__

    def params(self) -> dict:
        # anthropic SDK 1.x exposes no sampling parameters (no temperature); provider default applies.
        return {"temperature": "provider default (not exposed by SDK)", "max_tokens": MODEL_MAX_TOKENS,
                "tool_choice": "any, no parallel tool use", "timeout_s": MODEL_TIMEOUT_S,
                "sdk": f"anthropic {self.sdk_version}"}

    @staticmethod
    def _messages(transcript: list[dict]) -> list[dict]:
        msgs: list[dict] = []
        for t in transcript:
            if t["role"] == "user":
                msgs.append({"role": "user", "content": [{"type": "text", "text": t["text"]}]})
            elif t["role"] == "assistant":
                content = []
                if t.get("text"):
                    content.append({"type": "text", "text": t["text"]})
                tc = t["tool_call"]
                content.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["args"]})
                msgs.append({"role": "assistant", "content": content})
            elif t["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": t["id"], "content": t["text"],
                         "is_error": bool(t.get("is_error"))}
                msgs.append({"role": "user", "content": [block]})
        return msgs

    def next_turn(self, system: str, transcript: list[dict], tools: list[dict]) -> ModelTurn:
        t0 = time.monotonic()
        try:
            resp = self.client.messages.create(
                model=self.model, system=system, messages=self._messages(transcript), tools=tools,
                tool_choice={"type": "any", "disable_parallel_tool_use": True},
                max_tokens=MODEL_MAX_TOKENS)
        except self._anthropic.APIError as exc:
            raise ModelError(f"{type(exc).__name__}: {exc}") from exc
        latency = int((time.monotonic() - t0) * 1000)
        uses = [b for b in resp.content if b.type == "tool_use"]
        text = " ".join(b.text for b in resp.content if b.type == "text").strip()
        if not uses:
            raise ModelError(f"model returned no tool call (stop_reason={resp.stop_reason})")
        u = uses[0]
        return ModelTurn(tool_name=u.name, args=dict(u.input), tool_call_id=u.id, text=text,
                         provider=self.provider, model=resp.model, latency_ms=latency,
                         usage={"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens},
                         raw=resp.model_dump(mode="json"))


# --------------------------------------------------------------------------- OpenAI
class OpenAIModel:
    """OpenAI-compatible chat-completions adapter. Not exercised in the author's
    environment (no OpenAI access there); provided so the hiring team's agreed
    provider can be used. See README 'Known limitations'."""
    provider = "openai"

    def __init__(self, model: str | None = None):
        try:
            import openai
        except ImportError as exc:
            raise ModelError("openai SDK not installed") from exc
        key = os.environ.get("OPENAI_API_KEY") or os.environ.get("MODEL_API_KEY")
        if not key:
            raise ModelError("no API key: set OPENAI_API_KEY (or MODEL_API_KEY) or use `replay`")
        self._openai = openai
        self.client = openai.OpenAI(api_key=key, base_url=os.environ.get("OPENAI_BASE_URL") or None,
                                    timeout=MODEL_TIMEOUT_S, max_retries=MODEL_MAX_RETRIES)
        self.model = model or DEFAULT_MODELS["openai"]
        self.sdk_version = openai.__version__

    def params(self) -> dict:
        return {"temperature": MODEL_TEMPERATURE, "max_tokens": MODEL_MAX_TOKENS,
                "tool_choice": "required", "timeout_s": MODEL_TIMEOUT_S, "sdk": f"openai {self.sdk_version}"}

    @staticmethod
    def _messages(system: str, transcript: list[dict]) -> list[dict]:
        msgs = [{"role": "system", "content": system}]
        for t in transcript:
            if t["role"] == "user":
                msgs.append({"role": "user", "content": t["text"]})
            elif t["role"] == "assistant":
                tc = t["tool_call"]
                msgs.append({"role": "assistant", "content": t.get("text") or None, "tool_calls": [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}]})
            elif t["role"] == "tool":
                msgs.append({"role": "tool", "tool_call_id": t["id"], "content": t["text"]})
        return msgs

    def next_turn(self, system: str, transcript: list[dict], tools: list[dict]) -> ModelTurn:
        fn_tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                       "parameters": t["input_schema"]}} for t in tools]
        t0 = time.monotonic()
        try:
            resp = self.client.chat.completions.create(
                model=self.model, messages=self._messages(system, transcript), tools=fn_tools,
                tool_choice="required", parallel_tool_calls=False,
                temperature=MODEL_TEMPERATURE, max_tokens=MODEL_MAX_TOKENS)
        except self._openai.OpenAIError as exc:
            raise ModelError(f"{type(exc).__name__}: {exc}") from exc
        latency = int((time.monotonic() - t0) * 1000)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            raise ModelError("model returned no tool call")
        call = msg.tool_calls[0]
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError as exc:
            raise ModelError(f"tool arguments are not valid JSON: {exc}") from exc
        return ModelTurn(tool_name=call.function.name, args=args, tool_call_id=call.id, text=msg.content or "",
                         provider=self.provider, model=resp.model, latency_ms=latency,
                         usage=resp.usage.model_dump() if resp.usage else {}, raw=resp.model_dump(mode="json"))


# --------------------------------------------------------------------------- record / replay
class Recorder:
    """Wraps a live model and appends every real response to model-calls.jsonl."""

    def __init__(self, inner, path: Path):
        self.inner, self.path = inner, path
        self.provider, self.model = inner.provider, inner.model
        self.context: dict = {}

    def params(self) -> dict:
        return self.inner.params()

    def next_turn(self, system, transcript, tools) -> ModelTurn:
        digest = prompt_digest(system, transcript, tools)
        self.inner.context = self.context
        try:
            turn = self.inner.next_turn(system, transcript, tools)
        except ModelError as exc:
            self._write({**self.context, "prompt_sha256": digest, "error": str(exc), "source": "live"})
            raise
        turn.prompt_sha256 = digest
        self._write({**self.context, **asdict(turn), "params": self.params(),
                     "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        return turn

    def _write(self, rec: dict):
        with self.path.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")


class ReplayModel:
    """Returns recorded real responses in order, keyed by (request label, step).
    No API key needed. Divergence from the recorded prompt is flagged on the turn."""
    provider = "replay"

    def __init__(self, calls_file: Path):
        self.calls_file = calls_file
        self.records: dict[tuple[str, int], dict] = {}
        for line in calls_file.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                self.records[(rec["request_label"], rec["step"])] = rec
        first = next(iter(self.records.values()), {})
        self.model = f"replay of {first.get('provider', '?')}/{first.get('model', '?')}"
        self.context: dict = {}

    def params(self) -> dict:
        return {"replay_source": str(self.calls_file)}

    def next_turn(self, system, transcript, tools) -> ModelTurn:
        key = (self.context.get("request_label"), self.context.get("step"))
        rec = self.records.get(key)
        if rec is None:
            raise ModelError(f"no recorded response for {key}")
        if "error" in rec:
            raise ModelError(f"recorded failure replayed: {rec['error']}")
        digest = prompt_digest(system, transcript, tools)
        note = "" if digest == rec.get("prompt_sha256") else (
            "DIVERGED: current prompt differs from the recorded one (portal, prompt or earlier step changed)")
        return ModelTurn(tool_name=rec["tool_name"], args=rec["args"], tool_call_id=rec["tool_call_id"],
                         text=rec.get("text", ""), source="replay", provider=rec.get("provider", ""),
                         model=rec.get("model", ""), usage=rec.get("usage", {}),
                         prompt_sha256=rec.get("prompt_sha256", ""), note=note)


def build_live_model(provider: str, model: str | None):
    if provider == "anthropic":
        return AnthropicModel(model)
    if provider == "openai":
        return OpenAIModel(model)
    raise ModelError(f"unknown provider {provider!r}")
