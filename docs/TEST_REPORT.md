# 検証報告

## 第2段階（2026-09-19、現在の結果）

開始HEAD `ceaaf865cdbaefc125561ca21f14eaa0ef850c98`、ブランチ `feat/codex-gpt6-medium-refactor` を維持した。macOS arm64 / Python 3.12.13 / Streamlit 1.54.0で検証。再clone、SQLite再移行、本人の教材・進捗を用いた試験、main変更、push、mergeは行っていない。作業は専用CLI・home・能力診断・retry契約・再開harnessに限定し、前段階の5画面と学習/保存基盤を維持した。

### 通常suite・静的検証

```sh
env -u OPENAI_API_KEY -u CODEX_API_KEY -u AZURE_OPENAI_API_KEY \
  .venv/bin/python -m pytest -q --junitxml=.study-runtime/phase2-tests.xml
.venv/bin/ruff check .
.venv/bin/mypy src app.py main.py scripts
.venv/bin/python verify_score.py
git diff --check
```

**221 passed, 2 skipped, 5 warnings in 34.19s**。2件のskipは新installed CLI localhost probeと実ローカルE5で、以下のopt-in実行で別途成功を確認した。5 warningsは既存PyMuPDF/SWIGのdeprecation。ruff、mypy（38 source files）、採点閾値スクリプト、`git diff --check`も成功した。

通常suiteは合成ファイル・fake CLI/Providerだけを使用する。実認証・実LLM要求は含まない。既存のStreamlit AppTest 6件を含み、全5画面とPDF→検索→回答→講義→問題→採点→進捗→再起動、キャンセル・失敗、科目/会話分離、ポモドーロを再確認した。設問別採点/点数合計/合否/EXP一度だけの適用も回帰対象であり、実モデルの回答品質を試したことにはならない。

新しい主な試験は、専用binary/homeの選択と共有環境保全、0700/0600・所有者・symlink拒否、認証内容を読まないこと、管理者ポリシー検出、改変CLI拒否、実効MCP/endpoint/ツール設定の照合、cloud cache変更時の再診断、モデル一覧の全ページと未確認/非対応の区別、明示probe、medium維持、有限retry許容と自動生成0、deadline/cancel後の反映拒否である。

harnessのmock 12件では、7ジョブ完了、意図的誤答のある答案で84点/50EXP、再開後の生成0件・再加点0、認証失敗時0ジョブ、永続予算8件、ledger欠落・runtime変更・非合成教材の拒否、失敗の明示再実行、結果digest付き手動レビューを確認した。84点はmockの値であり、実GPT-6の採点結果ではない。

### 新installed CLIと実モデルを区別した検証

採用CLIは `0.155.1`、絶対パスは `/Users/shinrisuzuki/.local/share/study-with-ai/tools/codex/0.155.1/vendor/aarch64-apple-darwin/bin/codex`。公式npm packageの固定SHA-512とbinary SHA-256を照合した。詳細・導入途中の失敗と修正は[専用CLI監査](PHASE2_CLI_AUDIT.md)。

```sh
STUDY_RUN_CODEX_BOUNDARY_PROBE=1 .venv/bin/python -m pytest \
  tests/test_provider.py -k installed_cli -q
STUDY_TEST_LOCAL_EMBEDDING=1 .venv/bin/python -m pytest \
  tests/test_retrieval_semantic.py -q
.venv/bin/python scripts/codex_runtime.py --diagnose
.venv/bin/python scripts/live_e2e.py --check-only
```

- 新CLI localhost境界試験: **1 passed, 43 deselected in 0.59s**。合成HOME/専用homeのみ、Authorizationなし、外部転送なし。送信model=`gpt-6-astra`、effort=`medium`、tools空、全10種の指示マーカー混入なし、全7種のhook/MCP副作用なし。mock receiverのHTTP 400とCLI終了1は意図した試験条件。実生成の成功ではない。
- 実ローカルE5: **1 passed, 5 warnings in 2.70s**。通信を禁止して固定revisionのモデルを実ロードし、日英/言語横断4合成質問で期待教材が4/4 top1、384次元・正規化を確認。品質評価の範囲はこの小さな合成セット。
- 正式なモデル・設定診断: 同じ専用binary/homeで `model/list includeHidden=true` の全1ページに指定modelとmediumが掲載。`config/read` / `configRequirements/read` で境界を照合し、`boundary_verified=true`。未認証のCLI管理catalogであり、認証済み利用資格やサービス側モデル同一性の証明ではない。`thread/start` / `turn/start` は呼んでいない。
- 現在の専用home認証: `auth=unavailable`、`ready=false`、`probe_ready=false`。停止理由は **`auth_required` だけ**。診断helperの終了2はこの未認証状態を示す。強制条件を取り除いたりgateを迂回したりしていない。
- `live_e2e.py --check-only`: 生成ジョブ **0件**、専用合成保存先と8件上限を表示し、同じ未認証状態を確認した。実E2E保存領域の初期化・生成は行っていない。

