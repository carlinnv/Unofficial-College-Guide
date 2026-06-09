"""Embed document chunks and store them in ChromaDB.

This implements the "Embedding + Vector Store" stage from planning.md:

    Chunking -> [Embedding + Vector Store] -> Retrieval

Chunks come from chunk_documents.py. Each chunk is embedded with
sentence-transformers' all-MiniLM-L6-v2 model and persisted to a local
ChromaDB collection configured for cosine similarity, ready for the
top-k = 4 retrieval step.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import chromadb
from sentence_transformers import SentenceTransformer

from chunk_documents import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP,
    Chunk,
    chunk_documents,
)
from load_documents import load_documents_from_planning


ROOT_DIR = Path(__file__).resolve().parent
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
DEFAULT_PERSIST_DIR = ROOT_DIR / "chroma_db"
DEFAULT_COLLECTION = "unofficial_guide"
DEFAULT_BATCH_SIZE = 64
DEFAULT_TOP_K = 4


@dataclass(frozen=True)
class RetrievedChunk:
    """A single search hit: the chunk text, its metadata, and relevance score."""

    chunk_id: str
    text: str
    metadata: dict
    distance: float

    @property
    def similarity(self) -> float:
        """Cosine similarity in [0, 1] (1 - cosine distance)."""
        return 1.0 - self.distance


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Embed document chunks and store them in ChromaDB."
    )
    parser.add_argument(
        "--planning",
        type=Path,
        default=ROOT_DIR / "planning.md",
        help="Path to planning.md with the Documents table.",
    )
    parser.add_argument(
        "--index",
        type=int,
        default=None,
        help="Optional 1-based source index to load and embed only one document.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"Chunk size in characters (default: {DEFAULT_CHUNK_SIZE}).",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=DEFAULT_OVERLAP,
        help=f"Chunk overlap in characters (default: {DEFAULT_OVERLAP}).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="Delay between source fetches (passed to the loader).",
    )
    parser.add_argument(
        "--persist-dir",
        type=Path,
        default=DEFAULT_PERSIST_DIR,
        help=f"Directory for the persistent ChromaDB store (default: {DEFAULT_PERSIST_DIR}).",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=DEFAULT_COLLECTION,
        help=f"ChromaDB collection name (default: {DEFAULT_COLLECTION}).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Number of chunks to embed per batch (default: {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Run retrieval for this query against the existing store instead of embedding.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help=f"Number of chunks to retrieve for --query (default: {DEFAULT_TOP_K}).",
    )
    return parser.parse_args()


def load_chunks(
    planning_path: Path,
    chunk_size: int,
    overlap: int,
    sleep: float,
    index: int | None,
) -> list[Chunk]:
    """Fetch, clean, and chunk the planning.md sources."""
    documents = load_documents_from_planning(
        planning_path=planning_path,
        sleep=sleep,
        index=index,
    )
    return chunk_documents(documents=documents, chunk_size=chunk_size, overlap=overlap)


def embed_texts(
    model: SentenceTransformer, texts: Sequence[str], batch_size: int
) -> list[list[float]]:
    """Embed chunk texts with all-MiniLM-L6-v2.

    Normalized embeddings are used so cosine similarity behaves consistently
    with the cosine-distance space configured on the ChromaDB collection.
    """
    embeddings = model.encode(
        list(texts),
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return embeddings.tolist()


def get_collection(
    persist_dir: Path, collection_name: str
) -> chromadb.api.models.Collection.Collection:
    """Open (or create) a persistent cosine-similarity collection."""
    client = chromadb.PersistentClient(path=str(persist_dir))
    return client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def retrieve(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    persist_dir: Path = DEFAULT_PERSIST_DIR,
    collection_name: str = DEFAULT_COLLECTION,
    model: SentenceTransformer | None = None,
) -> list[RetrievedChunk]:
    """Return the top-k most relevant chunks for a query string.

    The query is embedded with the same all-MiniLM-L6-v2 model used at
    ingest time, then matched against the stored vectors by cosine
    similarity. Pass an already-loaded ``model`` to avoid reloading it on
    repeated queries.
    """
    if not query.strip():
        return []

    if model is None:
        model = SentenceTransformer(EMBEDDING_MODEL)

    query_embedding = model.encode(
        [query],
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).tolist()

    collection = get_collection(persist_dir, collection_name)
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    # Chroma nests one list per query; we only sent one query, so take index 0.
    ids = results["ids"][0]
    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    return [
        RetrievedChunk(
            chunk_id=chunk_id,
            text=document,
            metadata=metadata,
            distance=distance,
        )
        for chunk_id, document, metadata, distance in zip(
            ids, documents, metadatas, distances
        )
    ]


def store_chunks(
    collection: chromadb.api.models.Collection.Collection,
    chunks: Sequence[Chunk],
    embeddings: Sequence[Sequence[float]],
) -> None:
    """Upsert chunk embeddings, documents, and metadata into ChromaDB."""
    ids = [chunk.chunk_id for chunk in chunks]
    documents = [chunk.text for chunk in chunks]
    metadatas = [
        {
            "source_index": chunk.source_index,
            "source_name": chunk.source_name,
            "source_description": chunk.source_description,
            "source_url": chunk.source_url,
            "chunk_index": chunk.chunk_index,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
        }
        for chunk in chunks
    ]

    # upsert keeps re-runs idempotent: stable chunk_ids overwrite prior vectors.
    collection.upsert(
        ids=ids,
        embeddings=list(embeddings),
        documents=documents,
        metadatas=metadatas,
    )


def embed_and_store(
    chunks: Sequence[Chunk],
    persist_dir: Path,
    collection_name: str,
    batch_size: int,
) -> int:
    """Embed every chunk and persist it to ChromaDB. Returns the stored count."""
    if not chunks:
        print("No chunks to embed.")
        return 0

    print(f"Loading embedding model: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)

    print(f"Embedding {len(chunks)} chunks...")
    embeddings = embed_texts(model, [chunk.text for chunk in chunks], batch_size)

    print(f"Storing vectors in ChromaDB at {persist_dir} (collection: {collection_name})")
    collection = get_collection(persist_dir, collection_name)
    store_chunks(collection, chunks, embeddings)

    return collection.count()


def print_results(query: str, results: Sequence[RetrievedChunk]) -> None:
    print(f'Query: "{query}"')
    if not results:
        print("No results. Has the store been populated yet?")
        return

    for rank, hit in enumerate(results, start=1):
        print("=" * 80)
        print(
            f"#{rank}  {hit.chunk_id}  similarity={hit.similarity:.3f}  "
            f"source={hit.metadata.get('source_name')} ({hit.metadata.get('source_url')})"
        )
        print("-" * 80)
        print(hit.text)
        print()


def main() -> int:
    args = parse_arguments()

    if args.query is not None:
        results = retrieve(
            query=args.query,
            top_k=args.top_k,
            persist_dir=args.persist_dir,
            collection_name=args.collection,
        )
        print_results(args.query, results)
        return 0

    chunks = load_chunks(
        planning_path=args.planning,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        sleep=args.sleep,
        index=args.index,
    )

    stored = embed_and_store(
        chunks=chunks,
        persist_dir=args.persist_dir,
        collection_name=args.collection,
        batch_size=args.batch_size,
    )

    print(f"chunks_embedded: {len(chunks)}")
    print(f"vectors_in_collection: {stored}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
