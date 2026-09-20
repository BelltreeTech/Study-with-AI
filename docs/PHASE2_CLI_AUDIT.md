# 第2段階: 専用 Codex CLI 導入・境界監査

確認日: 2026-09-19、macOS arm64。開始 HEAD は `ceaaf865cdbaefc125561ca21f14eaa0ef850c98`、既存ブランチ `feat/codex-gpt6-medium-refactor` を維持。ここで扱う installed CLI / localhost 試験は実モデル生成ではない。

## 公式配布物と並行導入

[OpenAI 公式変更履歴](https://learn.chatgpt.com/docs/changelog)は 2026-09-18 の CLI 0.155.1 と、0.153.4 の Astra のモデル一覧表示修正を掲載していた。0.152.1 の catalog 欠落を新しい版の失敗根拠として流用せず、指定候補 0.155.1 を採用した。

公式掲載の npm パッケージ `@openai/codex@0.155.1` を [npm registry の版情報](https://registry.npmjs.org/@openai%2fcodex/0.155.1) で確認した。その macOS arm64 optional dependency は `npm:@openai/codex@0.155.1-darwin-arm64`。配布元 repository は `git+https://github.com/openai/codex.git`。公式プラットフォームパッケージの [metadata](https://registry.npmjs.org/@openai%2fcodex/0.155.1-darwin-arm64) が指定する tarball を直接取得し、npm の lifecycle script を実行せず展開した。

| 項目 | 実測 |
| --- | --- |
| 採用版 | `codex-cli 0.155.1` |
| 実行ファイル | `/Users/shinrisuzuki/.local/share/study-with-ai/tools/codex/0.155.1/vendor/aarch64-apple-darwin/bin/codex` |
| 配布 package | `@openai/codex@0.155.1-darwin-arm64` |
| 圧縮ファイル | `127465533` bytes |
| registry 掲載の展開サイズ | `317014114` bytes |
| binary SHA-256 | `8eaf1ad12fe6bf89b1710330f58900014322c7c5af677e43be116d8ac5fc0a9e` |
| 共有 CLI | `/opt/homebrew/bin/codex` は引き続き `0.152.1` |

tarball の確認済み SHA-512 integrity:

```text
sha512-cYxzGcRRoBrncyHlR8ed4yXwcoVJZC1pipGULSyJkGFKXJw/Uu57BklvzayuAptjJIipamnOk32CfUkk1F0bLw==
```

registry は署名と provenance の URL も掲載している。今回検証したのは HTTPS の公式 registry 情報との整合、固定 SHA-512、および binary SHA-256。署名・provenance の暗号学的な独立検証まで行ったとは主張しない。

再現コマンド:

```sh
uv run python scripts/setup_codex.py
```

installer は OS/arch、package 名、版、配布 URL、integrity を固定し、アーカイブのサイズ上限・path traversal・symlink・特殊ファイルを検査する。空の staging に展開して版と binary hash を確認してから rename する。既存の管理外ディレクトリを上書きしない。再実行では binary hash を再確認して `reused: true` となった。バイナリ・manifest は Git 外の専用ディレクトリに置く。PATH、Homebrew、Codex アプリ、共有設定、認証には変更を加えない。

最初の実行は旧版と同じ `vendor/.../codex/codex` 配置を想定して失敗した。最終 rename 前に停止して staging を回収し、実際の 0.155.1 package の `vendor/.../bin/codex` を確認して修正後に成功した。隣接する公式 resources を保持するため vendor 配置全体を維持し、別の wrapper に置換していない。

## help とモデル一覧

新バイナリの `exec --help` で `--ignore-user-config`、`--ephemeral`、`--strict-config`、`--json`、`--output-schema`、stdin 入力、`--sandbox read-only` を再確認した。

資格情報のない合成 HOME / CODEX_HOME で `debug models --bundled` を実行した結果:

| catalog 項目 | 値 |
| --- | --- |
| slug | `gpt-6-astra` |
| display_name | `GPT-6-Astra` |
| visibility | `list` |
| supported_reasoning_levels | `low`, **`medium`**, `high`, `xhigh`, `max`, `ultra` |
| default_reasoning_level | `low`（アプリは明示的に medium を指定） |
| default_service_tier | `null` |

これは **同梱 catalog の証拠**である。認証済み catalog、本人の利用資格、サーバーでの解決、実生成成功の証拠ではない。これらの結果はアプリの診断・実生成レポートで別に扱う。

`debug models` / `login status` は `--ignore-user-config` を受け付けず、`--strict-config` も対応外だった。この差を確かめずに exec と同じフラグを流用しない。次の正式設定は両者で受理された。

```text
-c cli_auth_credentials_store="file"
-c forced_login_method="chatgpt"
-c model_provider="openai"
```

合成専用 home では `login status` は `Not logged in`、同設定の `debug models --bundled` は Astra / medium を返した。診断と生成に同じ専用バイナリ・home・auth store を渡し、予期しない専用 `config.toml` を拒否する構成が必要である。

## 新版の合成 sentinel 境界試験

```sh
uv run python scripts/probe_codex.py \
  --executable "$HOME/.local/share/study-with-ai/tools/codex/0.155.1/vendor/aarch64-apple-darwin/bin/codex"
```

`scripts/probe_codex.py` は合成 HOME と、その **外**の専用 CODEX_HOME を生成する。共有相当の `HOME/.codex` に AGENTS / override、config、skills、hooks、plugin manifest/cache、history を置く。`HOME/.agents/skills` と project AGENTS / config / hooks も置く。共有・専用・project config は sentinel MCP command と `service_tier="fast"` を含む。実認証は一切置かず、環境変数も allowlist で構成する。

本番の `boundary_overrides()`、read-only、ephemeral、strict-config、output-schema、stdin を使用し、試験専用 custom provider の送信先を loopback receiver に限る。receiver はリクエストの必要なフィールドのみを採取して必ず HTTP 400 を返す。外部へ転送しない。実際の認証を mock endpoint へ渡す経路はない。この custom provider 試験を、組み込み OpenAI provider の実生成成功とは表現しない。

実測結果:

| 項目 | 結果 |
| --- | --- |
| model / reasoning.effort | `gpt-6-astra` / `medium` |
| output format | `json_schema` |
| 提供ツール | **空配列 `[]`** |
| service_tier | payload にフィールドなし（注入した Fast 設定を継承していない） |
| Authorization header | なし |
| shared global AGENTS / override | 混入なし |
| project AGENTS | 混入なし |
| shared / dedicated / project config の各マーカー | 混入なし |
| HOME `.agents` skills / legacy `.codex` skills | 混入なし |
| plugin / history マーカー | 混入なし |
| shared / dedicated / project hooks 副作用 | いずれもなし |
| shared / dedicated / project MCP 起動副作用 | いずれもなし |
| plugin hook 副作用 | なし |
| sessions の JSONL ファイル | 0 |
| 実モデル生成 | **0 回** |

CLI の終了コード 1 は mock の意図した HTTP 400 によるもの。境界検査合格を回答生成成功に読み替えない。plugin fixture は合成 cache / manifest と設定であり、実ユーザーの plugin をインストール・実行してはいない。startup 副作用マーカー、実際の送信 tool catalog、現行版の feature 無効設定を組み合わせて検査した。

過去の共有 home 問題を再現する場合だけ `--historical-shared-home` を指定できる。通常 probe と本番は専用 home を使用する。管理者・組織の強制設定を無視する flag は追加していない。

## 公式の実効設定検査

[公式 App Server 資料](https://learn.chatgpt.com/docs/app-server)にある読み取り用 `config/read` と `configRequirements/read` を、新バイナリの一時 stdio app-server で確認した。これは生成 Provider の App Server 移行ではなく、実効設定の確認に限る。

起動は `app-server --stdio --strict-config` に本番と同じ `-c` 境界設定、`model="gpt-6-astra"`、`sandbox_mode="read-only"` を付ける。`initialize` の応答を待ってから `initialized`、`config/read {"includeLayers":true}`、`configRequirements/read {}` を順に送信する。`thread/start` / `turn/start` は呼ばない。stdin を先に閉じると未完了の RPC 応答前にサーバーが終了することも確認したため、各応答後に停止・回収する。

合成専用 home で、model=`gpt-6-astra`、effort=`medium`、provider=`openai`、forced login=`chatgpt`、credential store=`file`、sandbox=`read-only`、approval=`never`、web=`disabled`、不要 feature=false、skip host skills=true、service tier=null を確認した。config layer の種類は sessionFlags / user / system、requirements は null。この時点の結果は未認証環境であり、ログイン後に現れ得る組織の強制設定については同じ診断を再実行し、上書き・回避せず照合する必要がある。

## 検証記録

- 専用 installer 実行: 成功。再実行: SHA-256 再検査後に `reused: true`。
- `pytest tests/test_codex_setup.py -q`: **5 passed**。管理外配置の保護、traversal / symlink 拒否、checksum 失敗、atomic install / reuse / tamper 検出を合成 archive で検証。
- 新版 localhost sentinel probe: 上表の結果。
- `ruff check scripts/setup_codex.py scripts/probe_codex.py tests/test_codex_setup.py`: 成功。
- scripts 単体 mypy（`--follow-imports=silent`）: 成功。全体 mypy / 回帰件数は `TEST_REPORT.md` の統合結果を参照。
- 共有 CLI の版確認: `0.152.1` を保持。本監査は共有パッケージ管理・シェル設定を変更していない。
- 本監査で本人の認証コピー・ログイン・実生成は実施していない。
