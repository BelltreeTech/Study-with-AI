import sys
import os

# プロジェクトルートにパスを通す
sys.path.append(os.path.abspath("."))

from src.config import PASS_SCORES
from src.views.view_curriculum import EXAM_DIFFICULTIES

def verify_exam_logic():
    print("=== view_exam.py Logic Verification ===")
    test_cases_exam = [
        {"diff": "Easy", "score": 75, "expected_pass": True},
        {"diff": "Normal", "score": 75, "expected_pass": False},
        {"diff": "Hard", "score": 95, "expected_pass": True},
    ]

    for tc in test_cases_exam:
        diff = tc["diff"]
        score = tc["score"]
        pass_line = PASS_SCORES.get(diff, PASS_SCORES["Normal"])
        passed = score >= pass_line
        result = "PASS" if passed == tc["expected_pass"] else "FAIL"
        print(f"[{result}] Difficulty: {diff:6s} | Score: {score} | Pass Line: {pass_line} | Passed: {passed} (Expected: {tc['expected_pass']})")

def verify_curriculum_logic():
    print("\n=== view_curriculum.py Logic Verification ===")
    test_cases_curr = [
        {"diff_label": "🟢 学部級（基礎確認）", "score": 75, "expected_pass": True},
        {"diff_label": "🟡 修士級（応用・分析）", "score": 75, "expected_pass": False},
        {"diff_label": "🔴 博士級（批判的考察）", "score": 95, "expected_pass": True},
    ]

    for tc in test_cases_curr:
        diff_label = tc["diff_label"]
        score = tc["score"]
        pass_line = EXAM_DIFFICULTIES[diff_label]["line"]
        passed = score >= pass_line
        result = "PASS" if passed == tc["expected_pass"] else "FAIL"
        print(f"[{result}] Level: {diff_label} | Score: {score} | Pass Line: {pass_line} | Passed: {passed} (Expected: {tc['expected_pass']})")

if __name__ == "__main__":
    verify_exam_logic()
    verify_curriculum_logic()
