"""
学習進捗の永続化モジュール（複数コース対応）。

カリキュラムの進捗データをローカルJSONファイルに保存・復元する。
データ構造:
{
  "courses": {
    "Deep Learning": {"curriculum": [...], "current_chapter_index": 0},
    "日本史": {"curriculum": [...], "current_chapter_index": 2}
  },
  "last_active_course": "Deep Learning"
}
"""

import json
from pathlib import Path

# 保存先ディレクトリとファイル
k_progressDir = Path("user_data")
k_progressFile = k_progressDir / "progress.json"


def _load_all_data() -> dict:
    """進捗ファイル全体を読み込む（内部用）。"""
    if not k_progressFile.exists():
        return {"courses": {}, "last_active_course": ""}
    try:
        raw: str = k_progressFile.read_text(encoding="utf-8")
        data: dict = json.loads(raw)
        # 旧フォーマットからのマイグレーション
        if "courses" not in data:
            return _migrate_legacy(data)
        return data
    except Exception as e:
        print(f"[Progress] 読み込みに失敗: {e}")
        return {"courses": {}, "last_active_course": ""}


def _migrate_legacy(old_data: dict) -> dict:
    """旧形式（単一コース）のデータを新形式にマイグレーションする。"""
    topic: str = old_data.get("topic", "Default Course")
    if not topic:
        topic = "Default Course"
    new_data: dict = {
        "courses": {
            topic: {
                "curriculum": old_data.get("curriculum", []),
                "current_chapter_index": old_data.get("current_chapter_index", 0),
            }
        },
        "last_active_course": topic,
    }
    _save_all_data(new_data)
    return new_data


def _save_all_data(data: dict) -> None:
    """進捗ファイル全体を書き込む（内部用）。"""
    k_progressDir.mkdir(parents=True, exist_ok=True)
    try:
        k_progressFile.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[Progress] 保存に失敗: {e}")


def save_course_progress(
    course_name: str,
    curriculum: list[dict],
    current_chapter_index: int,
) -> None:
    """
    指定したコースの進捗データを保存する。

    Args:
        course_name: コース名（トピック名）
        curriculum: カリキュラムデータ（章のリスト）
        current_chapter_index: 現在の章インデックス
    """
    data: dict = _load_all_data()
    data["courses"][course_name] = {
        "curriculum": curriculum,
        "current_chapter_index": current_chapter_index,
    }
    data["last_active_course"] = course_name
    _save_all_data(data)


def load_course_progress(course_name: str) -> dict | None:
    """
    指定したコースの進捗データを読み込む。

    Args:
        course_name: コース名

    Returns:
        {"curriculum": list, "current_chapter_index": int}
        コースが存在しない場合は None。
    """
    data: dict = _load_all_data()
    return data["courses"].get(course_name)


def get_all_courses() -> list[str]:
    """登録されている全コース名のリストを返す。"""
    data: dict = _load_all_data()
    return list(data["courses"].keys())


def get_last_active_course() -> str:
    """最後にアクティブだったコース名を返す。"""
    data: dict = _load_all_data()
    return data.get("last_active_course", "")


def get_course_summary(course_name: str) -> dict:
    """
    コースのサマリー情報（章数、完了数、進捗率）を返す。

    Returns:
        {"total": int, "completed": int, "progress": float, "current_chapter_index": int}
    """
    course_data: dict | None = load_course_progress(course_name)
    if not course_data:
        return {"total": 0, "completed": 0, "progress": 0.0, "current_chapter_index": 0}
    curriculum: list[dict] = course_data.get("curriculum", [])
    total: int = len(curriculum)
    completed: int = sum(1 for ch in curriculum if ch.get("status") == "completed")
    progress: float = completed / total if total > 0 else 0.0
    return {
        "total": total,
        "completed": completed,
        "progress": progress,
        "current_chapter_index": course_data.get("current_chapter_index", 0),
    }


def delete_course(course_name: str) -> None:
    """指定したコースを削除する。"""
    data: dict = _load_all_data()
    if course_name in data["courses"]:
        del data["courses"][course_name]
    if data["last_active_course"] == course_name:
        data["last_active_course"] = ""
    _save_all_data(data)


def set_last_active_course(course_name: str) -> None:
    """最後にアクティブだったコース名を更新する。"""
    data: dict = _load_all_data()
    data["last_active_course"] = course_name
    _save_all_data(data)
