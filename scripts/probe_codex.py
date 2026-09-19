"""Reproduce the CLI boundary audit without credentials or real generation.

The mock server only binds loopback, returns an error, and retains no payload.
It does not forward requests. This is a test harness, never an app fallback.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.codex_provider import CodexProvider, CodexSettings, boundary_overrides  # noqa: E402


def local_boundary_probe(executable: str, extra_overrides: tuple[str, ...] = ()) -> dict[str, Any]:
    """Use a synthetic HOME/CODEX_HOME; never read the user's auth or input."""
    with tempfile.TemporaryDirectory(prefix="study-codex-boundary-") as dirname:
        base = Path(dirname)
        home = base / "home"
        codex_home = home / ".codex"
        work = base / "work"
        codex_home.mkdir(parents=True)
        work.mkdir()
        (codex_home / "AGENTS.md").write_text("INJECTED_GLOBAL_AGENT_MARKER", encoding="utf-8")
        (work / "AGENTS.md").write_text("INJECTED_PROJECT_AGENT_MARKER", encoding="utf-8")
        (codex_home / "config.toml").write_text(
            'developer_instructions="INJECTED_USER_CONFIG_MARKER"\n'
            '[mcp_servers.boundary_sentinel]\ncommand="/usr/bin/false"\n', encoding="utf-8",
        )
        skill = home / ".agents" / "skills" / "sentinel"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: sentinel\ndescription: INJECTED_SKILL_MARKER\n---\nINJECTED_SKILL_MARKER",
            encoding="utf-8",
        )
        hook_sentinel = base / "hook-ran"
        (codex_home / "hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [
            {"hooks": [{"type": "command", "command": f"/usr/bin/touch {hook_sentinel}"}]}
        ]}}), encoding="utf-8")
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
                    "markers": {kind: marker in text for kind, marker in {
                        "global_agents": "INJECTED_GLOBAL_AGENT_MARKER",
                        "project_agents": "INJECTED_PROJECT_AGENT_MARKER",
                        "user_config": "INJECTED_USER_CONFIG_MARKER",
                        "skills": "INJECTED_SKILL_MARKER",
                    }.items()},
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
                "--json", "-C", str(work)]
        for value in config:
            args.extend(["-c", value])
        args.append("-")
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
               "CODEX_HOME": str(codex_home), "LANG": "en_US.UTF-8", "RUST_LOG": "off"}
        try:
            completed = subprocess.run(args, input="Synthetic boundary audit; no action requested.",
                                       text=True, capture_output=True, env=env, cwd=work,
                                       timeout=30, shell=False, check=False)
            # Only synthetic diagnostics; no raw request or credentials are printed.
            return {"returncode": completed.returncode, "requests": requests,
                    "hook_ran": hook_sentinel.exists(), "real_generation_calls": 0,
                    "config_rejected": "error loading config.toml" in completed.stderr.lower(),
                    "stderr_summary": completed.stderr[:500]}
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostics", action="store_true", help="Official CLI auth status and model catalog only")
    parser.add_argument("--config-variants", action="store_true", help="Probe hypothetical instruction config names")
    args = parser.parse_args()
    if args.diagnostics:
        result = CodexProvider().diagnostics()
    elif args.config_variants:
        result = {name: local_boundary_probe(CodexSettings().executable, overrides) for name, overrides in {
            "baseline": (), "instructions_empty": ('instructions=""',),
            "user_instructions_empty": ('user_instructions=""',),
            "base_instructions_empty": ('base_instructions=""',),
            "builtin_retry_zero": ("model_providers.openai.request_max_retries=0",
                                   "model_providers.openai.stream_max_retries=0"),
        }.items()}
    else:
        result = local_boundary_probe(CodexSettings().executable)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
