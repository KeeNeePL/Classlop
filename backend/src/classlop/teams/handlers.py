import logging

import httpx

from classlop import teams
from classlop.shared.auth import graph_token
from classlop.shared.jobs import Progress, SignInRequired, handler
from classlop.shared.models import Job
from classlop.shared.schedule import declare_every
from classlop.teams import GRAPH_SCOPES

log = logging.getLogger(__name__)

declare_every("teams.sync-rosters", "rate(15 minutes)", "teams.sync_rosters")
declare_every("teams.sync-calendar", "rate(15 minutes)", "teams.sync_calendar")


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


@handler("teams.sync_rosters")
async def sync_rosters(job: Job, progress: Progress) -> dict:
    """Every Class's roster, in step with its team; one failing Class does not stop the rest."""
    failed = 0
    for klass in await teams.list_classes():
        try:
            await teams.sync_roster(klass.id)
        except SignInRequired:
            raise
        except Exception:
            failed += 1
            log.exception("roster sync of class %s failed", klass.id)
    return {"failed": failed}


@handler("teams.sync_calendar")
async def sync_calendar(job: Job, progress: Progress) -> None:
    """Also enqueued on demand when the dashboard opens."""
    await teams.sync_calendar()
