"""
学習分析ダッシュボードのUI描画。

EXP・称号システム、ストリーク、Plotlyレーダーチャートを表示する。
"""

from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st

from src.progress import check_and_update_streak, get_dashboard_data, get_due_reviews
from src.runtime import Runtime
from src.views.navigation import queue_navigation


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


def render_analytics() -> None:
    """学習分析ダッシュボードを描画する。"""
    st.subheader("学習の記録")

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



def render_dashboard(runtime: Runtime | None = None) -> None:
    st.title("今日の学び")
    st.caption("目標を決める。理解する。自分の言葉で使ってみる。")
    data = get_dashboard_data()
    courses = {key: value for key, value in data['courses'].items() if value.get('curriculum') and value.get('subject')}
    subject = st.session_state.get('selected_subject', '')
    selected = {key: course for key, course in courses.items() if not subject or course['subject'] == subject}
    with st.container(border=True):
        st.subheader("次の一歩から、始めましょう")
        if selected:
            course_id, course = next(reversed(selected.items()))
            chapters = course['curriculum']
            index = min(course.get('current_chapter_index', 0), len(chapters) - 1)
            completed = sum(ch.get('status') == 'completed' for ch in chapters)
            st.markdown('**' + course.get('title', course_id) + '**')
            st.write(f"第{index + 1}章 · {chapters[index]['title']}")
            st.progress(completed / len(chapters), text=f'{completed} / {len(chapters)}章を修了')
            st.button('学習を再開', type='primary', on_click=queue_navigation,
                      args=('Curriculum', course['subject'], course_id), key='home_resume')
        else:
            st.write('読みたいPDFを、無理なく進められる自分専用のコースに。例題の量も、説明のたとえも、学びたい目的に合わせます。')
            left, right = st.columns(2)
            left.button('PDFを追加する', type='primary', icon=':material/upload_file:',
                        on_click=queue_navigation, args=('Library',), key='home_upload')
            right.button('PDFからコースを作る', disabled=not subject, on_click=queue_navigation,
                         args=('Curriculum', subject), key='home_create')
            if not subject:
                st.caption('すでに教材がある場合は、サイドバーで科目を選ぶとコースを作れます。')
    cols = st.columns(3)
    for col, step, title, text in zip(cols, ['01', '02', '03'],
        ['教材を入れる', '学び方を決める', '理解を確かめる'],
        ['PDFのページを根拠に学びます。資料は科目ごとに整理。',
         '目標・前提知識・例題・たとえ・学習時間を設定。',
         '授業、内容相談、テストを行き来し、弱点を復習。'], strict=True):
        with col.container(border=True):
            st.caption(step)
            st.markdown('**' + title + '**')
            st.write(text)
    due = get_due_reviews()
    if due:
        st.subheader('今日、思い出しておきたいこと')
        for number, review in enumerate(due[:5]):
            owner = data['courses'].get(review['course'], {})
            review_subject = owner.get('subject', review['course'])
            with st.container(border=True):
                st.write(review['keyword'])
                st.caption(owner.get('title', review_subject))
                st.button('このテーマを復習', key=f'review_home_{number}', on_click=queue_navigation,
                          args=('Feynman Drill', review_subject, '', review['keyword']))
    if selected:
        st.subheader('あなたのコース')
        for course_id, course in selected.items():
            if not course.get('curriculum'):
                continue
            with st.container(border=True):
                st.markdown('**' + course.get('title', course_id) + '**')
                brief = course.get('learning_options', {})
                st.caption(f"{course['subject']} · {brief.get('learning_approach', '体系的に理解')} · 1回{brief.get('session_minutes', 25)}分")
                st.button('コースを開く', key='open_' + course_id, on_click=queue_navigation,
                          args=('Curriculum', course['subject'], course_id))
    with st.expander('学習の記録・復習・達成度', expanded=False):
        render_analytics()
