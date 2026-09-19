"""Backward-compatible progress API backed by transactional, versioned SQLite.

Legacy progress.json is imported once and never modified. All dates use Asia/Tokyo.
Callers should supply a stable event_id for XP, completions and pomodoro rewards.
"""

from __future__ import annotations

import datetime
import hashlib
from pathlib import Path

from src.config import USER_DATA_DIR
from src.repository import TOKYO, Repository, canonical_json, migrate_legacy_data

k_progressDir: Path = USER_DATA_DIR
k_progressFile = k_progressDir / "progress.json"


def get_repository() -> Repository:
    return Repository(k_progressDir / "progress.sqlite3", k_progressFile)


def _today() -> datetime.date:
    return datetime.datetime.now(TOKYO).date()


def _load_all_data() -> dict:
    return get_repository().read()


def _migrate_legacy(old_data: dict) -> dict:
    return migrate_legacy_data(old_data)


def _save_all_data(data: dict) -> None:
    """Compatibility snapshot writer. Prefer transactional public update functions."""
    validated = migrate_legacy_data(data)

    def replace(current: dict) -> None:
        current.clear()
        current.update(validated)

    get_repository().update(replace)


def _course(data: dict, name: str) -> dict:
    return data.setdefault("courses", {}).setdefault(name, {"curriculum": [], "current_chapter_index": 0})


def _fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def save_course_progress(
    course_name: str, curriculum: list[dict], current_chapter_index: int, *, metadata: dict | None = None
) -> None:
    def update(data: dict) -> None:
        course = _course(data, course_name)
        if metadata:
            course.update(metadata)
        course.update(curriculum=curriculum, current_chapter_index=current_chapter_index)
        data["last_active_course"] = course_name

    get_repository().update(update)


def load_course_progress(course_name: str) -> dict | None:
    return _load_all_data()["courses"].get(course_name)


def get_all_courses() -> list[str]:
    return list(_load_all_data()["courses"])


def get_last_active_course() -> str:
    return _load_all_data().get("last_active_course", "")


def get_course_summary(course_name: str) -> dict:
    course = load_course_progress(course_name) or {}
    curriculum = course.get("curriculum", [])
    total = len(curriculum)
    completed = sum(ch.get("status") == "completed" for ch in curriculum)
    return {
        "total": total,
        "completed": completed,
        "progress": completed / total if total else 0.0,
        "current_chapter_index": course.get("current_chapter_index", 0),
    }


def delete_course(course_name: str) -> None:
    def remove(data: dict) -> None:
        data["courses"].pop(course_name, None)
        if data.get("last_active_course") == course_name:
            data["last_active_course"] = ""

    get_repository().update(remove)


def set_last_active_course(course_name: str) -> None:
    get_repository().update(lambda data: data.update(last_active_course=course_name))


def _update_weaknesses(data: dict, course_name: str, values: list[str]) -> None:
    weaknesses = _course(data, course_name).setdefault("weaknesses", {})
    tomorrow = (_today() + datetime.timedelta(days=1)).isoformat()
    for keyword in dict.fromkeys(value.strip() for value in values):
        if not keyword or keyword == "なし":
            continue
        previous = weaknesses.get(keyword, {})
        if not isinstance(previous, dict):
            previous = {"legacy_value": previous}
        previous.update(error_count=previous.get("error_count", 0) + 1, srs_level=1, next_review=tomorrow)
        weaknesses[keyword] = previous


def update_weaknesses(course_name: str, new_weaknesses: list[str], *, event_id: str | None = None) -> None:
    if new_weaknesses:
        get_repository().update(
            lambda data: _update_weaknesses(data, course_name, new_weaknesses),
            event_id=event_id,
            fingerprint=_fingerprint(["weaknesses", course_name, new_weaknesses]),
        )


def get_weaknesses(course_name: str) -> dict:
    return (_load_all_data()["courses"].get(course_name) or {}).get("weaknesses", {})


