# 再開用状態

確認日: 2026-09-19、macOS arm64 / Python 3.12.13。

## ソースと作業場所

- origin: `https://github.com/BelltreeTech/Study-with-AI`
- branch: `feat/codex-gpt6-medium-refactor`
- 第1段階の開始SHA: `8cee252b629138ba5ce2cca677ba3cc3a0b987dc`
- 第2段階の開始SHA（第1段階完了commit）: `ceaaf865cdbaefc125561ca21f14eaa0ef850c98`
- 正規作業場所: `~/Developer/projects/Study-with-AI`
- `~/Developer` の分類を確認し、継続アプリ用 `projects/` を使用。同じoriginの既存cloneは見つからなかった。ユーザー表記 `~/Devepoler` は存在しなかった。
- mainへの直接変更、push、merge、履歴書換えは行っていない。終了SHAは自己参照する値を文書へ埋め込まず、`git log -1 --format="%H %s"` と完了報告で確認する。

## 完了した実装

Streamlitの5画面、共通Service、公式Codex CLI Provider、型付き出力/採点、ローカルE5/BM25、PDF/OCR、永続ジョブ、キャンセル/timeout/利用枠エラー、科目/セッション/講義単位の履歴、SQLite進捗移行を実装した。詳細は[機能対応表](FEATURE_INVENTORY.md)と[設計](ARCHITECTURE.md)。APIキー入力とOpenAI SDK/直接生成/Embedding API経路は除去した。

既存進捗はGit外へbackupした上で、元JSONを保持してSQLiteへ本移行した。全値一致と元JSONの不変を確認した。追跡解除はindexからだけ行い、作業ツリーの個人ファイルとGitの過去履歴を保持している。テストは合成データ専用である。

取得済みローカルE5モデル、合成PDF、テストruntimeはignoredディレクトリ内にある。本人の教材をモデル評価に使っていない。サンプル生成script、モデル取得script、lockfileをcommit対象に含めた。

## 第2段階で追加した実装と現在の停止理由

公式Codex CLI **0.155.1**を `~/.local/share/study-with-ai/tools/codex/0.155.1/vendor/aarch64-apple-darwin/bin/codex` へ並行導入した。公式npm配布の固定integrityとbinary hashを確認した。共有CLIは0.152.1のまま、Homebrew・Codexアプリ・PATH・共有設定を変更していない。再現用installerは `scripts/setup_codex.py`。

専用 `~/.local/share/study-with-ai/codex-home` を本人所有・0700・所有記録付きで準備した。同じhomeと `cli_auth_credentials_store="file"` / `forced_login_method="chatgpt"` を公式CLIのログイン、状態確認、モデル一覧、生成に指定する。共有authの読取り・コピー・logoutは行っていない。本人のブラウザログインはまだ完了していない。

実機診断の最新状態は **`model_status: listed`、`boundary_verified: true`、停止理由 `auth_required` のみ**。新CLIの `gpt-6-astra` / `medium` 掲載、実効設定と強制要件の読み取り専用検査、合成localhost probeの空tool catalogとsentinel隔離を確認した。モデル一覧の掲載は本人の利用資格や実生成成功の証明ではない。第1・第2段階とも実生成は **0回**。

第1段階の「旧catalog未掲載」「共有global AGENTS混入」「内部retryを0にできない」という3停止理由は、その当時の記録として [CODEX_BOUNDARY.md](CODEX_BOUNDARY.md) に保持した。第2段階では専用homeで共有設定から分離し、ユーザー指示に従って有限内部retryを許容する。アプリ自動再試行0回、無制限接続retry=false、deadline/cancel/出力上限/排他は維持する。サービス側の実推論数・利用枠消費数は不明で、1ジョブ1回とは説明しない。利用上限に達してもResetクレジットを自動消費しない（本人の追加指示）。

公式app-serverの `config/read` / `configRequirements/read` / `model/list` は生成前の診断に限る。生成は引き続き `codex exec`。MCP基盤や別UIフレームワークは追加していない。管理者/組織の強制設定は保持し、両立性を確認できなければ停止する。認証後も実効設定を再検査する。

合成専用 `scripts/live_e2e.py` を追加した。probe→回答→5章curriculum→1章の講義→対話→問題→部分誤答の採点という7ジョブを、永続ledgerで累計8ジョブ以内に制限する。本人の教材・進捗を使わず、再開時の生成重複と進捗二重加算を防ぐ。実行制御のmock試験と、実モデルの内容品質確認は区別する。現時点で実E2E・手動品質レビューは未実施。

## 本人ログイン後の再開手順

```sh
cd ~/Developer/projects/Study-with-AI
uv run --frozen python scripts/setup_codex.py
uv run --frozen python scripts/codex_runtime.py --setup-home
uv run --frozen python scripts/codex_runtime.py --login-command
# 表示されたコマンドを本人が実行し、公式ブラウザログインを完了する。
uv run --frozen python scripts/codex_runtime.py --diagnose
uv run --frozen python scripts/live_e2e.py --check-only
# 診断通過後の明示的な実生成。本人の利用枠を消費する。
uv run --frozen --extra semantic python scripts/live_e2e.py --run --confirm-live
```

専用CLIとhomeが既に正常ならsetupはその検証になる。`--login-command`はコマンド表示だけで、認証済みなら再ログインを要求しない。診断と `--check-only` は生成ジョブを開始しない。`auth_required`が残れば実行を続けない。

harnessのledger・合成教材・結果・進捗は `.study-runtime/phase2-live` に保存する。実生成後は `report.json` と `manual-review-template.json` を確認し、引用ページ・教材との整合・対話・出題・減点理由・再開を根拠付きでレビューして `manual-review.json` に記録する。JSONが正しいだけで品質を合格にしない。失敗の自動再試行はなく、必要な再実行は原因と修正根拠を明示し、永続予算の残り1件の範囲で行う。

## 検証と再開

[TEST_REPORT.md](TEST_REPORT.md)が実行コマンド・pass/skip・制約の正本。再開時は `git status --short` と差分、CLI版、lockfile、関連sourceの変更有無を先に確認する。同じ版で済んだ調査を無理由に繰り返さない。新しいCLIや依存を導入した場合は境界・model・cache契約が変わるため再検証する。

通常の起動/停止と分離したデモは[README](../README.md)、バックアップ/rollbackは[MIGRATION](MIGRATION.md)。第1段階のブラウザsmokeは合成用ポート8517で実施し、Ctrl+Cで正常終了させた。第2段階の最新検証はTEST_REPORTの記録を参照する。日常利用のサーバーは起動したままにしていない。

## 未検証・未対応

- 専用homeでの本人のChatGPTログイン、実GPT-6生成、実学習E2E、回答/講義/対話/出題/採点の内容品質、実アカウントの利用枠超過。
- CLI内部の実送信回数とサービス側の推論回数。レポートは不明とし、アプリジョブ数と混同しない。
- 大規模・本人教材の検索品質、実画像PDFのOCR精度。実E5評価は小さな合成4問のみ。
- Linuxは未検証。WindowsはPOSIX flock/process group/dirfdのため未対応。
- 任意の複雑なMermaid図は描画せずcode表示。SQLiteから旧JSONへの自動逆移行は未実装。
- 別stateディレクトリのアプリ間で同時生成数を共有しない。資料ファイルとSQLiteを跨ぐ完全なtransactionはなく、最後の版チェック直後に外部編集される小さな競合余地がある。
