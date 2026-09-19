# 機能・コード・保存・検証の対応表

対象の開始commitは `8cee252b629138ba5ce2cca677ba3cc3a0b987dc`。旧コードの機能を調べてから変更した。実進捗JSONをfixtureへ転用していない。

「動作確認済み」は下表の合成データ・mock・ローカル実装の範囲を指す。**実Codexによる文章品質と学習E2Eは未検証、実生成は0回**。第2段階の専用CLI 0.155.1では`gpt-6-astra` / `medium`掲載と実効境界を確認した。現在は専用homeの本人のChatGPTログインが未完了で、`auth_required`のみを理由に生成を停止する。モデル掲載やAPIからCodexへの変更だけで、本番生成成功とは扱わない。

| 機能 | 旧コード | 現コード・保存 | 確認した範囲 |
| --- | --- | --- | --- |
| 5画面の切替・科目選択 | `app.py` の起動時components生成 | `app.py` / `runtime.py`、lazy生成資源 | AppTest全5画面、APIキーなし、未登録時のDashboard/Library、ブラウザ起動 |
| 回答・履歴・根拠 | `rag_core.py.query` / `view_rag.py` | `service.py` answer、共通Retriever、`learning.sqlite3` | PDF→検索→mock回答、セッション・科目分離、source ID・ページ、再起動後履歴 |
| 出題傾向 | `ai_tutor.py.generate_trend_report` | Service trend、取得抜粋だけを分析、learning DB | schema/根拠/プロンプト制限、実生成品質は未検証 |
| 教材検索 | `embedder.py` OpenAI Embedding + 各Tutor検索 | `retriever.py` / `embedder.py`、E5+BM25、新namespace | BM25、実E5通信禁止、日英・言語横断4問top1、revision・破損cache・科目分離 |
| 検索語展開 | LLMへ追加要求する `expand_query` | 追加生成を廃しローカル多言語検索 | 追加の利用枠消費なし。大規模corpus検索品質は未評価 |
| PDF・OCR | `pdf_reader.py` | ページ別抽出、画像ページのみOCR、source/page/hash | 混在PDF選択OCR、依存欠如、破損、上限、symlink拒否。実OCR精度は未評価 |
| Feynman問題 | `generate_quiz` / `view_exam.py` | Service quiz、厳格schema、attempt、learning DB | 難易度別配点、合計100、採点前に模範解答/基準を公開しない |
| 採点・合否 | `grade_answer` 内の自由文数値抽出 | `schemas.py.grade_total`、設問別pointsから計算 | Easy70/Normal80/Hard90、欠落/重複/上限/不正根拠拒否、失敗時点数・XP不変 |
| コース生成・再開 | `generate_curriculum` / `view_curriculum.py` | Service curriculum、5/10/15章、progress SQLite | mock5章生成、必要な1章だけ講義、旧コース保全と明示的科目割当 |
| 講義・再生成・保存 | `generate_lecture` | Service lecture、各章に講義IDと教材版、Markdown export | 遅延生成、一般補足分離、source、合成export。実文章品質は未検証 |
| ソクラテス対話 | `run_socratic_dialogue` | Service dialogue、科目/セッション/コース/章/講義別履歴 | mock対話、旧教材版の履歴除外、古い講義による要求拒否 |
| 章試験・進級 | `view_curriculum.py` | typed quiz/grade、章完了transaction | mock問題→回答→100点→50EXP→次章、rerun二重加算防止、章と講義の照合 |
| 弱点・復習 | `progress.py` JSON弱点情報 | SQLite state未知field保全、SRS、review event | due日/弱点level/EXPイベント、再適用拒否。本人の学習効果は評価対象外 |
| Dashboard | `view_dashboard.py` | EXP/称号/streak/半年heatmap/radar/目標 | AppTestとブラウザ、Asia/Tokyo、日跨ぎdaily EXP、保存進捗表示 |
| ポモドーロ | `app.py` | fragment、25分/20EXP、event receipt | 時計を合成して達成・rerun20EXP一回、終了時刻表示 |
| Library | `view_library.py` | `materials.py` upload・一覧、索引・診断 | PDF/パス検証、同名上書き拒否、科目選択、明示index更新 |
| Mermaid/数式 | 外部Mermaid component / Markdown | 許可した単純flowchart→DOT、他はcode、Markdown数式 | HTML/click/URL等の図構文拒否、受動表示。複雑なMermaidの描画は非対応 |
| CLI | `main.py` 直接クライアント生成 | UIと同じService/jobs/Provider、search-only/diagnose | import/API経路監査、ローカル検索。実Codex生成は未検証 |
| 永続化・移行 | `progress.json`、session state | `repository.py` / `learning_repository.py`、SQLite schema1 | 合成旧形式/未知field/同時更新/破損/rollback、原JSON保持、本移行の値一致 |
| 待機・キャンセル・復旧 | 同期生成、終了処理 | `jobs.py` SQLite+flock、Provider process group | 別プロセス同時1、rerun/多タブclaim、cancel/timeout/orphan、部分出力を成功にしない |
| 専用CLIの導入・認証 | 直接APIクライアント / 共有環境依存 | `setup_codex.py` / `codex_runtime.py`、専用binary/home、file auth store | 公式0.155.1のintegrity/hash、独立配置、再実行の検証。本人の専用ログインは未完了 |
| 実効設定・モデル診断 | なし | Providerの公式read-only config/requirements/model RPCとCLI login status | Astra/medium掲載、境界確認、空tool catalogとsentinel隔離。実生成や利用資格の証明とは区別 |
| 利用枠・内部retry | APIクライアント任せ | app自動0、CLI有限retry許容、unbounded=false、合計期限/cancel | 固定版公式ソース監査とmock回帰。実利用枠到達・内部送信数は未観測 |
| 合成教材の実E2E手順 | なし | `live_e2e.py`、専用ledger/results/progress、7操作+予備1 | mockで予算・失敗・再開・進捗一度を確認。実7操作と品質レビューは未実行 |
| 生成内容の品質判定 | 自由文表示 | 合成E2Eのreportと結果digestに結び付く手動review | 引用/教材整合/対話/部分誤答採点のレビュー欄を実装。schema成功だけで品質合格にしない |

