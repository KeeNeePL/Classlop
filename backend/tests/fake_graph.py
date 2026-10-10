"""A stateful in-memory Microsoft Graph, served at the HTTP transport. It grows with the
endpoints `teams` uses; tests seed it through the methods and never see its routes."""

import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

PAGE_SIZE = 2
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class FakeGraph:
    def __init__(self, teacher_id: str):
        self.teacher_id = teacher_id
        self.teams: dict[str, dict] = {}
        self.events: dict[str, dict] = {}
        # What calendarView delta reports: (kind, event or occurrence id), in order.
        self.changes: list[tuple[str, str]] = []
        self.transport = httpx.MockTransport(self._handle)

    def add_team(self, name: str, *, owner: str | None = None) -> str:
        team_id = str(uuid.uuid4())
        general = self._channel_id()
        self.teams[team_id] = {
            "name": name,
            "channel": general,
            "channels": [general],
            "members": {},
        }
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

    @staticmethod
    def _channel_id() -> str:
        return f"19:{uuid.uuid4().hex}@thread.tacv2"

    def add_channel(self, team_id: str, name: str) -> str:
        channel = self._channel_id()
        self.teams[team_id]["channels"].append(channel)
        return channel

    def add_meeting(
        self,
        subject: str,
        start: datetime,
        end: datetime,
        *,
        attendees: list[str],
        channel: str | None = None,
        weekly_until: date | None = None,
    ) -> str:
        """An online meeting the Teacher made in Teams, in a channel or by inviting people."""
        body = {
            "subject": subject,
            "isOnlineMeeting": True,
            "attendees": [{"emailAddress": {"address": a}} for a in attendees],
            "start": self._local(start),
            "end": self._local(end),
        }
        if weekly_until:
            body["recurrence"] = {
                "pattern": {"type": "weekly", "daysOfWeek": [_DAYS[start.weekday()]]},
                "range": {
                    "startDate": start.date().isoformat(),
                    "endDate": weekly_until.isoformat(),
                },
            }
        event_id = json.loads(self._create_event(body).content)["id"]
        thread = channel or f"19:{uuid.uuid4().hex}@thread.v2"
        self.events[event_id]["onlineMeeting"] = {
            "joinUrl": f"https://teams.example.org/l/meetup-join/{quote(thread)}/0"
        }
        return event_id

    def reschedule(self, event_id: str, start: datetime, end: datetime) -> None:
        """A time change made in Teams, of an event or of one occurrence of a series."""
        master, _, day = event_id.partition("@")
        event = self.events[master]
        if day:
            event.setdefault("moved", {})[day] = (start, end)
        else:
            event["start"], event["end"] = self._local(start), self._local(end)
        self.changes.append(("changed", master))

    def cancel(self, event_id: str) -> None:
        """A cancellation made in Teams: the event leaves the Teacher's calendar."""
        master, _, day = event_id.partition("@")
        if day:
            self.events[master].setdefault("cancelled", set()).add(day)
        else:
            del self.events[master]
        self.changes.append(("removed", event_id))

    @staticmethod
    def _local(when: datetime) -> dict:
        local = when.astimezone(ZoneInfo("Europe/Warsaw")).replace(tzinfo=None)
        return {"dateTime": local.isoformat(), "timeZone": "Europe/Warsaw"}

    def event_of(self, event_id: str) -> tuple[str, set[str]]:
        """The subject and invitee addresses of an event or of an occurrence of a series."""
        event = self.events[event_id.split("@")[0]]
        return event["subject"], {a["emailAddress"]["address"] for a in event["attendees"]}

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
        if path == "/me/calendarView/delta":
            return self._delta(request)
        if match := re.fullmatch(r"/teams/([^/]+)/channels", path):
            if (team := self.teams.get(match[1])) is None:
                return httpx.Response(404, json={"error": {"code": "NotFound"}})
            return self._page(request, [{"id": c} for c in team["channels"]])
        if match := re.fullmatch(r"/me/events/([^/]+)", path):
            if (event := self.events.get(match[1])) is None:
                return httpx.Response(404, json={"error": {"code": "NotFound"}})
            if request.method == "PATCH":
                event.update(json.loads(request.content))
                self.changes.append(("changed", event["id"]))
            return httpx.Response(200, json=self._shown(event))
        if match := re.fullmatch(r"/me/events/([^/]+)/instances", path):
            if (event := self.events.get(match[1])) is None:
                return httpx.Response(404, json={"error": {"code": "NotFound"}})
            return self._page(request, self._instances(event, request.url.params))
        return httpx.Response(404, json={"error": {"code": "UnknownRoute", "message": path}})

    def _create_event(self, body: dict) -> httpx.Response:
        event_id = str(uuid.uuid4())
        self.events[event_id] = {
            **body,
            "id": event_id,
            "onlineMeeting": {"joinUrl": f"https://teams.example.org/l/{event_id}"},
        }
        self.changes.append(("changed", event_id))
        return httpx.Response(201, json=self._shown(self.events[event_id]))

    @staticmethod
    def _utc(when: dict) -> dict:
        local = datetime.fromisoformat(when["dateTime"]).replace(tzinfo=ZoneInfo(when["timeZone"]))
        return {
            "dateTime": local.astimezone(UTC).replace(tzinfo=None).isoformat(),
            "timeZone": "UTC",
        }

    def _shown(self, event: dict) -> dict:
        plain = {k: v for k, v in event.items() if k not in ("moved", "cancelled")}
        return {**plain, "start": self._utc(event["start"]), "end": self._utc(event["end"])}

    def _instances(self, event: dict, params) -> list[dict]:
        window = [datetime.fromisoformat(params[k]) for k in ("startDateTime", "endDateTime")]
        if "recurrence" not in event:
            shown = self._shown(event)
            begins = datetime.fromisoformat(shown["start"]["dateTime"]).replace(tzinfo=UTC)
            return [shown] if window[0] <= begins < window[1] else []
        rng = event["recurrence"]["range"]
        day, last = date.fromisoformat(rng["startDate"]), date.fromisoformat(rng["endDate"])
        weekday = _DAYS.index(event["recurrence"]["pattern"]["daysOfWeek"][0])
        first = datetime.fromisoformat(event["start"]["dateTime"]).time()
        length = datetime.fromisoformat(event["end"]["dateTime"]) - datetime.fromisoformat(
            event["start"]["dateTime"]
        )
        out = []
        while day <= last:
            if day.weekday() == weekday and str(day) not in event.get("cancelled", ()):
                start = datetime.combine(day, first)
                zone = event["start"]["timeZone"]
                occurrence = {
                    **event,
                    "id": f"{event['id']}@{day}",
                    "start": {"dateTime": start.isoformat(), "timeZone": zone},
                    "end": {"dateTime": (start + length).isoformat(), "timeZone": zone},
                }
                if str(day) in event.get("moved", ()):
                    occurrence["start"], occurrence["end"] = map(
                        self._local, event["moved"][str(day)]
                    )
                shown = self._shown(occurrence)
                begins = datetime.fromisoformat(shown["start"]["dateTime"]).replace(tzinfo=UTC)
                if window[0] <= begins < window[1]:
                    out.append(shown)
            day += timedelta(days=1)
        return out

    def _delta(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        rows: dict[str, dict] = {}
        for kind, event_id in self.changes[int(params.get("$deltatoken", 0)) :]:
            if kind == "removed":
                rows[event_id] = {"id": event_id, "@removed": {"reason": "deleted"}}
            elif event := self.events.get(event_id):
                series = event_id if "recurrence" in event else None
                for shown in self._instances(event, params):
                    rows[shown["id"]] = {**shown, "seriesMasterId": series}
        response = self._page(request, list(rows.values()))
        body = json.loads(response.content)
        if "@odata.nextLink" not in body:
            link = request.url.copy_remove_param("skip")
            body["@odata.deltaLink"] = str(link.copy_set_param("$deltatoken", len(self.changes)))
        return httpx.Response(200, json=body)

    def _page(self, request: httpx.Request, rows: list[dict]) -> httpx.Response:
        start = int(request.url.params.get("skip", 0))
        body: dict = {"value": rows[start : start + PAGE_SIZE]}
        if start + PAGE_SIZE < len(rows):
            body["@odata.nextLink"] = str(request.url.copy_set_param("skip", start + PAGE_SIZE))
        return httpx.Response(200, json=body)
