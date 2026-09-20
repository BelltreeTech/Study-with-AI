# 検証報告

## 2026-09-20 追加改善: 読む位置と復習候補への導線

通常suite **534 passed / 2 skipped / 5 warnings、54.86秒**。Ruff、Mypy（45 source files）、差分検査成功。実生成・Reset消費なし。本人教材・進捗を使わず隔離mock/AppTestで確認。

- 分割講義の全章/単一節切替、前後の節、画面移動後の読む位置復元、新講義版への分離を検証。読む位置でEXPを増やさない。
- 練習の復習候補フィルター、候補解除後の空表示、非表示答案の復元、操作による生成0件を検証。
- 問題番号・問題種類を表示。練習本文と解答を共通の安全なMarkdown描画に統一。最新の提出フィードバックを先頭に開き、参照教材と以前の提出も保持。
- 新しいUIはStreamlit AppTestで検証。今回追加したUIの実ブラウザ目視・実Codex生成は行っていない。任意CLI/E5テスト2件は従来どおりskip。

証跡: `.study-runtime/reading-navigation-tests.xml`。前回までの結果は以下に保持。

## 2026-09-20 追加改善: 練習の継続・履歴保全

最終通常suite **532 passed / 2 skipped / 5 warnings、52.96秒**。Ruff、Mypy（45 source files）、`git diff --check`成功。追加の実Codex生成・Reset消費なし。本人データを使用せず、合成mockと隔離SQLite／AppTestで検証した。

- 新しい練習セットの成功後に最新セットを表示。手動で選んだ過去セットと下書きは、別の生成が失敗しても維持。
- 旧セットのarchive、最新セット、receiptを同一transactionへ移動。保存途中の故障で全体rollbackし、2件の同時適用でも全セットを保持。
- やり直しでヒントと解答を閉じる。ヒントの再表示に追加生成はなく、累計利用記録・提出履歴は保持。
- 完了済み未反映の講義に「保存済みの講義を反映」を表示。AppTestで追加Provider呼出し0件、元の講義結果と一致を確認。

個別の保存/UI検証は21件成功。最終suiteへ含まれるため重複加算しない。2 skipは従来どおり実CLI localhost probeと実E5の任意テスト。新しい実生成品質の検証は保留のまま。証跡: `.study-runtime/practice-followup-tests.xml`。

## 2026-09-20: 日本語図・分割講義・独立練習の改修

**今回の最終通常suite: 527 passed / 2 skipped / 5 warnings、52.03秒。** macOS arm64、既存 `.venv`、合成PDF・mock Provider・隔離保存先で実施。実Codex生成は0件、Reset消費0件。旧8ジョブのledgerは再初期化・追加実行していない。本人教材・答案・進捗を検証に利用していない。

```sh
.venv/bin/pytest -q --junitxml=.study-runtime/lecture-v4-tests.xml
.venv/bin/ruff check .
.venv/bin/mypy src app.py main.py scripts
.venv/bin/python verify_score.py
git diff --check
```

Ruff、Mypy（45 source files）、既存の採点閾値検査、差分空白検査も成功。2 skipはinstalled CLI localhost probeと実ローカルE5のopt-in。今回Provider・E5実装を変更していないため、これらは再実施せず、下記2026-09-19の結果を旧版の証拠として保持する。5 warningsは既存PyMuPDF/SWIGのdeprecation。

| 対象 | 今回確認した内容 |
| --- | --- |
| 図 | 日本語・英語・数式記号をDOTに保持。危険構文・引用符・バックスラッシュ・制御文字・サイズ制限の回帰。 |
| ブラウザ描画 | `127.0.0.1:8517`の合成Streamlit図で「入力データ」「正解」「損失」「連鎖律」、ŷ/∂/α/βを視認、AXにも正しい日本語。`uXXXX`化なし。本人教材・生成なし。 |
| 時間・講義設計 | 旧設定のlegacy_totalと新設定lecture_input、全生成経路のインプット時間指示。合成の誤差逆伝播計画、前提・連鎖律・数値例・コード・目標・先行要約、節別検索。 |
| 章バッチ | 最大8節＋設計、親lock FD保持、CAS、成功節再利用、各種失敗/利用枠/取消/総deadline/教材変更、実process異常終了→起動時0要求→明示再開、完了checkpoint保全。 |
| 練習 | 3問契約、概念問題、条件付きコード、scope/revision/問題ID、ヒント・解答の明示表示と追加生成0、下書き復元、答案フィードバック・履歴・やり直し・復習候補、XP不変。 |
| 保存互換・UI | APIキーなし5画面、4タブ、途中本文と明示再開、新旧講義版の分離・旧本文/答案の保存/書出し、従来の試験と進捗・章50EXPの冪等性。 |
| 入力サイズ | 大きな合法3問snapshotを検証後1問へ絞る。全10根拠の送信重複を除外し、48KB/64KiB上限と保存原本を維持。 |
| HTML仕様書 | localhostで改訂内容と11生成契約・節検索を表示確認。20節、検索でlecture_planを含む節へ絞込み。DOM幅1280pxに対し文書幅1280px。 |

