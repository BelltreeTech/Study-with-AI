"""
RAG検索モードのUI描画。

チャットインターフェース、デバッグ情報、参照ソースの表示を担当する。
"""

import streamlit as st
from pathlib import Path
import uuid

from src.core.rag_core import RAGCore


def render_rag_mode(
    rag_core: RAGCore,
    debug_mode: bool,
    top_k: int,
    style: str,
    length: str,
) -> None:
    """知識検索（RAG）モードのUI。"""
    # ---- メイン画面：チャットUI ----
    st.title("📖 まりによるRAG System")
    st.caption("NumPyベースのベクトル検索（スクラッチ実装）によるPDF質問応答")

    # チャット履歴はstate_managerで初期化済み

    # 既存のチャット履歴を表示
    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            # デバッグ情報（履歴再表示時）
            if debug_mode and "debug_info" in message:
                _render_debug_info(message["debug_info"])
            st.markdown(message["content"])
            # 回答にソース情報がある場合表示
            if "sources" in message:
                _render_sources(message["sources"])

    # ユーザー入力
    if prompt := st.chat_input("PDFについて質問してください..."):
        # ユーザーメッセージを表示・保存
        st.session_state["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # RAG回答を生成
        with st.chat_message("assistant"):
            with st.spinner("🔍 検索・回答生成中..."):
                result: dict = rag_core.query(prompt, top_k=top_k, style=style, length=length)

            # デバッグモードON → 回答の上にテンソル演算ログを表示
            if debug_mode:
                _render_debug_info(result.get("debug_info", {}))

            # 回答をMarkdownで表示（LaTeX数式も自動レンダリング）
            # LLMが非対応デリミタを使った場合のサニタイズ
            answer_text: str = result["answer"]
            answer_text = answer_text.replace(r"\[", "$$").replace(r"\]", "$$")
            answer_text = answer_text.replace(r"\(", "$").replace(r"\)", "$")
            st.markdown(answer_text)

            # 参照ソースを折りたたみ表示
            _render_sources(result["sources"])

        # アシスタントメッセージを保存
        st.session_state["messages"].append({
            "role": "assistant",
            "content": result["answer"],
            "sources": result["sources"],
            "debug_info": result.get("debug_info", {}),
        })


def _render_debug_info(debug_info: dict) -> None:
    """テンソル演算・LLM通信ペイロード・トークン消費をタブで可視化する。"""
    if not debug_info:
        return

    # 呼び出しごとに一意なIDを生成（キー重複防止）
    unique_suffix: str = str(uuid.uuid4())[:8]

    with st.expander("🛠 Deep Fluoroscopy（深淵の監視モニター）", expanded=True):
        # クエリ拡張結果の表示
        expanded_query: str = debug_info.get("expanded_query", "")
        if expanded_query:
            st.info(f"🔄 **クエリ拡張:** {expanded_query}")

        tab1, tab2, tab3 = st.tabs([
            "🧠 テンソル演算ログ",
            "📡 送信プロンプト (Payload)",
            "📊 パフォーマンス & コスト",
        ])

        # ---- タブ1: テンソル演算ログ ----
        with tab1:
            # ---- 検索結果サマリ ----
            st.subheader("📊 検索結果サマリ")
            results_for_debug: list[dict] = debug_info.get("results_for_debug", [])
            if results_for_debug:
                sim_cols = st.columns(len(results_for_debug))
                for idx, r in enumerate(results_for_debug):
                    sim_score: float = r.get("similarity", 0.0)
                    if sim_score >= 0.5:
                        label = "🟢"
                    elif sim_score >= 0.3:
                        label = "🟡"
                    else:
                        label = "🔴"
                    sim_cols[idx].metric(
                        f"{label} Chunk {idx+1}",
                        f"{sim_score:.4f}",
                        help=f"Source: {r.get('source_file', '?')} / Page {r.get('page_number', '?')}",
                    )

            # ---- Semantic Shift ----
            shift: float | None = debug_info.get("semantic_shift")
            if shift is not None:
                st.subheader("📐 Semantic Shift（クエリ拡張の意味変化）")
                shift_col1, shift_col2 = st.columns(2)
                shift_col1.metric("cos(original, expanded)", f"{shift:.4f}")
                if shift >= 0.9:
                    shift_label = "🟢 微小な変化（同義拡張）"
                elif shift >= 0.7:
                    shift_label = "🟡 中程度の変化"
                else:
                    shift_label = "🔴 大幅な意味変化"
                shift_col2.markdown(f"**解釈:** {shift_label}")

            # ---- L2 Norm Breakdown ----
            query_l2: float = debug_info.get("query_l2_norm", 0.0)
            top1_l2: float = debug_info.get("top1_doc_l2_norm", 0.0)
            raw_dot: float = debug_info.get("raw_dot_product", 0.0)
            if query_l2:
                st.subheader("📐 L2 Norm Breakdown（コサイン類似度の因数分解）")
                l2_cols = st.columns(3)
                l2_cols[0].metric("‖Query‖ (L2)", f"{query_l2:.4f}")
                l2_cols[1].metric("‖Top-1 Doc‖ (L2)", f"{top1_l2:.4f}")
                l2_cols[2].metric("A · B (内積)", f"{raw_dot:.4f}")
                st.caption(
                    f"cos(θ) = (A · B) / (‖A‖ × ‖B‖) = "
                    f"{raw_dot:.4f} / ({query_l2:.4f} × {top1_l2:.4f}) = "
                    f"{raw_dot / (query_l2 * top1_l2 + 1e-10):.4f}"
                )

            # ---- Top-K Dimensions ----
            top_dims: list = debug_info.get("top_k_dimensions", [])
            if top_dims:
                import pandas as pd
                st.subheader("🔥 Top-5 発火次元（Query Vector）")
                dim_df = pd.DataFrame(top_dims)
                dim_df.columns = ["次元 Index", "値"]
                dim_df.index = [f"#{i+1}" for i in range(len(dim_df))]
                st.dataframe(dim_df, width="stretch")

            # ---- PCA 2D マッピング ----
            pca_data: dict | None = debug_info.get("pca_plot_data")
            if pca_data:
                import pandas as pd
                st.subheader("🗺️ ベクトル空間 2Dマッピング (PCA投影)")

                # チャンクのカテゴリ分け（通常=青, top_k=緑）
                top_k_pos: set = set(pca_data.get("top_k_positions", []))
                chunk_labels: list[str] = []
                for i in range(len(pca_data["chunks_x"])):
                    if i in top_k_pos:
                        chunk_labels.append("Top-K チャンク")
                    else:
                        chunk_labels.append("チャンク")

                # クエリ + チャンク群を結合
                plot_df = pd.DataFrame({
                    "PC1": [pca_data["query"]["x"]] + pca_data["chunks_x"],
                    "PC2": [pca_data["query"]["y"]] + pca_data["chunks_y"],
                    "カテゴリ": ["🔴 クエリ"] + chunk_labels,
                })

                st.scatter_chart(
                    plot_df,
                    x="PC1",
                    y="PC2",
                    color="カテゴリ",
                    height=400,
                )
                evr = pca_data.get("explained_variance_ratio", [])
                if evr:
                    st.caption(
                        f"PCA累積寄与率: PC1={evr[0]:.2%}, PC2={evr[1]:.2%}, "
                        f"合計={sum(evr):.2%}"
                    )

        # ---- タブ2: 送信プロンプト (Payload) ----
        with tab2:
            st.subheader("System Prompt")
            system_prompt: str = debug_info.get("system_prompt", "（取得できません）")
            st.text_area(
                "LLMに渡されたシステムプロンプト全文",
                value=system_prompt,
                height=200,
                disabled=True,
                label_visibility="collapsed",
                key=f"debug_system_prompt_{unique_suffix}",
            )

            st.subheader("Context (Retrieved Chunks)")
            raw_context: str = debug_info.get("raw_context", "（取得できません）")
            st.text_area(
                "検索結果から構築されたコンテキスト全文",
                value=raw_context,
                height=300,
                disabled=True,
                label_visibility="collapsed",
                key=f"debug_raw_context_{unique_suffix}",
            )

            st.subheader("User Prompt")
            user_prompt: str = debug_info.get("user_prompt", "（取得できません）")
            st.text_area(
                "LLMに渡されたユーザープロンプト全文",
                value=user_prompt,
                height=200,
                disabled=True,
                label_visibility="collapsed",
                key=f"debug_user_prompt_{unique_suffix}",
            )

        # ---- タブ3: パフォーマンス＆コスト ----
        with tab3:
            llm_model: str = debug_info.get("llm_model", "不明")
            st.markdown(f"**モデル:** `{llm_model}`")

            # トークン消費量
            st.subheader("🎫 トークン消費")
            token_usage: dict = debug_info.get("token_usage", {})
            if token_usage:
                col1, col2, col3 = st.columns(3)
                col1.metric("Prompt Tokens", f"{token_usage.get('prompt_tokens', 0):,}")
                col2.metric("Completion Tokens", f"{token_usage.get('completion_tokens', 0):,}")
                col3.metric("Total Tokens", f"{token_usage.get('total_tokens', 0):,}")
            else:
                st.info("トークン消費量を取得できませんでした。")

            # レイテンシ
            st.subheader("⏱ レイテンシ")
            lat_cols = st.columns(4)
            lat_cols[0].metric(
                "① Embedding生成",
                f"{debug_info.get('latency_embedding_ms', 0):.0f} ms",
            )
            lat_cols[1].metric(
                "② 内積計算",
                f"{debug_info.get('latency_cosine_ms', 0):.1f} ms",
            )
            lat_cols[2].metric(
                "③ top_kソート",
                f"{debug_info.get('latency_sort_ms', 0):.1f} ms",
            )
            lat_cols[3].metric(
                "④ LLM回答生成",
                f"{debug_info.get('latency_llm_ms', 0):.0f} ms",
            )

            # コスト
            st.subheader("💰 概算コスト (USD)")
            cost: dict = debug_info.get("cost", {})
            if cost:
                cost_cols = st.columns(4)
                cost_cols[0].metric("Embedding", f"${cost.get('embedding_usd', 0):.6f}")
                cost_cols[1].metric("Prompt", f"${cost.get('prompt_usd', 0):.6f}")
                cost_cols[2].metric("Completion", f"${cost.get('completion_usd', 0):.6f}")
                cost_cols[3].metric("合計", f"${cost.get('total_usd', 0):.6f}")

            # 生成速度
            st.subheader("🚀 生成速度")
            velocity: float = debug_info.get("token_velocity", 0.0)
            st.metric("トークン生成速度", f"{velocity:.1f} tokens/sec")

            # 低確率トークン（ハルシネーション予備軍）
            st.subheader("⚠️ 低確率トークン（ハルシネーション予備軍）")
            low_prob: list = debug_info.get("low_prob_tokens", [])
            if low_prob:
                st.caption(f"確率 90% 未満のトークン: {len(low_prob)} 個検出")
                # 確率が低い順に並べ替え（上位20件）
                sorted_tokens = sorted(low_prob, key=lambda x: x["probability"])[:20]
                for item in sorted_tokens:
                    prob_val: float = item["probability"]
                    # 確率に応じたバッジ
                    if prob_val < 50:
                        badge = "🔴"
                    elif prob_val < 70:
                        badge = "🟠"
                    else:
                        badge = "🟡"
                    st.markdown(f"- {badge} `{item['token']}` : **{prob_val}%**")
            else:
                st.success("✅ 全トークンが 90% 以上の確率で生成されました。")


def _render_sources(sources: list[dict]) -> None:
    """参照ソースをエクスパンダーで折りたたんで表示する。"""
    with st.expander(f"📚 参照ソース ({len(sources)} 件)", expanded=False):
        for i, source in enumerate(sources, 1):
            source_name: str = Path(source.get("source_file", "不明")).name
            similarity: float = source.get("similarity", 0.0)

            # 類似度に応じた色
            if similarity >= 0.5:
                badge = "🟢"
            elif similarity >= 0.3:
                badge = "🟡"
            else:
                badge = "🔴"

            st.markdown(
                f"**{badge} [{i}] {source_name}** — "
                f"ページ {source['page_number']} "
                f"(類似度: `{similarity:.4f}`)"
            )
            st.caption(source.get("text_preview", ""))
            if i < len(sources):
                st.divider()
