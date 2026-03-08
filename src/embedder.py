"""
Embedding生成モジュール。

OpenAI Embedding APIを直接呼び出し、テキストをベクトルに変換する。
結果はキャッシュファイル（.npy/.json）に保存し、再実行時の再生成を回避する。

🧮 【Embedding（埋め込み）の数学的意味】
Embeddingは、離散的なテキストデータを連続的なベクトル空間の座標に変換する射影関数:
  f: Text → R^d (d = embedding_dim, 例: 1536)

この変換により、テキスト間の「意味的な距離」をユークリッド空間で測定可能になる。
- 意味が近いテキスト → ベクトルが近い（コサイン類似度が高い）
- 意味が遠いテキスト → ベクトルが遠い（コサイン類似度が低い）

💡 【直感的意味とDL概念との紐付け】
Embeddingは、NLPにおける「Word2Vec」や「GloVe」の進化版。
TransformerベースのEmbeddingモデル（text-embedding-3-small等）は、
テキスト全体の文脈を考慮した「文脈的埋め込み」を生成する。
これはBERT/GPTの中間層から抽出される Hidden State に相当する。

📐 【出力Shape】
generate_embeddings(["テスト"]) → Shape: (1, 1536)
generate_embeddings(["a", "b", "c"]) → Shape: (3, 1536)
"""

import hashlib
import json
import os
from pathlib import Path

import numpy as np
from openai import OpenAI

# キャッシュディレクトリ
from src.config import CACHE_DIR, EMBEDDING_MODEL, EMBEDDING_BATCH_SIZE

# Embeddingキャッシュ保存ディレクトリ
k_cacheDir: Path = CACHE_DIR

# 💡 使用するEmbeddingモデル: text-embedding-3-small
#    出力次元: 1536次元。大きいモデル(text-embedding-3-large)は3072次元。
#    次元数が大きいほど表現力は高いが、計算コストとストレージも増加する。
k_embeddingModel: str = EMBEDDING_MODEL

# 💡 バッチサイズ: 一度のAPI呼び出しで処理するテキスト数。
#    OpenAI APIは1回のリクエストで最大2048テキストを受け付ける。
k_batchSize: int = EMBEDDING_BATCH_SIZE


def _get_client() -> OpenAI:
    """
    OpenAIクライアントを生成する。

    環境変数またはカレントディレクトリの.envからAPIキーを読み込む。

    💡 APIキーはOpenAIのEmbedding APIおよびChat Completion APIの認証に使用。
    """
    api_key: str | None = os.environ.get("OPENAI_API_KEY")

    # .envファイルからの読み込み（環境変数が未設定の場合）
    if not api_key:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("OPENAI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break

    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY が設定されていません。"
            "環境変数またはカレントディレクトリの .env ファイルに設定してください。"
        )

    return OpenAI(api_key=api_key)


def generate_cache_key(pdf_paths: list[str]) -> str:
    """
    選択されたPDFの組み合わせからキャッシュキーを生成する。

    🧮 SHA256ハッシュ関数を使用。
    同一のPDFセット → 常に同一のキー（決定的）が得られるため、
    PDFが変更されない限りEmbeddingの再生成を回避できる。

    💡 【直感的意味】
    PDF群の「指紋」を生成する。ファイル名が1つでも変われば異なるキーになる。

    Args:
        pdf_paths: PDFファイルパスのリスト

    Returns:
        キャッシュキー文字列（16文字のhex）
    """
    # ファイル名のみを抽出してソートし、一意なキーを生成
    names: list[str] = sorted(Path(p).name for p in pdf_paths)
    combined: str = "|".join(names)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]


