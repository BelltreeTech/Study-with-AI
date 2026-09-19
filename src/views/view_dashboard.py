"""
学習分析ダッシュボードのUI描画。

EXP・称号システム、ストリーク、Plotlyレーダーチャートを表示する。
"""

from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st

from src.progress import check_and_update_streak, get_dashboard_data, get_due_reviews


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
            st.markdown(
                f"- 📘 **{courses.get(review['course'], {}).get('title', review['course'])}**: `{review['keyword']}` (現在 Lv.{review['level']})"
            )
        st.info(
            "💡 サイドバーから「模擬試験 (Feynman Drill)」に移動し、「🔥弱点克服特化モード」でクエストに挑戦してください。"
        )

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

    # --- ヒートマップセクション: GitHub風「草」 ---
    st.markdown("#### 🌿 学習ヒートマップ (過去半年)")
    exp_history = profile.get("exp_history", {})

    import datetime

    # 過去26週分（182日）の日付データを生成
    days_to_show = 182
    today_date = datetime.datetime.now(ZoneInfo("Asia/Tokyo")).date()
    start_date = today_date - datetime.timedelta(days=days_to_show - 1)

    heatmap_data = []
    today_str = datetime.datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    daily_exp_fallback = profile.get("daily_exp", 0)

    for i in range(days_to_show):
        target_date = start_date + datetime.timedelta(days=i)
        target_str = target_date.isoformat()

        # 今日かつ履歴が0なら、daily_expをフォールバックとして使う
        exp_val = exp_history.get(target_str, 0)
        if target_str == today_str and exp_val == 0:
            exp_val = daily_exp_fallback

        heatmap_data.append(
            {
                "date": target_date,
                "exp": exp_val,
                "week": i // 7,
                "day_of_week": target_date.weekday(),  # 0: Mon, 6: Sun
            }
        )

    df_heat = pd.DataFrame(heatmap_data)
    # y軸を曜日、x軸を週にするピボット
    pivot_heat = df_heat.pivot(index="day_of_week", columns="week", values="exp").fillna(0)

    # GitHub風のカラースケール（0の場合は薄いグレー、高いほど濃い緑）
    github_colors = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]

    fig_heat = px.imshow(
        pivot_heat,
        labels=dict(x="Weeks", y="Day of Week", color="EXP"),
        x=pivot_heat.columns,
        y=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        color_continuous_scale=github_colors,
        range_color=[0, max(50, df_heat["exp"].max() if not df_heat.empty else 100)],
        aspect="auto",
    )

    fig_heat.update_layout(
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False),
        plot_bgcolor="white",
        margin=dict(t=10, b=10, l=40, r=10),
        coloraxis_showscale=False,
        hovermode="closest",
    )
    st.plotly_chart(fig_heat, width="stretch")
    st.divider()

    # --- ボトムセクション: レーダーチャート ---
    st.markdown("#### 🕸️ 科目別スキルバランス")
    radar_data = []
    for c_name, c_data in courses.items():
        exp = c_data.get("exp", 0)
        if exp > 0:
            radar_data.append({"科目": c_data.get("title", c_name), "EXP": exp})

    if radar_data:
        df = pd.DataFrame(radar_data)
        fig = px.line_polar(df, r="EXP", theta="科目", line_close=True, markers=True)
        fig.update_traces(fill="toself")
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("科目を学習してEXPを獲得すると、ここにレーダーチャートが表示されます。")