新CLIのcatalog未掲載問題と専用homeによるglobal AGENTS隔離を再検証し、旧3停止理由をそのまま残していない。内部retryを0にできないだけで停止する旧要件は、本人の追補に従って有限retry許容へ変更した。アプリ自動再生成0、unbounded retry=false、総timeout180秒、cancel/process group回収、進捗一度だけの適用を維持する。実送信回数・サービス側推論数・消費利用枠は不明。利用上限でもResetクレジットを自動消費しない。

### APIキーなしの実起動・UI・ローカル検索

```sh
env -u OPENAI_API_KEY -u CODEX_API_KEY -u AZURE_OPENAI_API_KEY \
  STUDY_DATA_DIR="$PWD/sample_data" \
  STUDY_STATE_DIR="$PWD/.study-runtime/phase2-smoke-state" \
  STUDY_CACHE_DIR="$PWD/.study-runtime/phase2-smoke-cache" \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/streamlit run app.py --server.address 127.0.0.1 \
  --server.port 8517 --server.headless true --browser.gatherUsageStats false
```

health endpointはHTTP 200 / `ok`。実ブラウザで合成用Dashboardと5画面の切替項目を確認し、`Example/Study-Basics`のRAG画面でローカル検索を実行した。`hybrid`、合成PDFの1～3ページと根拠ID、3件の教材抜粋が表示された。UIの生成なし診断でも専用0.155.1・指定model/medium・境界true・auth_requiredのみを確認した。生成ボタンは押していない。全5画面の操作回帰は上記AppTestが担当する。

CLI `main.py --search-only`も別の`.study-runtime/phase2-search-state` / `phase2-search-cache`で実行し、同じ合成教材の該当1ページ目を先頭取得した。本人の保存先は使っていない。サーバーはCtrl+Cで終了0、検証ブラウザを閉じ、ポート8517のlistenerなしを確認した。ログイン待ちプロセスも起動・放置していない。

### 共有環境・未検証事項

共有 `/opt/homebrew/bin/codex` は **0.152.1**のまま。開始時と終了時に実体パスとbinary hashが同一で、共有`config.toml` / `AGENTS.md` / `auth.json`のinode・サイズ・mtimeも不変だった。認証の内容は読まず、metadataだけ比較した。専用homeはGit/backup/exportから分離され、共有認証や設定のコピー・変更はない。

第2段階の追加実生成ジョブは **0件 / 上限8件**。本人の専用home公式ChatGPTログインだけが現在未完了の操作である。ログイン後のアカウント要件と実生成可否は再診断が必要。実GPT-6の構造化応答・RAG/講義の根拠支持・対話・問題/部分誤答の採点品質・実E2E再開は **未検証**。手動品質レビューも未実施で、成功とは扱わない。準備済みの正確なログイン/再開手順は[PROJECT_STATE](PROJECT_STATE.md)と[README](../README.md)に記載する。

### 調査・検証中に修正した項目

独立レビューで、実効configに混入したMCP/endpoint等の見落とし、公式RPCがnested toolsの設定を省略する型の差、cloud cache更新時の診断失効、setup時のmarker symlinkと共有homeのsymlink子パス、ログインコマンドの親環境継承を指摘された。それぞれ実装を補強し、合成回帰を追加した。明示model probeは正確なmetadata警告だけを区別し、非対応modelやschema/完了不足を成功としない。初回のmypyはsession_flagsの型注釈不足1件で失敗し、型を明示して再実行した。失敗を隠して旧結果を最終成功としていない。