レビューで検出した空sessionによるバッチ開始不可、旧版の未採点解答露出、練習snapshotの大きさ・根拠重複、checkbox再描画による復習候補消去を修正した。修正後の限定再レビューで今回指摘に未解決P1/P2なし。テスト件数は重複する個別実行を足し合わせず、最終suiteの値を採用した。

**未検証の範囲:** 新しい `lecture_plan` / `lecture_section` / `practice_set` / `practice_feedback` の実Codex生成、長い章の実生成時間・利用枠消費、実際の教材に対する説明品質・教育効果。構成・参照の検証は意味上の正しさの保証ではない。本文のコードは自動実行しない。初回最大9要求、明示再開では未完了分の追加消費があり、1回の開始/再開の総期限は30分。追加の実検証には別途明示予算が必要。

README、学習仕様、設計・機能表・検索仕様、HTML仕様書を更新。既存branch `feat/codex-gpt6-medium-refactor`上で作業し、main変更・push・mergeは実施しない。

---

以下は以前の改修・実生成の履歴。上記の追加機能を実Codexで検証した記録とは扱わない。

## 第3段階（2026-09-19、現在の結果）

開始HEAD `1a6aaafabf18aa82c3efe917851a5150627807c0`、ブランチ `feat/codex-gpt6-medium-refactor`。macOS arm64 / Python 3.12.13 / Streamlit 1.54.0。同じcheckoutの学習基盤を維持し、個別化した学習導線と公式Codexの実生成を実装・検証した。本人の専用home公式ChatGPTログインは完了済み。再clone、SQLite再移行、main変更、push、merge、履歴書換え、Reset消費は行っていない。本人の教材・進捗・答案を試験に使用していない。

**実コースの5操作（カリキュラム・講義・対話・問題・採点）が成功した。実生成は失敗3件を含めて8ジョブで終了。直接RAG回答の実生成は未検証であり、全経路のE2E完了とは扱わない。**

### 学習機能と回帰検証

5画面を維持し、PDF登録→学習プロフィール→コース作成→続きの章→テスト・復習へ進めるようにした。科目ごとの目標・前提知識・学び方・たとえ・学習時間を保存し、コースの生成条件を固定する。例題・ヒント付き練習・自力確認・間違いからの復習を生成指示へ追加した。質問/答案の下書き、過去答案、進捗再開、生成完了の自動表示、別タブの結果を消さない試験切替を確認した。

通常suiteの最終結果は **410 passed, 2 skipped, 5 warnings in 40.15s**。2件のskipは実CLI境界probeと実ローカルE5のopt-inで、下記の独立実行で成功を確認した。5 warningsは既存PyMuPDF/SWIGのdeprecation。ruff、mypy（42 source files）、Easy70 / Normal80 / Hard90の合格閾値、`git diff --check`も成功した。

```sh
env -u OPENAI_API_KEY -u CODEX_API_KEY -u AZURE_OPENAI_API_KEY \
  .venv/bin/python -m pytest -q --junitxml=.study-runtime/phase3-tests.xml
.venv/bin/ruff check .
.venv/bin/mypy src app.py main.py scripts
.venv/bin/python verify_score.py
git diff --check
```

通常suiteは合成PDF/fake CLI/Providerだけを使用する。Providerの有限通信retry/既知警告/未知エラー拒否、送信用Schemaの非破壊変換と元Schema検証、代表抜粋と科目分離、長文講義の範囲選択、個別化、補足の引継ぎ、答案のatomicな切替、harnessの累計上限と失敗証拠の保全を追加した。harnessの38件は8件上限、部分検証、失敗の非再分類、再開時の生成0・加点0も確認する。

実出力の点検で、講義の例題が補足にある場合に対話/問題へ渡らないことと、対話の補足の問いが次ターンから消えることを発見した。保存本文40,000字・補足20,000字を変更せず、合わせて6,000字以内の抜粋を別fieldで提供し、新しい会話履歴には補足区分を明示して保存する。保存用`result`の重複で48KB制限へ早く到達する問題も修正し、実際の会話本文・その他入力の上限は維持した。これらは合成Service/AppTestで確認した。実5操作の完了後の修正なので、追加の実生成で検証したとは扱わない。

### 認証・実効設定・実行境界

