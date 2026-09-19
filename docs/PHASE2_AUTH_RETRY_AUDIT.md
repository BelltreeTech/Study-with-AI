# Phase 2: Codex 0.155.1 の認証・内部再試行・管理者ポリシー監査

確認日: 2026-09-19。対象は OpenAI 公式 `openai/codex` の `rust-v0.155.1`。
この文書は公式ソースと公式資料に基づく監査であり、実アカウントの認証成功・モデル利用成功・実生成の証明ではない。
この監査ではユーザーの認証ファイルを読まず、トークンをコピーせず、login/logout を実行せず、共有設定も変更していない。

Phase 2 指示書の「有限の CLI 内部 retry は許可し、アプリ自身の自動再試行は 0 回」を適用する。
Phase 1 の「内部 retry を 0 にできなければ停止」は、このバージョンの採用判断には使用しない。

## ソースの同一性

- [公式 0.155.1 リリース][release]。
- [公式タグ参照][tag-ref] の annotated tag object は `4e21628f9ec9ee656650cd2b62ef92225725b5ac`。
- [タグオブジェクト][tag-object] が指す commit は `be2951ea34f0d295ed0becf97079f92fa5f6950e`。
- 下記ソースリンクはすべてこの commit を固定している。公式 GitHub API の同タグ source archive を一時ディレクトリに取得し、該当実装を読んだ。別バージョンの挙動から推定していない。
- 公開ドキュメントは更新されるため、設定の意味を補足する資料とし、回数・分岐の根拠は固定ソースとした。

## HTTP とストリームの有限再試行

| 層 | 0.155.1 の動作 | 実装根拠 |
| --- | --- | --- |
| 組み込み OpenAI provider の HTTP | `request_max_retries` の既定値は **4**。設定値の hard cap は **100**。実装は初回を含め `0..=max_attempts` なので、既定で **1 回の HTTP retry loop 当たり最大 5 回の送信試行** | [既定値・上限 L29–38][retry-defaults]、[有効値 L415–427][retry-effective]、[HTTP loop L80–106][http-loop] |
| HTTP の対象エラー | 5xx、transport timeout、connection、network error を再試行。HTTP 429 はこの層では再試行しない。他の HTTP 4xx もこの汎用 HTTP retry の対象外 | [provider retry policy L370–377][http-policy]、[判定 L21–35][http-predicate] |
| HTTP 待機 | 基本 200ms、指数 2 倍、約 0.9–1.1 倍の jitter。既定 4 retry の基準値は 200/400/800/1600ms。通信そのものの時間は別 | [policy][http-policy]、[backoff L39–47][http-backoff] |
| ストリーム再試行 | `stream_max_retries` の既定値は **5**、設定値 hard cap は **100**。sampling request ごとに retry state を作り、再試行可能エラーのみ共通 helper に渡す | [既定値・上限][retry-defaults]、[sampling loop L1560–1657][sampling-loop] |
| 接続の無制限再試行 | `features.unbounded_connection_retries` の標準値は **true**。有効時の対象 `ConnectionFailed` は通常の有限カウンターとは別に、5 秒から最大 60 秒間隔で繰り返す。アプリは必ず **false** を明示する | [feature L1236–1240][unbounded-default]、[別分岐 L65–90][stream-helper] |
| WebSocket → HTTPS | ストリーム予算を使い切ると、可能な場合に HTTPS transport へ一度切り替えて retry counter を 0 にする。その後も有限予算。これは同じモデルへの通信方式の変更 | [counter reset L92–107][stream-helper]、[一度だけ切替 L2014–2029][transport-switch] |
| ストリームの待機 | サーバーが指定した retry delay があればそれを使い、なければ 200ms から指数 2 倍 + jitter。retry delay の総時間を CLI の回数上限だけで短時間に制限できるとは限らない | [helper L109–143][stream-helper]、[backoff L6–7, L86–90][stream-backoff] |
| ストリーム idle timeout | 組み込み既定は **300,000ms**。これはアプリの合計 deadline とは別 | [既定値 L29][retry-defaults]、[有効値 L429–433][retry-effective] |
| 認証回復 | HTTP 401 の ChatGPT 認証回復は `Reload → RefreshToken → Done` の有限 state machine。再読込・更新を尽くした後の 401 はエラーとして上がる | [説明 L1856–1868][auth-recovery]、[状態遷移 L1983–2037][auth-recovery-steps] |

