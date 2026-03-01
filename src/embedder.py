"""
Embedding生成モジュール。

OpenAI Embedding APIを直接呼び出し、テキストをベクトルに変換する。
結果はキャッシュファイル（.npy/.json）に保存し、再実行時の再生成を回避する。
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

# 使用するEmbeddingモデル
k_embeddingModel: str = EMBEDDING_MODEL

# Embedding生成のバッチサイズ
k_batchSize: int = EMBEDDING_BATCH_SIZE


def _get_client() -> OpenAI:
    """
    OpenAIクライアントを生成する。

    環境変数またはカレントディレクトリの.envからAPIキーを読み込む。
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

    ファイル名をソートして連結し、SHA256ハッシュの先頭16文字を返す。

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

    Args:
        texts: ベクトル化するテキストのリスト
        model: 使用するEmbeddingモデル名

    Returns:
        形状 (len(texts), embedding_dim) のnumpy配列
    """
    client: OpenAI = _get_client()
    all_embeddings: list[list[float]] = []

    # バッチ処理
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
            batch_embeddings: list[list[float]] = [
                item.embedding for item in response.data
            ]
            all_embeddings.extend(batch_embeddings)
        except Exception as e:
            raise RuntimeError(f"Embedding API呼び出しに失敗しました: {e}")

    return np.array(all_embeddings, dtype=np.float32)


def save_cache(
    embeddings: np.ndarray,
    chunks: list[dict],
    cache_key: str,
    cache_dir: Path = k_cacheDir,
) -> None:
    """
    Embeddingベクトルとチャンクデータをキャッシュに保存する。

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