専用CLI **0.155.1**、専用home `~/.local/share/study-with-ai/codex-home`。本人による公式ChatGPTログイン後の診断は終了0、`auth=chatgpt` / `model=gpt-6-astra` / `effort=medium` / `model_status=listed` / `model_available=true` / `boundary_verified=true` / `ready=true`。`model/list includeHidden=true`の1ページ全件と`config/read` / `configRequirements/read`を照合した。実効値はprovider=`openai`、login=`chatgpt`、file auth store、read-only、approval=`never`、web search無効、service tier既定、unbounded connection retries=false。診断で生成thread/turnは開始しない。

専用binary SHA256は `8eaf1ad12fe6bf89b1710330f58900014322c7c5af677e43be116d8ac5fc0a9e`。共有Homebrew版0.152.1の実体/hash、共有`config.toml` / `AGENTS.md` / `auth.json`のinode・サイズ・mtimeは開始時baselineと不変だった。認証ファイルの内容は読まず、metadataだけ比較した。認証コピー、共有設定の削除・変更、Codexアプリの上書きはしていない。

最終sourceの実CLI localhost境界試験は **1 passed in 0.60s**。それ以前のProvider/recoveryとの統合実行も **84 passed in 30.49s**。両者を通常suiteへ重複加算しない。合成HOMEと認証なしのlocalhost receiverで、tools空、model/medium、10種の指示マーカー混入なし、7種のhooks/MCP副作用なしを確認した。receiverのHTTP400とCLI終了1は意図した試験で、実生成ではない。

```sh
STUDY_RUN_CODEX_BOUNDARY_PROBE=1 .venv/bin/python -m pytest \
  tests/test_provider.py::test_installed_cli_dedicated_home_isolates_tools_instructions_and_hooks -q
```

アプリの自動再生成は0回。CLI内部の有限HTTP/stream再試行と、アプリの総timeout180秒・キャンセル・同時1ジョブ・進捗一度だけの反映を区別する。モデル・effort・APIへのfallbackはない。サービス側のモデル同一性、実送信回数、推論数、各要求の利用枠消費量は独立には観測できない。

### 実生成8ジョブの記録

全件、専用runtimeと`.study-runtime/phase2-live`の合成PDF・答案・独立DB・永続ledgerを使用した。各要求は`gpt-6-astra / medium`固定。失敗も上限へ計上し、次の表の8件以後は生成していない。

| 順序 | 操作 | 実測 |
| --- | --- | --- |
| 1 | 最小probe | `process_error`。raw情報を保存していないため原因未確定 |
| 2 | 根拠を伴うprobe再実行 | `process_error`。CLI終了0・stderr0・最終agent_message1・turn.completed1だが、Code Mode無効の通知を厳格parserが拒否。最終JSON検証未完了なので失敗を維持 |
| 3 | 構造確認を兼ねるRAG回答 | CLI終了1、HTTP400、Invalid schema、turn.failed。回答未生成 |
| 4 | 5章カリキュラム | 成功。個別化した目標・前提・練習・到達確認と学習順序 |
| 5 | 第1章の講義 | 成功。本文と根拠、料理のたとえ、例題2件、練習、自力確認 |
| 6 | 講義への対話 | 成功。想起と再読の差、料理例A/Bとソクラテス式の問い |
| 7 | Normal問題 | 成功。4択5問×4点＋記述5問×16点、合計100点 |
| 8 | 部分誤答の採点 | 成功。Q10が0/16、総得点84点、合格、章完了、50EXP |

2件目の通知のcanonical JSON hashを公式0.155.1の固定sourceから再構成して一致させた。正確なCode Mode停止通知だけを許容し、host/toolsを有効化していない。3件目はschema拒否を確認したが、raw本文を破棄していたためサーバーが指摘した個別keywordは未確定。公式Structured Outputs subsetに合わせ、送信用コピーだけから`uniqueItems` / `minLength` / `maxLength`を除去した。出力には元Schemaの長さ・一意性と業務検証を維持する。[公式supported schemas](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas)、[詳細な境界と根拠](CODEX_BOUNDARY.md)。

保存した失敗証拠、正常catalog、runtime一致、具体的な修正根拠を照合する明示部分検証モードで残り5件を使用した。`course_flow_completed=true`だが、`technical_flow_completed=false`、`rag_answer_succeeded=false`、`explicit_probe_succeeded=false`。失敗したprobe/回答を成功へ変更していない。終了0も、この区別を消さない。

### 実出力の内容点検と再開

