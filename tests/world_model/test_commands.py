import subprocess
import sys

from industrialsim.world_model.commands import worker_command


def test_worker_uses_the_running_project_interpreter(monkeypatch) -> None:
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, '{"status":"ready"}', '')
    monkeypatch.setattr(subprocess, "run", run)
    assert worker_command("preflight") == {"status": "ready"}
    assert calls[0][0] == sys.executable
    assert calls[0][-1] == "preflight"
