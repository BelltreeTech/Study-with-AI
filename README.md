# Study-with-AI

PDF教材から学ぶローカルStreamlitアプリです。Dashboard / RAG / Feynman Drill / Curriculum / Libraryの5画面を維持し、生成を共通の公式Codex CLI Providerへ、教材EmbeddingをローカルE5へ移しました。OpenAI SDK、Chat Completions / Responses / Embedding APIの直接呼出し、APIキー設定UIはありません。

学習ゴール、前提知識、学び方（体系的・例題中心・実践・試験対策）、たとえに使う分野、1章のインプット時間の目安を保存できます。PDFを登録してコースを作り、講義 → 相談・練習 → 修了試験 → 弱点の復習へ進みます。作成済みコースは当時の設定を保持し、答案の下書きや相談履歴から再開できます。

**2026-09-19: 専用Codex CLI 0.155.1への本人の公式ChatGPTログインが完了しています。** `gpt-6-astra / medium` の正式catalog掲載と実効設定・実行境界を確認しています。合成教材でカリキュラム・講義・対話・問題・採点の5操作が実生成に成功しました。失敗3件を含む検証上限8ジョブに達したため追加生成は終了し、単独の内容相談の実生成は未検証です。内容点検と制約は[最新の検証報告](docs/TEST_REPORT.md)を参照してください。別モデル・別effort・APIへのfallback、Resetの自動消費はありません。

最初に「教材ライブラリ」でPDFを追加し、「あなたの学び方を設定」を保存します。「この教材で学ぶ」からコースを作成すると、ホームの「続きから学ぶ」で再開できます。相談の「要点をつかむ」は代表的なページを参照し、具体的な質問では該当箇所を検索します。長いPDFの全ページ・全概念を一度に網羅する保証はなく、参照範囲と根拠ページを確認できます。

## セットアップ

macOS arm64、Python 3.12、uvで検証しました。Python要件は`>=3.12,<3.14`。この実装のジョブ排他にはPOSIX `fcntl`を使うため、Windowsには未対応です。Linuxは未検証です。専用CLIのinstallerはmacOS arm64版を対象とし、共有Codex CLI、Homebrew、Codexアプリ、PATHを更新しません。

```sh
cd ~/Developer/projects/Study-with-AI
uv sync --frozen --extra semantic
uv run --frozen python scripts/setup_codex.py
uv run --frozen python scripts/codex_runtime.py --setup-home
uv run --frozen python scripts/codex_runtime.py --login-command
```

最後のコマンドはログインを実行せず、本人がターミナルで実行する公式ブラウザログインのコマンドを表示します。専用homeが未認証の場合だけ、表示されたコマンドを実行し、本人がブラウザでChatGPTログインを完了してください。共有Codexの既存ログインはそのまま保持し、認証コピーや共有側のlogoutは行いません。アプリは認証ファイルの内容を読まず、認証・更新・状態確認を公式CLIに任せます。

```sh
# 本人のログイン完了後。同じ専用CLI/home/auth storeで再診断します。
uv run --frozen python scripts/codex_runtime.py --diagnose
```

診断は生成を行いません。`ready: true`になる前は通常生成を開始せず、理由を表示します。組織の強制設定や独自endpoint等を検出した場合はその設定を回避せず、追加監査が必要として停止します。モデル一覧への掲載、ChatGPT認証、サーバーでの実生成成功は別々の確認事項です。

| 設定 | 値 |
| --- | --- |
| 生成モデル / reasoning effort | **GPT-6、実ID `gpt-6-astra` / `medium`** |
| 専用実行ファイル | `~/.local/share/study-with-ai/tools/codex/0.155.1/vendor/aarch64-apple-darwin/bin/codex` |
| 専用CODEX_HOME | `~/.local/share/study-with-ai/codex-home`、本人所有・0700 |
| 認証 | `forced_login_method="chatgpt"`、`cli_auth_credentials_store="file"` |
| service tier | Fastを指定・継承しない。実効設定は通常の既定値 |
| 上限 | 生成timeout 180秒、診断全体15秒、入力64KiB、stdout/stderr合計2MiB |
| 同時生成 | 同じ保存領域を使うアプリ全体で1 |
| 再試行 | アプリの自動再試行0回。CLIの有限内部retryは許容し、無制限接続retryを無効化 |

