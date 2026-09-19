# 機能・コード・保存・検証の対応表

対象の開始commitは `8cee252b629138ba5ce2cca677ba3cc3a0b987dc`。旧コードの機能を調べてから変更した。実進捗JSONをfixtureへ転用していない。

下表の検証欄は合成データ・mock・ローカル実装の範囲を示す。現在の認証状態、実Codexの実行結果、テスト件数、内容品質の評価は [TEST_REPORT](TEST_REPORT.md) と [CODEX_BOUNDARY](CODEX_BOUNDARY.md) を正本とする。モデル掲載、schema適合、UIテストだけで本番生成や学習品質の成功とは扱わない。

| 機能 | 旧コード | 現コード・保存 | 確認した範囲 |
| --- | --- | --- | --- |
| 5画面の切替・科目選択 | `app.py` の起動時components生成 | `app.py` / `runtime.py` / `views/navigation.py`、lazy生成資源 | AppTest全5画面、APIキーなし、未登録時Dashboard/Library、保存コースへの遷移で自動生成しない |
| 学習プロフィール | 説明対象・長さ・スタイル等の選択 | `config.py` / `views/learning_profile.py`、科目別optionsをlearning DBへ保存 | goal/prior knowledge/approach/analogy/session、文字数・enum・時間の検証、科目分離・再起動・旧設定互換・不正値保全 |
| 回答・履歴・根拠 | `rag_core.py.query` / `view_rag.py` | Service answer、共通Retriever、scope別履歴・下書き・参照方法、Markdown export | PDF→検索→mock回答、質問候補は入力へ追加だけ、セッション・科目分離、source ID・ページ、再起動後履歴 |
| 教材の全体概要を相談 | なし | RAGの明示overview選択、`course_context()`、`context_coverage` | BM25環境でも代表抜粋を取得、解除して通常検索へ復帰、検索不一致時の無断fallbackなし、全文網羅とは表示しない |
| 出題傾向 | `ai_tutor.py.generate_trend_report` | Service trend、取得抜粋だけを分析、learning DB | schema/根拠/プロンプト制限、資料全体の統計と混同しない指示 |
| 教材検索 | `embedder.py` OpenAI Embedding + 各Tutor検索 | `retriever.py` / `embedder.py`、E5+BM25、新namespace | BM25、実E5通信禁止、日英・言語横断4問top1、revision・破損cache・科目分離 |
| 検索語展開 | LLMへ追加要求する `expand_query` | 追加生成を廃しローカル多言語検索 | 追加の利用枠消費なし。大規模corpus検索品質は未評価 |
| PDF・OCR | `pdf_reader.py` | ページ別抽出、画像ページのみOCR、source/page/hash | 混在PDF選択OCR、依存欠如、破損、上限、symlink拒否。実OCR精度は未評価 |
| Feynman問題 | `generate_quiz` / `view_exam.py` | Service quiz、厳格schema、attempt、learning DB | 難易度別配点、合計100、問題がある間の再生成抑止、採点前に模範解答/基準を公開しない |
| 答案下書き・試験切替 | 画面のsession state中心 | attempt別draft、公開問題と答案のarchive、`LearningRepository.reset_exam()` | 画面移動・再起動復元、未採点draftの切替確認、CASとactive確認と保管/解除を同一transaction、古いタブの新attempt消去防止 |
| 採点・合否 | `grade_answer` 内の自由文数値抽出 | `schemas.py.grade_total`、設問別pointsから計算 | Easy70/Normal80/Hard90、欠落/重複/上限/不正根拠拒否、失敗時点数・XP不変 |
| コース生成・再開 | `generate_curriculum` / `view_curriculum.py` | Service curriculum、5/10/15章、代表抜粋の範囲・作成時options・教材版をprogress SQLiteへ保存 | 章生成と講義生成を分離、後のprofile変更でもcourse設定保持、旧コース保全と明示的科目割当、ロードマップ・保存コース再開 |
| 講義・再生成・保存 | `generate_lecture` | Service lecture、各章に講義IDと教材版、Markdown export | 目標/前提→概念→理由→例題→ヒント付き練習→自力確認→復習の指示、たとえの対応と限界、短い設定でも必要段階を省略しない |
| 長い講義の参照 | 冒頭6,000字のみ | `lecture_context.py` の本文・一般的補足の原文抜粋、field別位置範囲・選択長のmetadata | 保存全文は保持し、両field合計6,000字以内で冒頭・末尾・関連箇所・離れた節から選択、補足の例題も参照し教材引用と区別、抜粋範囲の表示と試験/gradeへの継承 |
| ソクラテス対話 | `run_socratic_dialogue` | Service dialogue、科目/セッション/コース/章/講義別の履歴・下書き | 言換え/具体例/理解確認の候補、course設定引継ぎ、表示した補足の問いを次ターンへ保持、旧教材版の履歴除外、古い講義による要求拒否 |
| 章試験・進級 | `view_curriculum.py` | typed quiz/grade、章完了transaction | mock問題→回答→100点→50EXP→次章、rerun二重加算防止、章と講義の照合 |
| 弱点・復習 | `progress.py` JSON弱点情報 | SQLite state未知field保全、SRS、review event | due日/弱点level/EXPイベント、再適用拒否。本人の学習効果は評価対象外 |
| Dashboard | `view_dashboard.py` | 次の一歩・保存コース再開・弱点への導線、既存EXP/称号/streak/半年heatmap/radar/目標 | PDF登録/コース作成/再開の遷移、科目とコース選択、Asia/Tokyo、日跨ぎdaily EXP、遷移だけでは生成/EXP更新しない |
| ポモドーロ | `app.py` | fragment、25分/20EXP、event receipt | 時計を合成して達成・rerun20EXP一回、終了時刻表示 |
| Library | `view_library.py` | `materials.py` 複数PDF upload・一覧、索引・診断、コース作成への導線 | PDF/パス検証、同名上書き拒否、保存に成功したPDF保持、科目選択、明示index更新、登録だけでは生成しない |
| Mermaid/数式 | 外部Mermaid component / Markdown | 許可した単純flowchart→DOT、他はcode、Markdown数式 | HTML/click/URL等の図構文拒否、受動表示。複雑なMermaidの描画は非対応 |
| CLI | `main.py` 直接クライアント生成 | UIと同じService/jobs/Provider、search-only/diagnose | import/API経路監査、ローカル検索、生成結果の根拠・構造検証はUIと共通 |
| 永続化・移行 | `progress.json`、session state | `repository.py` / `learning_repository.py`、SQLite schema1 | 合成旧形式/未知field/同時更新/破損/rollback、原JSON保持、本移行の値一致 |
| 待機・キャンセル・復旧 | 同期生成、終了処理 | `jobs.py` SQLite+flock、Provider process group、pending fragmentを2秒ごとに更新 | 別プロセス同時1、rerun/多タブclaim、完了receipt反映後full rerun、cancel/timeout/orphan、待機中設定変更で再投入しない |
| 専用CLIの導入・認証 | 直接APIクライアント / 共有環境依存 | `setup_codex.py` / `codex_runtime.py`、専用binary/home、file auth store | 公式0.155.1のintegrity/hash、独立配置、環境を限定した本人用公式loginコマンド、認証状態は別途診断 |
| 実効設定・モデル診断 | なし | Providerの公式read-only config/requirements/model RPCとCLI login status | Astra/medium掲載、境界確認、空tool catalogとsentinel隔離。実生成や利用資格の証明とは区別 |
| 利用枠・内部retry | APIクライアント任せ | app自動0、CLI有限retry許容、unbounded=false、合計期限/cancel | 固定版公式ソース監査とmock回帰。1ジョブから内部送信数・課金量を推定しない |
| 合成教材の実E2E手順 | なし | `live_e2e.py`、専用ledger/results/progress、7操作+予備1の契約 | mockで予算・失敗・再開・進捗一度を確認。実行状況はTEST_REPORTを参照 |
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

第3段階は `1a6aaaf` から学習体験を拡張し、5画面と既存学習機能を保持した。profile・course設定・下書き・archive・context範囲は既存JSON documentへ追加するため、SQLite schema versionの変更や既存データの移行は不要。旧request/optionsを既定値付きで読み、新しい生成指示は `PROMPT_VERSION=study-3` として区別する。講義中の練習・理解チェックは正式試験の採点やXPイベントではない。

未実装・未対応は、Windows実行、旧コード向けSQLite→JSON逆移行、複雑なMermaid描画。運用は [README](../README.md) の診断と合成E2E手順に従う。強制設定が新たに現れた場合は保持したまま監査する。現在の実行境界と第1段階の履歴は [CODEX_BOUNDARY.md](CODEX_BOUNDARY.md)、実行済みテスト・skip・内容品質の判定範囲は [TEST_REPORT.md](TEST_REPORT.md) に記録する。
