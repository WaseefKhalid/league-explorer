"""
Public and admin access.

Everyone can view every analysis and download any analysis as a PNG.
The admin (one password) also gets the Raw Data page and CSV downloads.

The password is never in the code: it lives in the app's Secrets on Streamlit
Community Cloud (App settings → Secrets), as

    ADMIN_PASSWORD = "your password here"

Without that secret, admin sign-in is switched off and the site stays public-only.
Admin rights last for the browser tab's session; closing the tab signs out.
"""
from __future__ import annotations

import hmac
import time

import streamlit as st

_KEY = "wz_admin"
_FAILS = "wz_admin_fails"
_LOCKED_UNTIL = "wz_admin_locked_until"

SESSION_TRIES = 5          # wrong passwords allowed in one tab …
SESSION_LOCK_S = 300       # … before that tab waits 5 minutes
GLOBAL_TRIES = 30          # wrong passwords from everyone together …
GLOBAL_WINDOW_S = 900      # … within 15 minutes pause sign-in for everyone for 15 minutes


def _secret() -> str:
    try:
        return str(st.secrets.get("ADMIN_PASSWORD", "") or "")
    except Exception:          # no secrets file at all
        return ""


def configured() -> bool:
    return bool(_secret())


def is_admin() -> bool:
    return bool(st.session_state.get(_KEY)) and configured()


@st.cache_resource
def _failures() -> list[float]:
    """Times of recent wrong passwords, shared by every visitor (one server process)."""
    return []


def _recent_failures() -> list[float]:
    log = _failures()
    cutoff = time.time() - GLOBAL_WINDOW_S
    log[:] = [t for t in log if t > cutoff]
    return log


def _wait_seconds() -> int:
    now = time.time()
    wait = st.session_state.get(_LOCKED_UNTIL, 0) - now
    log = _recent_failures()
    if len(log) >= GLOBAL_TRIES:
        wait = max(wait, log[-1] + GLOBAL_WINDOW_S - now)
    return max(0, int(wait + 0.999))


def _try_sign_in(password: str) -> bool:
    secret = _secret()
    ok = bool(secret) and hmac.compare_digest(password.encode("utf-8"), secret.encode("utf-8"))
    if ok:
        st.session_state[_KEY] = True
        st.session_state[_FAILS] = 0
        return True
    _failures().append(time.time())
    fails = st.session_state.get(_FAILS, 0) + 1
    st.session_state[_FAILS] = fails
    if fails >= SESSION_TRIES:
        st.session_state[_LOCKED_UNTIL] = time.time() + SESSION_LOCK_S
        st.session_state[_FAILS] = 0
    return False


def _sign_out() -> None:
    st.session_state[_KEY] = False


def panel() -> None:
    """The small Admin control at the bottom of the sidebar."""
    if not configured():
        return
    if is_admin():
        st.caption(":material/verified_user: Signed in as admin")
        st.button("Sign out", on_click=_sign_out, icon=":material/logout:", width="stretch", key="wz_admin_out")
        return
    with st.popover("Admin", icon=":material/lock:", width="stretch"):
        wait = _wait_seconds()
        if wait:
            mins = max(1, round(wait / 60))
            st.caption(f"Too many wrong passwords. Try again in about {mins} minute{'s' if mins > 1 else ''}.")
            return
        with st.form("wz_admin_form", clear_on_submit=True, border=False):
            pw = st.text_input("Admin password", type="password", autocomplete="current-password")
            go = st.form_submit_button("Sign in", type="primary", width="stretch")
        if go:
            if pw and _try_sign_in(pw):
                st.rerun()
            if _wait_seconds():       # that was the last try: show the wait message now
                st.rerun()
            st.error("That password isn't right.", icon=":material/error:")


def public_css() -> str:
    """Visitors who aren't admin: no 'Download as CSV' on tables (PNG downloads stay)."""
    if is_admin():
        return ""
    return ('<style>[data-testid="stElementToolbar"] button[aria-label="Download as CSV"]'
            '{display:none !important;}</style>')
