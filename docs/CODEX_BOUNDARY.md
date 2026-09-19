# Codex CLI の実行境界と確認結果

確認日: 2026-09-19、macOS arm64。合成HOME/localhostの境界試験、正式な実効設定診断、本人アカウントでの実生成を区別する。最新の実生成件数・品質・回帰結果は[TEST_REPORT](TEST_REPORT.md)を正本とする。第1・第2段階終了時の実生成は0件で、第3段階で本人が専用homeの公式ログインを完了した。

## 現在の状態

公式配布の **Codex CLI 0.155.1** をアプリ専用領域へ並行導入済み。本人による専用homeのChatGPTログイン後、`auth: chatgpt`、`model_status: listed`、`model_available: true`、`boundary_verified: true`、`ready: true`を確認した。共有Codexの設定・認証はコピーせず、管理者ポリシー・実行境界は維持している。

第3段階では最小probeのCLI警告を誤って失敗にする不具合を修正した。2件目の実測は終了0・stderr0・agent_message1・turn.completed1だが、当時は最終JSONを保存する前に拒否したため成功に変更しない。警告2件のhashを公式ソースから再構成して完全一致させ、原因を特定した。1件目はraw情報がなく原因未確定である。

| 項目 | 現在の採用値・確認範囲 |
| --- | --- |
| 専用CLI | `~/.local/share/study-with-ai/tools/codex/0.155.1/vendor/aarch64-apple-darwin/bin/codex` |
| 版と配布物 | `codex-cli 0.155.1`。公式npm配布の固定integrityとbinary SHA-256を照合 |
| 専用CODEX_HOME | `~/.local/share/study-with-ai/codex-home`、本人所有・0700・所有記録付き |
| provider / login / auth store | 組み込み `openai` / `chatgpt` / `file` |
| 要求モデル / effort | `gpt-6-astra` / `medium` に固定 |
| モデルの証拠 | 0.155.1の同梱catalog、および公式app-server `model/list`。掲載はアカウントの利用資格・実生成成功の証明ではない |
| service tier | Fastを指定しない。実効設定は既定値、mock送信payloadに `service_tier` なし |
| ツール・設定境界 | 合成localhost試験の `tools=[]`、共有/専用/project sentinelの混入・実行副作用なし、実効設定照合を確認 |
| 現在の認証 | 本人が専用homeの公式ChatGPTログインを完了。共有0.152.1の認証をコピー・削除・流用していない |
| 再試行 | アプリの自動再試行0回、CLI内部は有限retryを許容。無制限接続retryをfalseに固定 |

版・hash・公式資料・合成sentinelの詳細は [PHASE2_CLI_AUDIT.md](PHASE2_CLI_AUDIT.md)、固定版の公式ソースによる認証・retry・管理者ポリシー監査は [PHASE2_AUTH_RETRY_AUDIT.md](PHASE2_AUTH_RETRY_AUDIT.md) を参照する。共有 `/opt/homebrew/bin/codex` は0.152.1のまま。PATH、Homebrew、Codexアプリ、共有設定には変更を加えていない。

第1段階の3つの停止理由は、新版のcatalog確認、専用homeの独立認証方式、ユーザーの第2段階指示による有限内部retryの許容によって再評価した。旧版の失敗を新版の失敗として流用せず、現在の実装には「内部retryを0にできなければ停止」とする条件を設けない。第1段階の実測はこの文書の後半に履歴として保持する。

## 現在の実行構成

`CodexProvider` が本番の公式CLI呼出しを所有する。通常の `generate(prompt, schema, cancel_event)` と、合成harnessの明示的な最小probeも同じ境界を通る。UIに任意の実行ファイル・CLI引数・コマンド・endpoint入力はない。モデルとeffortの正本は `src/config.py`、専用パスと制限は `CodexSettings`。

