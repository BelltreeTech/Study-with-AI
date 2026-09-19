# Study-with-AI

PDF教材から学ぶローカルStreamlitアプリです。Dashboard / RAG / Feynman Drill / Curriculum / Libraryの5画面を維持し、生成を共通の公式Codex CLI Providerへ、教材EmbeddingをローカルE5へ移しました。OpenAI SDK、Chat Completions / Responses / Embedding APIの直接呼出し、APIキー設定UIはありません。

**2026-09-19のこのMacでは、実Codex生成は安全側で停止します。** ChatGPTログインは確認済みですが、standalone CLI 0.152.1のモデルcatalogに`gpt-6-astra`がなく、認証の正規保存先にあるglobal AGENTSを個別要求から除外できません。また、この版の組込みOpenAI Providerの内部retry回数を正式設定で制限できることも確認できていません。別モデルやAPIへはfallbackしません。ローカル検索、書庫、履歴、Dashboardは利用できます。詳細は[実行境界](docs/CODEX_BOUNDARY.md)と[検証報告](docs/TEST_REPORT.md)を参照してください。

## セットアップ

macOS、Python 3.12、uvで検証しました。Python要件は`>=3.12,<3.14`。この実装のジョブ排他にはPOSIX `fcntl`を使うため、Windowsには未対応です。Linuxは未検証です。Codex CLIやグローバル環境を自動更新しません。

```sh
cd ~/Developer/projects/Study-with-AI
uv sync --frozen --extra semantic
codex --version
codex login status
```

ChatGPTに未ログインの場合だけ、本人が`codex login`でログインしてください。既存認証を破棄したり、APIキーを登録したりする必要はありません。認証確認は公式CLIに任せ、アプリがauth.jsonやトークンを独自解析することはありません。

生成モデルは**GPT-6、実ID `gpt-6-astra`、`model_reasoning_effort="medium"`**です。設定の正本は`src/config.py`と`src/codex_provider.py`の`CodexSettings`です。実行ファイルは起動時PATHから解決した絶対パス、生成timeout 180秒、診断全体15秒、入力64KiB、出力2MiB。同時生成は同じ保存領域を使うアプリ全体で1です。通常UIから任意のコマンド・実行ファイル・CLI引数は設定できません。

