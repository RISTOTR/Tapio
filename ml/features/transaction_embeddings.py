"""Frozen local E5 features; private content-addressed cache, never an API upload."""

import json
import os
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np

from ml.features.transactions import fingerprint

MODEL = "intfloat/multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
DIMENSION = 384


def cache_identity(texts):
    return fingerprint(
        {
            "model": MODEL,
            "revision": REVISION,
            "texts": texts,
            "prefix": "query: ",
            "normalize": True,
            "max_tokens": 512,
            "dtype": "float32",
            "format": 1,
            "stack": {
                p: version(p) for p in ("torch", "transformers", "sentence-transformers", "numpy")
            },
        }
    )


def validate_embeddings(array, rows):
    if array.shape != (rows, DIMENSION) or not np.isfinite(array).all():
        raise ValueError("Invalid embedding matrix")
    if not np.allclose(np.linalg.norm(array, axis=1), 1, atol=1e-5):
        raise ValueError("Embeddings must be normalized")


def embeddings(texts, root, *, refresh=False):
    os.environ.setdefault("HF_HOME", str(Path(root) / "huggingface"))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    import torch
    from sentence_transformers import SentenceTransformer

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    identity = cache_identity(texts)
    path = root / f"{identity}.npy"
    config = {
        "model": MODEL,
        "revision": REVISION,
        "dimension": DIMENSION,
        "device": "cpu",
        "normalize": True,
        "prefix": "query: ",
        "max_tokens": 512,
        "cache_fingerprint": identity,
        "threads": 1,
    }
    if path.exists() and not refresh:
        array = np.load(path, allow_pickle=False)
        validate_embeddings(array, len(texts))
        return array, {**config, "cache_hit": True, "runtime_seconds": 0.0}
    torch.set_num_threads(1)
    torch.manual_seed(42)
    torch.use_deterministic_algorithms(True)
    start = time.perf_counter()
    model = SentenceTransformer(
        MODEL,
        revision=REVISION,
        device="cpu",
        cache_folder=str(root / "huggingface"),
        trust_remote_code=False,
        model_kwargs={"use_safetensors": True},
    )
    model.max_seq_length = 512
    array = model.encode(
        ["query: " + text for text in texts],
        batch_size=8,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    ).astype(np.float32)
    validate_embeddings(array, len(texts))
    delta = (
        float(np.max(np.abs(np.load(path, allow_pickle=False) - array))) if path.exists() else None
    )
    np.save(path, array, allow_pickle=False)
    metadata = {
        **config,
        "cache_hit": False,
        "runtime_seconds": time.perf_counter() - start,
        "previous_cache_max_absolute_delta": delta,
    }
    path.with_suffix(".json").write_text(json.dumps(metadata, indent=2))
    return array, metadata
