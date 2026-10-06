"""Playwright wrapper: observe the rendered portal, execute validated actions.

The model never gets a raw browser. It sees a DOM-derived observation (labels,
control values, buttons, visible text) and may request one of three action kinds
by element ref. All network traffic outside the local portal origin is blocked
and recorded.
"""
from __future__ import annotations

import json

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from .config import BROWSER_ACTION_TIMEOUT_MS, PAGE_LOAD_TIMEOUT_MS

DRAFTS_STORAGE_KEY = "junior-vendor-drafts-v1"  # read only by the verifier, never by the model

_OBSERVE_JS = r"""
() => {
  window.__opN = window.__opN || 0;
  const ref = el => {
    if (!el.dataset.opRef) el.dataset.opRef = el.id || ('el' + (++window.__opN));
    return el.dataset.opRef;
  };
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const controls = [];
  for (const label of document.querySelectorAll('label')) {
    const c = label.control;
    if (!c || !visible(c)) continue;
    const text = [...label.childNodes].filter(x => x.nodeType === 3)
      .map(x => x.textContent).join(' ').replace(/\s+/g, ' ').trim();
    const kind = c.tagName === 'SELECT' ? 'select' : (c.type === 'checkbox' ? 'checkbox' : 'text');
    const item = {ref: ref(c), label: text, kind, disabled: c.disabled};
    if (kind === 'select') {
      item.value = c.value;
      item.options = [...c.options].map(o => ({value: o.value, text: o.textContent.trim()}));
    } else if (kind === 'checkbox') {
      item.checked = c.checked;
    } else {
      item.value = c.value;
      item.required = c.required;
    }
    controls.push(item);
  }
  const buttons = [...document.querySelectorAll('button')].filter(visible).map(b => ({
    ref: ref(b), text: b.textContent.trim(), submits_form: !!b.form && b.type === 'submit'
  }));
  const sections = [...document.querySelectorAll('h2')].map(h => {
    const s = h.nextElementSibling;
    return {heading: h.textContent.trim(), text: s && s.tagName === 'PRE' ? s.textContent : ''};
  });
  const status = [...document.querySelectorAll('[role=status]')].map(e => e.textContent.trim()).join(' | ');
  return {url: location.href, title: document.title,
          heading: (document.querySelector('h1') || {}).textContent || '',
          controls, buttons, sections, status};
}
"""


class BrowserUnavailable(RuntimeError):
    pass


class PortalBrowser:
    def __init__(self, portal_url: str, origin: str, headless: bool = True):
        self.portal_url, self.origin, self.headless = portal_url, origin, headless
        self.blocked_requests: list[str] = []
        self._pw = self._browser = self._context = self.page = None

    # lifecycle -----------------------------------------------------------
    def __enter__(self):
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=self.headless)
            self._context = self._browser.new_context()
            self._context.route("**/*", self._guard_route)
            self.page = self._context.new_page()
            self.page.set_default_timeout(BROWSER_ACTION_TIMEOUT_MS)
            self.page.goto(self.portal_url, timeout=PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightError as exc:
            self.__exit__()
            raise BrowserUnavailable(str(exc)) from exc
        return self

    def __exit__(self, *exc):
        for closer in (self._context, self._browser):
            try:
                closer and closer.close()
            except Exception:
                pass
        if self._pw:
            self._pw.stop()

    def _guard_route(self, route):
        url = route.request.url
        if url.startswith(self.origin + "/"):
            route.continue_()
        else:
            self.blocked_requests.append(url)
            route.abort()

    # observation ---------------------------------------------------------
    def reload(self):
        """Fresh form state for the next request; drafts persist in the page's storage."""
        self.page.goto(self.portal_url, timeout=PAGE_LOAD_TIMEOUT_MS)

    def observe(self) -> dict:
        return self.page.evaluate(_OBSERVE_JS)

    # actions (already validated by the guard) -----------------------------
    def _locator(self, ref: str):
        return self.page.locator(f'[data-op-ref="{ref}"]')

    def execute(self, name: str, args: dict) -> dict:
        try:
            loc = self._locator(args["ref"])
            if name == "select_option":
                loc.select_option(value=args["value"])
            elif name == "fill_field":
                loc.fill(args["value"])
            elif name == "click_button":
                loc.click()
            else:
                return {"ok": False, "error": f"unsupported action {name}"}
            return {"ok": True}
        except PlaywrightError as exc:
            return {"ok": False, "error": str(exc).splitlines()[0]}

    # harness + verifier (never exposed to the model) ----------------------
    def harness_set_fail_switch(self, on: bool):
        box = self.page.locator("#fail")
        box.check() if on else box.uncheck()

    def harness_reset_drafts(self):
        self.page.locator("#reset").click()

    def stored_drafts(self) -> list[dict]:
        raw = self.page.evaluate(f"localStorage.getItem('{DRAFTS_STORAGE_KEY}')")
        return json.loads(raw) if raw else []

    def rendered_drafts(self) -> list[dict]:
        text = self.page.locator("#drafts").inner_text()
        return json.loads(text) if text.strip() else []

    def portal_vendors(self) -> list[dict]:
        return self.page.evaluate("JSON.parse(JSON.stringify(vendors))")

    @property
    def current_url(self) -> str:
        return self.page.url


def render_observation(obs: dict) -> str:
    """Compact text form of the observation for the model."""
    # The URL is deliberately left out so recorded prompts stay identical across ports.
    lines = [f"PAGE: {obs['title']} — {obs['heading']}",
             f"STATUS MESSAGE: {obs['status'] or '(empty)'}", "", "CONTROLS:"]
    for c in obs["controls"]:
        if c["kind"] == "select":
            opts = "; ".join(f"{o['value'] or '(none)'} = {o['text']}" for o in c["options"])
            lines.append(f"  [{c['ref']}] select \"{c['label']}\" selected={c['value']!r} options: {opts}")
        elif c["kind"] == "checkbox":
            lines.append(f"  [{c['ref']}] checkbox \"{c['label']}\" checked={c['checked']}")
        else:
            lines.append(f"  [{c['ref']}] text input \"{c['label']}\" value={c['value']!r}")
    lines.append("BUTTONS:")
    for b in obs["buttons"]:
        kind = "submits the form" if b["submits_form"] else "standalone button"
        lines.append(f"  [{b['ref']}] \"{b['text']}\" ({kind})")
    lines.append("SECTIONS:")
    for s in obs["sections"]:
        lines.append(f"  == {s['heading']} ==")
        lines += [f"    {ln}" for ln in (s["text"] or "(empty)").splitlines()]
    return "\n".join(lines)