組み込み provider は retry の両フィールドを `None` にして既定値を使う。[OpenAI provider の構築 L443–477][builtin-provider]

`model_providers.openai.request_max_retries=0` のような指定を、組み込み OpenAI provider の retry を 0 にできた証拠にしてはいけない。
0.155.1 の merge は組み込み provider を先に登録し、通常の同名設定には `entry(key).or_insert(provider)` を使うため、既存 `openai` は置き換わらない。旧版のエラー文や config parse の成否とは区別する。
retry を変更する目的で custom provider alias・API 認証・別 endpoint を追加しない。[merge L604–649][provider-merge]

### 利用枠エラーと一時的エラーの区別

- `UsageLimitReached`、`UsageNotIncluded`、`QuotaExceeded`、`InvalidRequest`、`RefreshTokenFailed`、`ContextWindowExceeded`、`RetryLimit`、`ServerOverloaded` 等はストリーム retry 対象外。
- `Stream`、`RateLimitExceeded`、`Timeout`、`RequestTimeout`、`UnexpectedStatus`、`ResponseStreamFailed`、`ConnectionFailed`、`InternalServerError` 等は有限ストリーム retry の対象。
- HTTP 429 の body が `usage_limit_reached` なら `UsageLimitReached`、`usage_not_included` なら `UsageNotIncluded`、`insufficient_quota` 等なら `QuotaExceeded` に変換する。それ以外の HTTP 429 は `RetryLimit`。一方、ストリーム内の `rate_limit_exceeded` は `RateLimitExceeded` となり有限 retry の対象になる。単に「429 はすべて retry される／されない」と説明しない。

根拠: [retryability L372–409][retryability]、[HTTP 429 の変換 L133–181][quota-mapping]、[stream rate limit の変換 L25–38][stream-rate-limit]。sampling loop は利用枠到達を明示的に返す。[sampling loop][sampling-loop]

### アプリが保証する範囲

アプリ側の自動ジョブ再投入・子プロセス再起動は **0 回**とし、失敗後の再実行は本人の操作に限定する。
1 回の実行で CLI 内部が通信を再試行することは許容する。複数の層、認証回復、transport 切替があるので、
「1 subprocess = 1 HTTP request = 1 inference = 1 回の利用枠消費」とは説明しない。
上記値はそれぞれの loop の予算であり、1 ジョブ全体の課金回数上限ではない。

アプリの **1 つの合計 deadline、cancel、process group 終了、stdout/stderr の合計上限、二重起動防止**を維持する。
無制限 feature が false でも、有限 retry 中の長い待機を打ち切るためにアプリの期限が必要である。
`unbounded_connection_retries=false` は「すべての内部 retry が 0」の意味ではない。

## モデル・認証方式を変更しない

組み込み OpenAI provider の `OpenAiModelsManager` は明示された model を返す既定実装を利用し、要求がある場合に別の既定モデルを選ばない。
モデル情報が不足すると fallback **metadata** を作る経路はあるが、その `slug` は要求された文字列を保持する。これはモデル利用成功の証明にはならない。
request は `model_info.slug` を model に設定し、上記 retry helper は model を変更しない。
[manager 選択 L444–464][manager-selection]、[明示 model の保持 L181–208][explicit-model]、[fallback metadata L142–179][fallback-metadata]、[request L871–885][request-model]

アプリは `--model gpt-6-astra`、`model_reasoning_effort="medium"`、`model_provider="openai"`、`forced_login_method="chatgpt"` を固定する。
別モデルを明示・暗黙に試す処理は追加しない。catalog 未掲載と「server が unsupported と拒否」を別の状態として扱う。
同梱 catalog、cache、認証環境の `model/list`、実生成結果を混同しない。

ChatGPT 認証時の組み込み provider の既定 endpoint は `https://chatgpt.com/backend-api/codex`。
API key 等の経路の既定 endpoint は別であるため、ChatGPT `login status` が確認できない状態で生成に進まず、API 関連環境変数と endpoint override を継承しない。
[endpoint 選択 L350–368][auth-endpoint]。これは CLI が内部で HTTPS API を使わないという意味ではなく、アプリが OpenAI API クライアント・API キー課金経路を直接使わないという構成である。

