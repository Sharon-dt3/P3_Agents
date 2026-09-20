"""
Unattended Graph token refresh for the live runner (CHN-01's own
"separate future step" from scripts/graph_login.py, finally taken).

graph_login.py's own docstring says it plainly: "This access token is
short-lived by design -- re-run this script whenever it expires.
Turning this into something that refreshes itself automatically
without a human in the loop is a separate future step, deliberately
not attempted here." A live runner that polls Graph every few minutes,
all day, cannot work at all if a person has to re-run an interactive
device-code sign-in roughly once an hour -- so this module is that
step, built the same way MSAL itself recommends: a persisted
SerializableTokenCache holding the refresh token from one initial
interactive sign-in, and every later call going through
acquire_token_silent() first, which mints a fresh access token from
the cached refresh token with no browser, no code, and no human,
unless that refresh token has itself expired or been revoked.

get_access_token(allow_interactive=False) is the shape every unattended
caller (the live runner's own poll loop) must use: if silent refresh
fails for any reason, this raises GraphAuthError rather than ever
falling back to a blocking interactive prompt on a background thread
nobody may be watching. allow_interactive=True (the default, and what
a person running this by hand wants) is the one-time-seeding path: no
cached account yet, or the cached refresh token is dead, so a real
device-code sign-in runs -- exactly scripts/graph_login.py's own flow,
reused here rather than re-implemented, with the one addition that its
result also gets written into the persisted cache this time.

The cache file itself holds a live refresh token -- as sensitive as any
other credential in .env -- so it lives under data/ alongside the
sqlite databases, which .gitignore already excludes wholesale, rather
than inventing a new ignore rule.
"""

from __future__ import annotations

from pathlib import Path

import msal

GRAPH_SCOPES = [
    "ChannelMessage.Read.All",  # the only Graph call anything live makes -- see graph_login.py
]

# Repo-root-relative, matching every other script's own data/*.db convention.
DEFAULT_CACHE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "graph_token_cache.bin"


class GraphAuthError(Exception):
    """Raised whenever a valid access token could not be produced.
    Unattended callers (allow_interactive=False) must treat this as
    "skip this poll, log it loudly, try again next interval" -- never
    as a reason to block. It means either no account has ever been
    cached (graph_login was never run against this cache), or the
    cached refresh token itself has expired/been revoked (Azure AD
    default is 90 days of no use, or sooner if an admin revokes it or
    the user's password changes) -- both require a real human to sign
    in again, which only allow_interactive=True ever attempts."""


def _load_cache(cache_path: Path) -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if cache_path.exists():
        cache.deserialize(cache_path.read_text())
    return cache


def _save_cache_if_changed(cache: msal.SerializableTokenCache, cache_path: Path) -> None:
    if cache.has_state_changed:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(cache.serialize())


def get_access_token(
    *,
    tenant_id: str,
    client_id: str,
    cache_path: Path = DEFAULT_CACHE_PATH,
    allow_interactive: bool = True,
    app_factory=msal.PublicClientApplication,
) -> str:
    """Returns a live Graph access token, refreshing silently from the
    persisted cache whenever possible.

    app_factory is the same test seam scripts/graph_login.py's own
    acquire_token() already uses -- production always calls the real
    msal.PublicClientApplication (the default); tests substitute a fake
    one so no real network call and no real interactive login ever
    happens under pytest.
    """
    cache = _load_cache(cache_path)
    app = app_factory(
        client_id, authority=f"https://login.microsoftonline.com/{tenant_id}", token_cache=cache,
    )

    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save_cache_if_changed(cache, cache_path)
            return result["access_token"]

    if not allow_interactive:
        raise GraphAuthError(
            "No valid cached Graph token: either scripts/graph_seed_token_cache.py has never been "
            "run against this cache, or the cached refresh token has expired/been revoked. "
            "Run scripts/graph_seed_token_cache.py once (interactive sign-in) to fix this."
        )

    # Exactly graph_login.py's own device-code flow, reused rather than
    # duplicated -- the only difference is the result is also persisted
    # into `cache` here, which graph_login.py's own .env-only flow never did.
    flow = app.initiate_device_flow(scopes=GRAPH_SCOPES)
    if "user_code" not in flow:
        raise GraphAuthError(f"Could not start device flow: {flow.get('error_description', flow)}")
    print(flow["message"])
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise GraphAuthError(
            f"Sign-in did not produce a token: {result.get('error')} -- {result.get('error_description')}"
        )
    _save_cache_if_changed(cache, cache_path)
    return result["access_token"]