- 版と固定binary hash、専用homeの所有・権限・symlink・追加AGENTS/configを検査する。専用homeの準備は明示的setupだけで行い、既存の別用途ディレクトリを転用しない。
- CLIの login status、catalog、実効設定診断、生成で同じバイナリ・home・file auth store・ChatGPT方式を指定する。アプリが認証ファイルの内容を読むことはなく、公式CLIが認証と更新を行う。
- 子プロセス環境はallowlistで再構成し、APIキー、endpoint override、proxy、親Codex設定を引き継がない。`CODEX_HOME`は子の環境だけへ渡す。
- 生成は argv とstdin、`shell=False`、独立process groupを使う。要求ごとの空の一時ディレクトリにはアプリ所有schemaだけを置く。教材・答案はファイルへ保存しない。
- `--ignore-user-config --ephemeral --strict-config --skip-git-repo-check --sandbox read-only --json --output-schema` を使用する。`read-only`だけで情報アクセスを防げるとは説明しない。
- shell、file/image viewing、web、MCP、plugins、hooks、skills discovery、browser/computer use、multi-agent、image generation、code mode等を無効にする。教材・答案の命令を実行できるツールを渡さない。developer指示でもデータ内の命令を無視するよう要求するが、プロンプトだけを安全境界にはしない。
- 公式app-serverの読み取り専用 `config/read`、`configRequirements/read`、`model/list` を使い、実際に解決されたモデル・effort・認証保存方式・sandbox・機能フラグ・MCP・指示・endpoint・通常service tierを照合する。診断は `thread/start` / `turn/start` を呼ばず、文章生成を行わない。生成経路そのものは `codex exec` のままである。
- 管理者/組織の強制設定が存在すれば、保持したまま追加監査が必要として停止する。強制ポリシーを無視するflagは使わない。本人のログイン後には同じ診断を再実行し、認証後に現れた要件も照合する。
- stdout/stderrを並行に読み、合計2MiBまでに制限する。診断全体15秒、生成180秒のdeadlineとキャンセルを設け、所有process groupだけを終了・回収する。ジョブの排他lock FDを継承して、親が異常終了しても子の終了まで生成枠を保持する。
- JSONL完了イベントと最終回答JSONの両方を要求し、schema/domain検証を行う。不完全出力・キャンセル・失敗を成功や採点結果に変換しない。raw診断出力・reasoning・認証内容をUIへ返さない。

通常生成には認証・モデル・境界の全確認を要求する。モデル一覧だけが未確認で、認証と境界を満たす場合は、本人がopt-inした合成harnessの指定モデルprobeだけを許可する。別モデルを推測して試さず、同じ実行環境でその明示要求が完了した事実と、サーバー側のモデル同一性の証明も区別する。現在はモデル掲載と専用認証を確認している。catalog未確認の例外を通常UIで無条件に使える設計にはしない。

## 0.155.1の警告と完了判定

固定公式source `be2951ea34f0d295ed0becf97079f92fa5f6950e` を照合した。`exec/src/event_processor_with_jsonl_output.rs` はWarning/ConfigWarning/DeprecationNotice/ModelReroutedを `item.type=error` に変換し、再接続通知の `will_retry` をJSONLへ保持しない。すべてのerrorを致命扱いする実装と、すべてのwarningを無視する実装のどちらも採用しない。

許容するのは既知のhost skill discovery通知、明示probe時の正確なmetadata不足通知、公式の有限 `Reconnecting... N/5 (...)` と同モデルのWebSockets→HTTPS通信方式変更通知、そして正確に一致するCode Mode停止通知だけである。認証・利用枠・モデル変更・tool・権限・4xx・未知通知・完了後の通信errorは拒否する。許容した通知があっても、CLI終了0、`turn.completed`、最終JSON/schema/domain成功のすべてが必要。

実行時の2警告を `json.dumps(event, sort_keys=True)` のbyte数/hashで照合した:

- host discovery: 366 bytes、SHA-256 `6d68f87ee8fdcfea68147f2c9cc7d06f634c6559219890013ea979068985e389`。公式 `codex-rs/features/src/lib.rs:1825` のfeature警告。
- disabled Code Mode host: 241 bytes、SHA-256 `a6392b61f32ef19e067f816cef3cd273733c79e3a8c292c93d43e5449b5109d1`。公式 `core/src/tools/code_mode/mod.rs` と `code-mode/src/remote_session.rs` の停止通知。通知に書かれたhost有効化・追加ツール導入は行わず、`code_mode=false` / `code_mode_host=false`を維持する。

