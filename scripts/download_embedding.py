"""Explicit first-time model download. Application imports never call this script."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.embedder import E5_MODEL, E5_REVISION, default_model_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the pinned multilingual E5 model (network required)")
    parser.add_argument("--destination", type=Path, default=default_model_dir())
    args = parser.parse_args()
    from huggingface_hub import snapshot_download
    destination = args.destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    marker = destination / "study-model.json"
    if marker.exists():
        existing = json.loads(marker.read_text())
        if existing.get("model") != E5_MODEL or existing.get("revision") != E5_REVISION:
            raise SystemExit("Destination contains a different model. Choose a new destination.")
    snapshot_download(repo_id=E5_MODEL, revision=E5_REVISION, local_dir=destination,
                      allow_patterns=["*.json", "*.txt", "*.model", "*.safetensors"],
                      token=False)
    manifest = {"model": E5_MODEL, "revision": E5_REVISION, "license": "MIT",
                "source": f"https://huggingface.co/{E5_MODEL}/tree/{E5_REVISION}"}
    temp = destination / f".study-model.{os.getpid()}.tmp"
    temp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, marker)
    print(f"Model saved: {destination}")
    print("Normal embedding/search uses this local snapshot without network access.")


if __name__ == "__main__":
    main()
