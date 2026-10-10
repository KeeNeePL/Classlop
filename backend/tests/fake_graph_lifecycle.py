"""FakeGraph's deletions: a team deleted (and restorable), OneDrive items and calendar events
deleted. The methods without an underscore are what a test sees; FakeTeams has the same by name."""

import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

WARSAW = ZoneInfo("Europe/Warsaw")


def _gone() -> httpx.Response:
    return httpx.Response(404, json={"error": {"code": "itemNotFound"}})


class LifecycleRoutes:
    """Mixed into FakeGraph, which owns `teams`, `events`, `drive` and `_instances`."""

    teams: dict[str, dict]
    events: dict[str, dict]
    drive: dict[str, dict]

    def _instances(self, event: dict, params) -> list[dict]: ...

    def _init_lifecycle(self) -> None:
        self.deleted_teams: dict[str, dict] = {}

    # What a test does in Teams and inspects.
    def delete_team(self, team_id: str) -> None:
        """The team is deleted in Teams: gone from every read, restorable for 30 days."""
        self.deleted_teams[team_id] = self.teams.pop(team_id)

    def undelete_team(self, team_id: str) -> None:
        """The team is restored in Teams."""
        self.teams[team_id] = self.deleted_teams.pop(team_id)

    async def calendar_dates(self, first: date, last: date) -> list[date]:
        """The days from `first` to `last` (Warsaw) with an event Classlop made in the Teacher's
        calendar: Timetable occurrences and single Lessons, not meetings made in Teams."""
        window = {
            "startDateTime": datetime.combine(first, datetime.min.time(), WARSAW)
            .astimezone(UTC)
            .isoformat(),
            "endDateTime": datetime.combine(last + timedelta(days=1), datetime.min.time(), WARSAW)
            .astimezone(UTC)
            .isoformat(),
        }
        days = []
        for event in self.events.values():
            if event.get("made_in_teams"):
                continue
            for shown in self._instances(event, window):
                if shown.get("isCancelled"):
                    continue
                start = datetime.fromisoformat(shown["start"]["dateTime"]).replace(tzinfo=UTC)
                if first <= start.astimezone(WARSAW).date() <= last:
                    days.append(start.astimezone(WARSAW).date())
        return sorted(days)

    # The routes.
    def _lifecycle(self, request: httpx.Request) -> httpx.Response | None:
        path, method = request.url.path.removeprefix("/v1.0"), request.method
        if method == "DELETE" and (m := re.fullmatch(r"/groups/([^/]+)", path)):
            if m[1] not in self.teams:
                return _gone()
            self.delete_team(m[1])
            return httpx.Response(204)
        if method == "POST" and (
            m := re.fullmatch(r"/directory/deletedItems/([^/]+)/restore", path)
        ):
            if m[1] not in self.deleted_teams:
                return _gone()
            self.undelete_team(m[1])
            return httpx.Response(200, json={"id": m[1]})
        if method == "DELETE" and (m := re.fullmatch(r"/me/events/([^/]+)", path)):
            if self.events.pop(m[1], None) is None:
                return _gone()
            return httpx.Response(204)
        if method == "DELETE" and (m := re.fullmatch(r"/me/drive/items/([^/]+)", path)):
            if m[1] not in self.drive:
                return _gone()
            doomed = {m[1]}
            while more := {i["id"] for i in self.drive.values() if i["parent"] in doomed} - doomed:
                doomed |= more
            for item_id in doomed:
                del self.drive[item_id]
            return httpx.Response(204)
        return None
