"""A stateful in-memory Microsoft Graph, served at the HTTP transport. It grows with the
endpoints `teams` uses; tests seed it through the methods and never see its routes."""

import re
import uuid

import httpx

PAGE_SIZE = 2


class FakeGraph:
    def __init__(self, teacher_id: str):
        self.teacher_id = teacher_id
        self.teams: dict[str, dict] = {}
        self.transport = httpx.MockTransport(self._handle)

    def add_team(self, name: str, *, owner: str | None = None) -> str:
        team_id = str(uuid.uuid4())
        self.teams[team_id] = {"name": name, "channel": str(uuid.uuid4()), "members": {}}
        self._join(team_id, owner or self.teacher_id, "Anna Nowak", owner=True)
        return team_id

    def add_member(
        self, team_id: str, name: str, *, owner: bool = False, user_id: str | None = None
    ) -> str:
        user_id = user_id or str(uuid.uuid4())
        self._join(team_id, user_id, name, owner=owner)
        return user_id

    def remove_member(self, team_id: str, user_id: str) -> None:
        del self.teams[team_id]["members"][user_id]

    def make_owner(self, team_id: str, user_id: str) -> None:
        self.teams[team_id]["members"][user_id]["roles"] = ["owner"]

    def _join(self, team_id: str, user_id: str, name: str, *, owner: bool) -> None:
        upn = name.lower().replace(" ", ".") + "@example.org"
        self.teams[team_id]["members"][user_id] = {
            "userId": user_id,
            "displayName": name,
            "email": upn,
            "roles": ["owner"] if owner else [],
        }

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1.0")
        if path == "/me/ownedObjects/microsoft.graph.group":
            mine = [
                {"id": i, "displayName": t["name"], "resourceProvisioningOptions": ["Team"]}
                for i, t in self.teams.items()
                if self.teacher_id in t["members"]
                and "owner" in t["members"][self.teacher_id]["roles"]
            ]
            return self._page(request, mine)
        if match := re.fullmatch(r"/teams/([^/]+)/members", path):
            if (team := self.teams.get(match[1])) is None:
                return httpx.Response(404, json={"error": {"code": "NotFound"}})
            return self._page(request, list(team["members"].values()))
        if match := re.fullmatch(r"/teams/([^/]+)/primaryChannel", path):
            if (team := self.teams.get(match[1])) is None:
                return httpx.Response(404, json={"error": {"code": "NotFound"}})
            return httpx.Response(200, json={"id": team["channel"], "displayName": "General"})
        return httpx.Response(404, json={"error": {"code": "UnknownRoute", "message": path}})

    def _page(self, request: httpx.Request, rows: list[dict]) -> httpx.Response:
        start = int(request.url.params.get("skip", 0))
        body: dict = {"value": rows[start : start + PAGE_SIZE]}
        if start + PAGE_SIZE < len(rows):
            body["@odata.nextLink"] = str(request.url.copy_set_param("skip", start + PAGE_SIZE))
        return httpx.Response(200, json=body)