## 専用 CODEX_HOME と認証保存

推奨するアプリ所有の状態ルートは `~/.local/share/study-with-ai/codex-home`。
同じ専用 home と `cli_auth_credentials_store="file"` を **login、login status、catalog、generation のすべて**で使う。
プロセスの環境だけに設定し、親 shell の `CODEX_HOME` や共有 `~/.codex/config.toml` は変更しない。
ディレクトリはアプリ所有・0700・symlink なしを確認して準備する。既存の shared home を別名で指す symlink は隔離にならない。

| 保存方式 | 公式実装と共有への影響 |
| --- | --- |
| `file` | `CODEX_HOME/auth.json` のみを選択する `FileAuthStorage`。新規ファイルは Unix mode 0600 で生成。専用 home で明示すれば通常の auth store 操作は共有 home のファイルや OS keyring を選択しない。ファイル内容はアプリから読まず、CLI が管理する |
| `keyring` | 直接 keyring backend は service `Codex Auth` と canonical `CODEX_HOME` の SHA-256 先頭 16 桁を含む key を使う。secrets backend も存在するため、すべての keyring mode を単一 key の仕様と説明しない |
| `auto` | keyring を先に使い、読込／保存失敗時に file へ進む。保存先の曖昧さを避けるためアプリからは選択しない |
| `ephemeral` | 現プロセスのメモリだけなので、別々の CLI subprocess で login を再利用する今回の構成に適さない |

根拠: [file path L154–156][auth-file-path]、[file I/O L195–227][auth-file-store]、[store の分岐 L511–527][auth-store-choice]、[直接 keyring key L235–248][keyring-key]、[secrets backend L340–354][secrets-keyring]、[auto L428–455][auto-store]。
[公式認証資料][auth-doc]も `file` の保存先、`auto`/`keyring`/`ephemeral`、CLI と IDE が同じ保存先では認証を共有することを説明している。

**`codex login` は単なる読取りではない。** 0.155.1 の browser login と device login は新しい認証フローの前に、選択された store の既存 auth を logout/revoke する。
そのため共有 home で安易に再 login を実行すると、同じ認証を使う CLI/IDE に影響しうる。
専用 home でも再 login はそのアプリ用ログインを置き換える操作であり、自動では実行しない。
[login 前の clear L122–153][login-clear]、[device flow L318–354][device-login]、[revoke と削除 L967–992][logout-revoke]。
`logout_all_stores` は指定 home の ephemeral と選択 store を消すので、明示 `file` で keyring を追加削除する処理ではない。[L1435–1457][logout-stores]

### 本人が行う公式ログイン

準備済み専用環境から公式バイナリの `login` を起動し、本人がブラウザで同意する。
macOS の通常 browser flow を優先し、本人の環境で必要な場合だけ公式 `login --device-auth` を選ぶ。
デバイスコード方式はアカウント／workspace 側の許可が必要な場合がある。ログイン待機をアプリが自動起動したまま残さない。
[公式手順][auth-doc]、[CLI の login option L496–541][login-options]、[browser/device 分岐 L1598–1638][login-dispatch]

以下は公式 CLI 引数の対応を示すテンプレートである。実運用ではアプリの認証セットアップ用スクリプトから、環境 allowlist・専用 home 検査・固定バイナリ検査を通して同等の呼出しを行う。

```sh
CODEX_HOME="$HOME/.local/share/study-with-ai/codex-home" \
  "$HOME/.local/share/study-with-ai/tools/codex/0.155.1/codex" \
  -c 'cli_auth_credentials_store="file"' \
  -c 'forced_login_method="chatgpt"' login
```

`login status` は同じ home/store で確認し、成功条件は exit 0 と `Logged in using ChatGPT`。
API key、access token、personal access token、workload identity 等の別状態を同じ成功扱いにしない。
この版の status は主に保存された auth method の確認なので、期限切れやアカウントの GPT-6 利用可否まで保証しない。
[status L443–507][login-status]

資格情報のコピー、symlink、JSON の parse、ブラウザ cookie の転用、`--with-api-key`、トークンの注入による代用は行わない。
ユーザーの Phase 2 指示が禁止する auth cache コピーは、一般の公式 headless guide にその例があっても採用しない。

