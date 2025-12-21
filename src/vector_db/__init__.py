"""
Dolmenwood AI DM - Vector Database Module

This module provides semantic search functionality using ChromaDB
with OpenAI embeddings for rules, monsters, and locations.
"""

from .rules_retriever import (
    RulesRetriever,
    SearchResult,
    CollectionType,
    create_retriever,
)

__all__ = [
    "RulesRetriever",
    "SearchResult",
    "CollectionType",
    "create_retriever",
]
