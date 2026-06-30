# controllers/vector_store.py

import chromadb
from chromadb.config import Settings
from database.config import CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME
import uuid

# ---------------------------
# Singleton Chroma Client
# ---------------------------
_chroma_client = chromadb.Client(
    Settings(
        persist_directory=CHROMA_PERSIST_DIR,
        anonymized_telemetry=False
    )
)

_collection = None


def get_global_collection():
    """
    Returns a singleton global ChromaDB collection
    shared across all uploads and users.
    """
    global _collection

    if _collection is None:
        _collection = _chroma_client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )

    return _collection


def push_unstructured_to_vector_db(filename, text_content, metadata=None):
    """
    Push unstructured document text into global ChromaDB
    (chunked, no manual embedding)
    """
    if not text_content or not text_content.strip():
        return

    collection = get_global_collection()

    # ---- Chunking (VERY IMPORTANT) ----
    chunk_size = 800
    overlap = 100
    words = text_content.split()

    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)

    if not chunks:
        return

    ids = [str(uuid.uuid4()) for _ in chunks]
    metadatas = [
        {
            "source_file": filename,
            "type": "unstructured",
            **(metadata or {})
        }
        for _ in chunks
    ]

    collection.add(
        documents=chunks,
        metadatas=metadatas,
        ids=ids
    )