モデル/effortの正本は`src/config.py`、実行境界・上限の正本は`src/codex_provider.py`の`CodexSettings`です。CLIの版と配布binary hashも照合します。`STUDY_CODEX_BIN` / `STUDY_CODEX_HOME`はローカル管理者用の保存先指定であり、別版・別モデル・共有homeを通す機能ではありません。通常UIに任意コマンド・実行ファイル・CLI引数の入力欄はありません。`CODEX_HOME`を共有shellへexportする必要もありません。

[公式モデル一覧](https://learn.chatgpt.com/docs/models)、[GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra)、[認証](https://learn.chatgpt.com/docs/auth)、[設定](https://learn.chatgpt.com/docs/config-file/config-reference)と、固定版の公式ソースを確認しました。HTTP/stream内部retryの内訳と利用枠の扱いは[認証・retry監査](docs/PHASE2_AUTH_RETRY_AUDIT.md)に記録しています。1ジョブを1回のHTTP送信・1回の推論・1回の利用枠消費とは数えません。 利用上限に達してもResetクレジットを自動消費せず、有料APIや別モデルへ切り替えません。

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

## 講義と練習（2026-09-20）

60分は読む・理解するインプットの目安です。練習・試験・復習は別時間で、説明を省略して時間内に収める指示はしません。コース内は「講義」「相談」「練習」「修了試験」に分かれます。初回の章作成は設計1回＋本文最大8節、失敗・キャンセル後は保存済み節を使って明示再開できます。旧コースの時間設定・講義・進捗を保持し、「新方式の講義を作る」で新版へ移れます。

日本語の図は表示処理を修正しました。保存されたMermaid原文が正常なら、画面の再表示だけで直り、再生成は不要です。原文の破損を推測して書き換える処理はありません。

詳しくは [学習仕様](docs/LEARNING_DESIGN.md) と [HTML仕様書](docs/SYSTEM_SPECIFICATION.html) を参照してください。新方式の実生成については、2026-09-20に保存済み4節を再利用し、残る2節を公式Codexで生成して第1章全6節の完成を確認しました。章を最初から全節生成する成功率は未検証です。

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

`--search-only`を外すと生成要求になります。専用homeのChatGPT認証と実行境界の診断を通過していない場合は、理由付きで停止します。

## 学習と保存

- Dashboard（今日の学び）: コースの続き・PDF追加・復習への入口、EXP、称号、日次目標、ストリーク、学習ヒートマップ、科目別バランス、復習予定、ポモドーロ。
- RAG（内容を相談）: 科目別の学習設定・質問下書き、代表抜粋を使った概要相談、生成なしのローカル検索、教材根拠を示す回答、出題傾向分析、科目・学習セッション別の会話履歴。
- Feynman Drill（テスト・復習）: 答案の下書き復元・過去答案の保持、Easy/Normal/Hard、構造化設問・配点・採点基準・模範解答、弱点復習。模範解答は採点後だけ表示。
- Curriculum（コース・授業）: コースの学び方を固定、ロードマップ、5/10/15章、章の設計＋最大8節の一括生成・途中保存・明示再開、講義版の保存、節別相談、3問の練習・段階ヒント・答案フィードバック、章試験、章完了とEXP、保存講義のMarkdown出力。
- Library（教材ライブラリ）: 複数PDFの登録からコース作成への導線、PDF登録と一覧、ローカル索引作成・更新、モデル未取得/OCR/破損の診断。

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

合成教材での実確認には専用harnessを使用します。過去の実行と残り予算は永続ledgerで保持され、削除・初期化して再実行しません。実施済み結果は[検証報告](docs/TEST_REPORT.md)に記録しています。

```sh
# 認証・モデル・境界の確認だけ。生成ジョブは0件。
uv run --frozen python scripts/live_e2e.py --check-only

# 本人の利用枠を使う明示実行。失敗時の自動再試行はありません。
uv run --frozen --extra semantic python scripts/live_e2e.py --run --confirm-live
```

harnessは`.study-runtime/phase2-live`内の合成PDF・答案・DBだけを使用し、本人の教材・進捗には触れません。最小probe、RAG回答、5章curriculum、1章の講義、対話、問題生成、部分誤答の採点の7ジョブを順に実行します。永続ledgerで初回・再開・失敗を通算し、失敗した要求も含め**累計8ジョブ**が上限です。通常は7段階を別要求で実施します。今回の実測はprobe失敗2件と回答のSchema拒否1件の後、修正根拠・正常catalog・保存証拠を照合する明示modeで、残り5件のコース部分を完了しました。失敗probe/回答は失敗のまま残し、`course_flow_completed=true`と`technical_flow_completed=false`を区別しています。このcheckoutの検証枠は使用済みで、ledgerを削除して追加生成を行いません。完了済みの結果を再表示しても生成・進捗加算は繰り返しません。利用枠エラーや認証切れは成功として進めません。

結果は同ディレクトリの`report.json`と`results/`に保存します。`manual-review-template.json`に沿って教材・引用ページ・講義・対話・設問・部分誤答の減点理由・進捗復旧を確認し、具体的な照合根拠を`manual-review.json`へ記録します。構造化JSONの成功だけでは学習品質を合格にしません。レビュー済みの範囲と未検証事項は検証報告に記載します。CLI内部の実送信回数・サーバー推論回数は観測できず、レポートでも不明とします。

[機能対応表](docs/FEATURE_INVENTORY.md)、[設計](docs/ARCHITECTURE.md)、[テスト報告](docs/TEST_REPORT.md)、[再開用状態](docs/PROJECT_STATE.md)に確認済み範囲と制約を記録しています。公開CI用の実Codex生成は追加していません。

## 2026-09-20: 講義設計の形式エラーへの対応

講義設計の出力が `schema_error` で拒否された場合、JSON解析失敗とSchema違反を区別し、処理段階・定義済み項目へのパス・制約名・文字数/件数だけを診断として記録します。生成本文、答案、未知の項目名、例外の生メッセージは記録しません。画面には日本語の理由を表示し、講義の「通知を閉じる」後も作成途中の欄に直近の理由を残します。過去の失敗には診断がないため、従来の共通メッセージのままです。

固定CLI用のSchemaから除いていた `minLength` / `maxLength` / `uniqueItems` は、元Schemaから生成したアプリ所有の指示として全生成経路の先頭へ補います。追加指示込みで既存65,536バイト上限を検査します。Schema検査は緩めず、自動切詰め・重複除去・再生成もしません。講義設計などに存在しない `insufficient_evidence` / `supplemental_markdown` を作らせる共通指示を除きました。

ジョブDBには補助表 `job_diagnostics` を追加します（アプリ起動時に存在しなければ作成）。既存jobs行や学習・進捗DBの変換、再移行は不要です。講義の各試行にも安全な診断を保存します。既存チェックポイントの明示再開との互換性を保つため、学習要求の `study-4` / `study-3` は維持しています。この形式指定補足の実装版はGit履歴で識別します。

反映には実行中のStreamlitをCtrl+Cで停止し、通常の起動コマンドで再起動してください。失敗した章は「未完了の節から再開」で明示実行します。設計未保存なら設計から、保存済み節があればその次からです。再起動だけで生成は始まりません。再開は利用枠を消費し得ます。

追加の実Codex生成・Reset消費は行っていません。過去2件の実回答は残っておらず、個別の違反項目は確定できません。今回の修正で実生成が必ず成功するとの検証結果ではありません。

講義本文のタイムアウト対策として、60分・詳細の希望を章全体に適用し、節を越えた説明の重複や過剰な別例を減らします。導出やコードの意味は省略せず、長い章の論点を節に分散します。制限時間は1要求180秒・章全体30分を維持し、停止時には対象の節と上限秒数を表示します。

2026-09-20の明示依頼では、タイムアウトした第1章を成功済み4節から再開し、公式Codexの追加2要求で全6節をコースへ保存しました。実測は第5節101.48秒、第6節107.71秒。Reset消費なし。詳細は検証報告を参照してください。
