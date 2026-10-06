# AI workflow used during this exercise

## Tools and models

| Scope | Tool / model | Settings changed |
|---|---|---|
| Development | Claude app agentic session (shell plus file tools in a cloud workspace), configured model `claude-opus-5-5` | none (default) |
| Application | Anthropic Messages API, `claude-haiku-4-5-20251001`, `anthropic` SDK 1.11.0 | `max_tokens=1024`; forced tool use with one call per turn; timeout 60 s; 2 transport retries. Temperature: provider default, because the SDK exposes no sampling parameters |
| Application (alternative) | OpenAI-compatible API, `gpt-4.1-mini` default, `openai` SDK 3.24.0 | `temperature=0`, `max_tokens=1024`, `tool_choice=required`. **Not exercised** |
| Browser | Playwright 1.56.0 + Chromium (headless by default) | 5 s action timeout, 10 s page load, all non-portal requests aborted |

## Configuration files

| What | Path | Status |
|---|---|---|
| Runtime system prompt | `prompts/operator-system.md` | used. Versions are in git history; the sha256 is in every `run.json` |
| Tool definitions + guard | `ui_operator/actions.py` | used |
| Model parameters and limits | `ui_operator/config.py` | used |
| Model adapters, recorder, replay | `ui_operator/model.py` | used |
| Environment variable names | `.env.example` (copy here: `ai-workflow/.env.example`) | used, values redacted |
| Development agent instructions (CLAUDE.md, AGENTS.md, rules) | none | not-used |
| Skills | starter-pack `generate-assignment-data` was read for guidance only | not-used |
| Subagents, hooks, MCP servers, editor plugins | none | not-used |
| Development tool permissions | hosted session | not-exportable |

No user-level configuration was copied. The only secret is the API key. It is read from the environment and never logged, so no file contains it.

## One workflow example

**Instruction:** build the G operator from the brief and starter pack. The model must act only through the observed UI, every action is validated before execution, the saved state is verified in code, and real responses are recorded for replay.

**Configuration that affected it:** the default development session only. At runtime, the system prompt and the guard in `actions.py`.

**Check:** I ran a scripted harness run and the pytest suite (14 tests, which include negative tests for a fabricated success, the reset button, a wrong vendor, an invented value, a model outage and the step limit). I also ran the live path with a dummy key and looked at a screenshot of the report.

**Correction:** the live-path run failed with `unexpected keyword argument 'temperature'` from the Anthropic SDK. I removed the parameter and recorded "provider default" in the run metadata instead. Three more corrections are listed in `docs/llm-usage.md`.

## Reproduce or replay

```bash
python3 -m pip install -r requirements.txt && python3 -m playwright install chromium
python3 -m ui_operator replay runs/<live-run-id>     # no key, real browser, recorded model responses
python3 -m ui_operator run                           # new live run (needs ANTHROPIC_API_KEY or MODEL_API_KEY)
```

Replay feeds each recorded response back at the same request and step. It compares the current prompt hash with the recorded one and marks any mismatch `DIVERGED`. The recorded action still passes through the guard, and the outcome is still verified against the real portal. No hooks exist, so nothing runs implicitly.

## Decisions and limitations

* A default development setup was enough for a one-day exercise. Custom skills, agents and hooks would have added nothing the brief assesses.
* A small, fast model was chosen for the runtime because the task is a short, bounded loop over a small DOM snapshot. Swap it with `--model` if the hiring team provides a different one.
* The model sees a DOM-derived observation rather than screenshots. That is cheaper and deterministic, and the brief explicitly allows it.
* Change next: try a screenshot-based observation and compare the two, and exercise the OpenAI adapter.
