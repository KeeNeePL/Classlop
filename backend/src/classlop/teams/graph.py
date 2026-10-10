"""A thin Graph client as the Teacher: token through the shared sign-in, paging, throttling."""

import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx

from classlop.shared.auth import graph_token

GRAPH_SCOPES = [
    "User.Read",
    "Group.ReadWrite.All",
    "TeamMember.ReadWrite.All",
    "Channel.ReadBasic.All",
    "Team.Create",
    "User.ReadBasic.All",
]

BASE = "https://graph.microsoft.com/v1.0"
MAX_TRIES = 5
MAX_CONCURRENT = 4
_RETRY = {429, 503, 504}


class GraphError(Exception):
    def __init__(self, response: httpx.Response):
        super().__init__(f"{response.request.method} {response.request.url.path}: {response.text}")
        self.status = response.status_code


class GraphOperationFailed(Exception):
    """An asynchronous Graph operation, such as creating a team, ended in failure."""


class GraphClient:
    def __init__(
        self,
        *,
        token: Callable[[], Awaitable[str]] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._token = token or (lambda: graph_token(GRAPH_SCOPES))
        self._http = httpx.AsyncClient(transport=transport, base_url=BASE, timeout=30)
        self._sleep = sleep
        # One Teacher is one tenant, so one limit.
        self._slots = asyncio.Semaphore(MAX_CONCURRENT)

    async def wait_for(self, url: str, *, tries: int = 60) -> None:
        """Poll a Graph async operation until it succeeds."""
        for _ in range(tries):
            status = (await self.get(url))["status"]
            if status == "succeeded":
                return
            if status == "failed":
                raise GraphOperationFailed(url)
            await self._sleep(2)
        raise TimeoutError(url)

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        extra = kwargs.pop("headers", {})
        for attempt in range(MAX_TRIES):
            async with self._slots:
                headers = {"Authorization": f"Bearer {await self._token()}", **extra}
                response = await self._http.request(method, url, headers=headers, **kwargs)
            if response.status_code not in _RETRY:
                break
            if attempt < MAX_TRIES - 1:
                retry_after = response.headers.get("Retry-After")
                await self._sleep(
                    float(retry_after) if retry_after else 2**attempt + random.random()
                )
        if response.is_error:
            raise GraphError(response)
        return response

    async def get(self, url: str, *, headers: dict | None = None, **params) -> dict:
        return (await self.request("GET", url, params=params or None, headers=headers or {})).json()

    async def get_all(self, url: str, *, headers: dict | None = None, **params) -> list[dict]:
        """Every row of a collection, following `@odata.nextLink`."""
        rows: list[dict] = []
        page = await self.get(url, headers=headers, **params)
        while True:
            rows += page["value"]
            if "@odata.nextLink" not in page:
                return rows
            page = (
                await self.request("GET", page["@odata.nextLink"], headers=headers or {})
            ).json()
