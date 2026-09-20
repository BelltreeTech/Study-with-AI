"""Set up/diagnose the dedicated runtime; print an official login command for its owner."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.codex_provider import CodexProvider, CodexSettings, prepare_codex_home  # noqa: E402


def login_command(settings: CodexSettings) -> str:
    return shlex.join([
        "/usr/bin/env", "-i", f"HOME={Path.home()}", "PATH=/usr/bin:/bin:/usr/sbin:/sbin",
        f"CODEX_HOME={settings.codex_home}", settings.executable,
        "-c", 'cli_auth_credentials_store="file"', "-c", 'forced_login_method="chatgpt"',
        "-c", 'model_provider="openai"', "login",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--setup-home", action="store_true")
    group.add_argument("--login-command", action="store_true")
    group.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()
    settings = CodexSettings()
    if args.setup_home:
        path = prepare_codex_home(settings)
        print(json.dumps({"dedicated_home": str(path), "created_or_owned": True}, ensure_ascii=False))
        return 0
    provider = CodexProvider(settings)
    diagnostics = provider.diagnostics()
    if args.login_command:
        if not diagnostics["boundary_verified"]:
            print(json.dumps(diagnostics, ensure_ascii=False, indent=2))
            return 2
        if diagnostics["auth"] == "chatgpt":
            print("専用homeはChatGPTログイン済みです。再ログインは不要です。")
            return 0
        print("次のコマンドを本人が実行し、表示された公式ブラウザログインを完了してください。")
        print("共有Codexからlogoutせず、同じアカウントの通常利用としてログインします。")
        print(login_command(settings))
        return 0
    print(json.dumps(diagnostics, ensure_ascii=False, indent=2))
    return 0 if diagnostics["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
