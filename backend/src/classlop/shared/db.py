from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from classlop.shared.settings import get_settings

SCHEMAS = ("shared", "teams", "grading", "items", "dashboard")


class Base(DeclarativeBase):
    """Every area's models; each table sets its area's schema."""


@lru_cache
def engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def sessions() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine(), expire_on_commit=False)


async def ping() -> None:
    async with engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
