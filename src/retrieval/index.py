from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
import pandas as pd

from core.config import Settings
from core.utils import read_json, safe_slug, write_json
from retrieval.embeddings import MiniLMEmbeddings


@dataclass(frozen=True)
class SearchResult:
    paper_id: str
    title: str
    score: float
    content: str
    metadata: dict[str, Any]


class LocalEmbeddingIndex:
    def __init__(
        self,
        settings: Settings,
        collection_name: str,
        documents: list[dict[str, Any]],
        persist_path: Path,
    ):
        self.settings = settings
        self.collection_name = collection_name
        self.documents = documents
        self.persist_path = persist_path
        self.embedding_backend = "chroma"
        self.embedding_model = MiniLMEmbeddings(settings.embedding_model)
        self.client = chromadb.PersistentClient(path=str(persist_path))
        self.collection = self.client.get_collection(name=collection_name)
        self.documents_by_paper_id = {document["paper_id"].lower(): document for document in documents}
        self.documents_by_title = {document["title"].lower(): document for document in documents}

    @staticmethod
    def _build_documents(df: pd.DataFrame) -> list[dict[str, Any]]:
        records = df.to_dict(orient="records")
        documents: list[dict[str, Any]] = []
        for index, row in enumerate(records):
            documents.append(
                {
                    "record_id": f"{row['paper_id']}::{index}",
                    "paper_id": row["paper_id"],
                    "title": row["title"],
                    "content": row["text_for_embedding"],
                    "metadata": {
                        "paper_id": row["paper_id"],
                        "title": row["title"],
                        "published": row["published"],
                        "authors_joined": row["authors_joined"],
                        "categories_joined": row["categories_joined"],
                        "summary": row["summary"],
                        "abs_url": row["abs_url"],
                        "pdf_url": row["pdf_url"],
                    },
                }
            )
        return documents

    @staticmethod
    def _derive_collection_name(settings: Settings, embeddings_output_path: Path | None, collection_name_hint: str | None = None) -> str:
        """Derive collection name from embeddings output path or explicit hint.

        The hint (e.g. 'papers-live') takes priority. Otherwise falls back
        to path-based mapping:
          - data/embeddings/papers_embeddings.json   → papers-live   (authoritative)
          - data/embeddings/papers_embeddings_corrupted.json → papers-corrupted
          - data/embeddings/papers_embeddings_repaired.json   → papers-repaired
        """
        if collection_name_hint:
            return collection_name_hint

        if embeddings_output_path is None:
            return settings.baseline_collection_name

        name_map = {
            # Authoritative live collection (produced by phase1 / live pipeline)
            settings.paths.embeddings_json.resolve(): "papers-live",
            # Named collections for corruption flow
            settings.paths.corrupted_embeddings_json.resolve(): settings.corrupted_collection_name,
            settings.paths.repaired_embeddings_json.resolve(): settings.repaired_collection_name,
        }
        resolved_path = embeddings_output_path.resolve()
        if resolved_path in name_map:
            return name_map[resolved_path]
        return safe_slug(embeddings_output_path.stem)

    @classmethod
    def build(
        cls,
        df: pd.DataFrame,
        settings: Settings,
        embeddings_output_path: Path | None = None,
        collection_name: str | None = None,
    ) -> "LocalEmbeddingIndex":
        derived_name = cls._derive_collection_name(settings, embeddings_output_path)
        active_name = collection_name or derived_name
        documents = cls._build_documents(df)
        persist_path = settings.paths.chroma_dir
        persist_path.mkdir(parents=True, exist_ok=True)

        embedding_model = MiniLMEmbeddings(settings.embedding_model)
        client = chromadb.PersistentClient(path=str(persist_path))
        try:
            client.delete_collection(name=active_name)
        except Exception:
            pass
        collection = client.create_collection(
            name=active_name,
            metadata={"hnsw:space": "cosine"},
        )
        embeddings = embedding_model.embed_documents([document["content"] for document in documents])
        collection.add(
            ids=[document["record_id"] for document in documents],
            embeddings=embeddings,
            documents=[document["content"] for document in documents],
            metadatas=[document["metadata"] for document in documents],
        )

        manifest_path = embeddings_output_path or settings.paths.embeddings_json
        write_json(
            manifest_path,
            {
                "backend": "chroma",
                "embedding_model": settings.embedding_model,
                "persist_path": str(persist_path),
                "collection_name": active_name,
                "documents": documents,
            },
        )
        return cls(
            settings=settings,
            collection_name=active_name,
            documents=documents,
            persist_path=persist_path,
        )

    @classmethod
    def load(cls, settings: Settings, embeddings_path: Path | None = None) -> "LocalEmbeddingIndex":
        payload = read_json(embeddings_path or settings.paths.embeddings_json)
        return cls(
            settings=settings,
            collection_name=payload["collection_name"],
            documents=payload["documents"],
            persist_path=Path(payload["persist_path"]),
        )

    def search(self, query: str, top_k: int | None = None) -> list[SearchResult]:
        query_embedding = self.embedding_model.embed_query(query)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k or self.settings.top_k,
            include=["documents", "metadatas", "distances"],
        )
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        scored: list[SearchResult] = []
        for record_id, content, metadata, distance in zip(ids, documents, metadatas, distances, strict=False):
            if not record_id or not metadata or not content:
                continue
            scored.append(
                SearchResult(
                    paper_id=str(metadata["paper_id"]),
                    title=str(metadata["title"]),
                    score=max(0.0, 1.0 - float(distance or 0.0)),
                    content=str(content),
                    metadata=dict(metadata),
                )
            )
        return scored

    def lookup(self, value: str) -> dict[str, Any] | None:
        needle = value.strip().lower()
        if needle in self.documents_by_paper_id:
            return self.documents_by_paper_id[needle]
        if needle in self.documents_by_title:
            return self.documents_by_title[needle]
        return None


