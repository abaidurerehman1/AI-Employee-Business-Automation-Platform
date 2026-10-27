import math

import httpx

from app.core.config import settings


class EmbeddingError(Exception):
    pass


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not settings.openai_api_key:
        raise EmbeddingError("OpenAI API key is not configured")
    if not texts:
        return []
    embeddings = []
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            for start in range(0, len(texts), 64):
                batch = texts[start : start + 64]
                response = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                    json={
                        "model": settings.embedding_model,
                        "input": batch,
                        "encoding_format": "float",
                        "dimensions": 1536,
                    },
                )
                response.raise_for_status()
                data = sorted(response.json()["data"], key=lambda item: item["index"])
                if len(data) != len(batch) or [item["index"] for item in data] != list(
                    range(len(batch))
                ):
                    raise EmbeddingError("Embedding response did not match input")
                for item in data:
                    vector = item["embedding"]
                    if len(vector) != 1536 or not all(
                        isinstance(value, (float, int)) and math.isfinite(value) for value in vector
                    ):
                        raise EmbeddingError("Embedding response has invalid dimensions")
                    embeddings.append(vector)
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise EmbeddingError("Embedding service failed; check configuration and retry") from exc
    return embeddings