Providerは終了コード・固定enumのevent件数・errorのbyte数/hash等だけをメモリへ記録する。実harnessはこの非機密metadataを専用ignored保存先へ記録し、raw stdout/stderr、reasoning、教材、認証本文を診断として保存しない。metadataだけでは捨てられた最終JSONのschema成功を後付け証明できない。

## 出力Schemaの送信形式とアプリの検証

実教材回答の最初の要求では、CLI終了1・HTTP 400・`Invalid schema`・`turn.failed`を非機密metadataで確認した。認証や利用枠の失敗とは区別する。元のサーバーエラー本文は保存していないため、拒否された単一keywordの実測までは断定しない。

アプリのSchemaには配列の`uniqueItems`があり、公式Structured Outputsのサポートする配列制約（`minItems`/`maxItems`）の範囲外だった。`codex_wire_schema`はCLIへ渡すコピーだけを対応subsetへ射影する。`uniqueItems`と、文字列の送信制約として保守的に省く`minLength`/`maxLength`は元のSchemaで引き続き検証し、アプリ契約を変更しない。数値範囲・配列件数・required・additionalProperties=falseは送信側にも維持する。最終JSONをProviderとServiceで元のSchemaへ照合し、重複ID・配点・文字数・引用などの不正は従来どおり拒否する。再生成、結果の自動修正、検査の省略はしない。

[公式Structured Outputsの対応Schema](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas)を形式仕様として参照した。アプリからAPIを直接呼ぶ経路やAPIキー認証を追加したものではない。

## 内部retryと利用枠

0.155.1の組み込みproviderはHTTP retry既定4回、stream retry既定5回を持つ。これらは個別loopの値であり、transport切替・認証回復もあるため、ジョブ全体のHTTP数・推論数・利用枠消費数へ単純換算しない。`features.unbounded_connection_retries=false`を明示し、実効設定でも確認する。アプリは失敗ジョブや子プロセスを自動再投入しない。利用枠エラーでは停止し、手動再実行に追加消費の可能性があることを示す。有限retry中でもアプリのdeadline/cancelを維持する。

この監査で実際のCLI内部送信回数やサービス側の推論回数は観測していない。実E2Eのレポートもこれらを `unknown` と記録する。詳しいエラー分類・回数のソース根拠は [認証・retry監査](PHASE2_AUTH_RETRY_AUDIT.md) に記載した。

## 再現と本人ログイン後の再開

```sh
uv run --frozen python scripts/setup_codex.py
uv run --frozen python scripts/codex_runtime.py --setup-home
uv run --frozen python scripts/codex_runtime.py --login-command
# 表示されたコマンドを本人が実行し、ブラウザで専用homeのChatGPTログインを完了する。
uv run --frozen python scripts/codex_runtime.py --diagnose
uv run --frozen python scripts/live_e2e.py --check-only
# 診断が通った後の明示実行。実生成と利用枠消費を伴う。
uv run --frozen --extra semantic python scripts/live_e2e.py --run --confirm-live
```

`--login-command`はコマンドを表示するだけで、本人のブラウザ操作を代行しない。既存authのコピー・共有側のlogout・APIキーへの変更は不要である。

合成harnessは通常probe/回答/curriculum/講義/対話/問題/採点の7段階を実施し、失敗も含む永続ledger上の累計8ジョブを上限とする。今回のprobe失敗2件と回答のSchema拒否1件は失敗のまま保持した。明示flagと修正根拠・正常catalog・保存した実行証拠を照合し、残り5件でカリキュラム・講義・対話・問題・採点を成功させた。累計8件で追加生成は終了し、直接RAG回答と最小probeは未検証のまま。コース部分の成功と全経路の完了を別指標として報告する。個人教材・進捗を使わず、成功済み結果の再表示・再開で生成や進捗加算を繰り返さない。JSON schema通過と教材への整合性は別に判定し、内容品質は根拠を伴う手動レビューが必要。実施済み結果と未検証範囲は最新の検証報告に記載する。

実生成なしで再現する境界試験:

```sh
uv run --frozen python scripts/probe_codex.py \
  --executable "$HOME/.local/share/study-with-ai/tools/codex/0.155.1/vendor/aarch64-apple-darwin/bin/codex"
STUDY_RUN_CODEX_BOUNDARY_PROBE=1 uv run --frozen pytest tests/test_provider.py -q
```

