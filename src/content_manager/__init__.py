"""
Content Manager Module

Provides source tracking and conflict resolution for Dolmenwood content.
"""

from .content_manager import (
    ContentManager,
    ContentManagerError,
    SourceNotFoundError,
    SourceIntegrityError,
    create_content_manager,
    create_core_book_source,
    create_adventure_source,
)

__all__ = [
    "ContentManager",
    "ContentManagerError",
    "SourceNotFoundError",
    "SourceIntegrityError",
    "create_content_manager",
    "create_core_book_source",
    "create_adventure_source",
]
