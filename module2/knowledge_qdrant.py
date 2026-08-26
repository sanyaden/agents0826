"""
М2 — той самий retriever, але у векторній БД (Qdrant).

Інтерфейс не змінився: retrieve() / as_context(). Агент про заміну сховища
не дізнається — саме в цьому й пуант шару знань.

Три режими, обирається сам — ЖОДЕН не потрібен для заняття, крім першого:
  нічого не задано    → вбудований ":memory:" — нуль інфраструктури, БЕЗ ключів
  QDRANT_URL          → свій сервер (docker run -p 6333:6333 qdrant/qdrant)
  QDRANT_URL + QDRANT_API_KEY → Qdrant Cloud (ключ з консолі кластера)

Що зʼявляється порівняно з in-memory списком (knowledge_vec.py):
  · окреме сховище: індекс переживає перезапуск процесу (на сервері)
  · payload — метадані поруч з вектором (у нас: номер правила, тема)
  · фільтри по метаданих + ANN-пошук замість повного перебору

    python knowledge_qdrant.py            # демо: індексація + 3 запити
    python knowledge_qdrant.py --filter   # пошук лише серед правил про повернення
"""

import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

try:
    from qdrant_client import QdrantClient, models
except ImportError:
    raise SystemExit("Потрібен клієнт:  pip install qdrant-client")

from domain.knowledge import KB

COLLECTION = "postal_rules"
MODEL_NAME = "intfloat/multilingual-e5-small"
THRESHOLD = 0.78            # той самий поріг, що й у knowledge_vec.py

_model = None
_client: QdrantClient | None = None


def _encode(texts: list[str], kind: str) -> list[list[float]]:
    """kind: 'query' | 'passage' — префікси потрібні моделям e5."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise SystemExit("Потрібно:  pip install sentence-transformers")
        _model = SentenceTransformer(MODEL_NAME)
    vecs = _model.encode([f"{kind}: {t}" for t in texts], normalize_embeddings=True)
    return [v.tolist() for v in vecs]


def _topic(keys: str) -> str:
    """Груба тема правила — щоб було що покласти в payload і чим фільтрувати."""
    for word, topic in (("повернення", "refund"), ("компенсація", "compensation"),
                        ("претензія", "claim"), ("розшук", "claim"),
                        ("тариф", "tariff"), ("оператор", "service")):
        if word in keys:
            return topic
    return "other"


def client() -> QdrantClient:
    """Сервер, якщо заданий QDRANT_URL; інакше вбудований режим.

    QDRANT_API_KEY потрібен ЛИШЕ для Qdrant Cloud. Локальний docker-сервер
    і вбудований режим працюють без жодних ключів.
    """
    global _client
    if _client is None:
        url = os.getenv("QDRANT_URL")
        if url:
            api_key = os.getenv("QDRANT_API_KEY") or None
            _client = QdrantClient(url=url, api_key=api_key)
        else:
            _client = QdrantClient(":memory:")
        _ensure_collection(_client)
    return _client


def _ensure_collection(c: QdrantClient) -> None:
    if c.collection_exists(COLLECTION):
        return
    dim = len(_encode(["проба"], "passage")[0])
    c.create_collection(
        COLLECTION,
        vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
    )
    vectors = _encode([f"{keys}. {text}" for keys, text in KB], "passage")
    c.upsert(COLLECTION, points=[
        models.PointStruct(
            id=i,
            vector=vec,
            payload={"text": text, "keys": keys, "topic": _topic(keys)},
        )
        for i, (vec, (keys, text)) in enumerate(zip(vectors, KB))
    ])


def retrieve(query: str, k: int = 3, topic: str | None = None) -> list[str]:
    """Той самий контракт, що й у лексичного та in-memory retriever'а."""
    flt = None
    if topic:
        flt = models.Filter(must=[models.FieldCondition(
            key="topic", match=models.MatchValue(value=topic))])
    hits = client().query_points(
        COLLECTION,
        query=_encode([query], "query")[0],
        limit=k,
        query_filter=flt,
        score_threshold=THRESHOLD,      # fail-closed на рівні БД
    ).points
    return [h.payload["text"] for h in hits]


def as_context(query: str, k: int = 3) -> str:
    hits = retrieve(query, k)
    if not hits:
        return ""                        # нічого не знайшли — не вигадуємо
    return "\n\nВитяг з бази знань:\n" + "\n---\n".join(hits)


if __name__ == "__main__":
    mode = os.getenv("QDRANT_URL") or ":memory: (вбудований, без Docker і без ключів)"
    print(f"Сховище: {mode}\nКолекція: {COLLECTION}, правил у KB: {len(KB)}\n")

    if "--filter" in sys.argv:
        q = "Що мені виплатять за втрачене вкладення?"
        print(f"Запит: «{q}»  (фільтр topic=compensation)")
        for t in retrieve(q, 3, topic="compensation"):
            print("  ·", t[:95])
        raise SystemExit

    for q in ("Кур'єр загубив мій пакунок, що мені виплатять?",
              "Скільки чекати виплату після повернення?",
              "Яка погода у Львові?"):
        hits = retrieve(q)
        print(f"Запит: «{q}»")
        if hits:
            for t in hits[:2]:
                print("  ·", t[:95])
        else:
            print("  — нічого понад поріг (fail-closed): агент не вигадуватиме правило")
        print()
