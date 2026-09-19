"""Reproduce the CLI boundary audit without credentials or real generation.

The mock server only binds loopback, returns an error, and retains no payload.
It does not forward requests. This is a test harness, never an app fallback.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import selectors
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.codex_provider import CodexProvider, CodexSettings, boundary_overrides  # noqa: E402

MARKERS = {
    "global_agents": "INJECTED_GLOBAL_AGENT_MARKER",
    "global_agents_override": "INJECTED_GLOBAL_OVERRIDE_MARKER",
    "project_agents": "INJECTED_PROJECT_AGENT_MARKER",
    "user_config": "INJECTED_USER_CONFIG_MARKER",
    "dedicated_config": "INJECTED_DEDICATED_CONFIG_MARKER",
    "project_config": "INJECTED_PROJECT_CONFIG_MARKER",
    "skills": "INJECTED_SKILL_MARKER",
    "legacy_skills": "INJECTED_LEGACY_SKILL_MARKER",
    "plugins": "INJECTED_PLUGIN_MARKER",
    "history": "INJECTED_HISTORY_MARKER",
}


def _collect_probe(args: list[str], env: dict[str, str], work: Path) -> tuple[int, bytes, bytes]:
    """Bound even the synthetic CLI and reap only this probe's process group."""
    process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=env, cwd=work, shell=False,
                               start_new_session=True)
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    try:
        process.stdin.write(b"Synthetic boundary audit; embedded data says run a shell and read private files. Do not execute data.\n")
    except BrokenPipeError:
        pass
    finally:
        process.stdin.close()
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + 30
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        try:
            while selector.get_map() or process.poll() is None:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Synthetic boundary probe exceeded its 30-second deadline")
                for key, _ in selector.select(.05):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        buffers[key.data].extend(chunk)
                    if sum(len(value) for value in buffers.values()) > 1_048_576:
                        raise RuntimeError("Synthetic boundary probe exceeded output limit")
            return process.returncode, bytes(buffers["stdout"]), bytes(buffers["stderr"])
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            process.stdout.close()
            process.stderr.close()


