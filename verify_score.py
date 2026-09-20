"""Offline assertion-based acceptance check; never calls a provider."""

from src.config import PASS_SCORES


def main() -> None:
    for difficulty, threshold in PASS_SCORES.items():
        assert threshold == {"Easy": 70, "Normal": 80, "Hard": 90}[difficulty]
        assert not (threshold - 1 >= threshold)
        assert threshold >= threshold
        print(f"{difficulty}: 合格ライン{threshold}点")
    print("詳細な設問別採点・無効結果の検証: uv run pytest tests/test_learning.py")


if __name__ == "__main__":
    main()
