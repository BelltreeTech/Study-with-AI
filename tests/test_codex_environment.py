"""Dedicated Codex environment boundaries; synthetic files/RPCs only."""
from __future__ import annotations

import copy
import json
import os
import stat
import threading
import time
import tomllib
from pathlib import Path
from typing import Any

import pytest

from src import codex_policy, codex_provider
from src.codex_provider import (
    HOME_MARKER,
    HOME_OWNER,
    CodexProvider,
    CodexSettings,
    ProviderError,
    boundary_overrides,
    child_environment,
    prepare_codex_home,
)


@pytest.fixture
def dedicated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CodexSettings:
    personal = tmp_path / "personal"
    personal.mkdir()
    monkeypatch.setenv("HOME", str(personal))
    monkeypatch.setattr(codex_provider, "managed_policy_present", lambda: False)
    return CodexSettings(executable=str(tmp_path / "codex"), codex_home=str(tmp_path / "app-home"))


def test_home_setup_is_private_idempotent_and_preserves_shared_home(dedicated_settings: CodexSettings) -> None:
    shared = Path.home() / ".codex"
    shared.mkdir()
    sentinel = shared / "AGENTS.md"
    sentinel.write_text("synthetic shared configuration must remain untouched")
    original = (sentinel.read_bytes(), sentinel.stat().st_mtime_ns)
    home = prepare_codex_home(dedicated_settings)
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    assert stat.S_IMODE((home / HOME_MARKER).stat().st_mode) == 0o600
    assert json.loads((home / HOME_MARKER).read_text()) == HOME_OWNER
    assert prepare_codex_home(dedicated_settings) == home
    CodexProvider(dedicated_settings)._check_home()
    assert (sentinel.read_bytes(), sentinel.stat().st_mtime_ns) == original
    assert set(shared.iterdir()) == {sentinel}


def test_home_setup_refuses_unowned_existing_directory_without_changes(dedicated_settings: CodexSettings) -> None:
    home = Path(dedicated_settings.codex_home)
    home.mkdir(mode=0o700)
    sentinel = home / "existing-data"
    sentinel.write_text("synthetic retained data")
    with pytest.raises(ValueError):
        prepare_codex_home(dedicated_settings)
    assert sentinel.read_text() == "synthetic retained data"
    assert set(home.iterdir()) == {sentinel}


