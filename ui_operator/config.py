"""Paths and limits. Everything tunable lives here so the run record can capture it."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTAL_DIR = ROOT / "portal"
PORTAL_FILE = "portal.html"
SEED_FILE = ROOT / "data" / "seed.json"
EXTRA_FILE = ROOT / "data" / "extra-requests.json"
REFERENCE_FILE = ROOT / "reference" / "reference-cases.json"
PROMPT_FILE = ROOT / "prompts" / "operator-system.md"
RUNS_DIR = ROOT / "runs"

PORTAL_HOST = "127.0.0.1"
PORTAL_PORT = int(os.environ.get("PORTAL_PORT", "8766"))

# Bounded agent loop
MAX_STEPS_PER_REQUEST = 12      # model turns per request, including rejected actions
MAX_SAVE_ATTEMPTS = 2           # first save + at most one retry (rule 4)
BROWSER_ACTION_TIMEOUT_MS = 5000
PAGE_LOAD_TIMEOUT_MS = 10000

# Model integration (application runtime, not the development tool)
DEFAULT_PROVIDER = os.environ.get("MODEL_PROVIDER", "anthropic")
DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4.1-mini",
}
MODEL_NAME = os.environ.get("MODEL_NAME", "")
MODEL_TEMPERATURE = 0.0
MODEL_MAX_TOKENS = 1024
MODEL_TIMEOUT_S = 60
MODEL_MAX_RETRIES = 2           # SDK-level transport retries only

ADDRESS_FIELDS = ("line1", "city", "postal_code", "country")
