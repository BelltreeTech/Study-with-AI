"""Login assistance only prints a bounded command; all diagnostics are synthetic."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import codex_runtime
from src.codex_provider import CodexSettings


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CodexSettings:
    personal = tmp_path / "synthetic user ' $(untouched) `untouched`"
    monkeypatch.setenv("HOME", str(personal))
    return CodexSettings(
        executable=str(tmp_path / "official CLI ' $(untouched) `untouched`"),
        codex_home=str(tmp_path / "private home ' $(untouched) `untouched`"),
    )


def test_login_command_is_shell_quoted_and_has_only_fixed_environment(settings: CodexSettings,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "AZURE_OPENAI_API_KEY", "OPENAI_BASE_URL",
                 "CODEX_ACCESS_TOKEN", "CODEX_HOME", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                 "SSL_CERT_FILE", "BROWSER", "DYLD_INSERT_LIBRARIES", "RUST_LOG", "PATH"):
        monkeypatch.setenv(name, "synthetic-secret-do-not-print")
    before = dict(os.environ)
    command = codex_runtime.login_command(settings)
    assert shlex.split(command) == [
        "/usr/bin/env", "-i", f"HOME={Path.home()}", "PATH=/usr/bin:/bin:/usr/sbin:/sbin",
        f"CODEX_HOME={settings.codex_home}", settings.executable,
        "-c", 'cli_auth_credentials_store="file"', "-c", 'forced_login_method="chatgpt"',
        "-c", 'model_provider="openai"', "login",
    ]
    assert "synthetic-secret-do-not-print" not in command
    assert dict(os.environ) == before


@pytest.mark.parametrize(("boundary", "auth", "expected"), [
    (True, "unavailable", 0), (True, "chatgpt", 0), (False, "unavailable", 2),
])
def test_login_helper_never_executes_login_or_mutates_environment(settings: CodexSettings,
                                                               monkeypatch: pytest.MonkeyPatch,
                                                               capsys: pytest.CaptureFixture[str],
                                                               boundary: bool, auth: str, expected: int) -> None:
    info = {"boundary_verified": boundary, "auth": auth, "ready": auth == "chatgpt", "blockers": []}
    calls: list[str] = []

    class FakeProvider:
        def __init__(self, supplied: CodexSettings):
            assert supplied is settings

        def diagnostics(self) -> dict[str, Any]:
            calls.append("diagnostics")
            return info

    def no_execution(*args: Any, **kwargs: Any) -> None:
        pytest.fail("login assistance must never execute login or a browser")

    monkeypatch.setattr(codex_runtime, "CodexSettings", lambda: settings)
    monkeypatch.setattr(codex_runtime, "CodexProvider", FakeProvider)
    monkeypatch.setattr(codex_runtime, "prepare_codex_home", no_execution)
    monkeypatch.setattr(subprocess, "Popen", no_execution)
    monkeypatch.setattr(os, "system", no_execution)
    monkeypatch.setattr(codex_runtime.sys, "argv", ["codex_runtime.py", "--login-command"])
    before = dict(os.environ)
    assert codex_runtime.main() == expected
    output = capsys.readouterr().out
    assert calls == ["diagnostics"]
    assert dict(os.environ) == before
    if not boundary:
        assert json.loads(output) == info
        assert "env -i" not in output
    elif auth == "chatgpt":
        assert "再ログインは不要" in output
        assert "env -i" not in output
    else:
        assert shlex.split(output.splitlines()[-1]) == shlex.split(codex_runtime.login_command(settings))
        assert "本人が実行" in output
