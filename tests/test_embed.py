import numpy as np
import pytest

from tome.embed import (
    EMBEDDING_MODEL_ID,
    PINNED,
    HashEmbedder,
    OnnxEmbedder,
    from_blob,
    pack_is_compatible,
    to_blob,
)


def test_model_id_pins_repo_revision_file_and_pooling():
    assert EMBEDDING_MODEL_ID.startswith("Xenova/bge-small-en-v1.5@ea104dacec62")
    assert "onnx/model_quantized.onnx" in EMBEDDING_MODEL_ID and EMBEDDING_MODEL_ID.endswith(
        "cls-l2"
    )
    assert PINNED.dim == 384


def test_blob_round_trip():
    v = np.arange(4, dtype=np.float32) / 3
    assert np.array_equal(from_blob(to_blob(v), 4), v)
    assert len(to_blob(v)) == 16
    with pytest.raises(ValueError):
        from_blob(to_blob(v), 5)


def test_compatibility_check():
    assert pack_is_compatible(EMBEDDING_MODEL_ID)
    assert not pack_is_compatible("sentence-transformers/all-MiniLM-L6-v2")
    assert not pack_is_compatible(None)


def test_hash_embedder_is_deterministic_and_normalised():
    e = HashEmbedder()
    a, b = e.embed_passages(["the abbé", "the abbé"])
    assert np.allclose(a, b) and np.isclose(np.linalg.norm(a), 1.0)


@pytest.mark.model
def test_pinned_onnx_model_embeds_sensibly():
    """Downloads ~34 MB from Hugging Face once (run with --run-model)."""
    e = OnnxEmbedder()
    passages = [
        "Dantès escaped from the Château d'If sewn into a burial sack and thrown into the sea.",
        "The three-master Pharaon arrived at Marseilles from Smyrna, Trieste and Naples.",
        "Haydée is the daughter of Ali Tepelini, the Pasha of Yanina.",
    ]
    m = e.embed_passages(passages)
    assert m.shape == (3, 384) and m.dtype == np.float32
    assert np.allclose(np.linalg.norm(m, axis=1), 1.0, atol=1e-4)
    q = e.embed_query("How did the prisoner get out of the fortress?")
    assert int(np.argmax(m @ q)) == 0
    q2 = e.embed_query("Whose child is the Greek girl?")
    assert int(np.argmax(m @ q2)) == 2
    # Default (unbatched) embedding is deterministic per text, as in the browser.
    assert np.array_equal(e.embed_passages(passages[:1])[0], m[0])
