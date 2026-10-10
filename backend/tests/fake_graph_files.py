"""FakeGraph's OneDrive, sharing, 1:1 chats and channel posts. Later tickets add routes here (or
beside it) and inspect the same state; the methods without an underscore are what a test sees,
and FakeTeams has the same by name."""

import json
import re
import uuid
from collections.abc import Callable
from datetime import datetime
from urllib.parse import unquote

import httpx

from classlop.teams.fake_giving import Post, Share
from classlop.teams.service import zulu

ROOT = "root"
# Where a file's content is served from, as Graph redirects a download to a URL of its own.
DOWNLOADS = "download.example.org"


def _gone() -> httpx.Response:
    return httpx.Response(404, json={"error": {"code": "itemNotFound"}})


class FilesRoutes:
    """Mixed into FakeGraph, which owns `teacher_id`, `teams` and `_page`."""

    teacher_id: str

    def _init_files(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        # The ids of drive items created, changed or deleted, in order: what the drive delta says.
        self._drive_log: list[str] = []
        # Drive items by id: the Teacher's OneDrive under ROOT and each channel's files folder.
        self.drive: dict[str, dict] = {ROOT: {"id": ROOT, "name": "", "parent": None, "url": ""}}
        self._channel_folders: dict[tuple[str, str], str] = {}
        self._posts: dict[str, list[Post]] = {}
        self._attachments: dict[str, list[dict]] = {}  # by post id
        self._replies: dict[str, list[str]] = {}  # by post id
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

    def replies_to(self, post_id: str) -> list[str]:
        """The HTML of the replies in the thread of a channel post."""
        return self._replies.get(post_id, [])

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

    def upload(self, user_id: str, name: str, content: bytes, folder: str | None = None) -> None:
        """A Student adds a file to the folder the Teacher shared with them (the one at `folder`,
        a path from `shared_with`, else the latest), as of the server's time. A file of the same
        name is replaced. Raises PermissionError once the folder is read-only."""
        target = self._shared_folder(user_id, folder)
        if target["shares"][user_id][1] != "write":
            raise PermissionError(f"{self._path(target['id'])} is read-only")
        now = zulu(self._clock())
        same = next(
            (i for i in self.drive.values() if i["parent"] == target["id"] and i["name"] == name),
            None,
        )
        if same:
            same.update(content=content, modified=now)
            self._drive_log.append(same["id"])
        else:
            self._child(target["id"], name, content=content, created=now, modified=now, by=user_id)

    def delete_file(self, user_id: str, name: str, folder: str | None = None) -> None:
        """A Student deletes a file from their folder."""
        target = self._shared_folder(user_id, folder)
        gone = next(
            i for i in self.drive.values() if i["parent"] == target["id"] and i["name"] == name
        )
        del self.drive[gone["id"]]
        self._drive_log.append(gone["id"])

    def _shared_folder(self, user_id: str, folder: str | None) -> dict:
        found = [
            i
            for i in self.drive.values()
            if user_id in i.get("shares", {}) and folder in (None, self._path(i["id"]))
        ]
        return found[-1]

    # The routes.
    def _files(self, request: httpx.Request) -> httpx.Response | None:
        path, method = unquote(request.url.path).removeprefix("/v1.0"), request.method
        if request.url.host == DOWNLOADS:
            return self._download(path.removeprefix("/"), request)
        if m := re.fullmatch(r"/teams/([^/]+)/channels/([^/]+)/filesFolder", path):
            return self._files_folder(m[1], m[2])
        if m := re.fullmatch(r"/drives/([^/]+)/items/([^/]+):/(.+):/content", path):
            return self._put_file(m[2], m[3], request)
        if m := re.fullmatch(r"/teams/([^/]+)/channels/([^/]+)/messages", path):
            return self._post(m[1], request)
        if m := re.fullmatch(r"/teams/([^/]+)/channels/([^/]+)/messages/([^/]+)", path):
            return self._message(m[1], m[3], request)
        if m := re.fullmatch(r"/teams/([^/]+)/channels/([^/]+)/messages/([^/]+)/replies", path):
            return self._reply(m[1], m[3], json.loads(request.content))
        if m := re.fullmatch(
            r"/users/[^/]+/teams/([^/]+)/channels/([^/]+)/messages/([^/]+)/softDelete", path
        ):
            return self._soft_delete(m[1], m[3])
        if m := re.fullmatch(r"/me/drive/root:/(.+)", path):
            found = self._by_path(m[1])
            return httpx.Response(200, json=self._item(found)) if found else _gone()
        if m := re.fullmatch(r"/me/drive/(?:root|items/([^/]+))/children", path):
            return self._new_folder(m[1] or ROOT, json.loads(request.content))
        if (m := re.fullmatch(r"/me/drive/items/([^/]+)/invite", path)) and method == "POST":
            return self._invite(m[1], json.loads(request.content))
        if (m := re.fullmatch(r"/me/drive/items/([^/]+)/permissions/([^/]+)", path)) and (
            method == "PATCH"
        ):
            return self._set_role(m[1], m[2], json.loads(request.content))
        if path == "/me/drive/root/delta":
            return self._drive_delta(request)
        if (m := re.fullmatch(r"/me/drive/items/([^/]+)/content", path)) and method == "GET":
            return self._redirect_to_download(m[1])
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
        self._drive_log.append(item_id)
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
        now = zulu(self._clock())
        file = self._child(
            folder_id,
            self._free_name(folder_id, name, stem_ext=True),
            content=request.content,
            created=now,
            modified=now,
            by=self.teacher_id,
        )
        return httpx.Response(201, json={**self._item(file), "eTag": f'"{{{uuid.uuid4()}}},1"'})

    def _post(self, team_id: str, request: httpx.Request) -> httpx.Response:
        if team_id in self._rejected:
            return httpx.Response(403, json={"error": {"code": "Forbidden"}})
        body = json.loads(request.content)
        post = Post(str(uuid.uuid4()), body["body"]["content"], self._attached(body))
        self._attachments[post.id] = body.get("attachments", [])
        self._posts.setdefault(team_id, []).append(post)
        return httpx.Response(201, json={"id": post.id})

    def _attached(self, body: dict) -> dict[str, bytes]:
        return {
            a["name"]: next(
                i["content"] for i in self.drive.values() if i["url"] == a["contentUrl"]
            )
            for a in body.get("attachments", [])
        }

    def _find_post(self, team_id: str, post_id: str) -> int | None:
        posts = self._posts.get(team_id, [])
        return next((n for n, p in enumerate(posts) if p.id == post_id), None)

    def _message(self, team_id: str, post_id: str, request: httpx.Request) -> httpx.Response:
        n = self._find_post(team_id, post_id)
        if n is None:
            return _gone()
        post = self._posts[team_id][n]
        if request.method != "PATCH":
            return httpx.Response(
                200,
                json={
                    "id": post_id,
                    "body": {"contentType": "html", "content": post.html},
                    "attachments": self._attachments.get(post_id, []),
                },
            )
        if team_id in self._rejected:
            return httpx.Response(403, json={"error": {"code": "Forbidden"}})
        body = json.loads(request.content)
        if "attachments" in body:
            self._attachments[post_id] = body["attachments"]
        self._posts[team_id][n] = Post(
            post_id, body["body"]["content"], self._attached(body) or post.files
        )
        return httpx.Response(204)

    def _reply(self, team_id: str, post_id: str, body: dict) -> httpx.Response:
        if self._find_post(team_id, post_id) is None:
            return _gone()
        if team_id in self._rejected:
            return httpx.Response(403, json={"error": {"code": "Forbidden"}})
        self._replies.setdefault(post_id, []).append(body["body"]["content"])
        return httpx.Response(201, json={"id": str(uuid.uuid4())})

    def _soft_delete(self, team_id: str, post_id: str) -> httpx.Response:
        n = self._find_post(team_id, post_id)
        if n is None:
            return _gone()
        del self._posts[team_id][n]
        self._replies.pop(post_id, None)
        return httpx.Response(204)

    def _new_folder(self, parent: str, body: dict) -> httpx.Response:
        if parent not in self.drive:
            return _gone()
        name = body["name"]
        if body.get("@microsoft.graph.conflictBehavior") == "rename":
            name = self._free_name(parent, name)
        elif any(i["parent"] == parent and i["name"] == name for i in self.drive.values()):
            return httpx.Response(409, json={"error": {"code": "nameAlreadyExists"}})
        return httpx.Response(201, json=self._item(self._child(parent, name, shares={})))

    def _set_role(self, item_id: str, permission: str, body: dict) -> httpx.Response:
        shares = self.drive.get(item_id, {}).get("shares", {})
        who = next((u for u, (p, _) in shares.items() if p == permission), None)
        if who is None:
            return _gone()
        shares[who] = (permission, body["roles"][0])
        return httpx.Response(200, json={"id": permission, "roles": body["roles"]})

    def _redirect_to_download(self, item_id: str) -> httpx.Response:
        if "content" not in self.drive.get(item_id, {}):
            return _gone()
        return httpx.Response(302, headers={"Location": f"https://{DOWNLOADS}/{item_id}"})

    def _download(self, item_id: str, request: httpx.Request) -> httpx.Response:
        # The URL is pre-authenticated: a token sent to it would be a leak.
        if "authorization" in request.headers or "content" not in self.drive.get(item_id, {}):
            return httpx.Response(401)
        return httpx.Response(200, content=self.drive[item_id]["content"])

    def _drive_delta(self, request: httpx.Request) -> httpx.Response:
        """What changed in the Teacher's drive since `token` (everything without one)."""
        rows = []
        for item_id in dict.fromkeys(self._drive_log[int(request.url.params.get("token", 0)) :]):
            item = self.drive.get(item_id)
            if item is None:
                rows.append({"id": item_id, "deleted": {"state": "deleted"}})
                continue
            row = {
                "id": item_id,
                "name": item["name"],
                "parentReference": {"id": item["parent"], "driveId": "drive-teacher"},
            }
            if "content" in item:
                row |= {
                    "file": {},
                    "createdDateTime": item["created"],
                    "lastModifiedDateTime": item["modified"],
                    "createdBy": {"user": {"id": item["by"]}},
                }
            else:
                row["folder"] = {}
            rows.append(row)
        body = json.loads(self._page(request, rows).content)
        if "@odata.nextLink" not in body:
            link = request.url.copy_remove_param("skip")
            body["@odata.deltaLink"] = str(link.copy_set_param("token", len(self._drive_log)))
        return httpx.Response(200, json=body)

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
