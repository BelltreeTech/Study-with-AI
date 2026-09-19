"""Subject-confined PDF uploads; no overwrite and no symlink following."""

import os
import uuid
from pathlib import Path, PurePosixPath

import fitz

MAX_UPLOAD_BYTES = 30 * 1024 * 1024


def validate_subject(subject: str) -> list[str]:
    parts = PurePosixPath(subject).parts
    if (
        PurePosixPath(subject).is_absolute()
        or len(parts) != 2
        or PurePosixPath(subject).as_posix() != subject
        or "\\" in subject
        or any(p.startswith(".") or p in ("", ".", "..") for p in parts)
    ):
        raise ValueError("カテゴリ/科目の形式で指定してください。ドットで始まる名前やパス指定は使用できません。")
    return list(parts)


def save_pdf(data_root: Path, subject: str, filename: str, content: bytes) -> Path:
    parts = validate_subject(subject)
    if (
        not filename
        or Path(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or filename.startswith(".")
        or Path(filename).suffix.lower() != ".pdf"
    ):
        raise ValueError("PDFのファイル名が不正です。")
    if not content.startswith(b"%PDF-") or len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("PDF形式または30MBのサイズ上限を確認してください。")
    try:
        with fitz.open(stream=content, filetype="pdf") as doc:
            if not doc.page_count or doc.is_encrypted:
                raise ValueError("空または暗号化されたPDFは登録できません。")
    except (RuntimeError, fitz.FileDataError) as exc:
        raise ValueError("PDFを読み取れません。") from exc
    root = Path(data_root).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fds = []
    temp = "." + uuid.uuid4().hex + ".upload"
    parent = None
    try:
        parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fds.append(parent)
        for part in parts:
            try:
                os.mkdir(part, mode=0o700, dir_fd=parent)
            except FileExistsError:
                pass
            parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            fds.append(parent)
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # link creates the destination exclusively, so existing material is never replaced.
        os.link(temp, filename, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        return root.joinpath(*parts, filename)
    except FileExistsError as exc:
        raise ValueError("同名教材が存在します。別のファイル名で登録してください。") from exc
    except OSError as exc:
        raise ValueError("安全な教材保存先を開けません。symlinkや権限を確認してください。") from exc
    finally:
        if parent is not None:
            try:
                os.unlink(temp, dir_fd=parent)
            except FileNotFoundError:
                pass
        for fd in reversed(fds):
            os.close(fd)


def list_materials(data_root: Path, subject: str) -> list[dict]:
    parts = validate_subject(subject)
    root = Path(data_root).resolve()
    path = root
    for part in parts:
        path /= part
        if path.is_symlink():
            raise ValueError("教材のsymlinkは使用できません。")
    result = []
    for directory, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in sorted(files):
            file = Path(directory) / name
            if file.suffix.lower() == ".pdf" and not file.is_symlink():
                result.append(
                    {"path": file.relative_to(root).as_posix(), "bytes": file.stat(follow_symlinks=False).st_size}
                )
    return result