## 初期状態の検証

- cloneにテストsuite・READMEはなかった。`uv sync --frozen`は成功し、旧 `verify_score.py` は6比較をPASS表示した。
- APIキーを除いた旧 `RAGCore('Synthetic/Subject')` は `OPENAI_API_KEY` 要求で停止した。
- 旧Streamlit AppTestは例外0だったが、教材未登録ロビーで止まる範囲のみ。旧学習フローの成功は確認していない。
- 教材PDFは初期cloneに0件。元の進捗ファイルは追跡されていたため、Git外へbackupして追跡解除し、実ファイルは保持した。

## 追加・変更した契約

生成要求を不変のrequestとして持ち、モデル/effort/教材版/科目/セッション/コース/設定/schema版を記録する。modelは `gpt-6-astra`、effortは `medium` 以外を拒否する。認証・モデル・実行境界を満たさない場合は生成前に停止し、APIや別モデルへ切り替えない。

生成処理のキャンセル・失敗から点数や進捗を作らない。成功しても教材が変わった場合は結果を反映せず、明示的に破棄して再生成できる。ローカル検索はCodexの状態から独立する。model未取得ならBM25と明示する。

第2段階は第1段階完了commit `ceaaf865cdbaefc125561ca21f14eaa0ef850c98`から継続し、既存の進捗・教材・保存契約を維持した。共有0.152.1は変更せず、認証のコピー・共有logout・API fallbackは行わない。有限CLI内部retryは許容するが、1アプリジョブを1HTTP送信・1推論とは数えない。

未実装・未対応は、Windows実行、旧コード向けSQLite→JSON逆移行、複雑なMermaid描画。実Codex確認は本人の専用homeログイン後、[README](../README.md)の診断と合成E2E手順から再開する。強制設定が新たに現れた場合は保持したまま監査する。現在の実行境界と第1段階の履歴は[CODEX_BOUNDARY.md](CODEX_BOUNDARY.md)、実行済みテスト・skip・未検証の内容品質は[TEST_REPORT.md](TEST_REPORT.md)に記録する。
