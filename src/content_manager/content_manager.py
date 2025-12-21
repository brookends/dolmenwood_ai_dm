"""
Dolmenwood AI Dungeon Master - Content Source Manager (v1.1)

This module manages content sources and resolves conflicts when multiple
sources provide the same information.

Features:
- SQLite database for persistent source tracking
- Source registration and retrieval
- Priority-based conflict resolution
- File integrity verification (SHA-256 hashing)
- In-memory caching for performance

Author: AI Dungeon Master Project
Version: 1.1
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_models import ContentSource, SourceType, SourceReference


# Configure logging
logger = logging.getLogger(__name__)


class ContentManagerError(Exception):
    """Base exception for ContentManager errors."""
    pass


class SourceNotFoundError(ContentManagerError):
    """Raised when a requested source is not found."""
    pass


class SourceIntegrityError(ContentManagerError):
    """Raised when source file integrity check fails."""
    pass


class ContentManager:
    """
    Manage content sources and resolve conflicts.
    
    This handles:
    - Registering content sources (core books, adventures)
    - Tracking which book content came from
    - Resolving conflicts when multiple sources provide info
    - Version tracking and updates
    - File integrity verification
    
    Attributes:
        db_path: Path to SQLite database file.
        conn: SQLite database connection.
        sources: In-memory cache of ContentSource objects.
    
    Example:
        >>> manager = ContentManager("./data/content_sources.db")
        >>> source = ContentSource(
        ...     source_id="players_book",
        ...     source_type=SourceType.CORE_RULEBOOK,
        ...     book_name="Dolmenwood Player's Book",
        ...     book_code="players_book",
        ...     file_path="/path/to/players.pdf"
        ... )
        >>> manager.register_source(source)
        >>> retrieved = manager.get_source("players_book")
        >>> print(retrieved.book_name)
        Dolmenwood Player's Book
    """
    
    def __init__(self, db_path: str = "./data/content_sources.db"):
        """
        Initialize the ContentManager.
        
        Args:
            db_path: Path to SQLite database file. Will be created if
                     it doesn't exist.
        """
        self.db_path = db_path
        
        # Ensure parent directory exists
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        
        # Connect to database
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Enable dict-like access
        
        # Initialize database schema
        self._init_database()
        
        # In-memory cache for quick lookups
        self.sources: dict[str, ContentSource] = {}
        self._load_sources()
        
        logger.info(f"ContentManager initialized with database: {db_path}")
    
    def _init_database(self) -> None:
        """Create database schema for content tracking."""
        cursor = self.conn.cursor()
        
        # Content sources table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS content_sources (
                source_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                book_name TEXT NOT NULL,
                book_code TEXT NOT NULL,
                version TEXT NOT NULL DEFAULT '1.0',
                publication_date TEXT,
                publisher TEXT DEFAULT 'Necrotic Gnome',
                file_path TEXT NOT NULL,
                file_hash TEXT,
                page_count INTEGER,
                imported_at TEXT NOT NULL,
                last_updated TEXT NOT NULL
            )
        """)
        
        # Content conflicts table - tracks when multiple sources have same info
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS content_conflicts (
                conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id TEXT NOT NULL,
                content_type TEXT NOT NULL,
                source_id_1 TEXT NOT NULL,
                source_id_2 TEXT NOT NULL,
                conflict_description TEXT,
                resolution TEXT,
                resolved_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (source_id_1) REFERENCES content_sources(source_id),
                FOREIGN KEY (source_id_2) REFERENCES content_sources(source_id)
            )
        """)
        
        # Index for faster conflict lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conflicts_content_id 
            ON content_conflicts(content_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conflicts_sources 
            ON content_conflicts(source_id_1, source_id_2)
        """)
        
        # Source metadata table for additional key-value data
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS source_metadata (
                source_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                PRIMARY KEY (source_id, key),
                FOREIGN KEY (source_id) REFERENCES content_sources(source_id)
            )
        """)
        
        self.conn.commit()
        logger.debug("Database schema initialized")
    
    def _load_sources(self) -> None:
        """Load all sources from database into cache."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM content_sources")
        
        for row in cursor.fetchall():
            try:
                source = ContentSource(
                    source_id=row["source_id"],
                    source_type=SourceType(row["source_type"]),
                    book_name=row["book_name"],
                    book_code=row["book_code"],
                    version=row["version"],
                    publication_date=row["publication_date"],
                    publisher=row["publisher"] or "Necrotic Gnome",
                    file_path=row["file_path"],
                    file_hash=row["file_hash"],
                    page_count=row["page_count"],
                    imported_at=datetime.fromisoformat(row["imported_at"]),
                    last_updated=datetime.fromisoformat(row["last_updated"])
                )
                self.sources[source.source_id] = source
            except Exception as e:
                logger.warning(f"Failed to load source {row['source_id']}: {e}")
        
        logger.debug(f"Loaded {len(self.sources)} sources from database")
    
    def register_source(self, source: ContentSource) -> None:
        """
        Register a new content source.
        
        If a source with the same ID already exists, it will be updated.
        
        Args:
            source: ContentSource object to register.
        
        Example:
            >>> source = ContentSource(
            ...     source_id="monster_book",
            ...     source_type=SourceType.CORE_RULEBOOK,
            ...     book_name="Dolmenwood Monster Book",
            ...     book_code="monster_book",
            ...     file_path="/path/to/monsters.pdf"
            ... )
            >>> manager.register_source(source)
        """
        cursor = self.conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO content_sources
            (source_id, source_type, book_name, book_code, version, 
             publication_date, publisher, file_path, file_hash, 
             page_count, imported_at, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            source.source_id,
            source.source_type.value,
            source.book_name,
            source.book_code,
            source.version,
            source.publication_date,
            source.publisher,
            source.file_path,
            source.file_hash,
            source.page_count,
            source.imported_at.isoformat(),
            source.last_updated.isoformat()
        ))
        
        self.conn.commit()
        
        # Update cache
        self.sources[source.source_id] = source
        
        logger.info(f"Registered source: {source.source_id} ({source.book_name})")
    
    def get_source(self, source_id: str) -> Optional[ContentSource]:
        """
        Get a content source by ID.
        
        Args:
            source_id: Unique identifier of the source.
        
        Returns:
            ContentSource if found, None otherwise.
        
        Example:
            >>> source = manager.get_source("players_book")
            >>> if source:
            ...     print(source.book_name)
        """
        return self.sources.get(source_id)
    
    def get_source_or_raise(self, source_id: str) -> ContentSource:
        """
        Get a content source by ID, raising an error if not found.
        
        Args:
            source_id: Unique identifier of the source.
        
        Returns:
            ContentSource object.
        
        Raises:
            SourceNotFoundError: If source is not found.
        """
        source = self.sources.get(source_id)
        if not source:
            raise SourceNotFoundError(f"Source not found: {source_id}")
        return source
    
    def list_sources(
        self, 
        source_type: Optional[SourceType] = None
    ) -> list[ContentSource]:
        """
        List all registered sources, optionally filtered by type.
        
        Args:
            source_type: Optional filter by source type.
        
        Returns:
            List of ContentSource objects.
        
        Example:
            >>> # Get all sources
            >>> all_sources = manager.list_sources()
            >>> 
            >>> # Get only adventure modules
            >>> adventures = manager.list_sources(SourceType.ADVENTURE_MODULE)
        """
        if source_type:
            return [
                s for s in self.sources.values() 
                if s.source_type == source_type
            ]
        return list(self.sources.values())
    
    def list_sources_by_priority(self) -> list[ContentSource]:
        """
        List all sources sorted by priority (highest priority first).
        
        Returns:
            List of ContentSource objects sorted by priority.
        """
        return sorted(self.sources.values(), key=lambda s: s.get_priority())
    
    def remove_source(self, source_id: str) -> bool:
        """
        Remove a content source.
        
        Args:
            source_id: Unique identifier of the source to remove.
        
        Returns:
            True if source was removed, False if not found.
        """
        if source_id not in self.sources:
            return False
        
        cursor = self.conn.cursor()
        
        # Remove from metadata table first (foreign key)
        cursor.execute(
            "DELETE FROM source_metadata WHERE source_id = ?",
            (source_id,)
        )
        
        # Remove from main table
        cursor.execute(
            "DELETE FROM content_sources WHERE source_id = ?",
            (source_id,)
        )
        
        self.conn.commit()
        
        # Update cache
        del self.sources[source_id]
        
        logger.info(f"Removed source: {source_id}")
        return True
    
    def get_source_priority(self, source_id: str) -> int:
        """
        Get priority level for a source (lower = higher priority).
        
        Priority order:
        1. Core Rulebooks (Player's Book, Monster Book)
        2. Campaign Setting (Campaign Book)
        3. Adventure Modules
        4. Homebrew
        
        Args:
            source_id: Unique identifier of the source.
        
        Returns:
            Priority level (1-4), or 999 for unknown sources.
        """
        source = self.sources.get(source_id)
        if not source:
            return 999  # Unknown source = lowest priority
        
        return source.get_priority()
    
    def resolve_conflicts(
        self, 
        content_items: list[dict[str, Any]],
        log_conflict: bool = True
    ) -> list[dict[str, Any]]:
        """
        When multiple sources provide information, sort by priority.
        
        This method sorts content items by their source priority,
        ensuring that higher-priority sources (core rulebooks) come
        before lower-priority sources (adventures, homebrew).
        
        Args:
            content_items: List of content dicts with 'metadata' 
                          containing 'source_id'.
            log_conflict: Whether to log the conflict to the database.
        
        Returns:
            Sorted list with highest priority items first.
        
        Example:
            >>> items = [
            ...     {"id": "goblin_adv", "metadata": {"source_id": "adventure"}},
            ...     {"id": "goblin_core", "metadata": {"source_id": "monster_book"}}
            ... ]
            >>> resolved = manager.resolve_conflicts(items)
            >>> # Core book item will be first
        """
        # Sort by source priority
        sorted_items = sorted(
            content_items,
            key=lambda x: self.get_source_priority(
                x.get("metadata", {}).get("source_id", "")
            )
        )
        
        # Log conflicts if multiple sources
        if log_conflict and len(content_items) > 1:
            self._log_conflict(content_items)
        
        return sorted_items
    
    def get_highest_priority_item(
        self, 
        content_items: list[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        """
        Get the single highest priority item from a list.
        
        Args:
            content_items: List of content dicts with source metadata.
        
        Returns:
            The highest priority item, or None if list is empty.
        """
        if not content_items:
            return None
        
        resolved = self.resolve_conflicts(content_items, log_conflict=False)
        return resolved[0] if resolved else None
    
    def _log_conflict(self, content_items: list[dict[str, Any]]) -> None:
        """
        Log when multiple sources provide conflicting information.
        
        Args:
            content_items: List of conflicting content items.
        """
        if len(content_items) < 2:
            return
        
        cursor = self.conn.cursor()
        
        # Get source IDs
        source_ids = [
            item.get("metadata", {}).get("source_id") 
            for item in content_items 
            if item.get("metadata", {}).get("source_id")
        ]
        
        if len(source_ids) < 2:
            return
        
        # Get content ID (use first available)
        content_id = (
            content_items[0].get("id") or 
            content_items[0].get("rule_id") or
            content_items[0].get("monster_id") or
            "unknown"
        )
        
        # Determine content type
        content_type = content_items[0].get("metadata", {}).get(
            "content_type", "unknown"
        )
        
        # Determine resolution
        winning_source = source_ids[0]
        resolution = f"Priority resolution: {winning_source}"
        
        try:
            cursor.execute("""
                INSERT INTO content_conflicts
                (content_id, content_type, source_id_1, source_id_2, 
                 conflict_description, resolution, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                content_id,
                content_type,
                source_ids[0],
                source_ids[1],
                f"Multiple sources provide content for {content_id}",
                resolution,
                datetime.now().isoformat()
            ))
            
            self.conn.commit()
            logger.debug(f"Logged conflict for {content_id}")
        except Exception as e:
            logger.warning(f"Failed to log conflict: {e}")
    
    def get_conflict_report(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        Get report of all content conflicts.
        
        Args:
            limit: Maximum number of conflicts to return.
        
        Returns:
            List of conflict records with source information.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT 
                conflict_id,
                content_id, 
                content_type, 
                source_id_1, 
                source_id_2, 
                conflict_description,
                resolution, 
                resolved_at,
                created_at
            FROM content_conflicts
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        
        conflicts = []
        for row in cursor.fetchall():
            # Get source names for readability
            source1 = self.get_source(row["source_id_1"])
            source2 = self.get_source(row["source_id_2"])
            
            conflicts.append({
                "conflict_id": row["conflict_id"],
                "content_id": row["content_id"],
                "content_type": row["content_type"],
                "sources": [row["source_id_1"], row["source_id_2"]],
                "source_names": [
                    source1.book_name if source1 else row["source_id_1"],
                    source2.book_name if source2 else row["source_id_2"]
                ],
                "description": row["conflict_description"],
                "resolution": row["resolution"],
                "resolved_at": row["resolved_at"],
                "created_at": row["created_at"]
            })
        
        return conflicts
    
    def get_conflicts_for_source(self, source_id: str) -> list[dict[str, Any]]:
        """
        Get all conflicts involving a specific source.
        
        Args:
            source_id: Source to find conflicts for.
        
        Returns:
            List of conflict records.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT 
                conflict_id, content_id, content_type,
                source_id_1, source_id_2,
                resolution, resolved_at
            FROM content_conflicts
            WHERE source_id_1 = ? OR source_id_2 = ?
            ORDER BY resolved_at DESC
        """, (source_id, source_id))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def clear_conflicts(self) -> int:
        """
        Clear all conflict records.
        
        Returns:
            Number of conflicts cleared.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM content_conflicts")
        count = cursor.fetchone()[0]
        
        cursor.execute("DELETE FROM content_conflicts")
        self.conn.commit()
        
        logger.info(f"Cleared {count} conflict records")
        return count
    
    def verify_source_integrity(self, source_id: str) -> dict[str, Any]:
        """
        Verify a source file hasn't changed since import.
        
        Computes the current SHA-256 hash of the file and compares
        it to the stored hash.
        
        Args:
            source_id: Unique identifier of the source.
        
        Returns:
            Dict with verification results:
            - valid: bool - Whether file matches stored hash
            - expected_hash: str - The stored hash
            - actual_hash: str - The computed hash
            - message: str - Human-readable result
        
        Example:
            >>> result = manager.verify_source_integrity("players_book")
            >>> if result["valid"]:
            ...     print("File integrity verified")
            ... else:
            ...     print(f"Warning: {result['message']}")
        """
        source = self.sources.get(source_id)
        if not source:
            return {
                "valid": False,
                "expected_hash": None,
                "actual_hash": None,
                "message": f"Source {source_id} not found"
            }
        
        # Check if file exists
        file_path = Path(source.file_path)
        if not file_path.exists():
            return {
                "valid": False,
                "expected_hash": source.file_hash,
                "actual_hash": None,
                "message": f"File not found: {source.file_path}"
            }
        
        # Compute current file hash
        try:
            actual_hash = self.compute_file_hash(source.file_path)
        except Exception as e:
            return {
                "valid": False,
                "expected_hash": source.file_hash,
                "actual_hash": None,
                "message": f"Error computing hash: {e}"
            }
        
        # No stored hash to compare
        if not source.file_hash:
            return {
                "valid": True,
                "expected_hash": None,
                "actual_hash": actual_hash,
                "message": "No stored hash to compare (file not verified)"
            }
        
        # Compare hashes
        if actual_hash == source.file_hash:
            return {
                "valid": True,
                "expected_hash": source.file_hash,
                "actual_hash": actual_hash,
                "message": "File integrity verified"
            }
        else:
            return {
                "valid": False,
                "expected_hash": source.file_hash,
                "actual_hash": actual_hash,
                "message": "File has been modified since import"
            }
    
    def verify_all_sources(self) -> dict[str, dict[str, Any]]:
        """
        Verify integrity of all registered sources.
        
        Returns:
            Dict mapping source_id to verification results.
        """
        results = {}
        for source_id in self.sources:
            results[source_id] = self.verify_source_integrity(source_id)
        return results
    
    @staticmethod
    def compute_file_hash(file_path: str) -> str:
        """
        Compute SHA-256 hash of a file.
        
        Args:
            file_path: Path to file.
        
        Returns:
            Hexadecimal hash string.
        
        Raises:
            FileNotFoundError: If file doesn't exist.
            IOError: If file cannot be read.
        """
        sha256_hash = hashlib.sha256()
        
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        
        return sha256_hash.hexdigest()
    
    def update_source_hash(self, source_id: str) -> Optional[str]:
        """
        Update the stored hash for a source file.
        
        Args:
            source_id: Source to update.
        
        Returns:
            New hash value, or None if source not found.
        """
        source = self.sources.get(source_id)
        if not source:
            return None
        
        try:
            new_hash = self.compute_file_hash(source.file_path)
        except Exception as e:
            logger.error(f"Failed to compute hash for {source_id}: {e}")
            return None
        
        # Update database
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE content_sources 
            SET file_hash = ?, last_updated = ?
            WHERE source_id = ?
        """, (new_hash, datetime.now().isoformat(), source_id))
        self.conn.commit()
        
        # Update cache
        source.file_hash = new_hash
        source.last_updated = datetime.now()
        
        logger.info(f"Updated hash for {source_id}")
        return new_hash
    
    def set_source_metadata(
        self, 
        source_id: str, 
        key: str, 
        value: Any
    ) -> None:
        """
        Set metadata for a source.
        
        Args:
            source_id: Source to set metadata for.
            key: Metadata key.
            value: Metadata value (will be JSON encoded if not string).
        """
        if source_id not in self.sources:
            raise SourceNotFoundError(f"Source not found: {source_id}")
        
        # JSON encode non-string values
        if not isinstance(value, str):
            value = json.dumps(value)
        
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO source_metadata (source_id, key, value)
            VALUES (?, ?, ?)
        """, (source_id, key, value))
        self.conn.commit()
    
    def get_source_metadata(
        self, 
        source_id: str, 
        key: str
    ) -> Optional[Any]:
        """
        Get metadata for a source.
        
        Args:
            source_id: Source to get metadata for.
            key: Metadata key.
        
        Returns:
            Metadata value, or None if not found.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT value FROM source_metadata
            WHERE source_id = ? AND key = ?
        """, (source_id, key))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        value = row[0]
        
        # Try to JSON decode
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    
    def get_all_source_metadata(self, source_id: str) -> dict[str, Any]:
        """
        Get all metadata for a source.
        
        Args:
            source_id: Source to get metadata for.
        
        Returns:
            Dict of all metadata key-value pairs.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT key, value FROM source_metadata
            WHERE source_id = ?
        """, (source_id,))
        
        metadata = {}
        for row in cursor.fetchall():
            value = row[1]
            try:
                metadata[row[0]] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                metadata[row[0]] = value
        
        return metadata
    
    def create_source_reference(
        self, 
        source_id: str,
        page_reference: Optional[str] = None,
        section: Optional[str] = None
    ) -> SourceReference:
        """
        Create a SourceReference for a registered source.
        
        Args:
            source_id: Source to create reference for.
            page_reference: Page number or range.
            section: Section name.
        
        Returns:
            SourceReference object.
        
        Raises:
            SourceNotFoundError: If source is not found.
        """
        source = self.get_source_or_raise(source_id)
        
        return SourceReference(
            source_id=source.source_id,
            book_code=source.book_code,
            page_reference=page_reference,
            section=section
        )
    
    def get_statistics(self) -> dict[str, Any]:
        """
        Get statistics about registered content.
        
        Returns:
            Dict with source counts and conflict statistics.
        """
        cursor = self.conn.cursor()
        
        # Count sources by type
        source_counts = {}
        for source_type in SourceType:
            count = len([
                s for s in self.sources.values() 
                if s.source_type == source_type
            ])
            source_counts[source_type.value] = count
        
        # Count conflicts
        cursor.execute("SELECT COUNT(*) FROM content_conflicts")
        conflict_count = cursor.fetchone()[0]
        
        # Get most recent conflict
        cursor.execute("""
            SELECT resolved_at FROM content_conflicts 
            ORDER BY resolved_at DESC LIMIT 1
        """)
        row = cursor.fetchone()
        last_conflict = row[0] if row else None
        
        return {
            "total_sources": len(self.sources),
            "sources_by_type": source_counts,
            "total_conflicts": conflict_count,
            "last_conflict": last_conflict
        }
    
    def export_sources(self) -> list[dict[str, Any]]:
        """
        Export all sources as a list of dicts.
        
        Useful for backup or migration.
        
        Returns:
            List of source data dicts.
        """
        return [
            {
                "source_id": s.source_id,
                "source_type": s.source_type.value,
                "book_name": s.book_name,
                "book_code": s.book_code,
                "version": s.version,
                "publication_date": s.publication_date,
                "publisher": s.publisher,
                "file_path": s.file_path,
                "file_hash": s.file_hash,
                "page_count": s.page_count,
                "imported_at": s.imported_at.isoformat(),
                "last_updated": s.last_updated.isoformat(),
                "priority": s.get_priority()
            }
            for s in self.sources.values()
        ]
    
    def refresh_cache(self) -> None:
        """Reload all sources from database into cache."""
        self.sources.clear()
        self._load_sources()
        logger.info("Cache refreshed")
    
    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.info("ContentManager database connection closed")
    
    def __enter__(self) -> "ContentManager":
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
    
    def __repr__(self) -> str:
        """String representation."""
        return f"ContentManager(db_path='{self.db_path}', sources={len(self.sources)})"


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_content_manager(
    db_path: str = "./data/content_sources.db"
) -> ContentManager:
    """
    Factory function to create a ContentManager.
    
    Args:
        db_path: Path to SQLite database file.
    
    Returns:
        Configured ContentManager instance.
    """
    return ContentManager(db_path)


