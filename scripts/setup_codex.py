"""Install the audited official Codex package beside the shared installation.

No npm lifecycle script, global package manager, PATH edit, login or credential
operation is performed. Only the pinned macOS arm64 package is supported.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

VERSION = "0.155.1"
PLATFORM_VERSION = "0.155.1-darwin-arm64"
METADATA_URL = f"https://registry.npmjs.org/@openai%2fcodex/{PLATFORM_VERSION}"
TARBALL_URL = f"https://registry.npmjs.org/@openai/codex/-/codex-{PLATFORM_VERSION}.tgz"
INTEGRITY = "sha512-cYxzGcRRoBrncyHlR8ed4yXwcoVJZC1pipGULSyJkGFKXJw/Uu57BklvzayuAptjJIipamnOk32CfUkk1F0bLw=="
BINARY_SHA256 = "8eaf1ad12fe6bf89b1710330f58900014322c7c5af677e43be116d8ac5fc0a9e"
RELATIVE_EXECUTABLE = Path("vendor/aarch64-apple-darwin/bin/codex")
MAX_ARCHIVE_BYTES = 200_000_000
MAX_UNPACKED_BYTES = 400_000_000


def install() -> dict[str, str | bool]:
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        raise RuntimeError("この監査済み installer は macOS arm64 専用です。")
    parent = Path.home() / ".local/share/study-with-ai/tools/codex"
    destination = parent / VERSION
    executable = destination / RELATIVE_EXECUTABLE
    if destination.exists() or destination.is_symlink():
        manifest_path = destination / "install-manifest.json"
        if destination.is_symlink() or not manifest_path.is_file() or executable.is_symlink():
            raise RuntimeError("既存の配置がこの installer の管理対象と確認できません。上書きしません。")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = manifest.get("binary_sha256")
        with executable.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if manifest.get("integrity") != INTEGRITY or expected != actual or actual != BINARY_SHA256:
            raise RuntimeError("既存 CLI の整合性検査に失敗しました。上書きしません。")
        return {"executable": str(executable), "version": VERSION, "reused": True, "binary_sha256": actual}
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with urllib.request.urlopen(METADATA_URL, timeout=30) as response:
        metadata = json.load(response)
    if (metadata.get("name") != "@openai/codex" or metadata.get("version") != PLATFORM_VERSION
            or metadata.get("repository", {}).get("url") != "git+https://github.com/openai/codex.git"
            or metadata.get("dist", {}).get("tarball") != TARBALL_URL
            or metadata.get("dist", {}).get("integrity") != INTEGRITY):
        raise RuntimeError("公式 registry の版・配布元・integrity が監査済み値と一致しません。")
    with tempfile.TemporaryDirectory(prefix=".install-codex-", dir=parent) as temp:
        staging = Path(temp)
        archive = staging / "package.tgz"
        digest = hashlib.sha512()
        count = 0
        with urllib.request.urlopen(TARBALL_URL, timeout=60) as response, archive.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > MAX_ARCHIVE_BYTES:
                    raise RuntimeError("配布物が想定サイズ上限を超えました。")
                digest.update(chunk)
                output.write(chunk)
        actual_integrity = "sha512-" + base64.b64encode(digest.digest()).decode("ascii")
        if actual_integrity != INTEGRITY:
            raise RuntimeError("配布物の SHA-512 integrity が一致しません。")
        unpack = staging / "unpacked"
        unpack.mkdir(mode=0o700)
        with tarfile.open(archive, mode="r:gz") as package:
            members = package.getmembers()
            if sum(member.size for member in members) > MAX_UNPACKED_BYTES:
                raise RuntimeError("展開後の配布物が想定サイズ上限を超えます。")
            for member in members:
                name = PurePosixPath(member.name)
                if (name.is_absolute() or ".." in name.parts or not name.parts
                        or name.parts[0] != "package" or not (member.isfile() or member.isdir())):
                    raise RuntimeError("安全に展開できないアーカイブメンバーです。")
                relative = Path(*name.parts[1:])
                target = unpack / relative
                if member.isdir():
                    target.mkdir(parents=True, mode=0o700, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                extracted = package.extractfile(member)
                if extracted is None:
                    raise RuntimeError("アーカイブメンバーを読み出せません。")
                with extracted, target.open("xb") as output:
                    shutil.copyfileobj(extracted, output)
                target.chmod(0o700 if member.mode & 0o111 else 0o600)
        staged_executable = unpack / RELATIVE_EXECUTABLE
        if not staged_executable.is_file():
            raise RuntimeError("公式 CLI バイナリが想定位置にありません。")
        result = subprocess.run([str(staged_executable), "--version"], text=True,
                                capture_output=True, timeout=15, check=True,
                                env={"PATH": "/usr/bin:/bin", "HOME": str(staging)}, shell=False)
        if result.stdout.strip() != f"codex-cli {VERSION}":
            raise RuntimeError("公式 CLI の実行版が一致しません。")
        with staged_executable.open("rb") as source:
            binary_sha256 = hashlib.file_digest(source, "sha256").hexdigest()
        if binary_sha256 != BINARY_SHA256:
            raise RuntimeError("公式 CLI バイナリの SHA-256 が監査済み値と一致しません。")
        manifest = {"package": "@openai/codex", "package_version": PLATFORM_VERSION,
                    "version": VERSION, "metadata_url": METADATA_URL, "tarball_url": TARBALL_URL,
                    "integrity": INTEGRITY, "archive_bytes": count,
                    "binary_sha256": binary_sha256,
                    "registry_signatures_present": bool(metadata["dist"].get("signatures")),
                    "signature_verification": "not independently verified; pinned SHA-512 verified"}
        (unpack / "install-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (unpack / "install-manifest.json").chmod(0o600)
        os.rename(unpack, destination)
    return {"executable": str(executable), "version": VERSION, "reused": False,
            "binary_sha256": binary_sha256}


if __name__ == "__main__":
    print(json.dumps(install(), indent=2, ensure_ascii=False))
