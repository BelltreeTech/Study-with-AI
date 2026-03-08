"""
学習分析ダッシュボードのUI描画。

EXP・称号システム、ストリーク、Plotlyレーダーチャートを表示する。
"""

import streamlit as st
import plotly.express as px
import pandas as pd
from src.progress import get_dashboard_data, check_and_update_streak, get_due_reviews


def get_title(level: int) -> str:
    """レベルに応じた称号を返す。"""
    if level <= 5:
        return "駆け出しの村人"
    if level <= 10:
        return "見習い探求者"
    if level <= 20:
        return "知恵を求める旅人"
    if level <= 30:
        return "熟練の探索者"
    if level <= 40:
        return "導かれし賢者"
    if level <= 50:
        return "真理の解明者"
    if level <= 70:
        return "大賢者"
    if level <= 99:
        return "星の理を知る者"
    return "万物の絶対者 (Polymath)"


def render_dashboard() -> None:
    """学習分析ダッシュボードを描画する。"""
    st.title("📊 学習分析ダッシュボード")

    data = get_dashboard_data()
    profile = data["profile"]
    courses = data["courses"]

    total_exp = profile.get("total_exp", 0)
    level = (total_exp // 100) + 1
    title = get_title(level)
    next_exp = (level * 100) - total_exp

    # --- トップセクション: プロフィール ---
    st.markdown(f"### 🛡️ 現在のランク: **Lv.{level} {title}**")
    st.progress((total_exp % 100) / 100.0)
    st.caption(f"次のレベルまであと **{next_exp} EXP** (累計: {total_exp} EXP)")

    st.divider()

    # --- クエストセクション: 本日の復習 ---
    st.markdown("### ⚔️ 本日の復習クエスト")
    due_reviews = get_due_reviews()

    if not due_reviews:
        st.success("🎉 現在、復習期日を迎えている弱点はありません。新しい学習を進めましょう！")
    else:
        st.warning(f"⚠️ 今日は **{len(due_reviews)} 個** の復習クエストが発生しています！忘却曲線に打ち勝ちましょう。")
        for review in due_reviews:
            st.markdown(f"- 📘 **{review['course']}**: `{review['keyword']}` (現在 Lv.{review['level']})")
        st.info("💡 サイドバーから「模擬試験 (Feynman Drill)」に移動し、「🔥弱点克服特化モード」でクエストに挑戦してください。")

    st.divider()

    # --- ミドルセクション: ストリークとスタッツ ---
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("🔥 連続学習", f"{profile.get('current_streak', 0)} 日")
    with col2:
        st.metric("✨ 今日EXP", f"{profile.get('daily_exp', 0)}")
    with col3:
        st.metric("🍅 集中回数", f"{profile.get('total_pomodoros', 0)} 回")
    with col4:
        st.metric("⏱️ 累計集中", f"{profile.get('focused_minutes', 0)} 分")

    # 目標設定UI
    st.markdown("#### ⚙️ 今日の目標設定")
    target_exp = st.slider(
        "ストリーク継続に必要なEXP",
        min_value=10,
        max_value=200,
        value=50,
        step=10,
    )
    if check_and_update_streak(target_exp):
        st.balloons()
        st.success("🎉 今日の目標達成！ストリークが更新されました！")
    elif profile.get("daily_exp", 0) >= target_exp:
        st.success("🔥 今日の目標は既に達成済みです！")
    else:
        st.info(f"目標達成まであと **{target_exp - profile.get('daily_exp', 0)} EXP** です。")

    st.divider()

    # --- ボトムセクション: レーダーチャート ---
    st.markdown("#### 🕸️ 科目別スキルバランス")
    radar_data = []
    for c_name, c_data in courses.items():
        exp = c_data.get("exp", 0)
        if exp > 0:
            radar_data.append({"科目": c_name, "EXP": exp})

    if radar_data:
        df = pd.DataFrame(radar_data)
        fig = px.line_polar(df, r="EXP", theta="科目", line_close=True, markers=True)
        fig.update_traces(fill="toself")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("科目を学習してEXPを獲得すると、ここにレーダーチャートが表示されます。")
