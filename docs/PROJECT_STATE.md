# 再開用状態

## 2026-09-20 読書・復習導線の改善

講義の節選択・前後移動・読む位置の保存、練習の復習候補フィルター、最新フィードバックの表示と教材根拠を追加。全体534 passed / 2 skipped、Ruff/Mypy成功。実生成・Reset・本人データ利用なし。既存branchにローカルcommitし、pushしない。

## 2026-09-20 追加改善

練習セット成功時のarchiveをtransaction化し、最新セット表示・選択と下書きの維持・ヒントを閉じてやり直す動作を修正。完了済み講義の未反映は追加生成なしと表示。最終532 passed / 2 skipped、Ruff/Mypy成功。実Codex生成・Reset消費・本人データによる試験なし。詳細はTEST_REPORT冒頭。

## 2026-09-20 更新: 講義と練習の分離

- 作業先・branch維持。変更前HEAD `25292fa7464524aa36c9d28f685409243b2fcf71`。
- 日本語DOTラベル修正、lecture_input/legacy_total、lecture_plan＋最大8節のbatch/途中保存/明示再開、講義版保存、独立3問練習・答案feedbackを実装。
- 通常527 passed / 2 skipped、Ruff・Mypy45files・採点閾値・diff成功。実ブラウザの日本語図、HTML仕様書の表示・検索を確認。
- 実生成0、Reset0。既存8ジョブledgerを保持。Provider、認証、model/effort、実行境界、Embedding、DBschemaを変更しない。
- 新方式の実Codex出力品質は未検証。再開の手順と制約は[学習仕様](LEARNING_DESIGN.md)、証拠は[TEST_REPORT](TEST_REPORT.md)。
- 本人教材・進捗を試験に使っていない。合成試験はtmpおよび`.study-runtime/lecture-ui-check`。HTML変更前コピーは`.study-runtime/specification/SYSTEM_SPECIFICATION.before-lecture-v4.html`。

以下は以前の状態記録。

確認日: 2026-09-19、macOS arm64 / Python 3.12.13 / Streamlit 1.54.0。

## 作業場所と履歴

- 正規checkout: `/Users/shinrisuzuki/Developer/projects/Study-with-AI`
- origin: `git@github.com:BelltreeTech/Study-with-AI.git`
- branch: `feat/codex-gpt6-medium-refactor`
- main: `8cee252b629138ba5ce2cca677ba3cc3a0b987dc`（変更なし）
- 第1段階完了: `ceaaf865cdbaefc125561ca21f14eaa0ef850c98`
- 第2段階完了・今回の開始HEAD: `1a6aaafabf18aa82c3efe917851a5150627807c0`
- 今回の終了SHAは自己参照を避け、`git log -1 --format="%H %s"`と完了報告で確認する。

同じcheckoutとブランチを維持した。再clone、SQLite再移行、main変更、push、merge、履歴書換えはしていない。最初の配置確認では`~/Developer`の`projects/`分類を採用し、`~/Devepoler`は存在しなかった。本人の教材・成績・進捗・会話は検証に使っていない。旧進捗の元JSON、以前のbackup、SQLite移行記録は保持している。[MIGRATION](MIGRATION.md)参照。

## 学習体験の現在地

5画面は「今日の学び」「内容を相談」「テスト・復習」「コース・授業」「教材ライブラリ」の表示名で維持する。PDF登録からコース作成へ、ホームから続きの章・復習へ進む導線を追加した。目標、前提知識、学び方、たとえ、15/25/45/60分の学習単位を科目別に保存し、新コースへ固定する。例題→ヒント付き練習→自力確認と、誤解・たとえの限界・復習を共通の生成方針に組み込んだ。

質問と答案の下書き、以前の答案、科目・学習セッション別の履歴を復元できる。試験の切替は別タブの新しい結果を消さないatomicな操作とした。生成は明示操作で開始し、完了は2秒間隔のfragmentで自動反映する。結果receiptと進捗eventにより生成・加点を繰り返さない。

カリキュラムと明示的な概要相談ではPDF間・ページ間に分散した代表抜粋を使う。長い保存講義は本文・一般的補足の原文を保持し、相談・出題には両fieldから冒頭・末尾・関連・分散した節を選んだ合計6000字以内のcontextを送る。補足は教材根拠に昇格させず、新しい会話では補足の問いも次ターンへ引き継ぐ。全ページ・全概念の網羅は保証せず、範囲metadataを表示する。検索・EmbeddingはローカルE5/BM25で、通常操作によるモデル取得や商用Embedding APIはない。

詳細は[設計](ARCHITECTURE.md)、[機能対応表](FEATURE_INVENTORY.md)、[検索](LOCAL_RETRIEVAL.md)。新しいUIフレームワーク、外部SaaS、MCP生成基盤は追加していない。

