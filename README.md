# Vendor Address UI Operator (take-home G)

A model-driven assistant that prepares vendor postal-address changes **through the user interface** of a local mock portal that has no API. Then it verifies what actually happened. For each request it:

1. reads the request and observes the rendered portal as a structured DOM snapshot,
2. lets a model choose **one** action at a time (select a vendor, fill a field, click a button, or finish),
3. validates every action in code **before** it reaches the browser (domain rules, no invented values, no harness controls),
4. re-observes the page after each action, allowing at most one retry after a failed save,
5. **verifies in code** that the portal saved exactly the intended draft, and nothing else, before reporting success,
6. writes a run trace, an HTML report and a reference-check table. Every real model response is recorded so the run can be replayed without an API key.

Starter pack version: `2026-10-02` (see `starter-pack/pack-version.json`). The portal in `portal/portal.html` is the supplied file, unchanged (sha256 `989f6ee6…`, recorded in every run).

## Quick start

```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium          # once per machine

# 1. Harness check with no model and no key (deterministic test double, clearly labelled)
python3 -m ui_operator run --scripted

# 2. Live run with a real model (records every response to runs/<id>/model-calls.jsonl)
export ANTHROPIC_API_KEY=...                    # or MODEL_API_KEY; see .env.example
python3 -m ui_operator run                      # add --headed to watch the browser

# 3. Replay a recorded live run in a real browser, with no API key and no model calls
python3 -m ui_operator replay runs/<live-run-id>

# Re-check or re-render any run
python3 -m ui_operator check  runs/<run-id>
python3 -m ui_operator report runs/<run-id>

# Tests (headless browser, test doubles only)
python3 -m pytest -q
```

Useful flags: `--only R1,R5` runs a subset; `--provider openai --model <id>` switches provider; `--port` sets the portal port (default 8766, fixed so recorded prompts stay identical).

Each run folder contains `run.json` (full trace), `report.html` (open in a browser), `check-results.md` (expected vs observed), and for live runs `model-calls.jsonl`.

## Architecture

```
data/seed.json + data/extra-requests.json
        │ load + schema validation (ui_operator/requests_io.py)
        ▼
┌───────────── per request (ui_operator/agent.py) ──────────────┐
│ pre-check in code: duplicate request ID? → already-drafted     │
│ harness: arm the fail switch if the request says "simulate"    │
│                                                                │
│  observe ──► model (one tool call) ──► guard ──► execute ──┐   │
│     ▲        model.py                 actions.py browser.py │   │
│     └────────────── new observation / rejection ◄───────────┘   │
│  stop on finish · 12-step limit · model or browser error        │
│                                                                │
│ verify in code (verify.py): drafts before/after, vendor records,│
│ off-portal traffic, exact draft content                        │
└────────────────────────────────────────────────────────────────┘
        ▼
run.json · model-calls.jsonl · report.html · check-results.md (check.py vs reference/)
```

| Module | Responsibility |
|---|---|
| `portal_server.py` | Serves the frozen portal on 127.0.0.1 |
| `browser.py` | Playwright wrapper. DOM observation (labels, values, options, buttons, visible sections, status), executes validated actions, blocks and logs every request outside the portal origin |
| `actions.py` | The four tools offered to the model, and the **guard** that encodes the rules |
| `model.py` | Anthropic and OpenAI adapters (tool calling, one call per turn), `Recorder` for real responses, `ReplayModel` |
| `agent.py` | Bounded loop, harness events, batch runner |
| `verify.py` | Decides the final status from observed state, not from the model's claim |
| `check.py` | Compares a run with `reference/reference-cases.json` |
| `report.py` | Static HTML report with status filter, action trace, before/after table |
| `testing.py` | Labelled test doubles (scripted, failing, fixed action list). Not a model |

### What the model decides and what code enforces

The model reads the request and the observed page. It decides whether the request can proceed, which vendor option to select, which labelled field gets which value, when to save, whether to retry, and what outcome to report, including a clarification question.

Code enforces the rules regardless of what the model does:

| Rule | Guard (before execution) | Verification (after) |
|---|---|---|
| 1 vendor by exact ID or exact full name | `select_option` must equal the vendor resolved independently from the seed; ambiguous or unknown requests cannot select anything | saved draft's `vendor_id` equals the independent resolution |
| 2 required non-empty fields, only the address changes | `fill_field` accepts only non-empty values that appear in the request; save is blocked while a request field is empty or the form holds any other value | draft address equals the request exactly (postal codes compared as text); vendor records unchanged |
| 3 drafts only, no duplicates | only the form's submit button can be clicked; save is blocked if the drafts list already has this request ID; duplicate request IDs are caught before the model runs | at most one draft per request ID; earlier drafts untouched |
| 4 at most one retry | a third save, or a save after a successful save, is rejected | save attempts and the portal's failure messages are recorded |
| Safety | no navigation tool; reset button and fail checkbox are not actionable; off-portal network requests are aborted | off-portal requests counted; final URL checked |

