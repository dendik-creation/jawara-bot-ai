"""Embedder behaviour that the RAG path depends on."""

import math

import pytest

from app.embeddings.hashing import HashingEmbedder

embedder = HashingEmbedder(1536)


async def test_vectors_match_the_configured_dimension():
    vectors = await embedder.embed(["air rebusan daun kitolod"])
    assert len(vectors[0]) == 1536
    embedder.ensure_dimension(vectors)


async def test_embeddings_are_deterministic_across_calls():
    # Qdrant stores these; a randomised hash would silently invalidate every
    # stored vector on restart.
    first = await embedder.embed(["benarkah bansos cair minggu depan"])
    second = await embedder.embed(["benarkah bansos cair minggu depan"])
    assert first == second


async def test_vectors_are_l2_normalised_for_cosine_distance():
    vector = (await embedder.embed(["klaim daun kitolod katarak"]))[0]
    assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0, rel_tol=1e-9)


async def test_near_duplicate_text_scores_far_above_unrelated_text():
    claim, restated, unrelated = await embedder.embed(
        [
            "air rebusan daun kitolod menyembuhkan katarak tanpa operasi",
            "air rebusan daun kitolod menyembuhkan katarak tanpa operasi dokter",
            "jadwal kereta api jakarta bandung besok pagi",
        ]
    )

    def cosine(left, right):
        return sum(a * b for a, b in zip(left, right))

    assert cosine(claim, restated) > 0.8
    assert cosine(claim, unrelated) < 0.2


async def test_empty_text_is_representable_without_a_zero_vector():
    # Qdrant rejects zero vectors under cosine distance.
    vector = (await embedder.embed([""]))[0]
    assert any(value != 0.0 for value in vector)


async def test_dimension_mismatch_is_caught_loudly():
    with pytest.raises(ValueError, match="expects"):
        embedder.ensure_dimension([[0.0] * 768])


async def test_alternative_dimension_is_configuration_not_code():
    indobert_sized = HashingEmbedder(768)
    vectors = await indobert_sized.embed(["halo"])
    assert len(vectors[0]) == 768