公式モデル掲載とこのアカウント・CLIでの利用可否は別です。[公式モデル一覧](https://learn.chatgpt.com/docs/models)、[GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra)、[認証](https://learn.chatgpt.com/docs/auth)、[設定](https://learn.chatgpt.com/docs/config-file/config-reference)を確認し、CLIの版・catalog・実行境界を再監査するまでは実生成を有効化しない設計です。

## 教材とローカルモデル

教材は次の2階層で配置します。同じ科目名でもカテゴリが違えば別科目です。

```text
data/
  Mathematics/
    線形代数/
      book.pdf
```

Libraryのアップロードも`カテゴリ/科目`を指定します。同名教材の上書き、パストラバーサル、symlinkへの保存を拒否します。PDFのテキスト抽出を優先し、文字が少なく画像があるページのみTesseract OCRを試します。日本語画像PDFにはTesseract本体と`jpn`/`eng`の言語データが必要です。OCR不足は警告として表示し、読めたページは保持します。

意味検索を有効にする初回の明示操作:

```sh
uv run --frozen --extra semantic python scripts/download_embedding.py
```

この操作だけはHugging Faceからモデルを取得するため通信が必要です。通常のEmbedding・検索はローカルファイルを使い、モデル未取得・読込失敗ならBM25検索へ縮退し、その状態を表示します。商用Embedding APIへのfallbackはありません。

- モデル: `intfloat/multilingual-e5-small`
- 固定revision: `614241f622f53c4eeff9890bdc4f31cfecc418b3`
- 384次元、512 tokens、`query: ` / `passage: `、L2正規化、MIT
- [公式model card](https://huggingface.co/intfloat/multilingual-e5-small/blob/614241f622f53c4eeff9890bdc4f31cfecc418b3/README.md)

キャッシュは内容hash・抽出/チャンク設定・モデルrevision/次元/prefix/正規化・library版を含む識別子で`cache/local-retrieval-v2`へ保存します。旧APIベクトルは読み込まず、削除もしません。[検索の設計と評価](docs/LOCAL_RETRIEVAL.md)。

## 起動と停止

通常利用:

```sh
uv run --frozen --extra semantic streamlit run app.py --server.address 127.0.0.1
```

ブラウザで`http://127.0.0.1:8501`を開きます。生成は必要な教材抜粋・会話・答案をCodex経由でサービスへ送り、契約の利用枠を消費します。APIキー不要であっても、生成は完全オフラインでも無制限でもありません。モデルに渡す量には上限があります。

画面の「キャンセル」は対象ジョブだけを停止します。「生成ジョブを停止して保存」はアプリが所有するジョブの終了を待ちます。サーバーを終了するには起動したターミナルで**Ctrl+C**を押してください。他のCodexプロセスを一括停止しません。ジョブと結果はSQLiteへ逐次保存され、異常終了後の未完了ジョブは成功にせず中断とします。明示再実行では利用枠を追加消費する場合があります。

本人の進捗・教材を使わず試す場合:

```sh
# sample_dataが既にある場合は再生成不要。同名サンプルは上書きしません。
uv run --frozen python scripts/create_sample.py --data-root sample_data
STUDY_DATA_DIR="$PWD/sample_data" \
STUDY_STATE_DIR="$PWD/.study-runtime/demo-state" \
STUDY_CACHE_DIR="$PWD/.study-runtime/demo-cache" \
uv run --frozen --extra semantic streamlit run app.py --server.address 127.0.0.1
```

`STUDY_DATA_DIR` / `STUDY_STATE_DIR` / `STUDY_CACHE_DIR`で保存先を分離できます。モデルの保存先は`STUDY_EMBEDDING_DIR`で指定できます。設定例は[study-env.example.sh](study-env.example.sh)。`.env`の自動読込はありません。

CLIも同じService/Provider/ジョブ管理を利用します。

```sh
uv run --frozen python main.py --diagnose
STUDY_DATA_DIR="$PWD/sample_data" STUDY_STATE_DIR="$PWD/.study-runtime/demo-state" \
STUDY_CACHE_DIR="$PWD/.study-runtime/demo-cache" \
uv run --frozen --extra semantic python main.py --subject Example/Study-Basics --question "間隔反復" --search-only
```

`--search-only`を外すと生成要求になります。現在の実機制約下では理由付きで停止します。

## 学習と保存

- Dashboard: EXP、称号、日次目標、ストリーク、学習ヒートマップ、科目別バランス、復習予定、ポモドーロ。
- RAG: 生成なしのローカル検索、教材根拠を示す回答、出題傾向分析、科目・学習セッション別の会話履歴。
- Feynman Drill: Easy/Normal/Hard、構造化設問・配点・採点基準・模範解答、弱点復習。模範解答は採点後だけ表示。
- Curriculum: 5/10/15章、必要な章だけ講義生成、再生成、ソクラテス対話、章試験、章完了とEXP、保存講義のMarkdown出力。
- Library: PDF登録と一覧、ローカル索引作成・更新、モデル未取得/OCR/破損の診断。

Easy=70、Normal=80、Hard=90点を維持。問題の配点合計、設問ID、得点範囲、根拠IDをアプリ側で検証し、合計と合否は決定的に計算します。失敗した採点を0点・不合格へ変換しません。初心者/専門家、回答長、チューター、数式・導出、難易度の設定を共通プロンプトへ渡します。

表示に使うのはMarkdownと検証したデータです。Mermaidはリンク・HTML・実行指示を含まない単純なflowchartのみ安全なGraphvizデータに変換し、それ以外はコード表示にします。生成文・引用の正しさは根拠IDの実在確認だけでは保証されないため、教材と照合してください。

進捗の旧JSONは保存したまま、version付きSQLiteへ一度だけ移行します。未知フィールドも保持します。学習履歴・ジョブは別SQLiteです。元JSONとSQLiteの扱い、rollback、追跡済み個人ファイルの解除は[移行手順](docs/MIGRATION.md)を参照してください。旧コースには科目対応がないため、まず科目未割当の保存コースとして閲覧・exportできます。本人が対象科目を選び「この科目へ割り当てて学習を再開」を押すと対応付けます。旧講義の教材版は不明なので、対話・試験を続ける前に講義を再生成します。

## 開発・検証

通常テストはAPIキー・認証・実LLM・本人の教材を使いません。

```sh
uv sync --frozen --extra semantic
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen mypy src app.py main.py scripts
uv run --frozen python verify_score.py

# opt-in: 取得済みローカルE5。通信禁止下の実Embedding/検索を検証
STUDY_TEST_LOCAL_EMBEDDING=1 uv run --frozen --extra semantic pytest tests/test_retrieval_semantic.py -q

# opt-in: installed CLIのlocalhost mock probe。実認証・実生成は使用しない
STUDY_RUN_CODEX_BOUNDARY_PROBE=1 uv run --frozen pytest tests/test_provider.py -q
```

[機能対応表](docs/FEATURE_INVENTORY.md)、[設計](docs/ARCHITECTURE.md)、[テスト報告](docs/TEST_REPORT.md)、[再開用状態](docs/PROJECT_STATE.md)に確認済み範囲と制約を記録しています。公開CI用の実Codex生成は追加していません。
