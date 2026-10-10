"""A stateful in-memory Microsoft Graph, served at the HTTP transport. It grows with the
endpoints `teams` uses; tests seed it through the methods and never see its routes."""

import json
import re
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from fake_graph_files import FilesRoutes
from fake_graph_lifecycle import LifecycleRoutes

from classlop.teams.service import local, zulu

PAGE_SIZE = 2
# A new team is not ready on the first poll, as in Graph.
CREATION_POLLS = 2
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _session(user_id: str | None, name: str, joined: datetime, left: datetime) -> dict:
    who = (
        {"user": {"id": user_id, "displayName": name}}
        if user_id
        else {"guest": {"displayName": name}}
    )
    return {"caller": {"identity": who}, "startDateTime": zulu(joined), "endDateTime": zulu(left)}


class FakeGraph(FilesRoutes, LifecycleRoutes):
    def __init__(self, teacher_id: str, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.teacher_id = teacher_id
        self.users: dict[str, tuple[str, str]] = {}
        self.teams: dict[str, dict] = {}
        self._operations: dict[str, int] = {}
        self.events: dict[str, dict] = {}
        # The events calendarView delta reports as changed, in order.
        self.changes: list[str] = []
        self.deleted: set[str] = set()
        self.call_records: list[dict] = []
        self._init_files(clock)
        self._init_lifecycle()
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
        general = self._channel_id()
        self.teams[team_id] = {
            "name": name,
            "channel": general,
            "channels": [general],
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
            "start": local(start),
            "end": local(end),
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
        self.events[event_id]["made_in_teams"] = True
        self.events[event_id]["onlineMeeting"] = {
            "joinUrl": f"https://teams.example.org/l/meetup-join/{quote(thread)}/0"
        }
        return event_id

    def reschedule(self, event_id: str, start: datetime, end: datetime) -> None:
        """A time change made in Teams, of an event or of one occurrence of a series."""
        self._edit(event_id, {"start": local(start), "end": local(end)})

    def delete(self, event_id: str) -> None:
        """A deletion made in Teams: the delta reports the event or occurrence as removed."""
        self.deleted.add(event_id)
        self.changes.append(event_id.partition("@")[0])

    def cancel(self, event_id: str) -> None:
        """A cancellation made in Teams: the event stays, cancelled."""
        self._edit(event_id, {"isCancelled": True})

    def _edit(self, event_id: str, body: dict) -> None:
        base, _, day = event_id.partition("@")
        event = self.events[base]
        if day:
            event.setdefault("exceptions", {}).setdefault(day, {}).update(body)
        else:
            event.update(body)
        self.changes.append(base)

    def event_of(self, event_id: str) -> tuple[str, set[str]]:
        """The subject and invitee addresses of an event or of an occurrence of a series."""
        event = self.events[event_id.split("@")[0]]
        subject = event.get("exceptions", {}).get(event_id.partition("@")[2], {}).get("subject")
        return subject or event["subject"], {
            a["emailAddress"]["address"] for a in event["attendees"]
        }

    def attend(self, join_url: str, sessions: list[tuple[str | None, str, datetime, datetime]]):
        """A call record of the meeting at `join_url`; each session is (user id or None for a
        guest, display name, joined, left)."""
        self.call_records.append(
            {
                "id": str(uuid.uuid4()),
                "joinWebUrl": join_url,
                "startDateTime": zulu(min(s[2] for s in sessions)),
                "endDateTime": zulu(max(s[3] for s in sessions)),
                "sessions": [_session(*s) for s in sessions],
            }
        )

    def _join(self, team_id: str, user_id: str, name: str, *, owner: bool) -> None:
        self.teams[team_id]["members"][user_id] = {
            "id": str(uuid.uuid4()),
            "userId": user_id,
            "displayName": name,
            "email": _upn(name),
            "roles": ["owner"] if owner else [],
        }

    def _handle(self, request: httpx.Request) -> httpx.Response:
        for routes in (self._lifecycle, self._files):
            if (found := routes(request)) is not None:
                return found
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
        if path == "/me/calendarView/delta":
            return self._delta(request)
        if match := re.fullmatch(r"/teams/([^/]+)/channels", path):
            if (team := self.teams.get(match[1])) is None:
                return _not_found()
            return self._page(request, [{"id": c} for c in team["channels"]])
        if match := re.fullmatch(r"/me/events/([^/]+)/cancel", path):
            return self._change(match[1], {"isCancelled": True}, request)
        if match := re.fullmatch(r"/me/events/([^/]+)", path):
            return self._change(match[1], json.loads(request.content or b"{}"), request)
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

    def _change(self, event_id: str, body: dict, request: httpx.Request) -> httpx.Response:
        """Read or change an event, or one occurrence of a series (an exception to it)."""
        base, _, day = event_id.partition("@")
        if (event := self.events.get(base)) is None:
            return httpx.Response(404, json={"error": {"code": "NotFound"}})
        if request.method != "GET":
            if day:
                event.setdefault("exceptions", {}).setdefault(day, {}).update(body)
            else:
                event.update(body)
            self.changes.append(base)
        if day:
            return httpx.Response(200, json=self._occurrence(event, date.fromisoformat(day)))
        return httpx.Response(200, json=self._shown(event))

    def _create_event(self, body: dict) -> httpx.Response:
        event_id = str(uuid.uuid4())
        self.events[event_id] = {
            **body,
            "id": event_id,
            "onlineMeeting": {"joinUrl": f"https://teams.example.org/l/{event_id}"},
        }
        self.changes.append(event_id)
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

    def _occurrence(self, event: dict, day: date) -> dict:
        start = datetime.fromisoformat(event["start"]["dateTime"])
        length = datetime.fromisoformat(event["end"]["dateTime"]) - start
        start = datetime.combine(day, start.time())
        zone = event["start"]["timeZone"]
        return self._shown(
            {
                **event,
                "id": f"{event['id']}@{day}",
                "start": {"dateTime": start.isoformat(), "timeZone": zone},
                "end": {"dateTime": (start + length).isoformat(), "timeZone": zone},
                **event.get("exceptions", {}).get(str(day), {}),
            }
        )

    def _instances(self, event: dict, params) -> list[dict]:
        if "recurrence" not in event:
            return [self._shown(event)]
        window = [datetime.fromisoformat(params[k]) for k in ("startDateTime", "endDateTime")]
        rng = event["recurrence"]["range"]
        day, last = date.fromisoformat(rng["startDate"]), date.fromisoformat(rng["endDate"])
        weekday = _DAYS.index(event["recurrence"]["pattern"]["daysOfWeek"][0])
        out = []
        while day <= last:
            if day.weekday() == weekday:
                shown = self._occurrence(event, day)
                begins = datetime.fromisoformat(shown["start"]["dateTime"]).replace(tzinfo=UTC)
                if window[0] <= begins < window[1]:
                    out.append(shown)
            day += timedelta(days=1)
        return out

    def _delta(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        window = [datetime.fromisoformat(params[k]) for k in ("startDateTime", "endDateTime")]
        rows = []
        for event_id in dict.fromkeys(self.changes[int(params.get("$deltatoken", 0)) :]):
            if (event := self.events.get(event_id)) is None:
                continue  # deleted since
            series = event_id if "recurrence" in event else None
            rows += [
                {"id": gone, "@removed": {"reason": "deleted"}}
                for gone in sorted(self.deleted)
                if gone.partition("@")[0] == event_id
            ]
            for shown in self._instances(event, params):
                begins = datetime.fromisoformat(shown["start"]["dateTime"]).replace(tzinfo=UTC)
                if shown["id"] not in self.deleted and window[0] <= begins < window[1]:
                    rows.append({**shown, "seriesMasterId": series})
        body = json.loads(self._page(request, rows).content)
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


def _upn(name: str) -> str:
    return name.lower().replace(" ", ".") + "@example.org"


def _bound_user(member: dict) -> str:
    return re.search(r"users\('([^']+)'\)", member["user@odata.bind"])[1]


def _not_found() -> httpx.Response:
    return httpx.Response(404, json={"error": {"code": "NotFound"}})
