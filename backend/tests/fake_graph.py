"""A stateful in-memory Microsoft Graph, served at the HTTP transport. It grows with the
endpoints `teams` uses; tests seed it through the methods and never see its routes."""

import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

PAGE_SIZE = 2
# A new team is not ready on the first poll, as in Graph.
CREATION_POLLS = 2
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class FakeGraph:
    def __init__(self, teacher_id: str):
        self.teacher_id = teacher_id
        self.users: dict[str, tuple[str, str]] = {}
        self.teams: dict[str, dict] = {}
        self._operations: dict[str, int] = {}
        self.events: dict[str, dict] = {}
        self.transport = httpx.MockTransport(self._handle)

    def add_user(self, name: str) -> str:
        user_id = str(uuid.uuid4())
        self.users[user_id] = (name, _upn(name))
        return user_id

    def add_team(self, name: str, *, owner: str | None = None) -> str:
        team_id = self._new_team(name, "public")
        self._join(team_id, owner or self.teacher_id, "Anna Nowak", owner=True)
        return team_id

    def _new_team(self, name: str, visibility: str) -> str:
        team_id = str(uuid.uuid4())
        self.teams[team_id] = {
            "name": name,
            "channel": str(uuid.uuid4()),
            "visibility": visibility,
            "members": {},
        }
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

    def rename_team(self, team_id: str, name: str) -> None:
        self.teams[team_id]["name"] = name

    def team_name(self, team_id: str) -> str:
        return self.teams[team_id]["name"]

    def team_members(self, team_id: str) -> set[str]:
        return set(self.teams[team_id]["members"])

    def team_is_private(self, team_id: str) -> bool:
        return self.teams[team_id]["visibility"] == "private"

    def event_of(self, event_id: str) -> tuple[str, set[str]]:
        """The subject and invitee addresses of an event or of an occurrence of a series."""
        event = self.events[event_id.split("@")[0]]
        return event["subject"], {a["emailAddress"]["address"] for a in event["attendees"]}

    def _join(self, team_id: str, user_id: str, name: str, *, owner: bool) -> None:
        self.teams[team_id]["members"][user_id] = {
            "id": str(uuid.uuid4()),
            "userId": user_id,
            "displayName": name,
            "email": _upn(name),
            "roles": ["owner"] if owner else [],
        }

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1.0")
        method = request.method
        if path == "/me/ownedObjects/microsoft.graph.group":
            mine = [
                {"id": i, "displayName": t["name"], "resourceProvisioningOptions": ["Team"]}
                for i, t in self.teams.items()
                if self.teacher_id in t["members"]
                and "owner" in t["members"][self.teacher_id]["roles"]
            ]
            return self._page(request, mine)
        if path == "/users":
            return self._search_users(request)
        if path == "/teams" and method == "POST":
            return self._create_team(json.loads(request.content))
        if match := re.fullmatch(r"/teams/([^/]+)/operations/([^/]+)", path):
            polls = self._operations[match[2]] = self._operations[match[2]] + 1
            status = "succeeded" if polls >= CREATION_POLLS else "inProgress"
            return httpx.Response(200, json={"id": match[2], "status": status})
        if match := re.fullmatch(r"/teams/([^/]+)", path):
            if (team := self.teams.get(match[1])) is None:
                return _not_found()
            if method == "PATCH":
                team["name"] = json.loads(request.content)["displayName"]
                return httpx.Response(204)
            return httpx.Response(200, json={"id": match[1], "displayName": team["name"]})
        if match := re.fullmatch(r"/teams/([^/]+)/members", path):
            if (team := self.teams.get(match[1])) is None:
                return _not_found()
            if method == "POST":
                body = json.loads(request.content)
                user_id = _bound_user(body)
                name = self._name(user_id)
                self._join(match[1], user_id, name, owner="owner" in body.get("roles", []))
                return httpx.Response(201, json=team["members"][user_id])
            return self._page(request, list(team["members"].values()))
        if match := re.fullmatch(r"/teams/([^/]+)/members/([^/]+)", path):
            if (team := self.teams.get(match[1])) is None:
                return _not_found()
            for user_id, member in team["members"].items():
                if member["id"] == match[2]:
                    del team["members"][user_id]
                    return httpx.Response(204)
            return _not_found()
        if match := re.fullmatch(r"/teams/([^/]+)/primaryChannel", path):
            if (team := self.teams.get(match[1])) is None:
                return _not_found()
            return httpx.Response(200, json={"id": team["channel"], "displayName": "General"})
        if path == "/me/events" and request.method == "POST":
            return self._create_event(json.loads(request.content))
        if match := re.fullmatch(r"/me/events/([^/]+)", path):
            if (event := self.events.get(match[1])) is None:
                return httpx.Response(404, json={"error": {"code": "NotFound"}})
            if request.method == "PATCH":
                event.update(json.loads(request.content))
            return httpx.Response(200, json=self._shown(event))
        if match := re.fullmatch(r"/me/events/([^/]+)/instances", path):
            if (event := self.events.get(match[1])) is None:
                return httpx.Response(404, json={"error": {"code": "NotFound"}})
            return self._page(request, self._instances(event, request.url.params))
        return httpx.Response(404, json={"error": {"code": "UnknownRoute", "message": path}})

    def _name(self, user_id: str) -> str:
        return self.users[user_id][0] if user_id in self.users else "Anna Nowak"

    def _create_team(self, body: dict) -> httpx.Response:
        team_id = self._new_team(body["displayName"], body["visibility"].lower())
        for member in body["members"]:
            user_id = _bound_user(member)
            self._join(team_id, user_id, self._name(user_id), owner="owner" in member["roles"])
        operation = str(uuid.uuid4())
        self._operations[operation] = 0
        return httpx.Response(
            202,
            headers={
                "Location": f"/teams('{team_id}')/operations('{operation}')",
                "Content-Location": f"/teams('{team_id}')",
            },
        )

    def _search_users(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("ConsistencyLevel") != "eventual":
            return httpx.Response(400, json={"error": {"code": "Request_UnsupportedQuery"}})
        term = request.url.params["$search"].strip('"').removeprefix("displayName:").lower()
        found = [
            {"id": i, "displayName": name, "userPrincipalName": upn}
            for i, (name, upn) in self.users.items()
            if any(word.startswith(term) for word in name.lower().split())
        ]
        return self._page(request, found)

    def _create_event(self, body: dict) -> httpx.Response:
        event_id = str(uuid.uuid4())
        self.events[event_id] = {
            **body,
            "id": event_id,
            "onlineMeeting": {"joinUrl": f"https://teams.example.org/l/{event_id}"},
        }
        return httpx.Response(201, json=self._shown(self.events[event_id]))

    @staticmethod
    def _utc(when: dict) -> dict:
        local = datetime.fromisoformat(when["dateTime"]).replace(tzinfo=ZoneInfo(when["timeZone"]))
        return {
            "dateTime": local.astimezone(UTC).replace(tzinfo=None).isoformat(),
            "timeZone": "UTC",
        }

    def _shown(self, event: dict) -> dict:
        return {**event, "start": self._utc(event["start"]), "end": self._utc(event["end"])}

    def _instances(self, event: dict, params) -> list[dict]:
        if "recurrence" not in event:
            return [self._shown(event)]
        window = [datetime.fromisoformat(params[k]) for k in ("startDateTime", "endDateTime")]
        rng = event["recurrence"]["range"]
        day, last = date.fromisoformat(rng["startDate"]), date.fromisoformat(rng["endDate"])
        weekday = _DAYS.index(event["recurrence"]["pattern"]["daysOfWeek"][0])
        first = datetime.fromisoformat(event["start"]["dateTime"]).time()
        length = datetime.fromisoformat(event["end"]["dateTime"]) - datetime.fromisoformat(
            event["start"]["dateTime"]
        )
        out = []
        while day <= last:
            if day.weekday() == weekday:
                start = datetime.combine(day, first)
                zone = event["start"]["timeZone"]
                occurrence = {
                    **event,
                    "id": f"{event['id']}@{day}",
                    "start": {"dateTime": start.isoformat(), "timeZone": zone},
                    "end": {"dateTime": (start + length).isoformat(), "timeZone": zone},
                }
                shown = self._shown(occurrence)
                begins = datetime.fromisoformat(shown["start"]["dateTime"]).replace(tzinfo=UTC)
                if window[0] <= begins < window[1]:
                    out.append(shown)
            day += timedelta(days=1)
        return out

    def _page(self, request: httpx.Request, rows: list[dict]) -> httpx.Response:
        start = int(request.url.params.get("skip", 0))
        body: dict = {"value": rows[start : start + PAGE_SIZE]}
        if start + PAGE_SIZE < len(rows):
            body["@odata.nextLink"] = str(request.url.copy_set_param("skip", start + PAGE_SIZE))
        return httpx.Response(200, json=body)


def _upn(name: str) -> str:
    return name.lower().replace(" ", ".") + "@example.org"


def _bound_user(member: dict) -> str:
    return re.search(r"users\('([^']+)'\)", member["user@odata.bind"])[1]


def _not_found() -> httpx.Response:
    return httpx.Response(404, json={"error": {"code": "NotFound"}})
