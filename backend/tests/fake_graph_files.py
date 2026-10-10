"""FakeGraph's OneDrive, sharing, 1:1 chats and channel posts. Later tickets add routes here (or
beside it) and inspect the same state; the methods without an underscore are what a test sees,
and FakeTeams has the same by name."""

import json
import re
import uuid
from urllib.parse import unquote

import httpx

from classlop.teams.fake_giving import Post, Share

ROOT = "root"


def _gone() -> httpx.Response:
    return httpx.Response(404, json={"error": {"code": "itemNotFound"}})


class FilesRoutes:
    """Mixed into FakeGraph, which owns `teacher_id`, `teams` and `_page`."""

    teacher_id: str

    def _init_files(self) -> None:
        # Drive items by id: the Teacher's OneDrive under ROOT and each channel's files folder.
        self.drive: dict[str, dict] = {ROOT: {"id": ROOT, "name": "", "parent": None, "url": ""}}
        self._channel_folders: dict[tuple[str, str], str] = {}
        self._posts: dict[str, list[Post]] = {}
        self._chats: dict[str, str] = {}  # the Student's user id -> the 1:1 chat with the Teacher
        self._chat_log: dict[str, list[str]] = {}
        self._rejected: set[str] = set()  # user ids and team ids whose chat or post is refused
        self._emails = 0

    # What a test sets up and inspects.
    def reject_chats(self, user_id: str) -> None:
        """Creating a chat with the user, or writing in it, fails until `accept_chats`."""
        self._rejected.add(user_id)

    def accept_chats(self, user_id: str) -> None:
        self._rejected.discard(user_id)

    def reject_posts(self, team_id: str) -> None:
        """Posting in the team's channels fails until `accept_posts`."""
        self._rejected.add(team_id)

    def accept_posts(self, team_id: str) -> None:
        self._rejected.discard(team_id)

    def channel_posts(self, team_id: str) -> list[Post]:
        return self._posts.get(team_id, [])

    def shared_with(self, user_id: str) -> list[Share]:
        """The folders the Teacher shared with the user, with their role."""
        return [
            Share(self._path(item["id"]), role, item["url"])
            for item in self.drive.values()
            for who, (_, role) in item.get("shares", {}).items()
            if who == user_id
        ]

    def chat_messages(self, user_id: str) -> list[str]:
        """The HTML of what the Teacher wrote to the user in their 1:1 chat."""
        return self._chat_log.get(self._chats.get(user_id, ""), [])

    def invitation_emails(self) -> int:
        return self._emails

    # The routes.
    def _files(self, request: httpx.Request) -> httpx.Response | None:
        path, method = unquote(request.url.path).removeprefix("/v1.0"), request.method
        if m := re.fullmatch(r"/teams/([^/]+)/channels/([^/]+)/filesFolder", path):
            return self._files_folder(m[1], m[2])
        if m := re.fullmatch(r"/drives/([^/]+)/items/([^/]+):/(.+):/content", path):
            return self._put_file(m[2], m[3], request)
        if m := re.fullmatch(r"/teams/([^/]+)/channels/([^/]+)/messages", path):
            return self._post(m[1], request)
        if m := re.fullmatch(r"/me/drive/root:/(.+)", path):
            found = self._by_path(m[1])
            return httpx.Response(200, json=self._item(found)) if found else _gone()
        if m := re.fullmatch(r"/me/drive/(?:root|items/([^/]+))/children", path):
            return self._new_folder(m[1] or ROOT, json.loads(request.content))
        if (m := re.fullmatch(r"/me/drive/items/([^/]+)/invite", path)) and method == "POST":
            return self._invite(m[1], json.loads(request.content))
        if path == "/chats" and method == "POST":
            return self._open_chat(json.loads(request.content))
        if m := re.fullmatch(r"/chats/([^/]+)/messages", path):
            return self._write(m[1], json.loads(request.content))
        return None

    def _path(self, item_id: str) -> str:
        names = []
        while item_id != ROOT and item_id in self.drive:
            names.append(self.drive[item_id]["name"])
            item_id = self.drive[item_id]["parent"]
        return "/".join(reversed(names))

    def _by_path(self, path: str) -> dict | None:
        return next(
            (i for i in self.drive.values() if i["id"] != ROOT and self._path(i["id"]) == path),
            None,
        )

    @staticmethod
    def _item(item: dict) -> dict:
        return {"id": item["id"], "name": item["name"], "webUrl": item["url"]}

    def _child(self, parent: str, name: str, **fields) -> dict:
        item_id = uuid.uuid4().hex
        item = {
            "id": item_id,
            "name": name,
            "parent": parent,
            "url": f"https://onedrive.example.org/{item_id}",
            **fields,
        }
        self.drive[item_id] = item
        return item

    def _free_name(self, parent: str, name: str, stem_ext: bool = False) -> str:
        """What OneDrive calls a new item whose name is taken, under conflictBehavior=rename."""
        taken = {i["name"] for i in self.drive.values() if i["parent"] == parent}
        stem, dot, ext = name.rpartition(".") if stem_ext else (name, "", "")
        candidate, n = name, 0
        while candidate in taken:
            n += 1
            candidate = f"{stem} {n}{dot}{ext}"
        return candidate

    def _files_folder(self, team_id: str, channel_id: str) -> httpx.Response:
        key = (team_id, channel_id)
        if key not in self._channel_folders:
            self._channel_folders[key] = self._child("files", f"{team_id}/{channel_id}")["id"]
        folder = self.drive[self._channel_folders[key]]
        return httpx.Response(
            200, json={**self._item(folder), "parentReference": {"driveId": f"drive-{team_id}"}}
        )

    def _put_file(self, folder_id: str, name: str, request: httpx.Request) -> httpx.Response:
        if folder_id not in self.drive:
            return _gone()
        file = self._child(
            folder_id, self._free_name(folder_id, name, stem_ext=True), content=request.content
        )
        return httpx.Response(201, json={**self._item(file), "eTag": f'"{{{uuid.uuid4()}}},1"'})

    def _post(self, team_id: str, request: httpx.Request) -> httpx.Response:
        if team_id in self._rejected:
            return httpx.Response(403, json={"error": {"code": "Forbidden"}})
        body = json.loads(request.content)
        files = {
            a["name"]: next(
                i["content"] for i in self.drive.values() if i["url"] == a["contentUrl"]
            )
            for a in body.get("attachments", [])
        }
        post = Post(str(uuid.uuid4()), body["body"]["content"], files)
        self._posts.setdefault(team_id, []).append(post)
        return httpx.Response(201, json={"id": post.id})

    def _new_folder(self, parent: str, body: dict) -> httpx.Response:
        if parent not in self.drive:
            return _gone()
        name = body["name"]
        if body.get("@microsoft.graph.conflictBehavior") == "rename":
            name = self._free_name(parent, name)
        elif any(i["parent"] == parent and i["name"] == name for i in self.drive.values()):
            return httpx.Response(409, json={"error": {"code": "nameAlreadyExists"}})
        return httpx.Response(201, json=self._item(self._child(parent, name, shares={})))

    def _invite(self, item_id: str, body: dict) -> httpx.Response:
        item = self.drive.get(item_id)
        if item is None:
            return _gone()
        self._emails += bool(body.get("sendInvitation"))
        granted = []
        for recipient in body["recipients"]:
            permission = str(uuid.uuid4())
            item["shares"][recipient["objectId"]] = (permission, body["roles"][0])
            granted.append({"id": permission, "roles": body["roles"]})
        return httpx.Response(200, json={"value": granted})

    def _open_chat(self, body: dict) -> httpx.Response:
        student = next(
            re.search(r"users\('([^']+)'\)", m["user@odata.bind"])[1]
            for m in body["members"]
            if self.teacher_id not in m["user@odata.bind"]
        )
        if student in self._rejected:
            return httpx.Response(403, json={"error": {"code": "Forbidden"}})
        chat = self._chats.setdefault(student, f"19:{uuid.uuid4().hex}@unq.gbl.spaces")
        self._chat_log.setdefault(chat, [])
        return httpx.Response(201, json={"id": chat})

    def _write(self, chat_id: str, body: dict) -> httpx.Response:
        owner = next((u for u, c in self._chats.items() if c == chat_id), None)
        if owner is None:
            return _gone()
        if owner in self._rejected:
            return httpx.Response(403, json={"error": {"code": "Forbidden"}})
        self._chat_log[chat_id].append(body["body"]["content"])
        return httpx.Response(201, json={"id": str(uuid.uuid4())})
