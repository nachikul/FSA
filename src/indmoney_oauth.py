"""OAuth 2.1 + PKCE client for INDmoney's public MCP server.

This is a from-scratch client against INDmoney's own documented endpoints
(https://mcp.indmoney.com/docs) — not something routed through Claude. The
server exposes standard OAuth discovery metadata and, notably, a dynamic
client registration endpoint (RFC 7591), so this app can register itself
as an OAuth client on first use without any manual approval step from
INDmoney.

Deliberately local-only and session-only by design (see README.md >
"INDmoney portfolio — live connect"): the redirect URI is fixed to
localhost, and nothing here is written to disk — the whole point of using
OAuth instead of asking for a password is that INDmoney's login (mobile +
OTP + MPIN) never touches this app at all, and the token this app does
hold lives only in Streamlit's session state for that one browser session.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Optional

import httpx

ISSUER = "https://mcp.indmoney.com/"
AUTHORIZE_ENDPOINT = "https://mcp.indmoney.com/authorize"
TOKEN_ENDPOINT = "https://mcp.indmoney.com/token"
REGISTER_ENDPOINT = "https://mcp.indmoney.com/register"
REVOKE_ENDPOINT = "https://mcp.indmoney.com/revoke"
SCOPES = "portfolio:read market:read"


class OAuthError(Exception):
    pass


@dataclass
class ClientCredentials:
    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass
class PendingAuth:
    """State kept between building the authorize URL and handling the
    redirect back — must survive across a Streamlit rerun, so it lives in
    st.session_state, not just a local variable."""
    code_verifier: str
    state: str
    redirect_uri: str


@dataclass
class TokenSet:
    access_token: str
    refresh_token: Optional[str]
    expires_at: float  # unix timestamp

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at - 30  # refresh a little early


def register_client(redirect_uri: str) -> ClientCredentials:
    """Dynamic client registration (RFC 7591). Called once per app session
    — there's no reason to persist the resulting client_id across restarts
    for a personal, local-only tool, and re-registering is free and
    supported by design."""
    resp = httpx.post(
        REGISTER_ENDPOINT,
        json={
            "client_name": "Financial Statement Analyser (local)",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
        },
        timeout=15,
    )
    if resp.status_code >= 400:
        raise OAuthError(f"Client registration failed ({resp.status_code}): {resp.text}")
    data = resp.json()
    return ClientCredentials(
        client_id=data["client_id"],
        client_secret=data.get("client_secret", ""),
        redirect_uri=redirect_uri,
    )


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(creds: ClientCredentials) -> tuple[str, PendingAuth]:
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": creds.client_id,
        "redirect_uri": creds.redirect_uri,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = httpx.URL(AUTHORIZE_ENDPOINT, params=params)
    return str(url), PendingAuth(code_verifier=verifier, state=state, redirect_uri=creds.redirect_uri)


def exchange_code(creds: ClientCredentials, pending: PendingAuth, code: str, returned_state: str) -> TokenSet:
    if not secrets.compare_digest(returned_state, pending.state):
        raise OAuthError("State mismatch on OAuth callback — possible CSRF, or a stale/reused login link. Try connecting again.")
    resp = httpx.post(
        TOKEN_ENDPOINT,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": pending.redirect_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "code_verifier": pending.code_verifier,
        },
        timeout=15,
    )
    if resp.status_code >= 400:
        raise OAuthError(f"Token exchange failed ({resp.status_code}): {resp.text}")
    return _token_set_from_response(resp.json())


def refresh_token(creds: ClientCredentials, tokens: TokenSet) -> TokenSet:
    if not tokens.refresh_token:
        raise OAuthError("No refresh token available — reconnect to INDmoney.")
    resp = httpx.post(
        TOKEN_ENDPOINT,
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
        },
        timeout=15,
    )
    if resp.status_code >= 400:
        raise OAuthError(f"Token refresh failed ({resp.status_code}): {resp.text}")
    return _token_set_from_response(resp.json())


def revoke(creds: ClientCredentials, tokens: TokenSet) -> None:
    try:
        httpx.post(
            REVOKE_ENDPOINT,
            data={"token": tokens.access_token, "client_id": creds.client_id, "client_secret": creds.client_secret},
            timeout=10,
        )
    except httpx.HTTPError:
        pass  # best-effort — the token still expires on its own


def _token_set_from_response(data: dict) -> TokenSet:
    expires_in = data.get("expires_in", 3600)
    return TokenSet(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=time.time() + float(expires_in),
    )
