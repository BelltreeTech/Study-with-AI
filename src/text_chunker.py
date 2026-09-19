"""Bounded page-local chunks with stable provenance and no duplicate tail."""
from __future__ import annotations

import hashlib


def chunk_text(pages: list[dict], chunk_size: int = 400, overlap: int = 60) -> list[dict]:
    if chunk_size < 1 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_sizeは正、overlapは0以上chunk_size未満にしてください")
    chunks: list[dict] = []
    for page in pages:
        text = page["text"]
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            if end < len(text):
                region_start = max(start + overlap + 1, end - 80)
                region = text[region_start:end]
                boundaries = [region.rfind(delimiter) + len(delimiter)
                              for delimiter in ("\n", "。", "！", "？", ". ", "? ")
                              if delimiter in region]
                if boundaries:
                    end = region_start + max(boundaries)
            content = text[start:end].strip()
            if content:
                provenance = {k: page[k] for k in ("source_file", "document_id", "content_hash") if k in page}
                identity = f"{provenance}|{page['page_number']}|{start}|{content}"
                digest = hashlib.sha256(identity.encode()).hexdigest()
                chunks.append({**provenance, "text": content,
                               "page_number": page["page_number"], "chunk_index": len(chunks),
                               "char_start": start, "char_end": end,
                               "chunk_id": digest, "source_id": "S-" + digest[:20]})
            if end >= len(text):
                break
            start = max(start + 1, end - overlap)
    return chunks