def process_weakness_clear(course_name: str, weakness_keyword: str, *, event_id: str | None = None) -> str:
    def clear(data: dict) -> str:
        weaknesses = data["courses"].get(course_name, {}).get("weaknesses", {})
        if weakness_keyword not in weaknesses:
            return "not_found"
        entry = weaknesses[weakness_keyword]
        if not isinstance(entry, dict):
            entry = {"legacy_value": entry, "srs_level": 1}
            weaknesses[weakness_keyword] = entry
        if entry.get("srs_level", 1) >= 3:
            del weaknesses[weakness_keyword]
            return "mastered"
        entry["srs_level"] = entry.get("srs_level", 1) + 1
        days = 3 if entry["srs_level"] == 2 else 7
        entry["next_review"] = (_today() + datetime.timedelta(days=days)).isoformat()
        return "leveled_up"

    return get_repository().update(
        clear, event_id=event_id, fingerprint=_fingerprint(["clear", course_name, weakness_keyword])
    )[1]


def _add_exp(data: dict, course_name: str | None, exp_amount: int) -> None:
    if isinstance(exp_amount, bool) or not isinstance(exp_amount, int) or exp_amount < 0:
        raise ValueError("EXPは0以上の整数で指定してください。")
    today = _today().isoformat()
    profile = data.setdefault("user_profile", {})
    if profile.get("last_active_date") != today:
        profile.update(daily_exp=0, last_active_date=today)
    profile["total_exp"] = profile.get("total_exp", 0) + exp_amount
    profile["daily_exp"] = profile.get("daily_exp", 0) + exp_amount
    history = profile.setdefault("exp_history", {})
    history[today] = history.get(today, 0) + exp_amount
    if course_name:
        course = _course(data, course_name)
        course["exp"] = course.get("exp", 0) + exp_amount


def add_exp(course_name: str | None, exp_amount: int, *, event_id: str | None = None) -> None:
    get_repository().update(
        lambda data: _add_exp(data, course_name, exp_amount),
        event_id=event_id,
        fingerprint=_fingerprint(["xp", course_name, exp_amount]),
    )


def check_and_update_streak(target_daily_exp: int) -> bool:
    if target_daily_exp <= 0:
        raise ValueError("日次目標は正の整数で指定してください。")

    def update(data: dict) -> bool:
        profile = data.get("user_profile", {})
        today = _today().isoformat()
        if profile.get("last_active_date") != today or profile.get("last_streak_date") == today:
            return False
        if profile.get("daily_exp", 0) < target_daily_exp:
            return False
        yesterday = (_today() - datetime.timedelta(days=1)).isoformat()
        profile["current_streak"] = (
            profile.get("current_streak", 0) + 1 if profile.get("last_streak_date") == yesterday else 1
        )
        profile["last_streak_date"] = today
        return True

    return get_repository().update(update)[1]


def get_dashboard_data() -> dict:
    data = _load_all_data()
    profile = data.get("user_profile", {"total_exp": 0, "daily_exp": 0, "current_streak": 0})
    if profile.get("last_active_date") != _today().isoformat():
        profile["daily_exp"] = 0
    return {"profile": profile, "courses": data.get("courses", {})}


def _add_pomodoro(data: dict, minutes: int) -> None:
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        raise ValueError("集中時間は正の整数で指定してください。")
    profile = data.setdefault("user_profile", {})
    profile["total_pomodoros"] = profile.get("total_pomodoros", 0) + 1
    profile["focused_minutes"] = profile.get("focused_minutes", 0) + minutes
    profile["last_pomodoro_at"] = datetime.datetime.now(TOKYO).isoformat()


def add_pomodoro_session(minutes: int, *, event_id: str | None = None) -> None:
    get_repository().update(
        lambda data: _add_pomodoro(data, minutes), event_id=event_id, fingerprint=_fingerprint(["pomodoro", minutes])
    )


