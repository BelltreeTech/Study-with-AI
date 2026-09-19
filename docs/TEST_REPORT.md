# 検証報告

確認日: 2026-09-19。環境: macOS arm64、Python 3.12.13、uv、Streamlit 1.54.0、pytest 8.4.2。依存の正本は `uv.lock`。mainへの変更・push・mergeなし。テスト用保存先は一時ディレクトリまたは `.study-runtime/`、教材は自作PDFのみ。

## 通常suite

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

## 実ローカルEmbedding

```sh
STUDY_TEST_LOCAL_EMBEDDING=1 .venv/bin/python -m pytest tests/test_retrieval_semantic.py -q
```

**1 passed, 5 warnings in 2.45s**。固定revisionの `intfloat/multilingual-e5-small` をCPUで実ロード。すべてのsocket接続を禁止し、接続呼出0回をassertした。384次元・L2正規化、日英/言語横断の合成4質問で期待教材4/4 top1。これは小さな動作評価であり、大規模教材の品質保証ではない。

初回モデル取得は明示scriptで実施した。通常のアプリ/検索でモデルを自動ダウンロードしない。意味検索モデルが意図的にない別保存先でもCLI `--search-only` がBM25で検索でき、期待する合成PDFの1ページ目を先頭取得した。

## installed CLIと実生成の区別

実測CLI: `/opt/homebrew/bin/codex` → 0.152.1、認証: ChatGPT。指定model `gpt-6-astra` / effort `medium`。本物のモデルへの生成要求は **0回**。版・help・login status・model catalogの診断、および合成HOMEとlocalhost receiverへのprobeだけを実施した。

```sh
STUDY_RUN_CODEX_BOUNDARY_PROBE=1 .venv/bin/python -m pytest tests/test_provider.py -q
```

最終再実行は **37 passed in 34.83s**。このopt-inは空tool catalog、global/project AGENTS、config、skills、hooks、モデル/effort payloadの検査。authは用いず、外部モデルへ転送しない。36件の通常fake試験を含むため、上記150件へ37件を単純加算しない。通常skipした2件は、この実行と実E5試験でそれぞれ成功した。詳細は[CODEX_BOUNDARY.md](CODEX_BOUNDARY.md)を参照。

実機で指定modelが一覧にないこと、global AGENTSの個別隔離ができないこと、組込みprovider retry制限が未確認であることから実生成を停止する。実GPT-6の回答・講義・対話・問題・採点E2E、内容品質、実利用枠超過は **未検証**。mockのquotaエラー処理を実アカウントの枠超過試験とは扱わない。

## 起動・停止・API経路

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

## 静的検証

```sh
.venv/bin/ruff check .
.venv/bin/mypy src app.py main.py scripts
.venv/bin/python verify_score.py
git diff --check
```

すべて成功。mypyは34 source files。Easy70 / Normal80 / Hard90点を確認。

## 調査中の失敗と修正

UIで間欠的に `invalid_result` となる不具合を再現し、原例外が教材revision変更検知であることを確認した。合成manifestの差分はNumPy版だけ `2.4.2`→`unavailable`。Streamlitのrerunが共有 `sys.path` を変更する間、Pythonのmetadata遅延走査がsite-packagesを見落としていた。実教材は変化していなかった。

実行ライブラリ版を構築時に固定し、metadata走査には検索パスの独立コピーを渡すよう修正した。合成reproと回帰テストに加え、修正後のUI6件を独立5processで実行して全30件成功。その後の上記全体suiteでもUI6件が成功した。

Providerのopt-in再実行では **36 passed / 1 failed**。子process回収テストの250ms期限がfake Pythonの起動より先に切れ、PID記録がまだないというテスト側の失敗を1件確認した。本番実装のtimeout判定は正しかった。fixtureの期限を2秒とし、fake本体の30秒待機・実PID記録・親と子の消滅assertは維持した。本番コードは変更せず、上記の **37 passed** を再確認した。最後の変更はこのテスト条件と文書だけで、機能sourceは150件成功の版と同一である。

## データと制約

すべてのテストは合成データで実施した。既存進捗の本移行は合成移行テスト成功後の運用操作として行い、移行前backup、元JSONのバイト不変、変換後の全値一致、SQLite snapshotを確認した。内容はログ/fixture/文書に出力していない。[MIGRATION.md](MIGRATION.md)参照。

画像PDFの実OCR精度、Linux、Windows、大規模教材の品質、実LLMは未検証。Windows実装、複雑なMermaid描画、SQLite→旧JSONの自動逆移行は未対応。実Codex有効化の残作業は[PROJECT_STATE.md](PROJECT_STATE.md)に記載した。
