# 再開用状態

確認日: 2026-09-19、macOS arm64 / Python 3.12.13。

## ソースと作業場所

- origin: `https://github.com/BelltreeTech/Study-with-AI`
- branch: `feat/codex-gpt6-medium-refactor`
- 開始SHA: `8cee252b629138ba5ce2cca677ba3cc3a0b987dc`
- 正規作業場所: `~/Developer/projects/Study-with-AI`
- `~/Developer` の分類を確認し、継続アプリ用 `projects/` を使用。同じoriginの既存cloneは見つからなかった。ユーザー表記 `~/Devepoler` は存在しなかった。
- mainへの直接変更、push、merge、履歴書換えは行っていない。終了SHAはこの文書を含むローカルcommitの `git rev-parse HEAD` と完了報告で確認できる。

## 完了した実装

Streamlitの5画面、共通Service、公式Codex CLI Provider、型付き出力/採点、ローカルE5/BM25、PDF/OCR、永続ジョブ、キャンセル/timeout/利用枠エラー、科目/セッション/講義単位の履歴、SQLite進捗移行を実装した。詳細は[機能対応表](FEATURE_INVENTORY.md)と[設計](ARCHITECTURE.md)。APIキー入力とOpenAI SDK/直接生成/Embedding API経路は除去した。

既存進捗はGit外へbackupした上で、元JSONを保持してSQLiteへ本移行した。全値一致と元JSONの不変を確認した。追跡解除はindexからだけ行い、作業ツリーの個人ファイルとGitの過去履歴を保持している。テストは合成データ専用である。

取得済みローカルE5モデル、合成PDF、テストruntimeはignoredディレクトリ内にある。本人の教材をモデル評価に使っていない。サンプル生成script、モデル取得script、lockfileをcommit対象に含めた。

## 実生成を止める条件

standalone Codex CLI 0.152.1、ChatGPT認証を確認した。指定は `gpt-6-astra` / `medium`。実生成は **0回**。

1. 実機model catalogに指定IDとmedium対応を確認できない。
2. 正規auth homeのglobal AGENTSを個別要求から除外できない。共有設定やauthを移動・上書きして回避しない。
3. 組込みOpenAI providerの内部retryを0に制限できたことを確認できない。

synthetic HOME + localhost probeは提供tool catalogが空であること、設定・skills・hooksの振舞いを確認する試験であり、実LLM成功とは異なる。[境界調査](CODEX_BOUNDARY.md)に公式資料と実測を記載した。本番gateをmockテストのように迂回する設定はない。

次に実生成を有効化する作業では、公式CLIの正式なモデル/設定/認証契約を再確認し、上記3条件と管理者設定を再監査する。モデル名の推測、無断fallback、API課金、認証コピー、global AGENTS削除では進めない。条件を満たせてから、既存ChatGPT認証で小さな合成学習E2Eだけをopt-in実行し、回数と結果を追記する。

## 検証と再開

[TEST_REPORT.md](TEST_REPORT.md)が実行コマンド・pass/skip・制約の正本。再開時は `git status --short` と差分、CLI版、lockfile、関連sourceの変更有無を先に確認する。同じ版で済んだ調査を無理由に繰り返さない。新しいCLIや依存を導入した場合は境界・model・cache契約が変わるため再検証する。

通常の起動/停止と分離したデモは[README](../README.md)、バックアップ/rollbackは[MIGRATION](MIGRATION.md)。今回のブラウザsmokeは合成用ポート8517で実施し、Ctrl+Cで正常終了させた。日常利用のサーバーは起動したままにしていない。

## 未検証・未対応

- 実GPT-6生成、回答/講義/対話/出題/採点の内容品質、実アカウントの利用枠超過。
- 大規模・本人教材の検索品質、実画像PDFのOCR精度。実E5評価は小さな合成4問のみ。
- Linuxは未検証。WindowsはPOSIX flock/process group/dirfdのため未対応。
- 任意の複雑なMermaid図は描画せずcode表示。SQLiteから旧JSONへの自動逆移行は未実装。
- 別stateディレクトリのアプリ間で同時生成数を共有しない。資料ファイルとSQLiteを跨ぐ完全なtransactionはなく、最後の版チェック直後に外部編集される小さな競合余地がある。