probeは実認証を持たない合成HOME、共有HOMEの外の専用CODEX_HOME、loopback receiverだけを使う。receiverはHTTP 400を返し、実サービスへ転送しない。新版のtool catalogは空、AGENTS/config/skills/plugin/historyのマーカーは混入せず、hooks/MCPの副作用も発生しなかった。これは任意の将来CLI版やOSへの保証ではない。バイナリ・設定・ポリシーの変更時は再監査が必要。最新の試験件数・失敗と修正・skipは [TEST_REPORT.md](TEST_REPORT.md) を正本とする。

## 第1段階の履歴（0.152.1、現在の停止条件ではない）

以下は開始commit `8cee252` から第1段階完了commit `ceaaf865` までに確認した当時の証拠である。当時の共有home・CLI・retry要件での停止判断と試験結果を保持する。「現在」「今後」等はその段階の時点を指す。第2段階の状態は上の節と第2段階監査文書を参照する。

### 確認した実機

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

### 実行構成

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

### 再現可能なローカル境界試験

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

### 第1段階の停止条件と残った制約

この端末には既存の global AGENTS がある。認証保存先と共有設定を保護しながらその注入を正式な CLI 設定で遮断する方法を確認できなかったため、Provider は **安全側で実生成を停止** する。global AGENTS を削除・上書きしたり、auth を別 home へコピーしたり、偽の設定を使って進めることはしない。モデル catalog 未掲載も独立した停止条件である。

さらに [公式 config schema](https://learn.chatgpt.com/docs/config-schema.json) には provider ごとの `request_max_retries` / `stream_max_retries` があるが、この CLI は `openai` の組み込み ID 自体を上書き禁止として拒否する。`features.unbounded_connection_retries=false` だけでは有限回の内部 retry がないことを証明できない。したがって `retry_control_verified=false` を追加の停止条件とする。不正な設定の単純追加や、ChatGPT 経路の保持を確認できない custom provider alias への変更は採用しない。

第1段階終了時には、要求モデルが CLI の正式な一覧で確認でき、global instruction の個別隔離、空の tool catalog、内部再試行 0 のすべてを再監査できた版で、版制約・境界 probe・回帰テストを更新する必要がある。利用者が今すぐログアウト・ログインをやり直して直ると案内しない。CLI バイナリや共通設定を本改修が更新することもない。

管理者設定ディレクトリが存在する場合も、必須ポリシーを保った追加監査が済むまで停止する。この adapter は任意の OS / CLI 版に対する隔離保証ではない。POSIX process group は macOS でテスト済み、Windows は未対応。

ローカル検索・書庫・履歴と mock による学習フローはこの制約から独立する。API キー不要であることと完全オフラインであることは異なり、将来有効化された生成は Codex 経由で入力を送信し、ChatGPT 契約の利用枠を消費する。

### 第1段階の Provider 回帰結果

2026-09-19 の macOS で `STUDY_RUN_CODEX_BOUNDARY_PROBE=1 uv run pytest tests/test_provider.py -q` は **37 passed**。この内 installed CLI の 1 テストも loopback / 合成 HOME による検査であり、実生成ではない。通常実行は **36 テスト + installed CLI probe の 1 skip** となる。`ruff check src/codex_provider.py scripts/probe_codex.py tests/test_provider.py` と `mypy src/codex_provider.py scripts/probe_codex.py` も成功。

追加の診断回帰では、巨大 stderr の上限、診断中 cancel、診断 timeout の子・孤児子プロセス回収、4 診断で共有する単一 deadline、内部 retry 制御が未確認なら `ready=true` にならないことを検査した。fake CLI fixture だけが retry audit gate を monkeypatch しており、本番に gate を外す UI・環境変数・設定項目は存在しない。

最終統合後の再実行は **37 passed in 34.83s**。直前にはfixtureの250ms期限がPythonの起動前に切れる失敗を1件確認したため、子process回収試験の期限を2秒へ変更した。fakeは30秒待機し、実際の親・子PIDの消滅assertを維持している。本番Providerのtimeout設定や停止処理は変更していない。失敗と再検証を[TEST_REPORT.md](TEST_REPORT.md)に区別して記録した。
