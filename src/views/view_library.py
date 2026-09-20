"""PDF onboarding and local search; uploading never starts a model request."""

from pathlib import Path

import streamlit as st

from src.config import DATA_DIR
from src.materials import list_materials, save_pdf
from src.runtime import Runtime
from src.views.navigation import queue_navigation


def render_library(runtime: Runtime) -> None:
    st.title('教材ライブラリ')
    st.caption('PDFを入れて、自分専用のコースへ。原本を残したまま、必要なページを根拠に学びます。')
    subjects = runtime.retriever.discover_subjects()
    with st.container(border=True):
        st.subheader('PDFを登録')
        target = st.text_input('登録先（カテゴリ/科目）', placeholder='Mathematics/線形代数', key='upload_subject',
                               help='例：教養/統計学、資格/基本情報。同じ科目のPDFはまとめて使えます。')
        uploaded_files = st.file_uploader('教材PDF（同名ファイルを上書きしません）', type=['pdf'], accept_multiple_files=True)
        st.caption('1ファイル30MBまで。暗号化されたPDFは解除後に登録してください。画像PDFは読み取り環境によってOCRが必要です。')
        if st.button('教材を保存', disabled=not uploaded_files or not target.strip(), type='primary', icon=':material/upload_file:'):
            saved = []
            failures = []
            for uploaded in uploaded_files or []:
                try:
                    save_pdf(Path(DATA_DIR), target.strip(), uploaded.name, uploaded.getvalue())
                    saved.append(uploaded.name)
                except (ValueError, OSError) as exc:
                    failures.append(f'{uploaded.name}: {exc}')
            if saved:
                st.session_state['import_result'] = {'subject': target.strip(), 'saved': saved, 'failures': failures}
            for failure in failures:
                st.error(failure)
            if saved and not failures:
                st.rerun()
            elif saved:
                st.warning('保存できたPDFは保持しました。上のエラーになったファイルだけを確認してください。')
    imported = st.session_state.get('import_result')
    if imported:
        st.success(f"{len(imported['saved'])}件のPDFを {imported['subject']} に保存しました。")
        st.button('この教材でコースを作る', type='primary', on_click=queue_navigation,
                  args=('Curriculum', imported['subject']), key='import_create')
        st.caption('「あなたの学び方を設定」で目標や例題・たとえを指定できます。生成は作成ボタンを押したときだけ始まります。')
    st.subheader('登録済みの教材')
    if not subjects:
        st.info('まだ教材はありません。上から最初のPDFを追加してください。')
    for subject in subjects:
        with st.expander(subject, expanded=subject == st.session_state.get('selected_subject')):
            files = list_materials(Path(DATA_DIR), subject)
            st.caption(f'{len(files)}件のPDF')
            for file in files:
                st.write(f"{Path(file['path']).name} · {file['bytes'] / 1024:.1f} KB")
            left, right = st.columns(2)
            if left.button('ローカル索引を構築・更新', key='index_' + subject):
                with st.spinner('PDFのページを読み取り、検索できるようにしています…'):
                    result = runtime.retriever.index(subject)
                if result['mode'] == 'hybrid':
                    st.success('ローカルEmbedding + BM25の索引を確認しました。')
                else:
                    st.info('BM25検索を利用できます。意味検索のモデルはまだ利用できません。')
            right.button('この科目を学ぶ', key='study_' + subject, on_click=queue_navigation,
                         args=('Curriculum', subject))
            diagnostic = runtime.retriever.diagnostics(subject)
            st.caption(f"検索状態: {diagnostic.get('mode', 'not_indexed')} · {diagnostic.get('chunk_count', 0)}件の教材抜粋")
            for warning in diagnostic.get('warnings', []):
                st.warning(str(warning))
    with st.expander('保存とプライバシー'):
        st.write('教材はこのMacに保存されます。検索だけでは生成モデルへ送信しません。生成時は必要な抜粋・会話・答案を公式Codexへ送ります。')
        st.caption('以前の索引・元PDF・進捗は保持します。モデル取得と保存先の詳細はREADMEに記載しています。')