## 専用 home でも残る管理者ポリシー

`CODEX_HOME` の変更で隔離されるのはユーザー状態ルートであり、管理者ポリシーを無効化する操作ではない。
`--ignore-user-config` は user config layer を空にするだけで、独立した managed requirements の読込みは残る。
[config layer 順 L97–126][config-layers]、[managed/cloud/system loading L191–256][requirements-load]、[user config ignore L530–545][ignore-user-config]

macOS 0.155.1 の管理者由来情報には少なくとも次がある。

- `/etc/codex/config.toml` の system defaults。
- `/etc/codex/requirements.toml` の強制要件。
- `/etc/codex/managed_config.toml` の legacy managed defaults と要件への変換。
- macOS CFPreferences の domain `com.openai.codex` にある `config_toml_base64` / `requirements_toml_base64`。
- ChatGPT workspace に紐づく enterprise cloud config / requirements。

根拠: [system requirements L750–764][system-requirements]、[Unix legacy path L219–231][legacy-managed-path]、[MDM keys L20–40][mdm-keys]、[CFPreferences 呼出し L113–137][mdm-read]、[公式 managed configuration][managed-doc]。
`/Library/Application Support/OpenAI/Codex` の存在確認だけでは MDM の有無を証明できない。

管理者は `cli_auth_credentials_store` を固定でき、bootstrap と最終 config の両方で user/CLI の `file` 指定より required value が優先される。
ログイン前に適用されるローカル認証要件と、認証後に取得する cloud 要件を区別する。
[bootstrap L58–77][auth-bootstrap]、[最終 store L4228–4234][auth-required-store]、[公式の local authentication requirements][managed-doc]。

したがって診断では「専用 home を使ったから policy なし」「`-c` に false を付けたから必ず false」と決めつけず、
CLI が示す有効設定・要件との衝突を確認する。必須 policy により tools/hook/endpoint/auth/retry の監査条件が満たせなければ、policy を消したり迂回せず具体的理由を示して停止する。
`--ignore-managed-requirements` 等を使わず、組織 policy の除外・改変・別 home への移動もしない。

このソース監査だけでは現在の端末の MDM/cloud policy の不存在や、専用 home での実 tools catalog の空集合までは証明していない。
それらは公式 CLI の同一版・同一境界設定による合成 probe と、認証後の実効設定確認で別に検証する。

## 実装との照合で追加した検査

`config/read` はすべてのキーを同じ形で返すわけではない。0.155.1 の API 型 `ToolsV2` は `web_search` だけを持ち、
`update_plan.enabled` と `experimental_request_user_input.enabled` は typed response から省略される。
元の `ToolsToml` には両方の設定が正式に存在するので、「省略される＝設定が無効」とも「省略される＝false」とも解釈しない。
実装は typed 値が存在するときはその値を検証し、省略時は `includeLayers=true` の raw `sessionFlags` に両方の明示 false があることを確認する。
管理者要件は別に検査して停止するため、管理者による上書きを無視して CLI flags を最高優先と扱わない。
[RPC 型 L158–162, L278–312][rpc-config-types]、[正式な tools 設定 L624–645][tools-config]、[型変換と layers の順序 L137–176][rpc-config-projection]。

さらに、非空の MCP/custom provider、独自 endpoint、追加 instructions、hooks/notify 等を合成 RPC で与え、実効設定の照合で拒否することを確認した。
`openai_base_url` に明示する `https://api.openai.com/v1` も、ChatGPT 認証時の未指定既定とは異なるため許可しない。
専用 home・owner marker の所有者/権限、marker/auth symlink、共有 `.codex` 自体が symlink の場合の子パスも検査する。

診断を再利用する identity には `cloud-config-bundle-cache.json` と `models_cache.json` の metadata も含める。
公式 cloud cache は既存ファイルを in-place 更新するので、home directory の mtime だけでは変更を検出できない。
認証ファイルや cloud cache の内容をアプリで読む必要はない。[cloud cache path と保存 L24–41, L128–165][cloud-cache]。

`tests/test_codex_environment.py` は合成ファイルと合成 RPC の **43 テストが成功**した。
実 CLI 実行なしで、共有設定を変更しないこと、API/token 関連環境を継承しないこと、hash 不一致では実行しないこと、
MDM key の存在検査と検査失敗時の停止、cache 更新による再診断、上記の実効設定拒否を確認している。
この結果を、実アカウントの認証や実生成の成功として扱わない。

