"""
The Bright / Dark switch in the top bar.

Clicking it switches Streamlit's own theme (tables, dropdowns, sidebar) right
away in the browser, remembers the choice for the next visit, and tells Python
the new mode so charts and table tints are redrawn to match. Both looks are
defined in .streamlit/config.toml ([theme.light] and [theme.dark]); the site's
CSS follows the active one by itself (see _root_vars() in theme.py).

First-time visitors get the bright look whatever their phone or computer uses.
"""
from __future__ import annotations

import streamlit as st

_SUN = ('<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M4.6 4.6l1.6 '
        '1.6M17.8 17.8l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6"/></svg>')
_MOON = ('<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" '
         'stroke-linecap="round" stroke-linejoin="round"><path d="M20.5 13.4A8.6 8.6 0 1 1 10.6 3.5a6.7 6.7 0 0 0 '
         '9.9 9.9z"/></svg>')

_HTML = f"""
<div class="sw" role="group" aria-label="Colour theme">
  <button type="button" data-mode="light" aria-pressed="true" title="Bright theme">{_SUN}<span>Bright</span></button>
  <button type="button" data-mode="dark" aria-pressed="false" title="Dark theme">{_MOON}<span>Dark</span></button>
</div>
"""

_CSS = """
:host { display: inline-block; }
.sw {
  display: inline-flex; align-items: center; gap: 2px; padding: 3px;
  border: 1px solid var(--line, #DFE4EC); border-radius: 999px; background: var(--panel, #F6F8FB);
  font-family: var(--body, system-ui, sans-serif);
}
button {
  all: unset; box-sizing: border-box; cursor: pointer;
  display: inline-flex; align-items: center; gap: .4rem;
  padding: .3rem .8rem .32rem; border-radius: 999px;
  font-size: .88rem; font-weight: 600; line-height: 1.2; white-space: nowrap;
  color: var(--muted, #667089); transition: background-color .15s ease, color .15s ease;
}
button:hover { color: var(--ink, #0E1528); }
button[aria-pressed="true"] { background: var(--flood, #C47510); color: var(--on-flood, #FFFFFF); cursor: default; }
button:focus-visible { outline: 2px solid var(--flood, #C47510); outline-offset: 2px; }
svg { width: 15px; height: 15px; flex: none; }
@media (max-width: 640px) {
  button { padding: .42rem .6rem; }
  button span { display: none; }
  svg { width: 16px; height: 16px; }
}
@media (prefers-reduced-motion: reduce) { button { transition: none; } }
"""

_JS = r"""
export default function (component) {
  const { parentElement, data, setStateValue } = component;
  const root = parentElement;
  const host = root.host || root;
  const W = (window.__wzTheme = window.__wzTheme || { last: 0, booted: false });
  W.data = data || {};
  W.set = setStateValue;
  W.root = root;

  const store = {
    get(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* storage blocked */ } },
  };
  const appEl = () => document.querySelector('[data-testid="stApp"]');
  // Streamlit puts color-scheme: light | dark on the app for the active theme.
  const scheme = () => {
    const a = appEl();
    return a && /dark/.test(getComputedStyle(a).colorScheme) ? 'dark' : 'light';
  };

  // Streamlit's settings menu switches themes through a React context that holds
  // setTheme() and the available themes; use the same one.
  const fiberOf = (el) => {
    const k = Object.keys(el).find((n) => n.startsWith('__reactFiber$'));
    return k ? el[k] : null;
  };
  function themeContext() {
    let el = host;
    while (el && !fiberOf(el)) el = el.parentElement;
    for (let f = el && fiberOf(el); f; f = f.return) {
      const v = f.memoizedProps && f.memoizedProps.value;
      if (v && typeof v === 'object' && typeof v.setTheme === 'function' && Array.isArray(v.availableThemes)) return v;
    }
    return null;
  }
  const NAMES = { light: ['Custom Theme Light', 'Light'], dark: ['Custom Theme Dark', 'Dark'] };
  function applyNative(mode) {
    const ctx = themeContext();
    if (!ctx) return false;
    const theme = NAMES[mode].map((n) => ctx.availableThemes.find((t) => t.name === n)).find(Boolean);
    if (!theme) return false;
    if (!ctx.activeTheme || ctx.activeTheme.name !== theme.name) ctx.setTheme(theme);
    return true;
  }

  function remember(mode) {
    store.set('wz-theme', mode);
    document.cookie = 'wz_theme=' + mode + '; path=/; max-age=31536000; SameSite=Lax';
    // Streamlit keeps its own theme choice per page address: save it for every
    // page so a link to any page opens straight in this look.
    const saved = JSON.stringify(mode === 'dark' ? 'Dark' : 'Light');
    const base = location.pathname.replace(/[^/]*$/, '');
    const paths = new Set([location.pathname, base].concat((W.data.pages || []).map((u) => base + u)));
    paths.forEach((p) => store.set('stActiveTheme-' + p + '-v2', saved));
  }
  function paint(mode) {
    if (!W.root) return;
    W.root.querySelectorAll('button[data-mode]').forEach((b) => {
      b.setAttribute('aria-pressed', String(b.dataset.mode === mode));
    });
  }
  // Tell Python, so charts and table tints are redrawn in this look.
  function tell(mode) {
    if (W.data.mode === mode) { W.pending = null; return; }
    if (W.pending === mode) return;
    W.pending = mode;
    W.set('mode', mode);
  }
  // Right after a click the app may not have repainted yet: trust the click.
  const current = () => (W.chosen && Date.now() - W.last < 2000 ? W.chosen : scheme());

  function choose(mode) {
    W.chosen = mode;
    W.last = Date.now();
    remember(mode);
    paint(mode);
    if (!applyNative(mode)) { location.reload(); return; }
    tell(mode);
  }
  root.querySelectorAll('button[data-mode]').forEach((b) => { b.onclick = () => choose(b.dataset.mode); });

  // Once per page load: the visitor's saved choice, else the bright default.
  if (!W.booted) {
    W.booted = true;
    const saved = store.get('wz-theme');
    const want = saved === 'dark' || saved === 'light' ? saved : (W.data.fallback || 'light');
    if (scheme() !== want && applyNative(want)) { W.chosen = want; W.last = Date.now(); }
  }

  // Keep the switch and Python in step with any other theme change.
  if (W.observer) W.observer.disconnect();
  const app = appEl();
  if (app) {
    W.observer = new MutationObserver(() => requestAnimationFrame(() => {
      const m = current();
      paint(m);
      tell(m);
    }));
    W.observer.observe(app, { attributes: true, attributeFilter: ['class'] });
  }
  const m = current();
  paint(m);
  tell(m);
}
"""

_SWITCH = st.components.v2.component("wz_theme_switch", html=_HTML, css=_CSS, js=_JS)


def _noop() -> None:
    pass


def render(mode: str, fallback: str) -> None:
    """Draw the switch. `mode` is what Python is drawing in this run."""
    from views.registry import PAGE_INFO  # local import: views import components

    _SWITCH(
        key="wz_theme",
        data={"mode": mode, "fallback": fallback, "pages": list(PAGE_INFO)},
        on_mode_change=_noop,
        width="content",
    )
