# ローカル教材検索

質問、講義、試験は `src/retriever.py` の `LocalRetriever` を共用する。生成ProviderとEmbeddingを分離し、検索はOpenAI SDK、APIキー、生成モデルを使用しない。科目の一覧・診断の表示でモデル読込やPDF抽出を始めない。

## モデルと初回取得

採用モデルは `intfloat/multilingual-e5-small`、revision は `614241f622f53c4eeff9890bdc4f31cfecc418b3` に固定した。公式model cardはMIT、384次元、入力上限512 tokens、検索質問の `query: ` と本文の `passage: ` prefix、L2正規化を示す。日本語・英語を含む多言語に対応する。[公式model card](https://huggingface.co/intfloat/multilingual-e5-small/blob/614241f622f53c4eeff9890bdc4f31cfecc418b3/README.md)

初回のみモデル配布元へのネットワーク接続が必要。アプリ起動時には自動取得しない。

```sh
uv sync --extra semantic
uv run --extra semantic python scripts/download_embedding.py
```

既定保存先は `models/multilingual-e5-small/<revision>/`。`STUDY_EMBEDDING_DIR` または取得scriptの `--destination` で変更できる。変更時はアプリにも同じ環境変数を設定する。モデルファイルはGit管理しない。

通常実行はローカルパスを `local_files_only=True`, `trust_remote_code=False`, `use_safetensors=True`, CPU に指定して読み込む。モデルがない、revisionが不一致、依存がない、計算に失敗した場合は **BM25のみ** に縮退し、診断に原因と取得コマンドを出す。商用Embeddingへの切替はない。初回取得後はアプリ再起動なしでも次の検索で取得状態の変更を検出できる。

確認時のライブラリ版は `uv.lock` と診断キャッシュmanifestに記録する。2026-09-19の実検証は sentence-transformers 5.1.2、transformers 4.57.6、torch 2.14.0、PyMuPDF 1.27.1、NumPy 2.4.2、Janome 0.5.0。環境による推論差があり得るため、これらの版もcacheの識別に含める。版情報は構築時に固定したPython検索パスから取得し、そのRetriever/Embedderの稼働中は保持する。依存版を変更した場合はアプリを再起動する。

## 教材と根拠

教材は `data/<カテゴリ>/<科目>/**/*.pdf` に配置する。科目IDはカテゴリも含む `Science/Learning` のような相対パス。相対パス、内容SHA256、document ID、1始まりのページ番号、chunk ID、参照用source IDを各抜粋に保持する。同名PDFでもカテゴリ・科目が異なれば別教材として扱う。

パストラバーサルとsymlinkの教材読込を拒否する。ファイル読込は親directoryのdescriptorを起点に各要素を `O_NOFOLLOW` で開き、symlink差替えにも対応する。PDFをバイト列として読み、その同じ内容のhashと抽出結果を結びつける。

PDFのテキスト層を先に抽出する。画像を含み、文字が不足するページのみPyMuPDFで描画してTesseract OCRを行う。Popplerは不要。空白ページもページ番号を保持する。OCRの日本語・英語データがない、timeout等が生じた場合は、抽出できたテキストを維持し、ページ別警告を表示する。暗号化・破損・上限超過PDFは成功と表示しない。OCRそのものの実認識精度は今回未評価で、選択するページと依存不足時の動作を合成fixtureで検証した。

検索はJanome形態素と日本語bigram・英語単語を使うBM25を基本にし、Embeddingが利用できる場合はcosine検索とreciprocal rank fusionで統合する。検索結果は最大12抜粋・合計12,000文字。既定chunkは400文字・60文字重複で、末尾chunkを重複生成しない。モデルのtokenizerは512 tokensを超える入力を切り詰めるため、特殊文字や極端に密な文書の末尾意味がEmbeddingへ反映されない場合がある。

## 質問検索とコース用の代表抜粋

通常の `search(subject, query, top_k)` は質問に関係する箇所を順位付けする。BM25だけの環境で一致語がない場合、空の結果になることがある。通常検索の不一致を理由に、全体概要の選択へ自動で切り替えない。

`course_context(subject, query, top_k=8)` は、同じ安全な教材列挙・索引・E5/BM25の順位付けを使い、科目全体の構造を考えるための代表抜粋を選ぶ。別の生成要求、文書要約モデル、Embedding APIは追加しない。コース作成ではこの方法を使い、RAGでは利用者が明示した場合だけ使う。

選択の方針は次のとおり。

- PDFが枠より多い場合、最も関連するPDFを残し、残りはファイル順の先頭・末尾・離れた位置へ分散する。
- 選んだPDF間で枠を配分する。各PDFでは関連箇所と読み取れたページの冒頭・末尾を優先し、残りを離れたページへ分散する。
- 枠に余裕があれば追加の関連ページを使う。全ページを一度含めた後は、長いページ内でも同じchunkを重ねず分散する。
- PDFを交互に取り出して文字数上限を守る。上限に入らないchunkは採用しない。空のqueryなら質問Embeddingを行わず代表位置だけで選ぶ。

教材の文字列、source ID、相対パス、ページ、chunk IDは元の索引と結びついたままになる。`context_role` は関連箇所か代表位置かを区別する。`context_coverage` は対象PDF数、読めたPDF/ページ数、選択したPDF/ページ/chunk数、文字数、教材revisionを持つ。壊れたPDFや文字を読めなかったページを、網羅したページとして数えない。これは代表的な抜粋の範囲であり、全ページ・全概念の網羅率や理解度を保証する値ではない。

Serviceはコース/明示overviewで8〜10抜粋を要求した後、生成用の共通上限である **最大10抜粋、合計10,000文字、1抜粋1,600文字** に収める。実際に渡したchunk数・ページ数・文字数を `provided_*` として記録し、索引段階の選択範囲と区別する。callerが付けたcoverageは使わず、RetrieverとServiceが作った値だけを使う。

RAGの「要点をつかむ」は質問文の候補を入れ、「教材全体から代表的な抜粋を参照」を有効にする。選択は科目/学習セッションごとに保存され、利用者が解除できる。明示した参照方法をローカル確認・回答・出題傾向で共用する。モデルへの送信は回答/分析を押したときだけで、候補選択やローカル確認では生成しない。

## 保存講義を相談・試験に渡す範囲

PDFの抜粋とは別に、講義を参照する相談や章試験には `src/lecture_context.py` が原文の範囲を選ぶ。保存講義の本文上限は40,000文字、一般的補足は20,000文字で、生成schemaと一致する。保存された全文をこの処理で書き換えない。モデルへ渡す講義contextは本文・補足の合計で6,000文字以内とし、位置ラベルと両fieldを区別する見出しも上限に含む。

補足がない場合は既存の本文選択方式を維持し、6,000文字以内なら本文をそのまま渡す。補足がある場合は両fieldへ枠を配分し、質問への一致が強いfieldに多くを割り当て、未使用枠を移す。両方が長い場合はそれぞれに少なくとも約3分の1の枠を確保する。各fieldで段落・文の境界を優先して分割し、冒頭、末尾、質問または章テーマに関係する箇所を最大2つ、残りの離れた節を選び、原文順に並べる。先頭だけを固定で切り取らず、後半や補足内の練習・まとめも選択候補にする。これはローカルの原文選択で、生成要約ではない。

`lecture_context` には全文長 `total_chars`、採用した原文長 `selected_chars`、ラベル込み長 `context_chars`、`is_excerpt`、選択法、元本文の `ranges` を保存する。rangeは0始まり・endを含まない位置と選択理由を持つ。補足がある場合は総数を両fieldの合計とし、rangeに `field` を持たせ、`sections` に各fieldの範囲・長さ・`content_kind`（`lecture_main` / `general_supplement_not_material`）を保持する。対話/試験の結果へ引き継ぎ、採点は元のexamの範囲記録を保持する。UIは抜粋利用と参照量を表示し、講義全体を漏れなく評価したと扱わない。

講義以外の入力は先に48,000 UTF-8 bytes以内か検査し、講義を抜粋にした後のpayload全体にも同じ上限を適用する。最終promptにはProvider側の64 KiB上限が別にある。教材revisionが古い講義は検索前に拒否する。講義生成の検索には章descriptionを、講義を参照する対話/試験の検索には選択講義を加え、教材根拠の候補を探す。

講義入力は保存した `markdown` 本文と `supplemental_markdown` であり、補足には固定の「一般的補足（教材原文ではありません）」ラベルを付ける。講義に保存された `sources` をそのまま再送する仕組みではなく、教材根拠は現在のRetrieverで選び直す。一般的な補足を教材の記述に読み替えず、出力で使える根拠IDはその要求で渡したものだけとする。抜粋にない論点は、十分に確認したと主張しない。

## キャッシュ

旧APIベクトルは変更・読込せず、新しい `cache_root/local-retrieval-v2/` namespaceに再構築する。cache keyには次を含む。

- 全教材の相対パスと内容hash。追加・削除・同名/同サイズ差替えを検出する。
- 抽出/OCR/chunk設定、実装形式version、関連ライブラリ版。
- EmbeddingモデルID/revision、次元、prefix、正規化、token上限。

chunksとvectorsを単一 `.npz` に保存し、固有の一時ファイルからatomic replaceする。読み出しでmanifest、chunk digest、vector digest、行数・次元・有限値、教材内容hash、chunk IDの重複を検証する。破損した新cacheは再構築し、旧cacheは保持する。失敗したOCRページがあるcacheは次回に抽出を再試行する。indexには教材抜粋が入るのでローカルの非公開データとして扱う。

## 合成教材と再現確認

本人の教材・進捗を使わず、次のscriptで日英3ページの自作教材を生成できる。既存の同名PDFを上書きしない。

```sh
uv run python scripts/create_sample.py --data-root sample_data
uv run pytest tests/test_retrieval.py tests/test_retrieval_semantic.py tests/test_course_context.py tests/test_rag_overview.py tests/test_lecture_context.py -q
STUDY_TEST_LOCAL_EMBEDDING=1 uv run --extra semantic pytest tests/test_retrieval_semantic.py -q
```

通常テストはモデル不要の合成fixtureを使う。実modelテストは明示opt-inで、Codex生成のテストとは別である。実行済み結果・件数・skipの正本は [TEST_REPORT](TEST_REPORT.md) を参照する。

実modelテストでは全socket接続を例外化し、通信呼出0をassertした状態で、index作成・質問Embedding・hybrid検索を行った。384次元とL2 normを確認し、4教材の合成corpusで日本語・英語・言語横断の4質問すべて期待教材を1位取得した。小さな動作確認であり、本人の教材や大規模検索の品質を保証する評価ではない。

検索unitテストは、科目分離、content/config/model revision更新、追加・削除、旧cache保全、vector不整合、symlink・不正パス拒否、壊れたPDF、混在PDFの選択OCR、OCR依存不足、空検索、モデル取得後の切替、query Embedding失敗時の縮退を確認した。合成PDFは3ページすべて描画し、日英テキストの欠け・重なりがないことを確認した。macOS上で検証し、Windowsのdirectory descriptor対応は未検証。

代表抜粋と学習導線には、多数PDF/長いPDFでの分散、関連箇所、空query、硬い件数/文字数上限、cache再利用、範囲metadata、BM25環境の明示overview、通常検索の無断fallback禁止、セッション別参照方法、長い講義の原文範囲選択を対象とする合成テストを追加している。これらの実装契約の検証を、大規模教材での教育品質の保証に読み替えない。

## 分割講義の参照（2026-09-20）

各節の生成では節のtitle/topicsで改めて教材を検索する。先行節全文ではなく要点だけを渡す。相談・練習では節の指定を優先し、章全体の試験では各節の目標・本文・補足を分散して合計6,000文字以内へ選ぶ。教材引用と一般的補足の区分を保持し、版からの抜粋であることを明示する。全節を保存していても、後続の1要求が講義全文を読んだことにはならない。