def upsert_documents(
    df: pd.DataFrame,
    settings: Settings,
    collection_name: str,
    embeddings_output_path: Path | None = None,
) -> LocalEmbeddingIndex:
    """Upsert documents into an existing Chroma collection without full rebuild.
    
    Adds NEW and UPDATED records only; does NOT re-embed UNCHANGED records.
    Persists manifest to track what has been indexed.
    """
    import chromadb
    
    persist_path = settings.paths.chroma_dir
    persist_path.mkdir(parents=True, exist_ok=True)
    
    embedding_model = MiniLMEmbeddings(settings.embedding_model)
    client = chromadb.PersistentClient(path=str(persist_path))
    
    try:
        collection = client.get_collection(name=collection_name)
    except Exception:
        collection = client.create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
    
    manifest_path = embeddings_output_path or (persist_path / f"{collection_name}_manifest.json")
    
    try:
        existing_manifest = read_json(manifest_path)
        existing_ids = set(existing_manifest.get("indexed_paper_ids", []))
    except Exception:
        existing_ids = set()
    
    records = df.to_dict(orient="records")
    new_documents = []
    new_embeddings = []
    new_ids = []
    new_metadatas = []
    
    for index, row in enumerate(records):
        paper_id = str(row["paper_id"])
        if paper_id in existing_ids:
            continue
        
        content = row.get("text_for_embedding", "")
        embedding = embedding_model.embed_documents([content])[0]
        
        record_id = f"{paper_id}::{index}"
        
        new_documents.append({
            "record_id": record_id,
            "paper_id": paper_id,
            "title": row.get("title", ""),
            "content": content,
            "metadata": {
                "paper_id": paper_id,
                "title": row.get("title", ""),
                "published": row.get("published", ""),
                "authors_joined": row.get("authors_joined", ""),
                "categories_joined": row.get("categories_joined", ""),
                "summary": row.get("summary", ""),
                "abs_url": row.get("abs_url", ""),
                "pdf_url": row.get("pdf_url", ""),
            },
        })
        new_ids.append(record_id)
        new_embeddings.append(embedding)
        new_metadatas.append(new_documents[-1]["metadata"])
        existing_ids.add(paper_id)
    
    if new_ids:
        collection.add(
            ids=new_ids,
            embeddings=new_embeddings,
            documents=[doc["content"] for doc in new_documents],
            metadatas=new_metadatas,
        )
    
    write_json(
        manifest_path,
        {
            "backend": "chroma",
            "embedding_model": settings.embedding_model,
            "persist_path": str(persist_path),
            "collection_name": collection_name,
            "indexed_paper_ids": list(existing_ids),
            "last_updated": str(settings.paths.project_dir),
        },
    )
    
    all_docs = [doc["metadata"] for doc in new_documents]
    return LocalEmbeddingIndex(
        settings=settings,
        collection_name=collection_name,
        documents=new_documents,
        persist_path=persist_path,
    )
