"""Zero-shot class probabilities from cached embeddings. See docs/VARUN_IMPLEMENTATION.md §6 T50.

Reuses the cached image embeddings (embed.py) against the class text
embeddings directly, so no image ever needs re-encoding here.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import torch

from .clip_model import CLASSES, _T
from .embed import CACHE_PATH as EMBEDDINGS_CACHE

ZEROSHOT_CACHE = Path("cctv/classifier/cache/zeroshot_v0.parquet")

# Matches the H6 column names in §6 T53 (p_normal, p_waterlogging, p_flooding, p_severe, p_unusable).
_PROB_COLUMN = {
    "NORMAL": "p_normal",
    "WATERLOGGING": "p_waterlogging",
    "FLOODING": "p_flooding",
    "SEVERE_FLOODING": "p_severe",
    "UNUSABLE": "p_unusable",
}


def _probs_from_embeddings(emb: np.ndarray) -> np.ndarray:
    f = torch.nn.functional.normalize(torch.tensor(emb, dtype=torch.float32), dim=-1)
    p = (100.0 * f @ _T.detach().cpu().T).softmax(-1)   # _T lives on the GPU when CUDA is available
    return p.numpy()


def _already_cached(cache_path: Path) -> set[str]:
    if not cache_path.exists():
        return set()
    return set(pd.read_parquet(cache_path, columns=["sha1"])["sha1"])


def write_zeroshot(embeddings_cache: Path = EMBEDDINGS_CACHE, zeroshot_cache: Path = ZEROSHOT_CACHE) -> int:
    """Returns the number of newly scored frames."""
    if not embeddings_cache.exists():
        return 0
    embeddings = pd.read_parquet(embeddings_cache)
    cached = _already_cached(zeroshot_cache)
    new = embeddings[~embeddings["sha1"].isin(cached)]
    if new.empty:
        return 0

    emb_matrix = np.stack(new["emb"].apply(np.asarray).to_numpy()).astype("float32")
    probs = _probs_from_embeddings(emb_matrix)

    rows = []
    for (_, row), p in zip(new.iterrows(), probs):
        entry = {"sha1": row["sha1"], "cam_id": row["cam_id"], "ts_utc": row["ts_utc"]}
        for cls, val in zip(CLASSES, p):
            entry[_PROB_COLUMN[cls]] = float(val)
        entry["argmax_class"] = CLASSES[int(np.argmax(p))]
        rows.append(entry)
    new_df = pd.DataFrame(rows)

    zeroshot_cache.parent.mkdir(parents=True, exist_ok=True)
    if zeroshot_cache.exists():
        out = pd.concat([pd.read_parquet(zeroshot_cache), new_df], ignore_index=True)
    else:
        out = new_df
    out.to_parquet(zeroshot_cache, index=False)
    return len(new_df)


def main() -> None:
    n = write_zeroshot()
    print(f"wrote zero-shot probs for {n} new frame(s) -> {ZEROSHOT_CACHE}")


if __name__ == "__main__":
    main()
