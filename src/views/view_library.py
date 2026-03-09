"""
知識の書庫（PDF・インデックス管理画面）のUI描画。

PDF一覧、アップロード、ベクトル化（インデックス構築）、インデックス初期化を提供する。
"""

import streamlit as st
from pathlib import Path
import shutil
import numpy as np

from src.config import DATA_DIR


def _get_subjects() -> list[str]:
    """data/ 配下の科目ディレクトリ一覧を取得する。"""
    data_path = Path(DATA_DIR)
    if not data_path.exists():
        return []
    return sorted(
        d.name for d in data_path.iterdir() if d.is_dir()
    )


def _get_pdf_files(subject: str) -> list[Path]:
    """指定科目のPDFファイル一覧を取得する。"""
    subject_dir = Path(DATA_DIR) / subject
    if not subject_dir.exists():
        return []
    return sorted(subject_dir.rglob("*.pdf"))


def _get_cache_info(subject: str) -> dict:
    """指定科目のキャッシュ（ベクトルストア）情報を取得する。"""
    cache_dir = Path("vector_stores") / subject
    if not cache_dir.exists():
        return {"exists": False, "chunk_count": 0, "files": []}

    npy_files = list(cache_dir.glob("embeddings_*.npy"))
    json_files = list(cache_dir.glob("chunks_*.json"))

    chunk_count = 0
    if npy_files:
        try:
            embeddings = np.load(npy_files[0])
            chunk_count = embeddings.shape[0]
        except Exception:
            pass

    return {
        "exists": bool(npy_files),
        "chunk_count": chunk_count,
        "files": [f.name for f in npy_files + json_files],
    }


def _build_index_pipeline(target_subject: str) -> None:
    """指定された科目のPDF群からインデックスを構築する一連のパイプライン処理。"""
    target_dir = Path(DATA_DIR) / target_subject
    pdf_paths = sorted(str(p) for p in target_dir.rglob("*.pdf"))

    if not pdf_paths:
        st.error(f"❌ {target_subject}ディレクトリにPDFが見つかりません。")
        return

    progress_bar = st.progress(0, text="インデックス構築を開始...")

    try:
        from src.pdf_reader import extract_text_from_pdf
        from src.text_chunker import chunk_text
        from src.embedder import (
            generate_cache_key,
            generate_embeddings,
            save_cache,
        )

        cache_key = generate_cache_key(pdf_paths)
        cache_dir = Path("vector_stores") / target_subject

        # 1. PDF読み込み
        progress_bar.progress(0.1, text="1/3: PDFからテキストを抽出中...")
        all_pages: list[dict] = []
        skipped: list[str] = []
        for pdf_path in pdf_paths:
            try:
                pages = extract_text_from_pdf(pdf_path)
                if pages:
                    for page in pages:
                        page["source_file"] = pdf_path
                    all_pages.extend(pages)
                else:
                    skipped.append(Path(pdf_path).name)
            except Exception as e:
                skipped.append(f"{Path(pdf_path).name} ({e})")

        if not all_pages:
            st.error("❌ すべてのPDFからテキストを抽出できませんでした。")
            return

        # 2. チャンク分割
        progress_bar.progress(0.4, text="2/3: テキストをチャンクに分割中...")
        chunks = chunk_text(all_pages)

        if not chunks:
            st.error(f"❌ テキストは抽出されましたが、チャンク分割結果が0件です（抽出ページ数: {len(all_pages)}）")
            return

        # 3. Embedding生成
        progress_bar.progress(0.6, text="3/3: Embedding生成中（API通信）...")
        texts = [c["text"] for c in chunks]
        if not texts:
            st.error("❌ Embedding対象のテキストが空です。")
            return
        embeddings = generate_embeddings(texts)

        # キャッシュ保存
        cache_dir.mkdir(parents=True, exist_ok=True)
        progress_bar.progress(0.9, text="キャッシュを保存中...")
        save_cache(embeddings, chunks, cache_key, cache_dir)

        progress_bar.progress(1.0, text="完了！")

        st.success(
            f"✅ インデックス構築完了！\n\n"
            f"- PDF: {len(pdf_paths)} 件\n"
            f"- チャンク: {len(chunks)} 個\n"
            f"- ベクトル次元: {embeddings.shape[1]}"
        )

        if skipped:
            st.warning(f"⚠️ スキップされたファイル: {', '.join(skipped)}")

        # RAGCoreのキャッシュをリセット（次回読み込み時に再構築させる）
        st.session_state.pop("rag_core", None)
        st.session_state.pop("ai_tutor", None)
        st.session_state.pop("pipeline_key", None)

    except Exception as e:
        st.error(f"❌ インデックス構築に失敗しました: {e}")


