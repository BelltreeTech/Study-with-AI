"""Installer security tests use only synthetic archives and temporary homes."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from scripts import setup_codex


@pytest.fixture
def installation_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(setup_codex.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(setup_codex.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(setup_codex.platform, "machine", lambda: "arm64")
    return tmp_path / ".local/share/study-with-ai/tools/codex" / setup_codex.VERSION


def fake_registry(monkeypatch: pytest.MonkeyPatch, entries: list[tuple[str, bytes, str]],
                  *, corrupt_integrity: bool = False) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content, kind in entries:
            item = tarfile.TarInfo(name)
            item.mode = 0o755
            if kind == "symlink":
                item.type = tarfile.SYMTYPE
                item.linkname = "/tmp/outside"
                archive.addfile(item)
            else:
                item.size = len(content)
                archive.addfile(item, io.BytesIO(content))
    raw = buffer.getvalue()
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()
    if corrupt_integrity:
        integrity = "sha512-incorrect"
    monkeypatch.setattr(setup_codex, "INTEGRITY", integrity)
    metadata = {
        "name": "@openai/codex", "version": setup_codex.PLATFORM_VERSION,
        "repository": {"url": "git+https://github.com/openai/codex.git"},
        "dist": {"tarball": setup_codex.TARBALL_URL, "integrity": integrity},
    }

    def fetch(url: str, **kwargs: object) -> io.BytesIO:
        assert url in {setup_codex.METADATA_URL, setup_codex.TARBALL_URL}
        return io.BytesIO(json.dumps(metadata).encode() if url == setup_codex.METADATA_URL else raw)

    monkeypatch.setattr(setup_codex.urllib.request, "urlopen", fetch)


def test_install_preserves_unowned_existing_directory(installation_home: Path) -> None:
    installation_home.mkdir(parents=True)
    sentinel = installation_home / "user-owned"
    sentinel.write_text("preserve")
    with pytest.raises(RuntimeError, match="上書きしません"):
        setup_codex.install()
    assert sentinel.read_text() == "preserve"


@pytest.mark.parametrize("kind", ["traversal", "symlink"])
def test_install_rejects_unsafe_archive(installation_home: Path, monkeypatch: pytest.MonkeyPatch,
                                      kind: str) -> None:
    name = "package/../escape" if kind == "traversal" else "package/link"
    fake_registry(monkeypatch, [(name, b"synthetic", kind)])
    with pytest.raises(RuntimeError, match="安全に展開できない"):
        setup_codex.install()
    assert not installation_home.exists()
    assert not (installation_home.parent / "escape").exists()


def test_install_rejects_checksum_mismatch(installation_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_registry(monkeypatch, [("package/fixture", b"synthetic", "file")], corrupt_integrity=True)
    with pytest.raises(RuntimeError, match="SHA-512"):
        setup_codex.install()
    assert not installation_home.exists()


def test_atomic_install_and_idempotent_reuse(installation_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = b"synthetic executable bytes"
    digest = hashlib.sha256(binary).hexdigest()
    fake_registry(monkeypatch, [("package/" + setup_codex.RELATIVE_EXECUTABLE.as_posix(), binary, "file")])
    monkeypatch.setattr(setup_codex, "BINARY_SHA256", digest)
    monkeypatch.setattr(setup_codex.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args[0], 0, stdout=f"codex-cli {setup_codex.VERSION}\n", stderr="",
    ))
    result = setup_codex.install()
    assert result["reused"] is False
    assert result["binary_sha256"] == digest
    assert Path(str(result["executable"])).read_bytes() == binary
    assert (installation_home / "install-manifest.json").stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(setup_codex.urllib.request, "urlopen", lambda *args, **kwargs: pytest.fail("unexpected network"))
    assert setup_codex.install()["reused"] is True
    Path(str(result["executable"])).write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="整合性検査"):
        setup_codex.install()
    assert Path(str(result["executable"])).read_bytes() == b"tampered"