## Codexと旧停止理由

専用公式CLIは **0.155.1**、実行ファイルは `~/.local/share/study-with-ai/tools/codex/0.155.1/vendor/aarch64-apple-darwin/bin/codex`。専用homeは `~/.local/share/study-with-ai/codex-home`、本人所有0700・file auth store。本人が公式ブラウザログインを完了した。実測診断は `auth=chatgpt` / `model_status=listed` / `model_available=true` / `boundary_verified=true` / `ready=true`、指定値は **gpt-6-astra / medium**。service tierは既定値。モデル一覧、要求設定、実生成、サービス側のモデル同一性の証明は区別する。

旧3停止理由は、①新版の正式catalogで掲載確認、②専用homeの公式独立ログインと隔離試験、③有限内部retryを許容する仕様と総timeout/cancelの維持、により対応した。旧版の失敗は[実行境界](CODEX_BOUNDARY.md)と[検証報告](TEST_REPORT.md)に履歴として残す。

第3段階で見つかったCLI警告の誤判定と送信Schema互換性を修正した。正確なCode Mode停止警告だけを許容し、hostやtoolsを有効にしない。送信用Schemaのコピーを対応subsetにし、返ったJSONは元の厳密なSchemaと業務規則に照合する。モデル・effort・APIへのfallbackはない。アプリ自動再生成0、CLIの無制限retry=false、180秒timeout、同時1ジョブ、process group停止を維持する。

## 検証結果と実生成の保存先

最新の件数・成功した操作・失敗履歴・品質点検・未検証事項は[TEST_REPORT](TEST_REPORT.md)を正本とする。通常suiteは合成PDF/fake CLI/Providerのみ。実CLI境界probeはlocalhostのみ、実E5は通信禁止下で実施し、実Codex要求と分けて報告する。

実生成harnessは `.study-runtime/phase2-live` の合成教材・専用DB・永続ledgerを使う。過去の失敗も予算に含め、累計8ジョブを超えない。既知の2probe失敗と1回答のSchema拒否を成功に書き換えず、残る5件でコース部分を優先して検証する明示modeを設けた。完全な7段階の技術完了と、コース部分の完了は別指標。実測は5件のコース操作すべて成功、84点で合格・章完了・50EXP。NoCalls Providerで再開し、生成0・加点0・8ジョブ不変を確認した。累計8件の検証枠は使用済みなので追加生成しない。直接RAG回答と最小probeの実検証は未完了のまま。実内容の7項目を照合したが、総合品質指標は未検証項目を含むため未承認とする。

`report.json`、`results/`、構造だけの `execution/`、`manual-review.json`はignored領域にある。認証・実行ログ本文・本人データ・binary・モデルをGitへ含めない。ledgerを消して予算を復活させない。完了結果の再表示/復元は新しい生成を行わない。

## 起動・診断・停止

```sh
cd ~/Developer/projects/Study-with-AI
uv run --frozen python scripts/codex_runtime.py --diagnose
uv run --frozen --extra semantic streamlit run app.py --server.address 127.0.0.1
```

ブラウザは `http://127.0.0.1:8501`。本人のログインは完了済みなので再ログイン不要。失効時だけ `uv run --frozen python scripts/codex_runtime.py --login-command` で専用homeの公式手順を表示し、本人がログインする。共有authをコピーしない。

停止は起動ターミナルで **Ctrl+C**。画面のキャンセルは対象ジョブだけ、「生成ジョブを停止して保存」はアプリ所有ジョブを停止する。他のCodexプロセスを一括停止しない。検証用8517/8531のサーバーと作成したブラウザタブは回収済み。両portのlistenerなしを確認した。

APIキーなしの合成デモとローカル検索コマンドは[README](../README.md)。通常テストは `.venv/bin/python -m pytest -q`、静的検証は `.venv/bin/ruff check .`、`.venv/bin/mypy src app.py main.py scripts`。再開時はGit差分とCLI版を確認し、変わっていない失敗調査を繰り返さない。

## 残る制約

- 実確認は小さな合成教材に限定。大規模PDF、本人教材、画像PDFのOCR精度、教育効果の長期評価は未検証。
- 選択抜粋は全ページ・全講義を網羅しない。BM25では教材と言語・語彙が違う質問に弱い。会話などを含む最終promptは64KiBを超えると拒否する。
- CLI内部HTTP試行数・サービス側推論数・利用枠消費量は不明。キャンセルがサーバー側処理の無消費を保証するわけではない。Resetを自動消費しない。
- Linux未検証、WindowsはPOSIX lock/process groupのため未対応。専用installerはmacOS arm64用。
- 複雑なMermaidはコード表示。SQLiteから旧JSONへの自動逆移行なし。別state保存先間で生成枠は共有しない。資料とDBを跨ぐ完全transactionはない。
