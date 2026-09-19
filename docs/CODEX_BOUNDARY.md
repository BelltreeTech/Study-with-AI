# Codex CLI の実行境界と確認結果

確認日: 2026-09-19、macOS arm64。実生成は **0 回**。公式 CLI のローカル mock 接続試験は、実生成の成功とは区別する。

## 確認した実機

| 項目 | 実測 |
| --- | --- |
| `command -v codex` | `/opt/homebrew/bin/codex` |
| 実体 | `/opt/homebrew/Caskroom/codex/0.152.1/bin/codex` |
| `codex --version` | `codex-cli 0.152.1` |
| `codex login status` | `Logged in using ChatGPT` |
| 要求モデル | `gpt-6-astra` |
| 要求推論強度 | `model_reasoning_effort="medium"` |
| `codex debug models` | この版・既存環境の一覧に `gpt-6-astra` がない |
| `codex debug models --bundled` | 同梱一覧にも `gpt-6-astra` がない |
| 組み込み OpenAI provider の内部 retry | 設定で 0 にできることを未確認。`model_providers.openai.*` は予約済み ID として CLI が拒否 |
| 通常配置の公式アプリ同梱 CLI | `/Applications/Codex.app` は存在しなかったため、同梱 CLI の比較対象なし |

[公式モデル資料](https://learn.chatgpt.com/docs/models)は `codex -m gpt-6-astra` を掲載している。[公式 GPT-6 Astra 資料](https://developers.openai.com/api/docs/models/gpt-6-astra)は medium 対応を示す。これはこの端末・アカウントでの利用成功を証明しない。実機 catalog にない状態を、他モデルへの置換や fallback metadata の容認で成功扱いしない。

アプリで現在の会話に利用できるモデル一覧と、standalone CLI のモデル一覧を同一視しない。追加の読み取り専用確認では通常配置の `/Applications/Codex.app` 自体が存在せず、その `Contents/Resources` 内の公式同梱 CLI を比較することはできなかった。別アプリの内部やユーザーディレクトリを広範囲には探索せず、実行パスの自動切替やバイナリ更新も行っていない。

## 実行構成

`CodexProvider.generate(prompt, schema, cancel_event)` だけが本番の生成子プロセスを扱う。UI から任意 CLI 引数・実行ファイル・コマンドを受け取らない。`CodexSettings` の model と effort は上記値以外を拒否する。

- `subprocess.Popen` は引数配列、`shell=False`、stdin 入力、独立 process group を使用する。
- 要求ごとに空の一時作業ディレクトリを作り、アプリ所有の出力 schema だけを書く。教材や答案をファイルに保存しない。
- `--ignore-user-config --ephemeral --strict-config --skip-git-repo-check --sandbox read-only --json --output-schema` を使用する。`--ignore-rules`、sandbox 迂回、共有設定の書換えは使用しない。
- `forced_login_method="chatgpt"` を要求する。環境変数は allowlist で組み直し、API キー、endpoint override、proxy、親タスク設定を子へ引き継がない。認証ファイルをアプリが開くことはない。
- shell/exec、apps、plugins、hooks、browser/computer use、image generation、multi-agent、file/image viewing、code mode、skill discovery、tool suggestions 等を個別に無効化する。web search も disabled とする。
- ツールがないことを権限境界とし、教材/答案内の命令を無視する developer 指示も加える。プロンプトだけを防御と説明しない。
- 生成と事前診断の両方で共通 collector が stdout/stderr を並行に読み、合計バイト数を制限する。診断全体に 1 つの deadline を設け、診断中も job cancel を受け付け、その診断の子プロセス群を停止する。JSONL と最終回答 JSON は別に検証し、完了イベントと最終回答の両方がなければ結果を拒否する。
- timeout/cancel はその要求の process group だけを停止・回収する。ジョブ管理の global lock FD があれば子へ継承し、親の異常終了後も子が終了するまでロックを保持する。
- 認証、モデル、利用枠、通信、非ゼロ終了、不完全出力、schema 違反を別の安全な日本語エラーにする。raw 出力や reasoning は UI/ログへ公開しない。アプリ自身は自動再試行しない。CLI 内部の再試行を止められたことが確認できない版は、生成前の診断で停止する。

[公式設定資料](https://learn.chatgpt.com/docs/config-file/config-reference)には `forced_login_method`、`web_search`、`features.shell_tool`、`project_doc_max_bytes` 等が記載されている。実際に存在する引数は installed CLI の help でも確認した。[認証資料](https://learn.chatgpt.com/docs/auth)に沿い、認証・更新は CLI に任せる。

## 再現可能なローカル境界試験

```sh
uv run python scripts/probe_codex.py
uv run python scripts/probe_codex.py --config-variants
uv run python scripts/probe_codex.py --diagnostics
STUDY_RUN_CODEX_BOUNDARY_PROBE=1 uv run pytest tests/test_provider.py -q
```

最初の 2 コマンドは、空の一時 HOME / CODEX_HOME と合成マーカーを使用する。loopback に mock HTTP receiver を立て、CLI からの入力を検査して必ずエラーを返す。実モデル・実 API への転送、資格情報読取り、認証ヘッダー送信はない。アプリ本番からこの receiver を使う経路はない。`--diagnostics` は公式 CLI の版・help・login status・model catalog だけを読み、生成しない。pytest の最終コマンドは通常の fake CLI 回帰テストに、この installed CLI / localhost probe を加える opt-in 実行である。

実測:

| 設定 | 提供ツール | global AGENTS | project AGENTS / user config / skills | hooks |
| --- | --- | --- | --- | --- |
| 本実装の境界設定 | `[]` | **混入する** | 混入しない | 未起動 |
| 上記 + `instructions=""` | `[]` | **混入する** | 混入しない | 未起動 |
| 上記 + `user_instructions=""` | config エラー | 未実行 | 未実行 | 未起動 |
| 上記 + `base_instructions=""` | config エラー | 未実行 | 未実行 | 未起動 |
| 上記 + `model_providers.openai.request_max_retries=0` / `stream_max_retries=0` | config エラー（組み込み provider ID の上書き禁止） | 未実行 | 未実行 | 未起動 |

要求 payload は `model: gpt-6-astra`、`reasoning.effort: medium`。`--ignore-user-config` は `$CODEX_HOME/config.toml` の除外であり、`$CODEX_HOME/AGENTS.md` の除外ではなかった。`project_doc_max_bytes=0` も global AGENTS を止めない。`user_instructions` と `base_instructions` はこの CLI では未知の設定。`--no-project-doc` 相当は help / 公開 schema で確認できなかった。`skip_host_skill_discovery` は under-development feature であり、版変更後に再監査が必要。

## 現在の停止条件と残る制約

この端末には既存の global AGENTS がある。認証保存先と共有設定を保護しながらその注入を正式な CLI 設定で遮断する方法を確認できなかったため、Provider は **安全側で実生成を停止** する。global AGENTS を削除・上書きしたり、auth を別 home へコピーしたり、偽の設定を使って進めることはしない。モデル catalog 未掲載も独立した停止条件である。

さらに [公式 config schema](https://learn.chatgpt.com/docs/config-schema.json) には provider ごとの `request_max_retries` / `stream_max_retries` があるが、この CLI は `openai` の組み込み ID 自体を上書き禁止として拒否する。`features.unbounded_connection_retries=false` だけでは有限回の内部 retry がないことを証明できない。したがって `retry_control_verified=false` を追加の停止条件とする。不正な設定の単純追加や、ChatGPT 経路の保持を確認できない custom provider alias への変更は採用しない。

今後、要求モデルが CLI の正式な一覧で確認でき、global instruction の個別隔離、空の tool catalog、内部再試行 0 のすべてを再監査できた版で、版制約・境界 probe・回帰テストを更新する必要がある。利用者が今すぐログアウト・ログインをやり直して直ると案内しない。CLI バイナリや共通設定を本改修が更新することもない。

管理者設定ディレクトリが存在する場合も、必須ポリシーを保った追加監査が済むまで停止する。この adapter は任意の OS / CLI 版に対する隔離保証ではない。POSIX process group は macOS でテスト済み、Windows は未対応。

ローカル検索・書庫・履歴と mock による学習フローはこの制約から独立する。API キー不要であることと完全オフラインであることは異なり、将来有効化された生成は Codex 経由で入力を送信し、ChatGPT 契約の利用枠を消費する。

## Provider 回帰結果

2026-09-19 の macOS で `STUDY_RUN_CODEX_BOUNDARY_PROBE=1 uv run pytest tests/test_provider.py -q` は **37 passed**。この内 installed CLI の 1 テストも loopback / 合成 HOME による検査であり、実生成ではない。通常実行は **36 テスト + installed CLI probe の 1 skip** となる。`ruff check src/codex_provider.py scripts/probe_codex.py tests/test_provider.py` と `mypy src/codex_provider.py scripts/probe_codex.py` も成功。

追加の診断回帰では、巨大 stderr の上限、診断中 cancel、診断 timeout の子・孤児子プロセス回収、4 診断で共有する単一 deadline、内部 retry 制御が未確認なら `ready=true` にならないことを検査した。fake CLI fixture だけが retry audit gate を monkeypatch しており、本番に gate を外す UI・環境変数・設定項目は存在しない。

最終統合後の再実行は **37 passed in 34.83s**。直前にはfixtureの250ms期限がPythonの起動前に切れる失敗を1件確認したため、子process回収試験の期限を2秒へ変更した。fakeは30秒待機し、実際の親・子PIDの消滅assertを維持している。本番Providerのtimeout設定や停止処理は変更していない。失敗と再検証を[TEST_REPORT.md](TEST_REPORT.md)に区別して記録した。