def render_library() -> None:
    """知識の書庫（PDF・インデックス管理画面）を描画する。"""
    st.title("📚 知識の書庫 (Library)")
    st.caption("PDFのアップロード・インデックス構築・データ管理を行います。")
    st.divider()

    subjects = _get_subjects()

    # ================================================================
    # セクション1: 現在のインデックス状態
    # ================================================================
    st.markdown("### 📊 現在のインデックス状態")

    if not subjects:
        st.info("まだ科目が登録されていません。下のアップロード機能からPDFを追加してください。")
    else:
        total_chunks = 0
        total_pdfs = 0
        for subject in subjects:
            pdfs = _get_pdf_files(subject)
            cache = _get_cache_info(subject)
            total_pdfs += len(pdfs)
            total_chunks += cache["chunk_count"]

            with st.expander(f"📁 {subject} — PDF: {len(pdfs)}件, チャンク: {cache['chunk_count']}"):
                if pdfs:
                    for pdf in pdfs:
                        size_mb = pdf.stat().st_size / (1024 * 1024)
                        st.markdown(f"- 📄 **{pdf.name}** ({size_mb:.1f} MB)")
                else:
                    st.caption("PDFファイルなし")

                if cache["exists"]:
                    st.success(f"✅ インデックス構築済み（{cache['chunk_count']} チャンク）")
                    if st.button("🔄 インデックスを再構築", key=f"rebuild_{subject}", width="stretch"):
                        _build_index_pipeline(subject)
                        st.rerun()
                else:
                    col_warn, col_btn = st.columns([2, 1])
                    with col_warn:
                        st.warning("⚠️ インデックス未構築")
                    with col_btn:
                        if st.button("🔄 インデックス構築", key=f"build_{subject}", type="primary", width="stretch"):
                            _build_index_pipeline(subject)
                            st.rerun()

        col1, col2 = st.columns(2)
        with col1:
            st.metric("📄 合計PDF数", f"{total_pdfs} 件")
        with col2:
            st.metric("🧩 合計チャンク数", f"{total_chunks}")

    st.divider()

    # ================================================================
    # セクション2: 新規PDFアップロードとベクトル化
    # ================================================================
    st.markdown("### 📤 新規PDFのアップロード")

    # 科目名の入力（既存 or 新規）
    subject_options = subjects + ["➕ 新規科目を作成"]
    selected_option: str = st.selectbox(
        "アップロード先の科目を選択",
        subject_options,
        index=0 if subjects else 0,
    )

    if selected_option == "➕ 新規科目を作成":
        target_subject: str = st.text_input(
            "新しい科目名を入力（半角英数字推奨）",
            placeholder="例: LinearAlgebra",
        )
    else:
        target_subject = selected_option

    uploaded_files = st.file_uploader(
        "PDFファイルを選択（複数可）",
        type=["pdf"],
        accept_multiple_files=True,
        key="library_pdf_uploader",
    )

    if uploaded_files and target_subject:
        st.info(f"📁 アップロード先: `data/{target_subject}/`")

        if st.button("🔄 インデックスを構築（ベクトル化）", type="primary", width="stretch"):
            target_dir = Path(DATA_DIR) / target_subject
            target_dir.mkdir(parents=True, exist_ok=True)

            # PDFを保存
            progress_bar = st.progress(0, text="PDFを保存中...")
            for i, uploaded_file in enumerate(uploaded_files):
                save_path = target_dir / uploaded_file.name
                save_path.write_bytes(uploaded_file.getvalue())
                progress_bar.progress(
                    (i + 1) / len(uploaded_files),
                    text=f"PDF保存中... ({i + 1}/{len(uploaded_files)})",
                )

            # 共通のインデックス構築パイプラインを呼び出し
            _build_index_pipeline(target_subject)
            st.rerun()

    elif uploaded_files and not target_subject:
        st.warning("⚠️ 科目名を入力してください。")

    st.divider()

    # ================================================================
    # セクション3: インデックスの初期化（パージ）
    # ================================================================
    st.markdown("### 🗑️ インデックスの管理")

    with st.expander("⚠️ 危険ゾーン: インデックスの削除", expanded=False):
        st.warning("この操作はベクトルデータ（キャッシュ）を完全に削除します。PDF原本は保持されます。")

        if subjects:
            delete_target: str = st.selectbox(
                "削除対象の科目",
                ["--- 選択してください ---"] + subjects + ["🔥 全科目のインデックスを削除"],
                key="delete_target_select",
            )

            confirm_delete: bool = st.checkbox(
                "本当に削除します（この操作は取り消せません）",
                key="confirm_delete_check",
            )

            if st.button("🗑️ インデックスを削除", disabled=not confirm_delete, width="stretch"):
                if delete_target == "--- 選択してください ---":
                    st.error("削除対象を選択してください。")
                elif delete_target == "🔥 全科目のインデックスを削除":
                    vs_root = Path("vector_stores")
                    if vs_root.exists():
                        shutil.rmtree(vs_root)
                        vs_root.mkdir(exist_ok=True)
                    st.session_state.pop("rag_core", None)
                    st.session_state.pop("ai_tutor", None)
                    st.session_state.pop("pipeline_key", None)
                    st.success("✅ 全科目のインデックスを削除しました。")
                    st.rerun()
                else:
                    cache_dir = Path("vector_stores") / delete_target
                    if cache_dir.exists():
                        shutil.rmtree(cache_dir)
                    st.session_state.pop("rag_core", None)
                    st.session_state.pop("ai_tutor", None)
                    st.session_state.pop("pipeline_key", None)
                    st.success(f"✅ {delete_target} のインデックスを削除しました。")
                    st.rerun()
        else:
            st.info("削除対象のインデックスがありません。")
