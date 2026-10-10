"""The Graph client's failure shapes: throttling and the retry limit."""

import httpx
import pytest
import respx

from classlop.teams.graph import BASE, MAX_TRIES, GraphClient, GraphError


async def _token() -> str:
    return "token"


@pytest.fixture
def slept() -> list[float]:
    return []


@pytest.fixture
def graph(slept):
    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    return GraphClient(token=_token, sleep=sleep)


@respx.mock
async def test_it_waits_as_long_as_retry_after_says(graph, slept):
    route = respx.get(f"{BASE}/me").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"id": "u1"}),
        ]
    )

    assert await graph.get("/me") == {"id": "u1"}
    assert slept == [7]
    assert route.calls.last.request.headers["Authorization"] == "Bearer token"


@respx.mock
async def test_it_backs_off_exponentially_without_retry_after(graph, slept):
    respx.get(f"{BASE}/me").mock(
        side_effect=[httpx.Response(503), httpx.Response(504), httpx.Response(200, json={})]
    )

    await graph.get("/me")

    assert [int(s) for s in slept] == [1, 2]


@respx.mock
async def test_it_gives_up_after_five_tries(graph):
    route = respx.get(f"{BASE}/me").mock(return_value=httpx.Response(429))

    with pytest.raises(GraphError):
        await graph.get("/me")

    assert route.call_count == MAX_TRIES == 5


@respx.mock
async def test_other_errors_are_not_retried(graph):
    route = respx.get(f"{BASE}/me").mock(return_value=httpx.Response(403))

    with pytest.raises(GraphError):
        await graph.get("/me")

    assert route.call_count == 1