## 第1段階の履歴（現在の停止理由ではない）

以下は前段階 `ceaaf865` 完了時点の実測を保持したもの。0.152.1の失敗、当時の停止条件、試験件数を現在の状態と混同しない。

確認日: 2026-09-19。環境: macOS arm64、Python 3.12.13、uv、Streamlit 1.54.0、pytest 8.4.2。依存の正本は `uv.lock`。mainへの変更・push・mergeなし。テスト用保存先は一時ディレクトリまたは `.study-runtime/`、教材は自作PDFのみ。

### 通常suite

```sh
env -u OPENAI_API_KEY -u CODEX_API_KEY -u AZURE_OPENAI_API_KEY \
  .venv/bin/python -m pytest -q --junitxml=.study-runtime/final-tests.xml
```

**150 passed, 2 skipped, 5 warnings in 23.14s**。2件のskipは明示opt-inのinstalled CLI localhost probeと取得済みE5実モデル試験。skipを成功とは数えていない。5 warningsはPyMuPDF/SWIGのdeprecationで、テスト失敗ではない。

| 領域 | 通常結果 | 主な内容 |
| --- | ---: | --- |
| Provider | 36 pass / 1 skip | fake CLI、argv/stdin、モデル固定、キー除外、JSONL、schema、quota/auth/model/network、timeout/cancel、子/孤児process回収、診断全体deadline |
| Retriever | 26 pass | BM25、PDF/選択OCR、source/page、revision/cache、科目分離、壊れたPDF・vector・symlink、library metadata競合 |
| Local E5 | 1 skip | モデルなしで通常suiteを動かすためopt-in |
| Service・採点・教材 | 29 pass | 学習E2E、配点・閾値・引用、プロンプト、入力上限、scope、教材変更拒否、PDF登録、移行script |
| Progress Repository | 16 pass | 旧JSON、未知field、再移行防止、破損/未来schema、XP/streak/復習、並行保存、WAL backup |
| Learning Repository | 13 pass | schema/version、初期化race、private file、claim・receipt・session append・CAS |
| Jobs | 11 pass | process間同時1、idempotency、cancel後破棄、shutdown、orphan復旧、親異常終了後lock継承 |
| 統合review回帰 | 13 pass | 対象章/講義/教材版、別章attempt流用拒否、XP once、古い講義/採点結果の適用拒否、旧形式export、pending復旧 |
| Streamlit AppTest | 6 pass | 5画面、PDF→index→質問→講義→問題→採点→進捗→再起動、履歴分離、失敗/cancel、ポモドーロ |

UIのE2Eはmock Providerで実行し、モデル回答の内容品質は検証していない。難易度別配点と合否はアプリ計算で検証した。合格前の解答非公開、100点合格による章完了50EXP、rerun後も50EXPのまま、ポモドーロ25分による20EXP一回を確認した。

### 実ローカルEmbedding

```sh
STUDY_TEST_LOCAL_EMBEDDING=1 .venv/bin/python -m pytest tests/test_retrieval_semantic.py -q
```

**1 passed, 5 warnings in 2.45s**。固定revisionの `intfloat/multilingual-e5-small` をCPUで実ロード。すべてのsocket接続を禁止し、接続呼出0回をassertした。384次元・L2正規化、日英/言語横断の合成4質問で期待教材4/4 top1。これは小さな動作評価であり、大規模教材の品質保証ではない。

初回モデル取得は明示scriptで実施した。通常のアプリ/検索でモデルを自動ダウンロードしない。意味検索モデルが意図的にない別保存先でもCLI `--search-only` がBM25で検索でき、期待する合成PDFの1ページ目を先頭取得した。

### installed CLIと実生成の区別

実測CLI: `/opt/homebrew/bin/codex` → 0.152.1、認証: ChatGPT。指定model `gpt-6-astra` / effort `medium`。本物のモデルへの生成要求は **0回**。版・help・login status・model catalogの診断、および合成HOMEとlocalhost receiverへのprobeだけを実施した。

```sh
STUDY_RUN_CODEX_BOUNDARY_PROBE=1 .venv/bin/python -m pytest tests/test_provider.py -q
```

