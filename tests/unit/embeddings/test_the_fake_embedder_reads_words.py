"""The offline embedder ranks a text by the words it shares with the query."""

from __future__ import annotations

from veupathdb_mcp.embeddings.fake import FakeEmbedder

_TITLE = "5 asexual and sexual stage transcriptomes"
_NAMED = f"{_TITLE} RNA-Seq of the asexual blood stages, gametocytes and ookinetes"
_STUDIES = [
    *(f"Study {n} of heat shock in mutant line {n}" for n in range(60)),
    _NAMED,
    *(f"Infection time course {n} in cell line {n}" for n in range(60)),
]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_a_title_finds_the_study_it_names() -> None:
    embedder = FakeEmbedder()
    query = await embedder.embed_query(_TITLE)
    studies = await embedder.embed_documents(_STUDIES)

    scores = [_cosine(query, study) for study in studies]

    assert _STUDIES[scores.index(max(scores))] == _NAMED


async def test_one_text_always_gives_one_vector() -> None:
    embedder = FakeEmbedder()

    first = await embedder.embed_query(_TITLE)
    second = await embedder.embed_documents([_TITLE])

    assert second == [first]
    assert abs(_cosine(first, first) - 1.0) < 1e-9
