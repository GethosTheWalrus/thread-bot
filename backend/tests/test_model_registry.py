import subprocess
import sys


def test_crud_registers_message_attribution_tables_in_isolated_process():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app.database import crud; "
                "from app.models.models import Message; "
                "assert {str(fk.column) for fk in Message.__table__.foreign_keys} == "
                "{'threads.id', 'agents.id', 'agent_versions.id', 'agent_runs.id'}"
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
