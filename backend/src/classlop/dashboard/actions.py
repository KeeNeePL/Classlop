"""Carrying out a Teacher's action through an area: what the area refuses becomes an HTTP error
the screen can show."""

from collections.abc import Awaitable

from fastapi import HTTPException, Response

from classlop import grading, teams
from classlop.shared.jobs import SignInRequired


async def carry_out(change: Awaitable[object]) -> Response:
    try:
        await change
    except LookupError as e:
        raise HTTPException(404) from e
    except SignInRequired as e:
        # The screen's interceptor answers a 401 with "Zaloguj się ponownie".
        raise HTTPException(401) from e
    except (ValueError, teams.ClassReadOnly, grading.TooEarly) as e:
        raise HTTPException(409, str(e) or None) from e
    return Response(status_code=204)
