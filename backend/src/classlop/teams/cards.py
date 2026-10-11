"""A 1:1 chat message to a Student as an Adaptive Card. The real area sends it through Graph and
FakeTeams logs its `text`, so both carry the same words."""

import json
import uuid
from html import escape

from classlop.teams.graph import html_body

CARD = "application/vnd.microsoft.card.adaptive"


def message(
    preview: str,
    kind: str,
    title: str,
    body: list[dict],
    actions: list[dict] | None = None,
    files: list[dict] | None = None,
) -> dict:
    """`preview` is the line above the card, which a notification shows; `files` are reference
    attachments shown under it."""
    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            text(kind, size="Small", weight="Bolder", color="Accent"),
            text(title, size="Large", weight="Bolder", spacing="None"),
            *body,
        ],
        "actions": actions or [],
    }
    content = json.dumps(card, ensure_ascii=False)
    attachment = {"id": uuid.uuid4().hex, "contentType": CARD, "content": content}
    attachments = [attachment, *(files or [])]
    tags = "".join(f'<attachment id="{a["id"]}"></attachment>' for a in attachments)
    return {"body": html_body(f"<p>{escape(preview)}</p>{tags}"), "attachments": attachments}


def text(value: str, **style) -> dict:
    return {"type": "TextBlock", "text": value, "wrap": True, **style}


def facts(pairs: list[tuple[str, str]], **style) -> dict:
    return {"type": "FactSet", "facts": [{"title": t, "value": v} for t, v in pairs], **style}


def link(title: str, url: str) -> dict:
    return {"type": "Action.OpenUrl", "title": title, "url": url}


def readable(message: dict) -> str:
    """What a fake logs: the body and each card, as the Student would read them."""
    cards = (a["content"] for a in message.get("attachments", []) if a["contentType"] == CARD)
    return "\n".join([message["body"]["content"], *cards])
