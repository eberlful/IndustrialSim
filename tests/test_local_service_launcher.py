"""Launcher behavior for source checkouts and prebuilt container assets."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from industrialsim import local_service


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    frontend = tmp_path / 'frontend'
    (frontend / 'dist').mkdir(parents=True)
    (frontend / 'package.json').write_text('{}')
    (frontend / 'dist' / 'index.html').write_text('<html>IndustrialSim</html>')
    (tmp_path / 'project').mkdir()
    monkeypatch.setattr(local_service, '__file__', str(tmp_path / 'src/industrialsim/local_service.py'))
    return tmp_path


def test_default_launcher_builds_and_binds_loopback(checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    build = Mock()
    serve = Mock()
    monkeypatch.setattr(local_service.shutil, 'which', lambda _: '/usr/bin/npm')
    monkeypatch.setattr(local_service.subprocess, 'run', build)
    monkeypatch.setattr(local_service.uvicorn, 'run', serve)

    assert local_service.main([str(checkout / 'project'), '--no-browser']) == 0

    assert [call.args[0] for call in build.call_args_list] == [
        ['/usr/bin/npm', 'ci', '--no-audit', '--no-fund'],
        ['/usr/bin/npm', 'run', 'build'],
    ]
    assert serve.call_args.kwargs == {'host': '127.0.0.1', 'port': 8765}


def test_container_launcher_uses_prebuilt_assets_without_node(checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    build = Mock(side_effect=AssertionError('Must not build at runtime'))
    serve = Mock()
    monkeypatch.setattr(local_service.shutil, 'which', lambda _: None)
    monkeypatch.setattr(local_service.subprocess, 'run', build)
    monkeypatch.setattr(local_service.uvicorn, 'run', serve)

    assert local_service.main([
        str(checkout / 'project'), '--skip-build', '--no-browser', '--host', '0.0.0.0',
    ]) == 0

    build.assert_not_called()
    assert serve.call_args.kwargs == {'host': '0.0.0.0', 'port': 8765}


def test_skip_build_reports_missing_assets(checkout: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (checkout / 'frontend/dist/index.html').unlink()

    with pytest.raises(SystemExit) as error:
        local_service.main([str(checkout / 'project'), '--skip-build', '--no-browser'])

    assert error.value.code == 2
    assert '--skip-build requires a built frontend/dist/index.html' in capsys.readouterr().err