最終再実行は **37 passed in 34.83s**。このopt-inは空tool catalog、global/project AGENTS、config、skills、hooks、モデル/effort payloadの検査。authは用いず、外部モデルへ転送しない。36件の通常fake試験を含むため、上記150件へ37件を単純加算しない。通常skipした2件は、この実行と実E5試験でそれぞれ成功した。詳細は[CODEX_BOUNDARY.md](CODEX_BOUNDARY.md)を参照。

実機で指定modelが一覧にないこと、global AGENTSの個別隔離ができないこと、組込みprovider retry制限が未確認であることから実生成を停止する。実GPT-6の回答・講義・対話・問題・採点E2E、内容品質、実利用枠超過は **未検証**。mockのquotaエラー処理を実アカウントの枠超過試験とは扱わない。

### 起動・停止・API経路

APIキーをunsetし、合成PDFと分離保存先で実Streamlitサーバーを `127.0.0.1:8517` に起動した。ブラウザでDashboard、RAG、実E5によるhybrid検索、ページ番号付き3件の教材根拠を確認した。生成ボタンは本番Providerの診断で `model_unavailable` となり、回答や進捗を追加しなかった。Ctrl+Cでexit 0を確認し、ポート8517が停止したことも確認した。日常利用のサーバーは残していない。

```sh
env -u OPENAI_API_KEY -u CODEX_API_KEY -u AZURE_OPENAI_API_KEY \
  STUDY_DATA_DIR="$PWD/sample_data" \
  STUDY_STATE_DIR="$PWD/.study-runtime/startup-smoke-state" \
  STUDY_CACHE_DIR="$PWD/.study-runtime/startup-smoke-cache" \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/streamlit run app.py --server.address 127.0.0.1 \
  --server.port 8517 --server.headless true --browser.gatherUsageStats false
```

本番の `src/`、`app.py`、`main.py` をAST/importとテキスト検索で監査した。OpenAI SDK、Chat Completions/Responses/Embeddingの直接呼出し、動的import/HTTP直呼び、APIキーUIはない。subprocessを直接使う本番moduleは `codex_provider.py` のみ。`uv.lock` にOpenAI SDKはない。`scripts/probe_codex.py` のloopback HTTP receiverは試験専用で、本番fallbackの経路を持たない。

### 静的検証

```sh
.venv/bin/ruff check .
.venv/bin/mypy src app.py main.py scripts
.venv/bin/python verify_score.py
git diff --check
```

すべて成功。mypyは34 source files。Easy70 / Normal80 / Hard90点を確認。

### 調査中の失敗と修正

UIで間欠的に `invalid_result` となる不具合を再現し、原例外が教材revision変更検知であることを確認した。合成manifestの差分はNumPy版だけ `2.4.2`→`unavailable`。Streamlitのrerunが共有 `sys.path` を変更する間、Pythonのmetadata遅延走査がsite-packagesを見落としていた。実教材は変化していなかった。

実行ライブラリ版を構築時に固定し、metadata走査には検索パスの独立コピーを渡すよう修正した。合成reproと回帰テストに加え、修正後のUI6件を独立5processで実行して全30件成功。その後の上記全体suiteでもUI6件が成功した。

Providerのopt-in再実行では **36 passed / 1 failed**。子process回収テストの250ms期限がfake Pythonの起動より先に切れ、PID記録がまだないというテスト側の失敗を1件確認した。本番実装のtimeout判定は正しかった。fixtureの期限を2秒とし、fake本体の30秒待機・実PID記録・親と子の消滅assertは維持した。本番コードは変更せず、上記の **37 passed** を再確認した。最後の変更はこのテスト条件と文書だけで、機能sourceは150件成功の版と同一である。

### データと制約

すべてのテストは合成データで実施した。既存進捗の本移行は合成移行テスト成功後の運用操作として行い、移行前backup、元JSONのバイト不変、変換後の全値一致、SQLite snapshotを確認した。内容はログ/fixture/文書に出力していない。[MIGRATION.md](MIGRATION.md)参照。

画像PDFの実OCR精度、Linux、Windows、大規模教材の品質、実LLMは未検証。Windows実装、複雑なMermaid描画、SQLite→旧JSONの自動逆移行は未対応。実Codex有効化の残作業は[PROJECT_STATE.md](PROJECT_STATE.md)に記載した。