自作`synthetic-note.pdf`は1ページ。想起練習、再読との違い、答え合わせ、間隔反復、1/3/7日の例が万人に最適ではないことを日英で記載した。3つの根拠IDはすべてこのp.1に対応する。5章は読む/思い出す→答え合わせ→失敗時のやり直し→間隔→復習計画の順序で、初学者・例題重視・料理のたとえ・25分という希望に沿う。

Codexによる出力全文の照合では、講義が教材の定義と限界を保持し、一般的補足の料理例では知識の想起と包丁などの実技を区別していた。対話は質問に答えた上でA/Bの理由を尋ねる。問題は教材内の概念を扱い、未習の料理知識を必要としない。採点はQ10の想起/分散/確認の誤解をルーブリックに沿って減点し、Q6/Q7との矛盾、3つの弱点、25分の復習手順を示した。

答案はQ1〜Q9の生成された模範解答を複写し、Q10だけ意図的な誤答にした。このため**独立した採点精度ベンチマークではない**。総得点・合否・章完了・50EXPはアプリが計算した。小さな合成教材での内容照合は、実学習者による教育効果や大規模教材の品質保証とは別である。

保存後、新しいprocessから`diagnostics` / `generate` / `probe_model`を呼ぶと即失敗するNoCalls Providerで同じharnessを再開して成功した。前後ともジョブ8件・50EXP・章completed、結果digest不変。追加の診断・生成・加点は0。証拠はignored領域の`replay-check.json`に保存した。

`manual-review.json`には7項目の具体的照合根拠を記録し、直接RAG根拠支持の1項目を未検証とした。result digestは`46a4afdf561d1078e6352523a7f3c52f7cb1855d263e771abde9071d5bc93ebb`。総合的な`educational_quality`は`manual_review_required`のままとし、全8項目の合格とは扱わない。人間による教育効果評価は未実施。

### APIキーなしの実UIとローカル検索

APIキー3種をunsetし、`sample_data`と`.study-runtime/experience-preview`の分離state/cacheで実Streamlitを起動した。実ブラウザでホーム→科目→目標/前提/料理のたとえ保存→コース作成の導線を確認した。390×844のモバイル表示で横幅`innerWidth=scrollWidth=390`、メニューの開閉とフォーム表示を確認。desktopでもDOMの横overflowはなかった。全5画面の生成・採点・再起動操作はAppTestのmock回帰で検証した。

別の合成fixture UIでは3秒待つFakeProviderで内容相談を1回実行し、手動refreshなしで結果と3件の出典が表示された。DBでも`answer / succeeded / 1件`を確認した。これは実ブラウザの完了自動反映の確認であり、実Codex回答の成功には数えていない。最初の候補port8518は他processが使用していたため変更し、他processを停止していない。

検証用port8517/8531の2サーバーはCtrl+Cで終了0。listenerなしを確認し、作成したブラウザタブも閉じた。ユーザー向けの本番サーバーを放置していない。

実ローカルEmbeddingは **1 passed, 5 warnings in 2.71s**。固定revisionのE5を通信禁止下でCPUロードし、384次元・正規化と日英4質問の期待教材4/4 top1を確認した。モデルなしでのBM25代表抜粋・質問検索も合成テストで成功。Embedding API、実行時の無断モデルダウンロードはない。

### 失敗履歴・制約

通常suiteの途中に`353 passed / 2 failed / 2 skipped`があった。`st.fragment`追加後、ScriptRunContextなしの直接呼出しが実行されないという既存テスト側の問題で、bare関数テストを`__wrapped__`呼出しへ変更しassertは保持した。実fragmentは上記ブラウザで別途検証し、その後`381 passed / 2 skipped`、さらに最後の補足修正後の最終suiteを実施した。補足履歴の新回帰は修正前`2 failed / 1 passed`で欠落を再現し、修正後に成功した。

独立レビューは生成境界、fragment、個別化、試験のatomicな切替、講義の抜粋と補足区分、入力上限と保存互換を対象とした。最終所見は具体的なP1/P2なし。試験は合成データだけで、本人保存先の再移行や内容点検はしていない。

未検証は直接RAG回答の実生成、大規模・画像PDFの品質/実OCR精度、長期の教育効果、Linux。WindowsはPOSIX lock/process groupのため未対応。抜粋方式は全文網羅を保証しない。実アカウントを故意に利用枠超過へ追い込む試験や、Reset消費試験はしていない。

## 第2段階の履歴（2026-09-19、当時の結果）

以下の未ログイン・実生成0件という記録は第2段階完了時点の履歴であり、現在の状態ではない。

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
- 第2段階終了時の専用home認証: `auth=unavailable`、`ready=false`、`probe_ready=false`。停止理由は **`auth_required` だけ**。診断helperの終了2はこの未認証状態を示す。強制条件を取り除いたりgateを迂回したりしていない。
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