def generate_embeddings(
    texts: list[str],
    model: str = k_embeddingModel,
) -> np.ndarray:
    """
    テキストリストからEmbeddingベクトルを生成する。

    🧮 【Embedding生成の内部処理（OpenAI API側）】
    1. テキストをTokenize（BPE: Byte Pair Encoding）
    2. トークン列をTransformerエンコーダに入力
    3. 最終層の出力を平均プーリング（Mean Pooling）して固定長ベクトルを生成
    4. L2正規化して単位ベクトルに変換

    📐 【Shape の流れ】
    texts: List[str] (長さ n)
    → API call → List[List[float]] (n × embedding_dim)
    → np.array → Shape: (n, embedding_dim)

    💡 【直感的意味】
    テキストを「意味の座標」に変換する。
    この変換はニューラルネットワーク（Transformer）が行うため、
    単なるBag-of-Words（単語の出現頻度）ではなく、文脈を考慮した
    「深い意味」を捉えたベクトルが得られる。

    Args:
        texts: ベクトル化するテキストのリスト
        model: 使用するEmbeddingモデル名

    Returns:
        形状 (len(texts), embedding_dim) のnumpy配列
    """
    client: OpenAI = _get_client()
    # 📐 型: List[List[float]] — 最終的にnp.arrayに変換される
    all_embeddings: list[list[float]] = []

    # 💡 バッチ処理: APIの呼び出し回数を減らし、スループットを向上させる
    #    例: 500チャンク、バッチサイズ100 → 5回のAPI呼び出し
    for i in range(0, len(texts), k_batchSize):
        batch: list[str] = texts[i:i + k_batchSize]
        batch_num: int = i // k_batchSize + 1
        total_batches: int = (len(texts) + k_batchSize - 1) // k_batchSize
        print(f"  Embedding生成中... バッチ {batch_num}/{total_batches}")

        try:
            response = client.embeddings.create(
                input=batch,
                model=model,
            )
            # 📐 型: List[List[float]] — 各テキストのEmbeddingベクトル
            #    各要素のShape: (embedding_dim,) — 例: (1536,)
            batch_embeddings: list[list[float]] = [
                item.embedding for item in response.data
            ]
            all_embeddings.extend(batch_embeddings)
        except Exception as e:
            raise RuntimeError(f"Embedding API呼び出しに失敗しました: {e}")

    # 📐 Shape: (len(texts), embedding_dim) — 例: (500, 1536)
    # 💡 float32を使用（float64の半分のメモリで十分な精度を確保）
    return np.array(all_embeddings, dtype=np.float32)


def save_cache(
    embeddings: np.ndarray,
    chunks: list[dict],
    cache_key: str,
    cache_dir: Path = k_cacheDir,
) -> None:
    """
    Embeddingベクトルとチャンクデータをキャッシュに保存する。

    💡 Embeddingは .npy（NumPyバイナリ形式）で保存し、高速な読み書きを実現。
       チャンクメタデータは .json（人間が読めるテキスト形式）で保存。

    📐 保存されるファイル:
    - embeddings_{cache_key}.npy — Shape: (n_chunks, embedding_dim)
    - chunks_{cache_key}.json — List[Dict]

    Args:
        embeddings: Embeddingベクトルの配列
        chunks: チャンクデータのリスト
        cache_key: PDF組み合わせに基づくキャッシュキー
        cache_dir: キャッシュ保存先ディレクトリ
    """
    cache_dir.mkdir(parents=True, exist_ok=True)

    np.save(cache_dir / f"embeddings_{cache_key}.npy", embeddings)

    with open(cache_dir / f"chunks_{cache_key}.json", "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    print(f"  キャッシュ保存完了: {cache_dir}/ (キー: {cache_key})")


def load_cache(
    cache_key: str,
    cache_dir: Path = k_cacheDir,
) -> tuple[np.ndarray, list[dict]] | None:
    """
    キャッシュからEmbeddingベクトルとチャンクデータを読み込む。

    💡 キャッシュヒット時はAPI呼び出しが不要になるため、
       起動時間とコストの両方を大幅に削減できる。

    📐 読み込まれるデータ:
    - embeddings: Shape (n_chunks, embedding_dim)
    - chunks: List[Dict]

    Args:
        cache_key: PDF組み合わせに基づくキャッシュキー
        cache_dir: キャッシュ保存先ディレクトリ

    Returns:
        (embeddings, chunks) のタプル。キャッシュが存在しない場合は None。
    """
    embeddings_path = cache_dir / f"embeddings_{cache_key}.npy"
    chunks_path = cache_dir / f"chunks_{cache_key}.json"

    if not embeddings_path.exists() or not chunks_path.exists():
        return None

    try:
        embeddings: np.ndarray = np.load(embeddings_path)

        with open(chunks_path, "r", encoding="utf-8") as f:
            chunks: list[dict] = json.load(f)

        print(f"  キャッシュ読み込み完了: {len(chunks)} チャンク (キー: {cache_key})")
        return embeddings, chunks
    except Exception as e:
        print(f"  キャッシュ読み込み失敗（再生成します）: {e}")
        return None
