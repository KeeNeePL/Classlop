"""`teams` ids are ULID strings; `items` and `grading` key everything on UUIDs. The two convert
without loss, so a Submission's id is `as_uuid(submission.id)` in a grading job and
`from_uuid(submission_id)` back in `teams`."""

import uuid

from ulid import ULID


def as_uuid(ulid: str) -> uuid.UUID:
    return ULID.from_str(ulid).to_uuid()


def from_uuid(value: uuid.UUID) -> str:
    return str(ULID.from_uuid(value))