[release]: https://github.com/openai/codex/releases/tag/rust-v0.155.1
[tag-ref]: https://api.github.com/repos/openai/codex/git/ref/tags/rust-v0.155.1
[tag-object]: https://api.github.com/repos/openai/codex/git/tags/4e21628f9ec9ee656650cd2b62ef92225725b5ac
[auth-doc]: https://learn.chatgpt.com/docs/auth
[managed-doc]: https://learn.chatgpt.com/docs/enterprise/managed-configuration
[retry-defaults]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/model-provider-info/src/lib.rs#L29-L38
[retry-effective]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/model-provider-info/src/lib.rs#L415-L440
[http-policy]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/model-provider-info/src/lib.rs#L370-L377
[http-predicate]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/codex-client/src/retry.rs#L21-L35
[http-loop]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/codex-client/src/retry.rs#L80-L106
[http-backoff]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/codex-client/src/retry.rs#L39-L47
[sampling-loop]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/core/src/session/turn.rs#L1560-L1657
[unbounded-default]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/features/src/lib.rs#L1236-L1240
[stream-helper]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/core/src/responses_retry.rs#L65-L143
[transport-switch]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/core/src/client.rs#L2014-L2029
[stream-backoff]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/core/src/util.rs#L1-L90
[builtin-provider]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/model-provider-info/src/lib.rs#L443-L477
[provider-merge]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/model-provider-info/src/lib.rs#L604-L649
[retryability]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/protocol/src/error.rs#L372-L409
[quota-mapping]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/codex-api/src/api_bridge.rs#L133-L181
[stream-rate-limit]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/codex-api/src/api_bridge.rs#L25-L38
[auth-recovery]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/login/src/auth/manager.rs#L1856-L1868
[auth-recovery-steps]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/login/src/auth/manager.rs#L1983-L2037
[manager-selection]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/model-provider/src/provider.rs#L444-L464
[explicit-model]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/models-manager/src/manager.rs#L181-L208
[fallback-metadata]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/models-manager/src/model_info.rs#L142-L179
[request-model]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/core/src/client.rs#L871-L885
[auth-endpoint]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/model-provider-info/src/lib.rs#L350-L368
[auth-file-path]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/login/src/auth/storage.rs#L154-L156
[auth-file-store]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/login/src/auth/storage.rs#L195-L227
[auth-store-choice]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/login/src/auth/storage.rs#L511-L527
[keyring-key]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/login/src/auth/storage.rs#L235-L248
[secrets-keyring]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/login/src/auth/storage.rs#L340-L354
[auto-store]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/login/src/auth/storage.rs#L428-L455
[login-clear]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/cli/src/login.rs#L122-L153
[device-login]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/cli/src/login.rs#L318-L354
[logout-revoke]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/login/src/auth/manager.rs#L967-L992
[logout-stores]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/login/src/auth/manager.rs#L1435-L1457
[login-options]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/cli/src/main.rs#L496-L541
[login-dispatch]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/cli/src/main.rs#L1598-L1638
[login-status]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/cli/src/login.rs#L443-L507
[config-layers]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/config/src/loader/mod.rs#L97-L126
[requirements-load]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/config/src/loader/mod.rs#L191-L256
[ignore-user-config]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/config/src/loader/mod.rs#L530-L545
[system-requirements]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/config/src/loader/mod.rs#L750-L764
[legacy-managed-path]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/config/src/loader/layer_io.rs#L219-L231
[mdm-keys]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/config/src/loader/macos.rs#L20-L40
[mdm-read]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/config/src/loader/macos.rs#L113-L137
[auth-bootstrap]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/core/src/config/auth_keyring.rs#L58-L77
[auth-required-store]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/core/src/config/mod.rs#L4228-L4234
[rpc-config-types]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/app-server-protocol/src/protocol/v2/config.rs#L158-L312
[tools-config]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/config/src/config_toml.rs#L624-L645
[rpc-config-projection]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/app-server/src/config_manager_service.rs#L137-L176
[cloud-cache]: https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/cloud-config/src/cache.rs#L24-L165
