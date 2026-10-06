# LLM usage note

## Tools and models

| Where | Tool / model | Use |
|---|---|---|
| Development | Claude in the Claude app (agentic session with a shell and a cloud workspace; configured model `claude-opus-5-5`) | Analysed the brief and starter pack, then generated all application code, tests, fixtures for R6–R9, reference cases and these docs |
| Application runtime | Anthropic Messages API, `claude-haiku-4-5-20251001` by default, via `anthropic` SDK 1.11.0 | Chooses each UI action and the final outcome (`ui_operator/model.py`) |
| Application runtime (alternative) | OpenAI-compatible chat completions via `openai` SDK 3.24.0 | Same role; adapter not exercised in the build environment |

## Generated components

AI generated all of it: `ui_operator/*` (loop, guard, verifier, browser wrapper, adapters, record/replay, report, check), `tests/*`, `prompts/operator-system.md`, `data/extra-requests.json`, `reference/*`, README and docs. I reviewed the code, ran the tests, and inspected the report and the live run. _Edit this paragraph to reflect what you personally reviewed or changed._

## Representative instruction

> "Let's start building the G task" — after an earlier analysis of the brief. The assistant was then directed (by the brief's requirements) to: keep the portal frozen, let the model act only through observed UI, validate actions before execution, verify saved state in code, record real responses for replay, and keep expected results separate from application output.

The design decision that came out of it is to split the work. The model chooses actions and outcomes; code guards each action and verifies the result. The guard's rule table is in the README.

## Corrections and verification steps (real, from this build)

1. **SDK parameter mismatch found by running the live path.** The first live-path run, using a dummy key to exercise the plumbing, failed with `TypeError: Messages.create() got an unexpected keyword argument 'temperature'`. The installed `anthropic` 1.11 SDK exposes no sampling parameters. Fix: removed `temperature` from the Anthropic call, recorded "provider default" in the model parameters, and documented that replay, not temperature 0, is the reproducibility mechanism. Re-running then reached the API and produced a visible `401 AuthenticationError` → `failed` status for every request, with the batch continuing. That run also confirmed the "model unavailable" path.
2. **Recorder bug caught by a test.** `test_record_then_replay_reproduces_outcomes` failed: every request ended `operator error: KeyError: 'request_label'`, because the recording wrapper did not pass the request/step context to the wrapped model. Fixed in `Recorder.next_turn`; the test now proves a recorded run replays with identical outcomes and no divergence.
3. **Replay stability (design correction).** The first observation text included the page URL. Tests use a random port, so the same run would hash to different prompts and replay would wrongly report divergence. The URL was removed from the model's observation; the final URL is still checked in verification.
4. **Report inspected visually.** A screenshot showed that the request JSON overflowed its column and hid the before/after table. Fixed the grid and wrapped the JSON.

_Add here what you observed in your live run, e.g. any action the guard rejected and how you responded (prompt change, or accepted as a caught model error)._
