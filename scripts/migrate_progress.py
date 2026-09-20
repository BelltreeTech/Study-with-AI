"""Explicit one-time progress migration with a private rollback copy and no data output."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.repository import Repository, migrate_legacy_data  # noqa: E402


def migrate(state_dir: Path, backup_root: Path) -> dict:
    source = state_dir / "progress.json"
    if not source.is_file() or source.is_symlink():
        raise ValueError("通常ファイルのprogress.jsonがありません。移行を停止しました。")
    raw = source.read_bytes()
    original = json.loads(raw)
    expected = migrate_legacy_data(original)
    backup = backup_root / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    backup.mkdir(parents=True, mode=0o700)
    saved = backup / "progress.json"
    fd = os.open(saved, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    db_path = state_dir / "progress.sqlite3"
    existed = db_path.exists()
    repository = Repository(db_path, source)
    migrated = repository.read()
    if source.read_bytes() != raw:
        raise ValueError("移行中に元JSONが変更されました。保存済みバックアップを確認してください。")
    if not existed and migrated != expected:
        raise ValueError("移行結果と元データの整合が一致しません。バックアップを保持して停止しました。")
    repository.backup(backup / "progress.sqlite3")
    report = {
        "source_bytes_unchanged": True,
        "backup_verified": saved.read_bytes() == raw,
        "migration_values_match": migrated == expected if not existed else None,
        "already_initialized": existed,
        "backup": str(backup),
        "schema_version": 1,
    }
    # SHA is kept in private manifest only; no course titles, marks or source JSON are printed.
    manifest = {**report, "source_sha256": hashlib.sha256(raw).hexdigest(), "state_dir": str(state_dir)}
    manifest_path = backup / "migration.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    manifest_path.chmod(0o600)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    args = parser.parse_args()
    state = args.state_dir.expanduser().resolve()
    backup = args.backup_root.expanduser().resolve()
    if backup.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("バックアップ先にはGit repository外を指定してください。")
    print(json.dumps(migrate(state, backup), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
