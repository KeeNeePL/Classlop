import httpx

from classlop.shared.auth import graph_token
from classlop.shared.jobs import Progress, handler
from classlop.shared.models import Job
from classlop.teams import GRAPH_SCOPES


@handler("teams.whoami")
async def whoami(job: Job, progress: Progress) -> dict:
    """Proves a background job can reach Graph as the Teacher with no browser open."""
    token = await graph_token(GRAPH_SCOPES)
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://graph.microsoft.com/v1.0/me", headers={"Authorization": f"Bearer {token}"}
        )
    response.raise_for_status()
    return {"name": response.json()["displayName"]}