@pytest.mark.parametrize("kind", ["shared", "shared-child", "shared-symlink-child", "symlink", "repository"])
def test_home_setup_rejects_conflicting_locations(dedicated_settings: CodexSettings, tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    shared = Path.home() / ".codex"
    shared.mkdir()
    if kind == "shared":
        target = shared
    elif kind == "shared-child":
        target = shared / "app"
    elif kind == "shared-symlink-child":
        shared.rmdir()
        external_shared = tmp_path / "external-shared-codex"
        external_shared.mkdir()
        shared.symlink_to(external_shared, target_is_directory=True)
        target = shared / "app"
    elif kind == "symlink":
        target = tmp_path / "shared-link"
        target.symlink_to(shared, target_is_directory=True)
    else:
        repository = tmp_path / "repository"
        monkeypatch.setattr(codex_provider, "__file__", str(repository / "src/codex_provider.py"))
        target = repository / "private-home"
    settings = CodexSettings(executable=dedicated_settings.executable, codex_home=str(target))
    with pytest.raises(ValueError):
        prepare_codex_home(settings)
    assert not list(shared.iterdir())


def test_home_and_auth_permissions_and_owner_are_checked(dedicated_settings: CodexSettings,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    home = prepare_codex_home(dedicated_settings)
    provider = CodexProvider(dedicated_settings)
    home.chmod(0o755)
    with pytest.raises(ProviderError, match="0700"):
        provider._check_home()
    home.chmod(0o700)
    auth = home / "auth.json"
    auth.write_bytes(b"synthetic; deliberately not JSON")
    auth.chmod(0o644)
    with pytest.raises(ProviderError, match="認証ファイル"):
        provider._check_home()
    auth.chmod(0o600)
    real_read = Path.read_text

    def safe_read(path: Path, *args: Any, **kwargs: Any) -> str:
        if path == auth:
            pytest.fail("Provider must never read or parse authentication contents")
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", safe_read)
    provider._check_home()
    actual_uid = os.getuid()
    monkeypatch.setattr(codex_provider.os, "getuid", lambda: actual_uid + 1)
    with pytest.raises(ProviderError, match="本人所有"):
        provider._check_home()


@pytest.mark.parametrize("name", [HOME_MARKER, "auth.json"])
def test_home_rejects_symlinked_sensitive_entries(dedicated_settings: CodexSettings, tmp_path: Path,
                                                name: str) -> None:
    home = prepare_codex_home(dedicated_settings)
    target = tmp_path / "synthetic-external"
    target.write_text(json.dumps(HOME_OWNER) if name == HOME_MARKER else "synthetic-private")
    linked = home / name
    linked.unlink(missing_ok=True)
    linked.symlink_to(target)
    with pytest.raises(ProviderError):
        CodexProvider(dedicated_settings)._check_home()
    assert target.read_text() == (json.dumps(HOME_OWNER) if name == HOME_MARKER else "synthetic-private")


def test_child_environment_uses_dedicated_home_and_filters_credentials(dedicated_settings: CodexSettings,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("CODEX_HOME", "CODEX_SQLITE_HOME", "OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN",
                "OPENAI_BASE_URL", "OPENAI_ORGANIZATION", "CODEX_AUTH_TOKEN", "HTTP_PROXY", "HTTPS_PROXY",
                "CODEX_CONFIG_OVERRIDES", "DYLD_INSERT_LIBRARIES"):
        monkeypatch.setenv(key, "synthetic-must-not-inherit")
    before = dict(os.environ)
    result = child_environment(dedicated_settings)
    assert result["CODEX_HOME"] == dedicated_settings.codex_home
    assert result["HOME"] == str(Path.home())
    assert result["RUST_LOG"] == "off"
    assert "synthetic-must-not-inherit" not in result.values()
    assert dict(os.environ) == before
    assert 'cli_auth_credentials_store="file"' in boundary_overrides()
    assert 'features.unbounded_connection_retries=false' in boundary_overrides()


def test_managed_policy_blocks_before_diagnostics_or_execution(dedicated_settings: CodexSettings,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    prepare_codex_home(dedicated_settings)
    provider = CodexProvider(dedicated_settings)
    monkeypatch.setattr(provider, "_check_executable", lambda: None)
    monkeypatch.setattr(codex_provider, "managed_policy_present", lambda: True)
    monkeypatch.setattr(provider, "_execute", lambda *a, **k: pytest.fail("must not start CLI"))
    info = provider.diagnostics()
    assert not info["ready"] and not info["probe_ready"]
    assert info["blockers"][0]["code"] == "boundary_unavailable"


def test_system_policy_directory_detection_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = tmp_path / "policy"
    policy.mkdir()
    sentinel = policy / "requirements.toml"
    sentinel.write_text("synthetic content intentionally not parsed")
    monkeypatch.setattr(codex_policy, "MANAGED_ROOTS", (policy,))
    monkeypatch.setattr(codex_policy.ctypes, "CDLL", lambda *a, **k: pytest.fail("filesystem policy sufficient"))
    assert codex_policy.managed_policy_present() is True
    assert sentinel.read_text() == "synthetic content intentionally not parsed"


def test_hash_mismatch_rejected_without_executing_file(dedicated_settings: CodexSettings,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    executable = Path(dedicated_settings.executable)
    executable.write_bytes(b"synthetic not the official executable")
    executable.chmod(0o700)
    prepare_codex_home(dedicated_settings)
    monkeypatch.setattr(codex_provider.subprocess, "Popen", lambda *a, **k: pytest.fail("must not execute mismatch"))
    info = CodexProvider(dedicated_settings).diagnostics()
    assert not info["ready"] and not info["probe_ready"]
    assert info["blockers"][0]["code"] == "boundary_unavailable"


def test_auth_metadata_change_invalidates_cached_readiness(dedicated_settings: CodexSettings,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    home = prepare_codex_home(dedicated_settings)
    provider = CodexProvider(dedicated_settings)
    provider._diagnostic_cache = (provider._context_identity(), time.monotonic(), {"ready": True})
    auth = home / "auth.json"
    auth.write_bytes(b"synthetic changed identity, no real credential")
    auth.chmod(0o600)
    calls = []

    def refused(cancel: threading.Event) -> dict[str, Any]:
        calls.append(cancel)
        return {"ready": False, "probe_ready": False, "blockers": [{"code": "auth_required", "message": "synthetic"}]}

    monkeypatch.setattr(provider, "diagnostics", refused)
    with pytest.raises(ProviderError) as error:
        provider._ensure_ready(threading.Event())
    assert error.value.code == "auth_required"
    assert len(calls) == 1


def _rpc_config(provider: CodexProvider, monkeypatch: pytest.MonkeyPatch, config: dict[str, Any],
                requirements: dict[str, Any] | None = None,
                layers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    def execute(args: list[str], prompt: bytes, cwd: Path, cancel: threading.Event,
                **kwargs: Any) -> tuple[bytes, bytes, int]:
        assert "app-server" in args
        handler = kwargs["rpc_handler"]
        requests = [json.loads(prompt)["method"]]
        for number, result in enumerate(({}, {"config": config, "layers": layers}, {"requirements": requirements},
                                         {"data": [], "nextCursor": None}), 1):
            reply = handler({"id": number, "result": result})
            if reply:
                requests.extend(json.loads(line)["method"] for line in reply.splitlines())
        assert requests == ["initialize", "initialized", "config/read", "configRequirements/read", "model/list"]
        return b"", b"", 0

    monkeypatch.setattr(provider, "_execute", execute)
    return provider._resolved_configuration(threading.Event(), 1)


@pytest.mark.parametrize(("setting", "value"), [
    ("mcp_servers", {"untrusted": {"command": "/synthetic/untrusted"}}),
    ("openai_base_url", "https://synthetic.invalid/v1"),
    ("openai_base_url", "https://api.openai.com/v1"),
    ("chatgpt_base_url", "https://synthetic.invalid/backend-api"),
    ("model_catalog_json", "/synthetic/catalog.json"),
    ("model_instructions_file", "/synthetic/instructions.md"),
    ("notify", ["/synthetic/notification-command"]),
    ("hooks", {"synthetic": {"command": "/synthetic/hook"}}),
    ("model_providers", {"synthetic": {"base_url": "https://synthetic.invalid"}}),
    ("developer_instructions", "synthetic extra system instruction"),
    ("skills.include_instructions", True),
    ("skills.bundled.enabled", True),
    ("tools.update_plan.enabled", True),
    ("tools.experimental_request_user_input.enabled", True),
    ("project_doc_max_bytes", 32000),
    ("features.unbounded_connection_retries", True),
])
def test_effective_configuration_rejects_inherited_unsafe_defaults(dedicated_settings: CodexSettings,
                                                                 monkeypatch: pytest.MonkeyPatch,
                                                                 setting: str, value: Any) -> None:
    config = tomllib.loads("\n".join([*boundary_overrides(), 'model="gpt-6-astra"', 'sandbox_mode="read-only"']))
    config = copy.deepcopy(config)
    nested = config
    components = setting.split(".")
    for component in components[:-1]:
        nested = nested[component]
    nested[components[-1]] = value
    with pytest.raises(ProviderError) as error:
        _rpc_config(CodexProvider(dedicated_settings), monkeypatch, config)
    assert error.value.code == "boundary_unavailable"


def test_effective_cloud_requirements_are_not_ignored(dedicated_settings: CodexSettings,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    config = tomllib.loads("\n".join([*boundary_overrides(), 'model="gpt-6-astra"', 'sandbox_mode="read-only"']))
    with pytest.raises(ProviderError) as error:
        _rpc_config(CodexProvider(dedicated_settings), monkeypatch, config, {"allowedApprovalPolicies": ["on-request"]})
    assert error.value.code == "boundary_unavailable"


def test_managed_policy_rechecked_even_when_readiness_is_cached(dedicated_settings: CodexSettings,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    prepare_codex_home(dedicated_settings)
    provider = CodexProvider(dedicated_settings)
    provider._diagnostic_cache = (provider._context_identity(), time.monotonic(), {"ready": True})
    monkeypatch.setattr(codex_provider, "managed_policy_present", lambda: True)
    monkeypatch.setattr(provider, "diagnostics", lambda *a, **k: pytest.fail("policy must block first"))
    with pytest.raises(ProviderError, match="管理者"):
        provider._ensure_ready(threading.Event())


@pytest.mark.parametrize("present_key", [b"config_toml_base64", b"requirements_toml_base64", None])
def test_mdm_keys_are_checked_without_decoding_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                    present_key: bytes | None) -> None:
    strings: dict[int, bytes] = {}
    released: list[int] = []
    looked_up: list[bytes] = []

    class Function:
        def __init__(self, implementation: Any):
            self.implementation = implementation

        def __call__(self, *args: Any) -> Any:
            return self.implementation(*args)

    def create_string(allocator: Any, value: bytes, encoding: int) -> int:
        pointer = len(strings) + 1
        strings[pointer] = value
        return pointer

    def copy_value(key: int, domain: int) -> int:
        assert strings[domain] == b"com.openai.codex"
        looked_up.append(strings[key])
        return 100 if strings[key] == present_key else 0

    class Core:
        CFStringCreateWithCString = Function(create_string)
        CFPreferencesCopyAppValue = Function(copy_value)
        CFRelease = Function(released.append)

    monkeypatch.setattr(codex_policy, "MANAGED_ROOTS", (tmp_path / "absent-policy",))
    monkeypatch.setattr(codex_policy.sys, "platform", "darwin")
    monkeypatch.setattr(codex_policy.ctypes, "CDLL", lambda *a, **k: Core())
    assert codex_policy.managed_policy_present() == (present_key is not None)
    assert looked_up == ([b"config_toml_base64"] if present_key == b"config_toml_base64" else
                         [b"config_toml_base64", b"requirements_toml_base64"])
    assert set(strings).issubset(released)
    assert (100 in released) == (present_key is not None)


def test_setup_refuses_symlinked_owner_marker(dedicated_settings: CodexSettings, tmp_path: Path) -> None:
    home = Path(dedicated_settings.codex_home)
    home.mkdir(mode=0o700)
    external = tmp_path / "external-owner-document"
    external.write_text(json.dumps(HOME_OWNER))
    (home / HOME_MARKER).symlink_to(external)
    with pytest.raises(ValueError):
        prepare_codex_home(dedicated_settings)
    assert external.read_text() == json.dumps(HOME_OWNER)


def test_cloud_cache_in_place_change_invalidates_cached_readiness(dedicated_settings: CodexSettings,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    home = prepare_codex_home(dedicated_settings)
    cloud_cache = home / "cloud-config-bundle-cache.json"
    cloud_cache.write_bytes(b"synthetic old policy cache")
    provider = CodexProvider(dedicated_settings)
    provider._diagnostic_cache = (provider._context_identity(), time.monotonic(), {"ready": True})
    directory_mtime = home.stat().st_mtime_ns
    cloud_cache.write_bytes(b"synthetic changed policy cache; not official schema")
    assert home.stat().st_mtime_ns == directory_mtime
    calls = []

    def refused(cancel: threading.Event) -> dict[str, Any]:
        calls.append(cancel)
        return {"ready": False, "probe_ready": False,
                "blockers": [{"code": "boundary_unavailable", "message": "synthetic changed policy"}]}

    monkeypatch.setattr(provider, "diagnostics", refused)
    with pytest.raises(ProviderError) as error:
        provider._ensure_ready(threading.Event())
    assert error.value.code == "boundary_unavailable"
    assert len(calls) == 1


@pytest.mark.parametrize("raw_tool_enabled", [False, True, None])
def test_typed_tools_omission_requires_explicit_disabled_session_flags(dedicated_settings: CodexSettings,
                                                                    monkeypatch: pytest.MonkeyPatch,
                                                                    raw_tool_enabled: bool | None) -> None:
    config = tomllib.loads("\n".join([*boundary_overrides(), 'model="gpt-6-astra"', 'sandbox_mode="read-only"']))
    config["tools"] = {"web_search": None}  # Exact 0.155.1 ToolsV2 projection.
    flags = {} if raw_tool_enabled is None else {"tools": {
        "update_plan": {"enabled": raw_tool_enabled},
        "experimental_request_user_input": {"enabled": raw_tool_enabled},
    }}
    layers = [{"name": {"type": "sessionFlags"}, "version": "synthetic", "config": flags}]
    if raw_tool_enabled is False:
        result = _rpc_config(CodexProvider(dedicated_settings), monkeypatch, config, layers=layers)
        assert result["effective_settings"]["unbounded_connection_retries"] is False
    else:
        with pytest.raises(ProviderError) as error:
            _rpc_config(CodexProvider(dedicated_settings), monkeypatch, config, layers=layers)
        assert error.value.code == "boundary_unavailable"


@pytest.mark.parametrize("error_type", [OSError, RuntimeError])
def test_policy_detection_failure_is_sanitized_and_blocks(dedicated_settings: CodexSettings,
                                                        monkeypatch: pytest.MonkeyPatch,
                                                        error_type: type[Exception]) -> None:
    prepare_codex_home(dedicated_settings)
    provider = CodexProvider(dedicated_settings)
    monkeypatch.setattr(provider, "_check_executable", lambda: None)

    def fail_policy() -> bool:
        raise error_type("synthetic internal failure; do not disclose")

    monkeypatch.setattr(codex_provider, "managed_policy_present", fail_policy)
    monkeypatch.setattr(provider, "_execute", lambda *a, **k: pytest.fail("must not start CLI"))
    result = provider.diagnostics()
    assert not result["ready"] and not result["probe_ready"]
    assert result["blockers"][0]["code"] == "boundary_unavailable"
    assert "do not disclose" not in json.dumps(result)
