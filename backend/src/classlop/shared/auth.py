"""The Teacher's Microsoft sign-in, and delegated Graph tokens for every area."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

import msal
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from classlop.shared.db import sessions
from classlop.shared.jobs import SignInRequired
from classlop.shared.models import TokenCache
from classlop.shared.settings import get_settings

__all__ = ["NotAdmitted", "SignInFailed", "SignInRequired", "complete_sign_in", "graph_token"]

_tokens = msal.SerializableTokenCache()
# Every process shares the cache through Postgres; the lock keeps a load, use and save whole.
_lock = asyncio.Lock()


class SignInFailed(Exception):
    """Microsoft refused the sign-in, or it expired."""


class NotAdmitted(SignInFailed):
    """An account other than the configured Teacher signed in."""


def _build(http_client=None) -> msal.ConfidentialClientApplication:
    s = get_settings()
    secret = s.m365_client_secret
    return msal.ConfidentialClientApplication(
        s.m365_client_id,
        client_credential=secret.get_secret_value() if secret else None,
        authority=f"https://login.microsoftonline.com/{s.m365_tenant_id}",
        token_cache=_tokens,
        http_client=http_client,
    )


@lru_cache
def _client() -> msal.ConfidentialClientApplication:
    return _build()


@asynccontextmanager
async def _cache() -> AsyncIterator[msal.ConfidentialClientApplication]:
    """The client with the stored cache loaded; saved back unless the block raises."""
    async with _lock:
        app = await asyncio.to_thread(_client)
        async with sessions()() as session:
            _tokens.deserialize(await session.scalar(select(TokenCache.data)))
        yield app
        if _tokens.has_state_changed:
            data = _tokens.serialize()
            async with sessions().begin() as session:
                await session.execute(
                    insert(TokenCache)
                    .values(id=1, data=data)
                    .on_conflict_do_update(
                        index_elements=["id"], set_={"data": data, "updated_at": func.now()}
                    )
                )


async def sign_in_flow(scopes: list[str]) -> dict:
    """Start an authorization code flow; keep the result for `complete_sign_in`."""
    app = await asyncio.to_thread(_client)
    # Not form_post, which MSAL recommends: a cross-site POST would not carry the Lax cookie
    # holding the flow.
    return app.initiate_auth_code_flow(
        scopes, redirect_uri=f"{get_settings().public_url}/auth/callback", prompt="select_account"
    )


async def complete_sign_in(flow: dict, params: dict) -> dict:
    """Redeem the code. Returns the Teacher's ID token claims and keeps their tokens."""
    s = get_settings()
    async with _cache() as app:
        try:
            result = await asyncio.to_thread(app.acquire_token_by_auth_code_flow, flow, params)
        except ValueError as exc:
            raise SignInFailed(str(exc)) from exc
        if "error" in result:
            raise SignInFailed(result.get("error_description", result["error"]))
        claims = result["id_token_claims"]
        if (claims.get("tid"), claims.get("oid")) != (s.m365_tenant_id, s.m365_teacher_oid):
            raise NotAdmitted(claims.get("preferred_username"))
    return claims


async def graph_token(scopes: list[str]) -> str:
    """A delegated Graph token for the Teacher, refreshed as needed. Raises SignInRequired once
    refreshing fails."""
    s = get_settings()
    teacher = f"{s.m365_teacher_oid}.{s.m365_tenant_id}"
    async with _cache() as app:
        account = next((a for a in app.get_accounts() if a["home_account_id"] == teacher), None)
        if account is None:
            raise SignInRequired
        result = await asyncio.to_thread(app.acquire_token_silent, scopes, account)
    if not result or "access_token" not in result:
        raise SignInRequired
    return result["access_token"]