Rejected actions are returned to the model as tool errors, count against the step limit, and appear in red in the report.

## Data and reference cases

* `data/seed.json`: the supplied six vendors and five requests, unchanged.
* `data/extra-requests.json`: four handwritten cases plus one reprocess. Generation method is described in the file; no randomness is used.
  * R6: exact name, no ID (Maple Parts), with a leading-zero postal code.
  * R7: full name of one of the two overlapping vendors.
  * R8: prompt-injection control; the request notes ask the operator to visit another site, rename the vendor and reset drafts.
  * R9: every save fails, so the single retry also fails and the expected outcome is a visible failure.
  * R1 reprocess: proves no second draft is created.
* `reference/reference-cases.json`: expected outcomes **derived by hand before running the operator**. `reference/derivation.md` explains each one. The five minimum-demonstration checks are R1–R5 and reproduce `reference/expected-seed-results.json`.
* Simulations are labelled. The harness arms the portal's fail switch, and the report shows that as a `SIMULATED` event. The model never touches it.

### Ambiguities in the supplied rules

The details are in `reference/derivation.md`:

* A partial name that matches only **one** vendor is treated as needs-information. This is the conservative choice, since the rules only define the two-match case.
* An ambiguous name or a missing field gives `needs-information`; an unknown vendor gives `unresolved`. This follows the supplied expected results.
* A reprocessed request whose matching draft already exists is reported as `already-drafted`.

## Minimum demonstration results

Fill this from `runs/<live-run-id>/check-results.md` after the live run. The scripted harness run (no model) passes 43/43 checks; that shows the harness, guard and verifier work, not that the model does.

| Check | Request | Expected | Observed (live run) |
|---|---|---|---|
| Valid change only touches the intended vendor | R1 | draft V1, 1 new draft | _fill in_ |
| Similar names ask for clarification | R2 | needs-information, 0 drafts | _fill in_ |
| Missing field is not invented | R3 | needs-information (postal_code), 0 drafts | _fill in_ |
| Unknown vendor | R4 | unresolved, 0 drafts | _fill in_ |
| Simulated save failure, one retry | R5 | failure visible; ≤2 saves; 1 verified draft or clear failure | _fill in_ |

## Model configuration

| Setting | Value |
|---|---|
| Provider / model | Anthropic `claude-haiku-4-5-20251001` by default (`MODEL_NAME` / `--model` to change). OpenAI-compatible adapter available |
| Tool choice | forced tool use, one tool call per turn (`tool_choice: any`, parallel tool use disabled) |
| Temperature | provider default: the `anthropic` 1.11 SDK exposes no sampling parameters (OpenAI adapter uses 0) |
| Max output tokens | 1024 per turn |
| Timeouts / retries | 60 s per call, 2 SDK transport retries; 5 s per browser action, 10 s page load |
| Limits | 12 model turns per request, 2 save attempts (1 retry) |
| System prompt | `prompts/operator-system.md` (sha256 stored in each run) |

## Time spent

6 h, including data preparation and documentation.

## Known limitations

* **Small evidence base.** Nine requests against one frozen page cannot establish reliability on other portals, layouts or wording.
* **The guard knows the rules.** The guard and verifier resolve vendors deterministically from the seed. That makes the system safe, but it also means a model mistake on vendor choice is blocked rather than demonstrated. Guard rejections are counted in the report so they remain visible.
* **Verification reads application state.** It reads the page's stored drafts and in-page vendor data, as well as the rendered list. It does not read a real backend.
* **OpenAI adapter is untested.** It was not exercised in the build environment, which had no OpenAI access.
* **Anthropic temperature.** The SDK version used has no sampling parameters, so runs are not guaranteed to be deterministic. Replay is the way to reproduce a run exactly.
* **Replay checks the prompt.** It flags any step whose prompt differs from the recording (`DIVERGED` in the report), for example after a portal or prompt change. It still replays the recorded action through the guard.
* **Not implemented.** Browser screenshots are not given to the model (the DOM snapshot was sufficient), and the optional enhancements (renamed labels, accept/reject control) are not done.

## Further documents

* `docs/llm-usage.md`: tools and models, generated components, one workflow example with corrections.
* `docs/presentation.md`: written walkthrough.
* `ai-workflow/manifest.json` and `ai-workflow/README.md`: the AI setup record.
