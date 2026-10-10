"""The Graph client's failure shapes: throttling and the retry limit."""

import asyncio

import httpx
import pytest
import respx

from classlop.shared.jobs import SignInRequired
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


@respx.mock
async def test_at_most_four_calls_run_at_once():
    running = peak = 0
    release = asyncio.Event()

    async def respond(request):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await release.wait()
        running -= 1
        return httpx.Response(200, json={})

    respx.get(f"{BASE}/me").mock(side_effect=respond)
    graph = GraphClient(token=_token)

    calls = asyncio.gather(*(graph.get("/me") for _ in range(10)))
    await asyncio.sleep(0.1)
    assert running == 4
    release.set()
    await calls

    assert peak == 4


@respx.mock
async def test_a_throttled_call_does_not_hold_a_slot_while_it_waits():
    entered = asyncio.Event()

    async def sleep(seconds: float) -> None:
        entered.set()
        await asyncio.sleep(10)

    respx.get(f"{BASE}/slow").mock(return_value=httpx.Response(429))
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={"id": "u1"}))
    graph = GraphClient(token=_token, sleep=sleep)

    waiting = [asyncio.create_task(graph.get("/slow")) for _ in range(4)]
    await entered.wait()

    assert await asyncio.wait_for(graph.get("/me"), 1) == {"id": "u1"}
    for task in waiting:
        task.cancel()


@respx.mock
async def test_a_rejected_token_means_the_teacher_must_sign_in_again(graph):
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(401))

    with pytest.raises(SignInRequired):
        await graph.get("/me")
