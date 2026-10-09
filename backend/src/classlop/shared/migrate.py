from pathlib import Path

from alembic import command
from alembic.config import Config

# backend/alembic.ini; the project is installed editable, in the image too.
ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"


def config() -> Config:
    return Config(ALEMBIC_INI)


def migrate() -> None:
    command.upgrade(config(), "heads")
