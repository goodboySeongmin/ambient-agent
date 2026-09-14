from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer


MODEL_NAME = "intfloat/multilingual-e5-small"

SEMANTIC_SIMILARITY_THRESHOLD = 0.80


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    """
    Embedding model은 프로세스당 한 번만 로드한다.
    """

    return SentenceTransformer(
        MODEL_NAME
    )


def normalize_query(
    query: str,
) -> str:
    return " ".join(
        query
        .strip()
        .lower()
        .split()
    )


def embed_queries(
    queries: list[str],
) -> np.ndarray:

    if not queries:
        return np.empty(
            (0, 0),
            dtype=np.float32,
        )

    model = get_embedding_model()

    normalized_queries = [
        normalize_query(query)
        for query in queries
    ]

    embeddings = model.encode(
        normalized_queries,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    return embeddings


def cosine_similarity(
    vector_a: np.ndarray,
    vector_b: np.ndarray,
) -> float:

    # normalize_embeddings=True이므로
    # dot product == cosine similarity
    return float(
        np.dot(
            vector_a,
            vector_b,
        )
    )


def calculate_search_similarity_pairs(
    search_queries: list[str],
) -> list[dict]:
    """
    시간 순서상 인접한 검색 query끼리
    semantic similarity를 계산한다.

    Q1 -> Q2
    Q2 -> Q3
    Q3 -> Q4
    """

    if len(search_queries) < 2:
        return []

    normalized_queries = [
        normalize_query(query)
        for query in search_queries
    ]

    embeddings = embed_queries(
        normalized_queries
    )

    results = []

    for index in range(
        1,
        len(normalized_queries),
    ):

        previous_query = (
            normalized_queries[
                index - 1
            ]
        )

        current_query = (
            normalized_queries[
                index
            ]
        )

        similarity = cosine_similarity(
            embeddings[index - 1],
            embeddings[index],
        )

        results.append(
            {
                "pair_index": index,

                "previous_query":
                    previous_query,

                "current_query":
                    current_query,

                "similarity": round(
                    similarity,
                    4,
                ),

                "threshold":
                    SEMANTIC_SIMILARITY_THRESHOLD,

                "is_semantic_loop": (
                    similarity
                    >=
                    SEMANTIC_SIMILARITY_THRESHOLD
                ),
            }
        )

    return results


def calculate_semantic_search_features(
    search_queries: list[str],
) -> dict:

    similarity_pairs = (
        calculate_search_similarity_pairs(
            search_queries
        )
    )

    if not similarity_pairs:

        return {
            "semantic_search_pair_count": 0,
            "semantic_search_loop_count": 0,
            "semantic_search_similarity_avg": 0.0,
            "semantic_search_similarity_max": 0.0,
        }

    similarities = [
        pair["similarity"]
        for pair
        in similarity_pairs
    ]

    semantic_loop_count = sum(
        1
        for pair
        in similarity_pairs
        if pair["is_semantic_loop"]
    )

    similarity_avg = (
        sum(similarities)
        / len(similarities)
    )

    similarity_max = max(
        similarities
    )

    return {
        "semantic_search_pair_count":
            len(similarity_pairs),

        "semantic_search_loop_count":
            semantic_loop_count,

        "semantic_search_similarity_avg":
            round(
                similarity_avg,
                4,
            ),

        "semantic_search_similarity_max":
            round(
                similarity_max,
                4,
            ),
    }