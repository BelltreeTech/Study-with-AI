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
from src.config import USER_DATA_DIR

k_progressDir: Path = USER_DATA_DIR
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
            data = _migrate_legacy(data)
            
        # 汚染データ「集中学習」の自動クリーンアップ
        if "courses" in data and "集中学習" in data["courses"]:
            del data["courses"]["集中学習"]
            _save_all_data(data)
            
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


def update_weaknesses(course_name: str, new_weaknesses: list[str]) -> None:
    """弱点キーワードを更新（新規登録、またはLv.1へのリセット）する。"""
    if not new_weaknesses:
        return
    data: dict = _load_all_data()
    if course_name not in data["courses"]:
        data["courses"][course_name] = {"curriculum": [], "current_chapter_index": 0}

    course_data = data["courses"][course_name]
    if "weaknesses" not in course_data:
        course_data["weaknesses"] = {}

    today = datetime.date.today()
    tomorrow = (today + datetime.timedelta(days=1)).isoformat()

    for w in new_weaknesses:
        w_clean = w.strip()
        if not w_clean or w_clean.lower() == "なし":
            continue
        if w_clean in course_data["weaknesses"]:
            # 既に存在し、再び間違えた場合はペナルティとしてLv.1にリセットし、エラーカウントを加算
            course_data["weaknesses"][w_clean]["error_count"] = course_data["weaknesses"][w_clean].get("error_count", 1) + 1
            course_data["weaknesses"][w_clean]["srs_level"] = 1
            course_data["weaknesses"][w_clean]["next_review"] = tomorrow
        else:
            # 新規登録
            course_data["weaknesses"][w_clean] = {
                "error_count": 1,
                "srs_level": 1,
                "next_review": tomorrow,
            }
    _save_all_data(data)


def get_weaknesses(course_name: str) -> dict:
    """指定したコースの弱点データを取得する。"""
    data: dict = _load_all_data()
    course_data = data["courses"].get(course_name, {})
    return course_data.get("weaknesses", {})


def process_weakness_clear(course_name: str, weakness_keyword: str) -> str:
    """弱点をクリアした際のレベルアップ処理を行う。戻り値は 'mastered' か 'leveled_up'。"""
    data: dict = _load_all_data()
    status = "not_found"
    if course_name in data["courses"]:
        weaknesses = data["courses"][course_name].get("weaknesses", {})
        if weakness_keyword in weaknesses:
            w_data = weaknesses[weakness_keyword]
            current_level = w_data.get("srs_level", 1)

            if current_level >= 3:
                # Lv.3をクリアしたら完全マスター（削除）
                del weaknesses[weakness_keyword]
                status = "mastered"
            else:
                # レベルアップと次の復習日の設定 (Lv.1 -> 3日後, Lv.2 -> 7日後)
                new_level = current_level + 1
                days_to_add = 3 if new_level == 2 else 7
                w_data["srs_level"] = new_level
                w_data["next_review"] = (datetime.date.today() + datetime.timedelta(days=days_to_add)).isoformat()
                status = "leveled_up"

            _save_all_data(data)


import datetime


def add_exp(course_name: str, exp_amount: int) -> None:
    """EXPを加算し、日次リセット判定と履歴（ヒートマップ用）の記録を行う"""
    data = _load_all_data()
    today = datetime.date.today().isoformat()

    if "user_profile" not in data:
        data["user_profile"] = {
            "total_exp": 0, "daily_exp": 0, "last_active_date": today,
            "current_streak": 0, "last_streak_date": "", "exp_history": {}
        }

    profile = data["user_profile"]

    # 履歴データの初期化（古いバージョンからの互換性確保）
    if "exp_history" not in profile:
        profile["exp_history"] = {}

    # 日付が変わっていたらデイリーEXPをリセット
    if profile.get("last_active_date") != today:
        profile["daily_exp"] = 0
        profile["last_active_date"] = today

    profile["total_exp"] = profile.get("total_exp", 0) + exp_amount
    profile["daily_exp"] = profile.get("daily_exp", 0) + exp_amount

    # --- ヒートマップ用履歴の記録 ---
    profile["exp_history"][today] = profile["exp_history"].get(today, 0) + exp_amount

    # コースごとのEXP（course_name が None/空欄 でない場合のみ科目として加算）
    if course_name:
        if "courses" not in data:
            data["courses"] = {}
        if course_name not in data["courses"]:
            data["courses"][course_name] = {"curriculum": [], "current_chapter_index": 0}
        data["courses"][course_name]["exp"] = data["courses"][course_name].get("exp", 0) + exp_amount

    _save_all_data(data)


def check_and_update_streak(target_daily_exp: int) -> bool:
    """目標EXPに達していればストリークを更新。更新した場合はTrueを返す。"""
    data = _load_all_data()
    profile = data.get("user_profile", {})
    if not profile:
        return False

    today = datetime.date.today().isoformat()
    last_streak = profile.get("last_streak_date", "")

    if last_streak == today:
        return False  # 今日はすでに達成済み

    if profile.get("daily_exp", 0) >= target_daily_exp:
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        if last_streak == yesterday:
            profile["current_streak"] = profile.get("current_streak", 0) + 1
        else:
            profile["current_streak"] = 1
        profile["last_streak_date"] = today
        _save_all_data(data)
        return True
    return False


def get_dashboard_data() -> dict:
    """ダッシュボード表示用のデータを一括取得する。"""
    data = _load_all_data()
    return {
        "profile": data.get("user_profile", {"total_exp": 0, "daily_exp": 0, "current_streak": 0}),
        "courses": data.get("courses", {}),
    }


def add_pomodoro_session(minutes: int) -> None:
    """ポモドーロのセッション回数と累計集中時間を更新する。"""
    data = _load_all_data()
    if "user_profile" not in data:
        data["user_profile"] = {}

    profile = data["user_profile"]
    profile["total_pomodoros"] = profile.get("total_pomodoros", 0) + 1
    profile["focused_minutes"] = profile.get("focused_minutes", 0) + minutes

    _save_all_data(data)


def get_due_reviews() -> list[dict]:
    """今日復習すべき全科目の弱点リストを取得する。"""
    import datetime
    data: dict = _load_all_data()
    due_reviews: list[dict] = []
    today = datetime.date.today().isoformat()

    for course_name, course_data in data.get("courses", {}).items():
        for keyword, w_data in course_data.get("weaknesses", {}).items():
            # 古いデータで next_review が無い場合は今日復習対象とする
            next_review = w_data.get("next_review", today) if isinstance(w_data, dict) else today
            if next_review <= today:
                level = w_data.get("srs_level", 1) if isinstance(w_data, dict) else 1
                due_reviews.append({
                    "course": course_name,
                    "keyword": keyword,
                    "level": level,
                })
    return due_reviews
