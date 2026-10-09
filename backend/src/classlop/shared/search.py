from functools import lru_cache

from opensearchpy import AsyncOpenSearch

from classlop.shared.settings import get_settings


@lru_cache
def client() -> AsyncOpenSearch:
    return AsyncOpenSearch(hosts=[get_settings().opensearch_url])


async def ping() -> None:
    plugins = await client().cat.plugins(params={"format": "json"})
    if not any(p["component"] == "analysis-stempel" for p in plugins):
        raise RuntimeError("OpenSearch lacks analysis-stempel")