def commit_learning_event(
    course_name: str | None,
    event_id: str,
    *,
    exp_amount: int = 0,
    weaknesses: list[str] | None = None,
    curriculum: list[dict] | None = None,
    current_chapter_index: int | None = None,
    grading_result: dict | None = None,
    pomodoro_minutes: int | None = None,
    metadata: dict | None = None,
) -> bool:
    """Commit an already validated successful result atomically, exactly once.

    The service must check that the owning job succeeded before calling this. A
    new intentional attempt needs a new event ID; a Streamlit rerun reuses it.
    """
    if not event_id:
        raise ValueError("完了イベントIDが必要です。")
    payload = [
        course_name,
        exp_amount,
        weaknesses,
        curriculum,
        current_chapter_index,
        grading_result,
        pomodoro_minutes,
        metadata,
    ]

    def commit(data: dict) -> None:
        if exp_amount:
            _add_exp(data, course_name, exp_amount)
        if pomodoro_minutes is not None:
            _add_pomodoro(data, pomodoro_minutes)
        if course_name:
            course = _course(data, course_name)
            if metadata:
                course.update(metadata)
            if curriculum is not None:
                course["curriculum"] = curriculum
            if current_chapter_index is not None:
                course["current_chapter_index"] = current_chapter_index
            if grading_result is not None:
                course.setdefault("grade_history", []).append(
                    {"event_id": event_id, "at": datetime.datetime.now(TOKYO).isoformat(), "result": grading_result}
                )
            if weaknesses:
                _update_weaknesses(data, course_name, weaknesses)

    return get_repository().update(commit, event_id=event_id, fingerprint=_fingerprint(payload))[0]


def get_due_reviews() -> list[dict]:
    today = _today().isoformat()
    reviews = []
    for course_name, course in _load_all_data().get("courses", {}).items():
        for keyword, entry in course.get("weaknesses", {}).items():
            value = entry if isinstance(entry, dict) else {}
            if value.get("next_review", today) <= today:
                reviews.append({"course": course_name, "keyword": keyword, "level": value.get("srs_level", 1)})
    return reviews


def complete_chapter(course_name: str, chapter_index: int, attempt_id: str, *, material_revision: str) -> bool:
    """Advance the exact graded lecture against its current material revision."""
    if type(chapter_index) is not int or chapter_index < 0 or not attempt_id or not material_revision:
        raise ValueError("章の修了対象・採点ID・教材revisionが不正です。")
    event_id = f"chapter-complete:{course_name}:{chapter_index}"

    def complete(data: dict) -> None:
        course = data["courses"].get(course_name)
        if not course or not 0 <= chapter_index < len(course.get("curriculum", [])):
            raise ValueError("修了対象の章がありません。")
        grades = [
            entry["result"]
            for entry in course.get("grade_history", [])
            if entry["result"].get("attempt_id") == attempt_id
        ]
        if not grades or grades[-1].get("passed") is not True:
            raise ValueError("検証済みの合格結果がありません。")
        grade = grades[-1]
        chapter = course["curriculum"][chapter_index]
        lecture = chapter.get("lecture_content") or {}
        if (
            grade.get("course_id") != course_name
            or grade.get("chapter_index") != chapter_index
            or not lecture.get("lecture_id")
            or grade.get("lecture_id") != lecture["lecture_id"]
        ):
            raise ValueError("合格した試験と修了対象の章・現在の講義が一致しません。")
        if grade.get("material_revision") != material_revision or lecture.get("material_revision") != material_revision:
            raise ValueError("教材が更新されています。現在の教材で講義と試験を再生成してください。")
        if chapter.get("status") == "completed":
            return
        if chapter.get("status") != "unlocked":
            raise ValueError("この章はまだ解放されていません。")
        chapter["status"] = "completed"
        next_index = min(chapter_index + 1, len(course["curriculum"]) - 1)
        if next_index > chapter_index and course["curriculum"][next_index].get("status") != "completed":
            course["curriculum"][next_index]["status"] = "unlocked"
        course["current_chapter_index"] = max(course.get("current_chapter_index", 0), next_index)
        _add_exp(data, course_name, 50)

    return get_repository().update(
        complete, event_id=event_id, fingerprint=_fingerprint(["chapter", course_name, chapter_index])
    )[0]
