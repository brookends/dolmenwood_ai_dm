"""
Test suite for Content Manager Module

Tests source registration, conflict resolution, integrity verification,
and metadata management.
"""

import pytest
import sys
import tempfile
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from content_manager import (
    ContentManager,
    ContentManagerError,
    SourceNotFoundError,
    SourceIntegrityError,
    create_content_manager,
    create_core_book_source,
    create_adventure_source,
)
from data_models import ContentSource, SourceType, SourceReference


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database path."""
    return str(tmp_path / "test_sources.db")


@pytest.fixture
def content_manager(temp_db):
    """Create a ContentManager with a temporary database."""
    manager = ContentManager(temp_db)
    yield manager
    manager.close()


@pytest.fixture
def sample_core_source():
    """Create a sample core rulebook source."""
    return ContentSource(
        source_id="players_book",
        source_type=SourceType.CORE_RULEBOOK,
        book_name="Dolmenwood Player's Book",
        book_code="players_book",
        file_path="/path/to/players.pdf",
        version="1.0"
    )


@pytest.fixture
def sample_adventure_source():
    """Create a sample adventure module source."""
    return ContentSource(
        source_id="fungal_tomb",
        source_type=SourceType.ADVENTURE_MODULE,
        book_name="Adventure: The Fungal Tomb",
        book_code="fungal_tomb",
        file_path="/path/to/fungal_tomb.pdf",
        version="1.0"
    )


@pytest.fixture
def temp_pdf_file(tmp_path):
    """Create a temporary file to test file hashing."""
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"This is test PDF content for hashing")
    return str(pdf_path)


# =============================================================================
# INITIALIZATION TESTS
# =============================================================================

class TestInitialization:
    """Test ContentManager initialization."""
    
    def test_create_manager(self, temp_db):
        """Test creating a ContentManager."""
        manager = ContentManager(temp_db)
        assert manager is not None
        assert manager.db_path == temp_db
        assert len(manager.sources) == 0
        manager.close()
    
    def test_create_manager_creates_directory(self, tmp_path):
        """Test that ContentManager creates parent directories."""
        db_path = str(tmp_path / "subdir" / "nested" / "test.db")
        manager = ContentManager(db_path)
        assert Path(db_path).parent.exists()
        manager.close()
    
    def test_factory_function(self, temp_db):
        """Test create_content_manager factory function."""
        manager = create_content_manager(temp_db)
        assert isinstance(manager, ContentManager)
        manager.close()
    
    def test_context_manager(self, temp_db):
        """Test using ContentManager as context manager."""
        with ContentManager(temp_db) as manager:
            assert manager is not None
        # Connection should be closed after context
    
    def test_repr(self, content_manager):
        """Test string representation."""
        repr_str = repr(content_manager)
        assert "ContentManager" in repr_str
        assert "sources=" in repr_str


# =============================================================================
# SOURCE REGISTRATION TESTS
# =============================================================================

class TestSourceRegistration:
    """Test source registration functionality."""
    
    def test_register_source(self, content_manager, sample_core_source):
        """Test registering a new source."""
        content_manager.register_source(sample_core_source)
        
        assert "players_book" in content_manager.sources
        assert content_manager.sources["players_book"].book_name == "Dolmenwood Player's Book"
    
    def test_register_multiple_sources(self, content_manager, sample_core_source, sample_adventure_source):
        """Test registering multiple sources."""
        content_manager.register_source(sample_core_source)
        content_manager.register_source(sample_adventure_source)
        
        assert len(content_manager.sources) == 2
        assert "players_book" in content_manager.sources
        assert "fungal_tomb" in content_manager.sources
    
    def test_update_existing_source(self, content_manager, sample_core_source):
        """Test updating an existing source."""
        content_manager.register_source(sample_core_source)
        
        # Update the source
        updated_source = ContentSource(
            source_id="players_book",
            source_type=SourceType.CORE_RULEBOOK,
            book_name="Dolmenwood Player's Book (Revised)",
            book_code="players_book",
            file_path="/path/to/players_v2.pdf",
            version="2.0"
        )
        content_manager.register_source(updated_source)
        
        # Should still have only 1 source
        assert len(content_manager.sources) == 1
        assert content_manager.sources["players_book"].book_name == "Dolmenwood Player's Book (Revised)"
        assert content_manager.sources["players_book"].version == "2.0"
    
    def test_source_persists_after_reload(self, temp_db, sample_core_source):
        """Test that sources persist across ContentManager instances."""
        # Register source
        manager1 = ContentManager(temp_db)
        manager1.register_source(sample_core_source)
        manager1.close()
        
        # Create new manager with same database
        manager2 = ContentManager(temp_db)
        assert "players_book" in manager2.sources
        assert manager2.sources["players_book"].book_name == "Dolmenwood Player's Book"
        manager2.close()


# =============================================================================
# SOURCE RETRIEVAL TESTS
# =============================================================================

class TestSourceRetrieval:
    """Test source retrieval functionality."""
    
    def test_get_source(self, content_manager, sample_core_source):
        """Test getting a source by ID."""
        content_manager.register_source(sample_core_source)
        
        source = content_manager.get_source("players_book")
        assert source is not None
        assert source.book_name == "Dolmenwood Player's Book"
    
    def test_get_source_not_found(self, content_manager):
        """Test getting a non-existent source."""
        source = content_manager.get_source("nonexistent")
        assert source is None
    
    def test_get_source_or_raise(self, content_manager, sample_core_source):
        """Test get_source_or_raise with existing source."""
        content_manager.register_source(sample_core_source)
        
        source = content_manager.get_source_or_raise("players_book")
        assert source.book_name == "Dolmenwood Player's Book"
    
    def test_get_source_or_raise_not_found(self, content_manager):
        """Test get_source_or_raise with non-existent source."""
        with pytest.raises(SourceNotFoundError):
            content_manager.get_source_or_raise("nonexistent")
    
    def test_list_sources(self, content_manager, sample_core_source, sample_adventure_source):
        """Test listing all sources."""
        content_manager.register_source(sample_core_source)
        content_manager.register_source(sample_adventure_source)
        
        sources = content_manager.list_sources()
        assert len(sources) == 2
    
    def test_list_sources_by_type(self, content_manager, sample_core_source, sample_adventure_source):
        """Test listing sources filtered by type."""
        content_manager.register_source(sample_core_source)
        content_manager.register_source(sample_adventure_source)
        
        core_sources = content_manager.list_sources(SourceType.CORE_RULEBOOK)
        assert len(core_sources) == 1
        assert core_sources[0].source_id == "players_book"
        
        adventure_sources = content_manager.list_sources(SourceType.ADVENTURE_MODULE)
        assert len(adventure_sources) == 1
        assert adventure_sources[0].source_id == "fungal_tomb"
    
    def test_list_sources_by_priority(self, content_manager, sample_core_source, sample_adventure_source):
        """Test listing sources sorted by priority."""
        # Register adventure first, then core
        content_manager.register_source(sample_adventure_source)
        content_manager.register_source(sample_core_source)
        
        sorted_sources = content_manager.list_sources_by_priority()
        
        # Core rulebook should be first (higher priority)
        assert sorted_sources[0].source_type == SourceType.CORE_RULEBOOK
        assert sorted_sources[1].source_type == SourceType.ADVENTURE_MODULE


# =============================================================================
# SOURCE REMOVAL TESTS
# =============================================================================

class TestSourceRemoval:
    """Test source removal functionality."""
    
    def test_remove_source(self, content_manager, sample_core_source):
        """Test removing a source."""
        content_manager.register_source(sample_core_source)
        assert "players_book" in content_manager.sources
        
        result = content_manager.remove_source("players_book")
        
        assert result is True
        assert "players_book" not in content_manager.sources
    
    def test_remove_nonexistent_source(self, content_manager):
        """Test removing a non-existent source."""
        result = content_manager.remove_source("nonexistent")
        assert result is False


# =============================================================================
# PRIORITY TESTS
# =============================================================================

class TestPriority:
    """Test source priority functionality."""
    
    def test_get_source_priority(self, content_manager, sample_core_source, sample_adventure_source):
        """Test getting source priority."""
        content_manager.register_source(sample_core_source)
        content_manager.register_source(sample_adventure_source)
        
        core_priority = content_manager.get_source_priority("players_book")
        adventure_priority = content_manager.get_source_priority("fungal_tomb")
        
        # Core rulebook has higher priority (lower number)
        assert core_priority < adventure_priority
        assert core_priority == 1
        assert adventure_priority == 3
    
    def test_get_priority_unknown_source(self, content_manager):
        """Test priority for unknown source."""
        priority = content_manager.get_source_priority("unknown")
        assert priority == 999
    
    def test_priority_order(self, content_manager):
        """Test all priority levels."""
        # Register sources of each type
        sources = [
            ContentSource(
                source_id="core",
                source_type=SourceType.CORE_RULEBOOK,
                book_name="Core",
                book_code="core",
                file_path="/core.pdf"
            ),
            ContentSource(
                source_id="campaign",
                source_type=SourceType.CAMPAIGN_SETTING,
                book_name="Campaign",
                book_code="campaign",
                file_path="/campaign.pdf"
            ),
            ContentSource(
                source_id="adventure",
                source_type=SourceType.ADVENTURE_MODULE,
                book_name="Adventure",
                book_code="adventure",
                file_path="/adventure.pdf"
            ),
            ContentSource(
                source_id="homebrew",
                source_type=SourceType.HOMEBREW,
                book_name="Homebrew",
                book_code="homebrew",
                file_path="/homebrew.pdf"
            ),
        ]
        
        for source in sources:
            content_manager.register_source(source)
        
        assert content_manager.get_source_priority("core") == 1
        assert content_manager.get_source_priority("campaign") == 2
        assert content_manager.get_source_priority("adventure") == 3
        assert content_manager.get_source_priority("homebrew") == 4


# =============================================================================
# CONFLICT RESOLUTION TESTS
# =============================================================================

class TestConflictResolution:
    """Test conflict resolution functionality."""
    
    def test_resolve_conflicts(self, content_manager, sample_core_source, sample_adventure_source):
        """Test resolving conflicts by priority."""
        content_manager.register_source(sample_core_source)
        content_manager.register_source(sample_adventure_source)
        
        items = [
            {
                "id": "goblin_1",
                "content": "Adventure goblin",
                "metadata": {"source_id": "fungal_tomb"}
            },
            {
                "id": "goblin_2",
                "content": "Core goblin",
                "metadata": {"source_id": "players_book"}
            }
        ]
        
        resolved = content_manager.resolve_conflicts(items)
        
        # Core book item should come first (higher priority)
        assert resolved[0]["metadata"]["source_id"] == "players_book"
        assert resolved[1]["metadata"]["source_id"] == "fungal_tomb"
    
    def test_resolve_conflicts_single_item(self, content_manager, sample_core_source):
        """Test resolve_conflicts with single item."""
        content_manager.register_source(sample_core_source)
        
        items = [
            {"id": "item_1", "metadata": {"source_id": "players_book"}}
        ]
        
        resolved = content_manager.resolve_conflicts(items)
        assert len(resolved) == 1
    
    def test_get_highest_priority_item(self, content_manager, sample_core_source, sample_adventure_source):
        """Test getting highest priority item."""
        content_manager.register_source(sample_core_source)
        content_manager.register_source(sample_adventure_source)
        
        items = [
            {"id": "item_1", "metadata": {"source_id": "fungal_tomb"}},
            {"id": "item_2", "metadata": {"source_id": "players_book"}}
        ]
        
        highest = content_manager.get_highest_priority_item(items)
        assert highest["metadata"]["source_id"] == "players_book"
    
    def test_get_highest_priority_item_empty(self, content_manager):
        """Test get_highest_priority_item with empty list."""
        result = content_manager.get_highest_priority_item([])
        assert result is None
    
    def test_conflict_logging(self, content_manager, sample_core_source, sample_adventure_source):
        """Test that conflicts are logged to database."""
        content_manager.register_source(sample_core_source)
        content_manager.register_source(sample_adventure_source)
        
        items = [
            {"id": "goblin", "metadata": {"source_id": "fungal_tomb", "content_type": "monster"}},
            {"id": "goblin", "metadata": {"source_id": "players_book", "content_type": "monster"}}
        ]
        
        content_manager.resolve_conflicts(items, log_conflict=True)
        
        conflicts = content_manager.get_conflict_report()
        assert len(conflicts) >= 1
        assert conflicts[0]["content_id"] == "goblin"


# =============================================================================
# CONFLICT REPORT TESTS
# =============================================================================

class TestConflictReport:
    """Test conflict reporting functionality."""
    
    def test_get_conflict_report(self, content_manager, sample_core_source, sample_adventure_source):
        """Test getting conflict report."""
        content_manager.register_source(sample_core_source)
        content_manager.register_source(sample_adventure_source)
        
        # Generate some conflicts
        items = [
            {"id": "item1", "metadata": {"source_id": "fungal_tomb"}},
            {"id": "item1", "metadata": {"source_id": "players_book"}}
        ]
        content_manager.resolve_conflicts(items)
        
        report = content_manager.get_conflict_report()
        assert isinstance(report, list)
        assert len(report) >= 1
        
        # Check report structure
        assert "content_id" in report[0]
        assert "sources" in report[0]
        assert "resolution" in report[0]
    
    def test_get_conflicts_for_source(self, content_manager, sample_core_source, sample_adventure_source):
        """Test getting conflicts for a specific source."""
        content_manager.register_source(sample_core_source)
        content_manager.register_source(sample_adventure_source)
        
        items = [
            {"id": "item1", "metadata": {"source_id": "fungal_tomb"}},
            {"id": "item1", "metadata": {"source_id": "players_book"}}
        ]
        content_manager.resolve_conflicts(items)
        
        conflicts = content_manager.get_conflicts_for_source("players_book")
        assert len(conflicts) >= 1
    
    def test_clear_conflicts(self, content_manager, sample_core_source, sample_adventure_source):
        """Test clearing all conflicts."""
        content_manager.register_source(sample_core_source)
        content_manager.register_source(sample_adventure_source)
        
        items = [
            {"id": "item1", "metadata": {"source_id": "fungal_tomb"}},
            {"id": "item1", "metadata": {"source_id": "players_book"}}
        ]
        content_manager.resolve_conflicts(items)
        
        count = content_manager.clear_conflicts()
        assert count >= 1
        
        report = content_manager.get_conflict_report()
        assert len(report) == 0


# =============================================================================
# FILE INTEGRITY TESTS
# =============================================================================

class TestFileIntegrity:
    """Test file integrity verification."""
    
    def test_compute_file_hash(self, temp_pdf_file):
        """Test computing file hash."""
        hash_value = ContentManager.compute_file_hash(temp_pdf_file)
        
        assert hash_value is not None
        assert len(hash_value) == 64  # SHA-256 hex
    
    def test_compute_file_hash_consistency(self, temp_pdf_file):
        """Test that hash is consistent."""
        hash1 = ContentManager.compute_file_hash(temp_pdf_file)
        hash2 = ContentManager.compute_file_hash(temp_pdf_file)
        
        assert hash1 == hash2
    
    def test_verify_source_integrity_valid(self, content_manager, temp_pdf_file):
        """Test verifying valid source integrity."""
        # Create source with correct hash
        file_hash = ContentManager.compute_file_hash(temp_pdf_file)
        source = ContentSource(
            source_id="test_source",
            source_type=SourceType.CORE_RULEBOOK,
            book_name="Test Book",
            book_code="test",
            file_path=temp_pdf_file,
            file_hash=file_hash
        )
        content_manager.register_source(source)
        
        result = content_manager.verify_source_integrity("test_source")
        
        assert result["valid"] is True
        assert result["message"] == "File integrity verified"
    
    def test_verify_source_integrity_modified(self, content_manager, tmp_path):
        """Test verifying modified source."""
        # Create file and register with hash
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"Original content")
        
        file_hash = ContentManager.compute_file_hash(str(pdf_path))
        source = ContentSource(
            source_id="test_source",
            source_type=SourceType.CORE_RULEBOOK,
            book_name="Test Book",
            book_code="test",
            file_path=str(pdf_path),
            file_hash=file_hash
        )
        content_manager.register_source(source)
        
        # Modify file
        pdf_path.write_bytes(b"Modified content")
        
        result = content_manager.verify_source_integrity("test_source")
        
        assert result["valid"] is False
        assert "modified" in result["message"].lower()
    
    def test_verify_source_integrity_missing_file(self, content_manager):
        """Test verifying source with missing file."""
        source = ContentSource(
            source_id="missing_source",
            source_type=SourceType.CORE_RULEBOOK,
            book_name="Missing Book",
            book_code="missing",
            file_path="/nonexistent/path/file.pdf",
            file_hash="somehash"
        )
        content_manager.register_source(source)
        
        result = content_manager.verify_source_integrity("missing_source")
        
        assert result["valid"] is False
        assert "not found" in result["message"].lower()
    
    def test_verify_source_not_found(self, content_manager):
        """Test verifying non-existent source."""
        result = content_manager.verify_source_integrity("nonexistent")
        
        assert result["valid"] is False
        assert "not found" in result["message"].lower()
    
    def test_verify_all_sources(self, content_manager, temp_pdf_file):
        """Test verifying all sources."""
        # Register source with valid file
        file_hash = ContentManager.compute_file_hash(temp_pdf_file)
        source = ContentSource(
            source_id="test_source",
            source_type=SourceType.CORE_RULEBOOK,
            book_name="Test Book",
            book_code="test",
            file_path=temp_pdf_file,
            file_hash=file_hash
        )
        content_manager.register_source(source)
        
        results = content_manager.verify_all_sources()
        
        assert "test_source" in results
        assert results["test_source"]["valid"] is True
    
    def test_update_source_hash(self, content_manager, temp_pdf_file):
        """Test updating source hash."""
        source = ContentSource(
            source_id="test_source",
            source_type=SourceType.CORE_RULEBOOK,
            book_name="Test Book",
            book_code="test",
            file_path=temp_pdf_file,
            file_hash="old_hash"
        )
        content_manager.register_source(source)
        
        new_hash = content_manager.update_source_hash("test_source")
        
        assert new_hash is not None
        assert new_hash != "old_hash"
        assert content_manager.sources["test_source"].file_hash == new_hash


# =============================================================================
# METADATA TESTS
# =============================================================================

class TestMetadata:
    """Test source metadata functionality."""
    
    def test_set_and_get_metadata(self, content_manager, sample_core_source):
        """Test setting and getting metadata."""
        content_manager.register_source(sample_core_source)
        
        content_manager.set_source_metadata("players_book", "author", "Necrotic Gnome")
        
        value = content_manager.get_source_metadata("players_book", "author")
        assert value == "Necrotic Gnome"
    
    def test_set_metadata_json(self, content_manager, sample_core_source):
        """Test setting JSON metadata."""
        content_manager.register_source(sample_core_source)
        
        content_manager.set_source_metadata("players_book", "chapters", ["Combat", "Magic", "Equipment"])
        
        value = content_manager.get_source_metadata("players_book", "chapters")
        assert value == ["Combat", "Magic", "Equipment"]
    
    def test_get_metadata_not_found(self, content_manager, sample_core_source):
        """Test getting non-existent metadata."""
        content_manager.register_source(sample_core_source)
        
        value = content_manager.get_source_metadata("players_book", "nonexistent")
        assert value is None
    
    def test_get_all_metadata(self, content_manager, sample_core_source):
        """Test getting all metadata for a source."""
        content_manager.register_source(sample_core_source)
        
        content_manager.set_source_metadata("players_book", "key1", "value1")
        content_manager.set_source_metadata("players_book", "key2", {"nested": "data"})
        
        metadata = content_manager.get_all_source_metadata("players_book")
        
        assert "key1" in metadata
        assert "key2" in metadata
        assert metadata["key1"] == "value1"
        assert metadata["key2"]["nested"] == "data"
    
    def test_set_metadata_nonexistent_source(self, content_manager):
        """Test setting metadata for non-existent source."""
        with pytest.raises(SourceNotFoundError):
            content_manager.set_source_metadata("nonexistent", "key", "value")


# =============================================================================
# SOURCE REFERENCE TESTS
# =============================================================================

class TestSourceReference:
    """Test SourceReference creation."""
    
    def test_create_source_reference(self, content_manager, sample_core_source):
        """Test creating a SourceReference."""
        content_manager.register_source(sample_core_source)
        
        ref = content_manager.create_source_reference(
            "players_book",
            page_reference="p. 42",
            section="Combat"
        )
        
        assert isinstance(ref, SourceReference)
        assert ref.source_id == "players_book"
        assert ref.book_code == "players_book"
        assert ref.page_reference == "p. 42"
        assert ref.section == "Combat"
    
    def test_create_source_reference_not_found(self, content_manager):
        """Test creating SourceReference for non-existent source."""
        with pytest.raises(SourceNotFoundError):
            content_manager.create_source_reference("nonexistent")


# =============================================================================
# STATISTICS TESTS
# =============================================================================

class TestStatistics:
    """Test statistics functionality."""
    
    def test_get_statistics(self, content_manager, sample_core_source, sample_adventure_source):
        """Test getting statistics."""
        content_manager.register_source(sample_core_source)
        content_manager.register_source(sample_adventure_source)
        
        stats = content_manager.get_statistics()
        
        assert stats["total_sources"] == 2
        assert "sources_by_type" in stats
        assert stats["sources_by_type"]["core_rulebook"] == 1
        assert stats["sources_by_type"]["adventure_module"] == 1
    
    def test_export_sources(self, content_manager, sample_core_source):
        """Test exporting sources."""
        content_manager.register_source(sample_core_source)
        
        exported = content_manager.export_sources()
        
        assert len(exported) == 1
        assert exported[0]["source_id"] == "players_book"
        assert exported[0]["priority"] == 1


# =============================================================================
# CACHE TESTS
# =============================================================================

class TestCache:
    """Test cache functionality."""
    
    def test_refresh_cache(self, content_manager, sample_core_source):
        """Test refreshing cache."""
        content_manager.register_source(sample_core_source)
        assert len(content_manager.sources) == 1
        
        content_manager.refresh_cache()
        
        # Source should still be there after refresh
        assert len(content_manager.sources) == 1
        assert "players_book" in content_manager.sources


# =============================================================================
# CONVENIENCE FUNCTION TESTS
# =============================================================================

class TestConvenienceFunctions:
    """Test convenience functions."""
    
    def test_create_core_book_source(self, temp_pdf_file):
        """Test creating core book source."""
        source = create_core_book_source(
            book_code="test_book",
            book_name="Test Book",
            file_path=temp_pdf_file,
            version="2.0"
        )
        
        assert source.source_type == SourceType.CORE_RULEBOOK
        assert source.book_code == "test_book"
        assert source.version == "2.0"
        assert source.file_hash is not None  # Should compute hash
    
    def test_create_adventure_source(self, temp_pdf_file):
        """Test creating adventure source."""
        source = create_adventure_source(
            adventure_code="test_adventure",
            title="Test Adventure",
            file_path=temp_pdf_file
        )
        
        assert source.source_type == SourceType.ADVENTURE_MODULE
        assert source.source_id == "test_adventure"
        assert "Adventure: Test Adventure" in source.book_name
        assert source.file_hash is not None
    
    def test_create_source_missing_file(self, tmp_path):
        """Test creating source with missing file."""
        source = create_core_book_source(
            book_code="missing",
            book_name="Missing",
            file_path="/nonexistent/path.pdf"
        )
        
        # Should create source but without hash
        assert source.file_hash is None


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Integration tests for complete workflows."""
    
    def test_complete_workflow(self, content_manager, temp_pdf_file):
        """Test complete source management workflow."""
        # 1. Register sources
        core_source = ContentSource(
            source_id="players_book",
            source_type=SourceType.CORE_RULEBOOK,
            book_name="Dolmenwood Player's Book",
            book_code="players_book",
            file_path=temp_pdf_file,
            file_hash=ContentManager.compute_file_hash(temp_pdf_file)
        )
        
        adventure_source = ContentSource(
            source_id="fungal_tomb",
            source_type=SourceType.ADVENTURE_MODULE,
            book_name="The Fungal Tomb",
            book_code="fungal_tomb",
            file_path=temp_pdf_file,
            file_hash=ContentManager.compute_file_hash(temp_pdf_file)
        )
        
        content_manager.register_source(core_source)
        content_manager.register_source(adventure_source)
        
        # 2. Add metadata
        content_manager.set_source_metadata("players_book", "page_count", 256)
        content_manager.set_source_metadata("fungal_tomb", "recommended_levels", "1-3")
        
        # 3. Verify integrity
        results = content_manager.verify_all_sources()
        assert all(r["valid"] for r in results.values())
        
        # 4. Resolve conflicts
        items = [
            {"id": "goblin", "metadata": {"source_id": "fungal_tomb"}},
            {"id": "goblin", "metadata": {"source_id": "players_book"}}
        ]
        resolved = content_manager.resolve_conflicts(items)
        assert resolved[0]["metadata"]["source_id"] == "players_book"
        
        # 5. Get statistics
        stats = content_manager.get_statistics()
        assert stats["total_sources"] == 2
        assert stats["total_conflicts"] >= 1
        
        # 6. Create source reference
        ref = content_manager.create_source_reference(
            "players_book",
            page_reference="p. 42",
            section="Combat Rules"
        )
        assert ref.source_id == "players_book"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
