"""Embeddings from one pinned small model, identical at ingestion and on the device.

The pinned model is ``Xenova/bge-small-en-v1.5`` (33M params, 384 dims,
512-token window), run from its quantized ONNX export at a fixed revision.
That is the same file transformers.js loads by default in the browser, so
the PWA can embed questions with exactly the weights the compiler used for
the pack. Texts are embedded one at a time by default: the quantized model
computes activation scales per batch, so padding a batch shifts the vectors
slightly, and the browser always embeds a single unpadded text. Pooling is
the [CLS] token, L2-normalised (as bge specifies), and queries get bge's
retrieval prefix.

The id recorded in a pack's manifest (``EMBEDDING_MODEL_ID``) names the repo,
revision, file and pooling; the app must refuse semantic search on a pack
whose id differs (keyword search still works).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class EmbeddingSpec:
    repo: str
    revision: str
    onnx_file: str
    dim: int
    pooling: str
    max_tokens: int
    query_prefix: str

    @property
    def model_id(self) -> str:
        return f"{self.repo}@{self.revision[:12]}:{self.onnx_file}:{self.pooling}-l2"


PINNED = EmbeddingSpec(
    repo="Xenova/bge-small-en-v1.5",
    revision="ea104dacec62c0de699686887e3f920caeb4f3e3",
    onnx_file="onnx/model_quantized.onnx",
    dim=384,
    pooling="cls",
    max_tokens=512,
    query_prefix="Represent this sentence for searching relevant passages: ",
)
EMBEDDING_MODEL_ID = PINNED.model_id
DEFAULT_CACHE = Path(os.environ.get("TOME_MODEL_CACHE", ".cache/models"))


class Embedder(Protocol):
    model_id: str
    dim: int

    def embed_passages(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


class OnnxEmbedder:
    """The real embedder. Downloads the pinned files from Hugging Face once."""

    def __init__(
        self, spec: EmbeddingSpec = PINNED, cache_dir: Path = DEFAULT_CACHE, batch_size: int = 1
    ):
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        self.spec = spec
        self.model_id = spec.model_id
        self.dim = spec.dim
        self.batch_size = batch_size

        def fetch(name: str) -> str:
            return hf_hub_download(
                spec.repo, name, revision=spec.revision, cache_dir=str(cache_dir)
            )

        self.tokenizer = Tokenizer.from_file(fetch("tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=spec.max_tokens)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(
            fetch(spec.onnx_file), opts, providers=["CPUExecutionProvider"]
        )
        self.input_names = {i.name for i in self.session.get_inputs()}

    def _embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for start in range(0, len(texts), self.batch_size):
            batch = self.tokenizer.encode_batch(texts[start : start + self.batch_size])
            ids = np.array([e.ids for e in batch], dtype=np.int64)
            mask = np.array([e.attention_mask for e in batch], dtype=np.int64)
            feeds = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.input_names:
                feeds["token_type_ids"] = np.zeros_like(ids)
            hidden = self.session.run(None, feeds)[0]  # (batch, seq, dim)
            out[start : start + len(batch)] = hidden[:, 0, :]  # [CLS] pooling
        return _l2(out)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([self.spec.query_prefix + text])[0]


class HashEmbedder:
    """Deterministic bag-of-words embedder for tests. Not semantically meaningful."""

    model_id = "test/hash-embedder"

    def __init__(self, dim: int = 64):
        self.dim = dim

    def _one(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for word in text.lower().split():
            h = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=4).digest(), "little")
            v[h % self.dim] += 1.0
        return v

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return _l2(np.stack([self._one(t) for t in texts]))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_passages([text])[0]


def _l2(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.where(norms == 0, 1, norms)


def to_blob(vec: np.ndarray) -> bytes:
    """float32 little-endian, the layout the PWA reads with a Float32Array."""
    return np.asarray(vec, dtype="<f4").tobytes()


def from_blob(blob: bytes, dim: int) -> np.ndarray:
    v = np.frombuffer(blob, dtype="<f4")
    if v.shape != (dim,):
        raise ValueError(f"expected {dim} floats, got {v.shape}")
    return v


def pack_is_compatible(manifest_model_id: str | None, embedder_id: str = EMBEDDING_MODEL_ID):
    """Whether semantic search may be used on a pack (else: keyword search only)."""
    return manifest_model_id == embedder_id
