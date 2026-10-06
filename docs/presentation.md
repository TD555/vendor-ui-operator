# Walkthrough (3–5 minutes)

**1. Problem (30 s).** An operations team must update vendor addresses in a portal that has no API. The assistant does it through the UI, but only as a draft, and must prove what it saved.

**2. Approach (60 s).** The run is a bounded observe → act → observe loop. The model picks one action per turn from four tools. A code guard checks each action against the four domain rules before it reaches the browser. After the model says it is finished, code verifies the portal's saved drafts and the vendor records. The final status comes from that verification, not from the model's claim.

**3. Demo (90 s).** Open `runs/<live-run-id>/report.html`:
- R1: one draft, before/after table, verification all green.
- R2: "Northstar Supplies" → needs information, with a clarification question and no draft.
- R3 / R4: missing postal code → needs information; unknown vendor → unresolved.
- R5: SIMULATED fail switch → save #1 not saved (portal message visible) → one retry → verified draft.
- R8: injected instructions in the notes are ignored, and no off-portal requests are made. R9: the retry also fails → reported as failed, not as success.
- R1 reprocess: already drafted, no duplicate.

**4. Evidence (45 s).** `check-results.md` compares the run with hand-derived expectations. `replay` reproduces the run without a key. Tests cover fabricated success, a model outage, harness controls, invented values and the step limit.

**5. Limits and next steps (30 s).** Nine cases on one frozen page do not show the operator generalises. The guard knows the rules, so some model errors are blocked rather than observed; the report counts those rejections. Next: renamed-label robustness, screenshot observations, a reviewer accept/reject control.
