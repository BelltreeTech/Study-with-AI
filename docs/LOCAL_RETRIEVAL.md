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
uv run pytest tests/test_retrieval.py tests/test_retrieval_semantic.py -q
STUDY_TEST_LOCAL_EMBEDDING=1 uv run --extra semantic pytest tests/test_retrieval_semantic.py -q
```

通常テストはモデル不要で26件成功、実modelテスト1件は明示opt-inのためskip。実modelテストも実行して成功した。これはCodex生成のテストではない。

実modelテストでは全socket接続を例外化し、通信呼出0をassertした状態で、index作成・質問Embedding・hybrid検索を行った。384次元とL2 normを確認し、4教材の合成corpusで日本語・英語・言語横断の4質問すべて期待教材を1位取得した。小さな動作確認であり、本人の教材や大規模検索の品質を保証する評価ではない。

検索unitテストは、科目分離、content/config/model revision更新、追加・削除、旧cache保全、vector不整合、symlink・不正パス拒否、壊れたPDF、混在PDFの選択OCR、OCR依存不足、空検索、モデル取得後の切替、query Embedding失敗時の縮退を確認した。合成PDFは3ページすべて描画し、日英テキストの欠け・重なりがないことを確認した。macOS上で検証し、Windowsのdirectory descriptor対応は未検証。
