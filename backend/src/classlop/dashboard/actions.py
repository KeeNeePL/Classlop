"""Carrying out a Teacher's action through an area: what the area refuses becomes an HTTP error
the screen can show."""

from collections.abc import Awaitable, Iterator
from contextlib import contextmanager

from fastapi import HTTPException, Response
from sqlalchemy.exc import NoResultFound

from classlop import grading, teams
from classlop.shared.jobs import SignInRequired


@contextmanager
def refusing() -> Iterator[None]:
    try:
        yield
    except (LookupError, NoResultFound) as e:
        raise HTTPException(404) from e
    except SignInRequired as e:
        # The screen's interceptor answers a 401 with "Zaloguj się ponownie".
        raise HTTPException(401) from e
    except teams.NotOwner as e:
        raise HTTPException(403) from e
    except (
        ValueError,
        teams.ClassReadOnly,
        teams.AlreadyLinked,
        teams.TimetableExists,
        grading.TooEarly,
    ) as e:
        raise HTTPException(409, str(e) or None) from e


async def carry_out(change: Awaitable[object]) -> Response:
    with refusing():
        await change
    return Response(status_code=204)
