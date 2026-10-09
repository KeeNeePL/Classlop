from alembic.script import ScriptDirectory

from classlop.shared.db import SCHEMAS
from classlop.shared.migrate import config


def test_one_branch_per_area_on_the_shared_base():
    script = ScriptDirectory.from_config(config())

    assert len(script.get_heads()) == len(SCHEMAS)
    for area in SCHEMAS:
        assert script.get_revision(f"{area}@head")
    for area in SCHEMAS[1:]:
        assert script.get_revision(f"{area}_base").dependencies == "shared_base"
