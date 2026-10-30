"""
Publish a league built on Admin · Add a league straight into the site's GitHub repository
(data/leagues/<slug>/), in one commit. Streamlit Cloud updates the app from the repository, so
the league then stays on the site for everyone, like the PSL.

Needs two Streamlit secrets (app → Settings → Secrets); they are never in the code:
    GITHUB_TOKEN = "github_pat_…"     # fine-grained token: this repository only, Contents read & write
    GITHUB_REPO  = "WaseefKhalid/league-explorer"
Optional: GITHUB_BRANCH (default "main").
"""
from __future__ import annotations

import base64
import io
import json

import pandas as pd
import requests
import streamlit as st

API = "https://api.github.com"


class PublishError(Exception):
    def __init__(self, text: str, status: int = 0):
        super().__init__(text)
        self.status = status


def _secret(name: str, default: str | None = None) -> str | None:
    try:
        v = st.secrets.get(name)
    except Exception:            # noqa: BLE001 — no secrets file at all
        v = None
    v = str(v).strip() if v is not None else ""
    return v or default


def configured() -> bool:
    return bool(_secret("GITHUB_TOKEN") and _secret("GITHUB_REPO"))


def repo() -> str:
    return _secret("GITHUB_REPO", "") or ""


def league_files(tables: dict[str, pd.DataFrame], meta: dict) -> dict[str, bytes]:
    """Repository path → file bytes for one league folder."""
    root = f"data/leagues/{meta['slug']}"
    out = {}
    for name, df in sorted(tables.items()):
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        out[f"{root}/{name}.parquet"] = buf.getvalue()
    out[f"{root}/meta.json"] = (json.dumps(meta, indent=2, ensure_ascii=False, default=str) + "\n").encode()
    return out


def _explain(r: requests.Response, what: str) -> PublishError:
    try:
        msg = r.json().get("message", "")
    except ValueError:
        msg = r.text[:200]
    if r.status_code == 401:
        text = "GitHub didn't accept the token (GITHUB_TOKEN is wrong or has expired)."
    elif r.status_code in (403, 404):
        text = (f"The token can't write to {repo()}. Give it access to that repository with "
                "Contents: Read and write, and check GITHUB_REPO.")
    else:
        text = f"GitHub refused the {what} ({r.status_code}: {msg})."
    return PublishError(text, r.status_code)


def publish(files: dict[str, bytes], message: str, folder: str, progress=None) -> str:
    """One commit that writes `files` and removes anything else left in `folder` (an older build).
    Returns the commit's web address. `progress(fraction, text)` is called as files go up."""
    token, rp = _secret("GITHUB_TOKEN"), _secret("GITHUB_REPO")
    if not (token and rp):
        raise PublishError("Publishing isn't set up: add GITHUB_TOKEN and GITHUB_REPO to the app's secrets.")
    branch = _secret("GITHUB_BRANCH", "main")
    api = (_secret("GITHUB_API", API) or API).rstrip("/")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                      "X-GitHub-Api-Version": "2022-11-28"})

    def call(method: str, path: str, what: str, **kw) -> dict:
        try:
            r = s.request(method, f"{api}/repos/{rp}/{path}", timeout=90, **kw)
        except requests.RequestException as e:
            raise PublishError(f"Couldn't reach GitHub ({type(e).__name__}). Try again in a moment.") from e
        if r.status_code >= 300:
            raise _explain(r, what)
        return r.json()

    entries = []
    for i, (path, data) in enumerate(files.items()):
        if progress:
            progress(0.05 + 0.8 * i / max(len(files), 1), f"Uploading {path.rsplit('/', 1)[-1]}")
        blob = call("POST", "git/blobs", "upload", json={"content": base64.b64encode(data).decode(),
                                                          "encoding": "base64"})
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    folder = folder.rstrip("/") + "/"
    for attempt in range(3):           # someone else may commit in between: start again from the new tip
        if progress:
            progress(0.9, "Committing")
        head = call("GET", f"git/ref/heads/{branch}", "branch lookup")["object"]["sha"]
        base_tree = call("GET", f"git/commits/{head}", "commit lookup")["tree"]["sha"]
        old = call("GET", f"git/trees/{base_tree}?recursive=1", "file list").get("tree", [])
        keep = {e["path"] for e in entries}
        stale = [{"path": t["path"], "mode": "100644", "type": "blob", "sha": None} for t in old
                 if t.get("type") == "blob" and t["path"].startswith(folder) and t["path"] not in keep]
        tree = call("POST", "git/trees", "folder", json={"base_tree": base_tree, "tree": entries + stale})["sha"]
        commit = call("POST", "git/commits", "commit", json={"message": message, "tree": tree, "parents": [head]})
        try:
            call("PATCH", f"git/refs/heads/{branch}", "branch update", json={"sha": commit["sha"], "force": False})
        except PublishError as e:
            if e.status == 422 and attempt < 2:
                continue
            raise
        if progress:
            progress(1.0, "Published")
        return commit.get("html_url") or f"https://github.com/{rp}/commit/{commit['sha']}"
    raise PublishError("GitHub kept changing while publishing. Try again.")