def create_core_book_source(
    book_code: str,
    book_name: str,
    file_path: str,
    version: str = "1.0"
) -> ContentSource:
    """
    Create a ContentSource for a core rulebook.
    
    Args:
        book_code: Short code (e.g., "players_book").
        book_name: Full name (e.g., "Dolmenwood Player's Book").
        file_path: Path to PDF file.
        version: Book version.
    
    Returns:
        Configured ContentSource.
    """
    file_hash = None
    if Path(file_path).exists():
        file_hash = ContentManager.compute_file_hash(file_path)
    
    return ContentSource(
        source_id=book_code,
        source_type=SourceType.CORE_RULEBOOK,
        book_name=book_name,
        book_code=book_code,
        file_path=file_path,
        file_hash=file_hash,
        version=version
    )


def create_adventure_source(
    adventure_code: str,
    title: str,
    file_path: str,
    version: str = "1.0"
) -> ContentSource:
    """
    Create a ContentSource for an adventure module.
    
    Args:
        adventure_code: Short code (e.g., "fungal_tomb").
        title: Adventure title (e.g., "The Fungal Tomb").
        file_path: Path to PDF file.
        version: Module version.
    
    Returns:
        Configured ContentSource.
    """
    file_hash = None
    if Path(file_path).exists():
        file_hash = ContentManager.compute_file_hash(file_path)
    
    return ContentSource(
        source_id=adventure_code,
        source_type=SourceType.ADVENTURE_MODULE,
        book_name=f"Adventure: {title}",
        book_code=adventure_code,
        file_path=file_path,
        file_hash=file_hash,
        version=version
    )