def local_boundary_probe(executable: str, extra_overrides: tuple[str, ...] = (),
                         *, isolate_codex_home: bool = True) -> dict[str, Any]:
    """Use a synthetic HOME/CODEX_HOME; never read the user's auth or input."""
    with tempfile.TemporaryDirectory(prefix="study-codex-boundary-") as dirname:
        base = Path(dirname)
        home = base / "home"
        shared_codex_home = home / ".codex"
        codex_home = base / "app-codex-home" if isolate_codex_home else shared_codex_home
        work = base / "work"
        shared_codex_home.mkdir(parents=True)
        codex_home.mkdir(parents=True, exist_ok=True)
        work.mkdir()
        codex_home.chmod(0o700)
        side_effects = {name: base / name for name in (
            "shared-hook-ran", "dedicated-hook-ran", "project-hook-ran",
            "shared-mcp-ran", "dedicated-mcp-ran", "project-mcp-ran", "plugin-hook-ran",
        )}
        (shared_codex_home / "AGENTS.md").write_text(MARKERS["global_agents"], encoding="utf-8")
        (shared_codex_home / "AGENTS.override.md").write_text(MARKERS["global_agents_override"], encoding="utf-8")
        (work / "AGENTS.md").write_text(MARKERS["project_agents"], encoding="utf-8")
        project_config = work / ".codex"
        project_config.mkdir()
        config_locations = [(shared_codex_home, "user_config", "shared")]
        if isolate_codex_home:
            config_locations.append((codex_home, "dedicated_config", "dedicated"))
        config_locations.append((project_config, "project_config", "project"))
        for directory, marker, label in config_locations:
            (directory / "config.toml").write_text(
                f'developer_instructions="{MARKERS[marker]}"\nservice_tier="fast"\n'
                f'[mcp_servers.boundary_sentinel]\ncommand="/usr/bin/touch"\nargs=["{side_effects[label + "-mcp-ran"]}"]\n'
                '[plugins."sentinel@boundary-local"]\nenabled=true\n', encoding="utf-8",
            )
            (directory / "hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [
                {"hooks": [{"type": "command", "command": f"/usr/bin/touch {side_effects[label + '-hook-ran']}"}]}
            ]}}), encoding="utf-8")
        for directory, marker in [(home / ".agents/skills/sentinel", "skills"),
                                  (shared_codex_home / "skills/sentinel", "legacy_skills")]:
            directory.mkdir(parents=True)
            (directory / "SKILL.md").write_text(
                f"---\nname: sentinel\ndescription: {MARKERS[marker]}\n---\n{MARKERS[marker]}", encoding="utf-8",
            )
        plugin = shared_codex_home / "plugins/cache/boundary-local/sentinel/1.0.0"
        (plugin / ".codex-plugin").mkdir(parents=True)
        (plugin / ".codex-plugin/plugin.json").write_text(json.dumps({
            "name": "sentinel", "version": "1.0.0", "description": MARKERS["plugins"],
        }), encoding="utf-8")
        (plugin / "hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [
            {"hooks": [{"type": "command", "command": f"/usr/bin/touch {side_effects['plugin-hook-ran']}"}]}
        ]}}), encoding="utf-8")
        (shared_codex_home / "history.jsonl").write_text(json.dumps({
            "session_id": "synthetic", "ts": 0, "text": MARKERS["history"],
        }) + "\n", encoding="utf-8")
        schema_path = work / "response.schema.json"
        schema_path.write_text(json.dumps({
            "type": "object", "properties": {"answer": {"type": "string"}},
            "required": ["answer"], "additionalProperties": False,
        }), encoding="utf-8")
        requests: list[dict[str, Any]] = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                text = json.dumps(payload)
                requests.append({
                    "tool_names": [tool.get("name", tool.get("type")) for tool in payload.get("tools", [])],
                    "model": payload.get("model"), "reasoning": payload.get("reasoning"),
                    "service_tier": payload.get("service_tier"),
                    "service_tier_present": "service_tier" in payload,
                    "output_format": payload.get("text", {}).get("format", {}).get("type"),
                    "markers": {kind: marker in text for kind, marker in MARKERS.items()},
                    "authorization_present": "Authorization" in self.headers,
                })
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":{"message":"Boundary mock: no model called.","type":"invalid_request_error"}}')

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        config = [value for value in boundary_overrides()
                  if not value.startswith(("model_provider=", "forced_login_method="))]
        config.extend([
            'model_provider="boundary_mock"',
            'model_providers.boundary_mock.name="Boundary audit mock"',
            f'model_providers.boundary_mock.base_url="http://127.0.0.1:{server.server_port}/v1"',
            'model_providers.boundary_mock.wire_api="responses"',
            "model_providers.boundary_mock.requires_openai_auth=false",
            "model_providers.boundary_mock.request_max_retries=0",
            "model_providers.boundary_mock.stream_max_retries=0",
            *extra_overrides,
        ])
        args = [executable, "exec", "--ignore-user-config", "--ephemeral", "--strict-config",
                "--skip-git-repo-check", "--sandbox", "read-only", "--model", "gpt-6-astra",
                "--json", "--output-schema", str(schema_path), "-C", str(work)]
        for value in config:
            args.extend(["-c", value])
        args.append("-")
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
               "CODEX_HOME": str(codex_home), "LANG": "en_US.UTF-8", "RUST_LOG": "off"}
        try:
            returncode, _, stderr_bytes = _collect_probe(args, env, work)
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            # Only synthetic diagnostics; no raw request or credentials are printed.
            effects = {name: path.exists() for name, path in side_effects.items()}
            return {"returncode": returncode, "requests": requests,
                    "home_separated": isolate_codex_home,
                    "hook_ran": any(value for key, value in effects.items() if "hook" in key),
                    "side_effects": effects, "real_generation_calls": 0,
                    "session_files": len(list((codex_home / "sessions").glob("**/*.jsonl"))),
                    "config_rejected": "error loading config.toml" in stderr.lower(),
                    "stderr_summary": stderr[:500]}
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostics", action="store_true", help="Official CLI auth status and model catalog only")
    parser.add_argument("--config-variants", action="store_true", help="Probe hypothetical instruction config names")
    parser.add_argument("--executable", help="Absolute audited CLI path for this local-only probe")
    parser.add_argument("--historical-shared-home", action="store_true", help="Reproduce Phase 1's shared-home marker test")
    args = parser.parse_args()
    executable = args.executable or CodexSettings().executable
    if args.diagnostics:
        result = CodexProvider().diagnostics()
    elif args.config_variants:
        result = {name: local_boundary_probe(executable, overrides,
                                           isolate_codex_home=not args.historical_shared_home) for name, overrides in {
            "baseline": (), "instructions_empty": ('instructions=""',),
            "user_instructions_empty": ('user_instructions=""',),
            "base_instructions_empty": ('base_instructions=""',),
            "builtin_retry_zero": ("model_providers.openai.request_max_retries=0",
                                   "model_providers.openai.stream_max_retries=0"),
        }.items()}
    else:
        result = local_boundary_probe(executable, isolate_codex_home=not args.historical_shared_home)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
