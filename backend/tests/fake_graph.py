"""A stateful in-memory Microsoft Graph, served at the HTTP transport. It grows with the
endpoints `teams` uses; tests seed it through the methods and never see its routes."""

import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

PAGE_SIZE = 2
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _z(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _session(user_id: str | None, name: str, joined: datetime, left: datetime) -> dict:
    who = (
        {"user": {"id": user_id, "displayName": name}}
        if user_id
        else {"guest": {"displayName": name}}
    )
    return {"caller": {"identity": who}, "startDateTime": _z(joined), "endDateTime": _z(left)}


class FakeGraph:
    def __init__(self, teacher_id: str):
        self.teacher_id = teacher_id
        self.teams: dict[str, dict] = {}
        self.events: dict[str, dict] = {}
        self.call_records: list[dict] = []
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

    def event_of(self, event_id: str) -> tuple[str, set[str]]:
        """The subject and invitee addresses of an event or of an occurrence of a series."""
        event = self.events[event_id.split("@")[0]]
        return event["subject"], {a["emailAddress"]["address"] for a in event["attendees"]}

    def attend(self, join_url: str, sessions: list[tuple[str | None, str, datetime, datetime]]):
        """A call record of the meeting at `join_url`; each session is (user id or None for a
        guest, display name, joined, left)."""
        self.call_records.append(
            {
                "id": str(uuid.uuid4()),
                "joinWebUrl": join_url,
                "startDateTime": _z(min(s[2] for s in sessions)),
                "endDateTime": _z(max(s[3] for s in sessions)),
                "sessions": [_session(*s) for s in sessions],
            }
        )

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
        if path == "/communications/callRecords":
            bounds = dict(re.findall(r"startDateTime (ge|lt) (\S+)", request.url.params["$filter"]))
            lo, hi = (datetime.fromisoformat(bounds[k]) for k in ("ge", "lt"))
            found = [
                {k: v for k, v in r.items() if k != "sessions"}
                for r in self.call_records
                if lo <= datetime.fromisoformat(r["startDateTime"]) < hi
            ]
            return self._page(request, found)
        if match := re.fullmatch(r"/communications/callRecords/([^/]+)/sessions", path):
            record = next((r for r in self.call_records if r["id"] == match[1]), None)
            if record is None:
                return httpx.Response(404, json={"error": {"code": "NotFound"}})
            return self._page(request, record["sessions"])
        return httpx.Response(404, json={"error": {"code": "UnknownRoute", "message": path}})

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
