"""
Tests for the Vector Database Module.

Uses mock embeddings to avoid API calls during testing.
"""

import os
import sys
import tempfile
import pytest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from vector_db.rules_retriever import (
    RulesRetriever,
    SearchResult,
    SearchOptions,
    CollectionType,
    MockEmbeddings,
    create_retriever,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_db_dir():
    """Create a temporary directory for the vector database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def retriever(temp_db_dir):
    """Create a retriever with mock embeddings."""
    return RulesRetriever(
        persist_directory=temp_db_dir,
        use_mock_embeddings=True
    )


@pytest.fixture
def sample_rules():
    """Sample rule objects for testing."""
    class MockRule:
        def __init__(self, rule_id, title, content, category):
            self.rule_id = rule_id
            self.title = title
            self.content = content
            self.category = category
            self.content_type = type('obj', (object,), {'value': 'rule'})()
            self.source = None
    
    return [
        MockRule("rule_001", "Combat Sequence", 
                "Combat proceeds in rounds. Each round, combatants act in initiative order.",
                "combat"),
        MockRule("rule_002", "Morale Checks",
                "Monsters must check morale when they first take casualties and when half are defeated.",
                "combat"),
        MockRule("rule_003", "Spellcasting",
                "Spellcasters must memorize spells after resting. Casting requires speaking and gesturing.",
                "magic"),
        MockRule("rule_004", "Movement",
                "Characters can move up to their movement rate each round during combat.",
                "exploration"),
        MockRule("rule_005", "Saving Throws",
                "When facing danger, roll d20 and compare to saving throw target.",
                "combat"),
    ]


@pytest.fixture
def sample_monsters():
    """Sample monster objects for testing."""
    class MockMonster:
        def __init__(self, monster_id, name, hit_dice, armor_class, morale, description, attacks=None):
            self.monster_id = monster_id
            self.name = name
            self.hit_dice = hit_dice
            self.armor_class = armor_class
            self.morale = morale
            self.description = description
            self.attacks = attacks or []
            self.movement = "60' (20')"
            self.alignment = "Neutral"
            self.habitat = ["forest"]
            self.special_abilities = []
            self.source = None
    
    return [
        MockMonster("mon_001", "Goblin", "1-1", 6, 7,
                   "Small, malicious humanoids that dwell in dark places."),
        MockMonster("mon_002", "Boggart", "2+1", 5, 8,
                   "Mischievous fairy creatures that delight in causing trouble.",
                   attacks=["2 × claw (1d4)", "1 × bite (1d6)"]),
        MockMonster("mon_003", "Moss Dwarf", "1", 8, 9,
                   "Small folk covered in living moss who protect the deep forest."),
        MockMonster("mon_004", "Drune", "3", 7, 10,
                   "Dark sorcerers who worship the Cold Prince and practice forbidden magic."),
    ]


@pytest.fixture
def sample_spells():
    """Sample spell objects for testing."""
    class MockSpell:
        def __init__(self, spell_id, name, level, magic_type, description, duration="Instantaneous", spell_range="Touch"):
            self.spell_id = spell_id
            self.name = name
            self.level = level
            self.magic_type = type('obj', (object,), {'value': magic_type})()
            self.description = description
            self.duration = duration
            self.range = spell_range
            self.reversible = False
            self.source = None
    
    return [
        MockSpell("spell_001", "Light", 1, "arcane",
                 "Creates a magical light illuminating 15' radius.", "6 turns", "120'"),
        MockSpell("spell_002", "Magic Missile", 1, "arcane",
                 "A glowing dart of energy strikes the target for 1d6+1 damage.", "Instantaneous", "150'"),
        MockSpell("spell_003", "Cure Light Wounds", 1, "divine",
                 "Heals 1d6+1 hit points of damage.", "Permanent", "Touch"),
        MockSpell("spell_004", "Sleep", 1, "arcane",
                 "Puts 2d8 HD of creatures into magical slumber.", "4d4 turns", "240'"),
    ]


@pytest.fixture
def sample_items():
    """Sample item objects for testing."""
    class MockItem:
        def __init__(self, item_id, name, item_type, cost_sp, damage=None, description=""):
            self.item_id = item_id
            self.name = name
            self.type = type('obj', (object,), {'value': item_type})()
            self.cost_sp = cost_sp
            self.damage = damage
            self.description = description
            self.weight = 1.0
            self.is_magical = False
            self.source = None
    
    return [
        MockItem("item_001", "Longsword", "weapon", 100, "1d8", "A well-balanced blade."),
        MockItem("item_002", "Chain Mail", "armor", 400, None, "Interlocking metal rings."),
        MockItem("item_003", "Healing Potion", "consumable", 50, None, "Restores 1d6+1 HP."),
        MockItem("item_004", "Rope, 50'", "gear", 10, None, "Strong hemp rope."),
    ]


@pytest.fixture
def sample_locations():
    """Sample hex location objects for testing."""
    class MockLocation:
        def __init__(self, hex_id, name, terrain, description, pois=None):
            self.hex_id = hex_id
            self.name = name
            self.terrain_type = type('obj', (object,), {'value': terrain})()
            self.description = description
            self.points_of_interest = pois or []
            self.settlements = []
            self.source = None
    
    return [
        MockLocation("0808", "Prigwort", "settlement",
                    "A small market town known for its Brewmasters' Guild.",
                    ["Brewmasters' Guild Hall", "Market Square"]),
        MockLocation("0707", "Hag's Addle", "swamp",
                    "A treacherous swampland where will-o'-wisps lure travelers.",
                    ["Ruined Tower", "Standing Stones"]),
        MockLocation("0909", "The Nagwood", "forest",
                    "Dense woodland where the trees grow thick and dark.",
                    ["Ancient Oak", "Hidden Shrine"]),
    ]


# =============================================================================
# MOCK EMBEDDINGS TESTS
# =============================================================================

class TestMockEmbeddings:
    """Test the mock embedding provider."""
    
    def test_embed_single_text(self):
        """Test embedding a single text."""
        embeddings = MockEmbeddings(dimension=1536)
        result = embeddings.embed_query("test query")
        
        assert isinstance(result, list)
        assert len(result) == 1536
        assert all(isinstance(v, float) for v in result)
    
    def test_embed_multiple_texts(self):
        """Test embedding multiple texts."""
        embeddings = MockEmbeddings(dimension=1536)
        texts = ["first text", "second text", "third text"]
        results = embeddings.embed_documents(texts)
        
        assert len(results) == 3
        for result in results:
            assert len(result) == 1536
    
    def test_deterministic_embeddings(self):
        """Test that same text produces same embedding."""
        embeddings = MockEmbeddings(dimension=1536)
        text = "consistent text"
        
        result1 = embeddings.embed_query(text)
        result2 = embeddings.embed_query(text)
        
        assert result1 == result2
    
    def test_different_texts_different_embeddings(self):
        """Test that different texts produce different embeddings."""
        embeddings = MockEmbeddings(dimension=1536)
        
        result1 = embeddings.embed_query("first text")
        result2 = embeddings.embed_query("second text")
        
        assert result1 != result2


# =============================================================================
# RETRIEVER INITIALIZATION TESTS
# =============================================================================

class TestRetrieverInitialization:
    """Test retriever initialization."""
    
    def test_create_retriever(self, temp_db_dir):
        """Test creating a retriever."""
        retriever = RulesRetriever(
            persist_directory=temp_db_dir,
            use_mock_embeddings=True
        )
        
        assert retriever is not None
        assert retriever.persist_directory == Path(temp_db_dir)
    
    def test_create_retriever_function(self, temp_db_dir):
        """Test convenience function."""
        retriever = create_retriever(
            persist_directory=temp_db_dir,
            use_mock_embeddings=True
        )
        
        assert isinstance(retriever, RulesRetriever)
    
    def test_collections_initialized(self, retriever):
        """Test that all collections are initialized."""
        stats = retriever.get_collection_stats()
        
        for collection_type in CollectionType:
            assert collection_type.value in stats


# =============================================================================
# INDEXING TESTS
# =============================================================================

class TestIndexing:
    """Test indexing operations."""
    
    def test_index_rules(self, retriever, sample_rules):
        """Test indexing rules."""
        count = retriever.index_rules(sample_rules)
        
        assert count == len(sample_rules)
        
        stats = retriever.get_collection_stats()
        assert stats["rules"] == len(sample_rules)
    
    def test_index_monsters(self, retriever, sample_monsters):
        """Test indexing monsters."""
        count = retriever.index_monsters(sample_monsters)
        
        assert count == len(sample_monsters)
        
        stats = retriever.get_collection_stats()
        assert stats["monsters"] == len(sample_monsters)
    
    def test_index_spells(self, retriever, sample_spells):
        """Test indexing spells."""
        count = retriever.index_spells(sample_spells)
        
        assert count == len(sample_spells)
        
        stats = retriever.get_collection_stats()
        assert stats["spells"] == len(sample_spells)
    
    def test_index_items(self, retriever, sample_items):
        """Test indexing items."""
        count = retriever.index_items(sample_items)
        
        assert count == len(sample_items)
        
        stats = retriever.get_collection_stats()
        assert stats["items"] == len(sample_items)
    
    def test_index_locations(self, retriever, sample_locations):
        """Test indexing locations."""
        count = retriever.index_locations(sample_locations)
        
        assert count == len(sample_locations)
        
        stats = retriever.get_collection_stats()
        assert stats["locations"] == len(sample_locations)
    
    def test_index_lore(self, retriever):
        """Test indexing lore entries."""
        lore = [
            {"topic": "The Cold Prince", "content": "An ancient deity of winter and death.", "category": "deities"},
            {"topic": "The Nagwood", "content": "A vast forest where the fairy realm bleeds through.", "category": "geography"},
        ]
        
        count = retriever.index_lore(lore)
        
        assert count == len(lore)
        
        stats = retriever.get_collection_stats()
        assert stats["lore"] == len(lore)


# =============================================================================
# SEARCH TESTS
# =============================================================================

class TestSearch:
    """Test search operations."""
    
    def test_search_rules(self, retriever, sample_rules):
        """Test searching rules."""
        retriever.index_rules(sample_rules)
        
        results = retriever.search_rules("how does combat work", n_results=3)
        
        assert len(results) > 0
        assert all(isinstance(r, SearchResult) for r in results)
        assert results[0].collection == CollectionType.RULES
    
    def test_search_monsters(self, retriever, sample_monsters):
        """Test searching monsters."""
        retriever.index_monsters(sample_monsters)
        
        results = retriever.search_monsters("fairy creature mischief", n_results=3)
        
        assert len(results) > 0
        assert results[0].collection == CollectionType.MONSTERS
    
    def test_search_spells(self, retriever, sample_spells):
        """Test searching spells."""
        retriever.index_spells(sample_spells)
        
        results = retriever.search_spells("healing magic", n_results=3)
        
        assert len(results) > 0
        assert results[0].collection == CollectionType.SPELLS
    
    def test_search_items(self, retriever, sample_items):
        """Test searching items."""
        retriever.index_items(sample_items)
        
        results = retriever.search_items("sword weapon blade", n_results=3)
        
        assert len(results) > 0
        assert results[0].collection == CollectionType.ITEMS
    
    def test_search_locations(self, retriever, sample_locations):
        """Test searching locations."""
        retriever.index_locations(sample_locations)
        
        results = retriever.search_locations("swamp dangerous", n_results=3)
        
        assert len(results) > 0
        assert results[0].collection == CollectionType.LOCATIONS
    
    def test_search_with_category_filter(self, retriever, sample_rules):
        """Test searching with category filter."""
        retriever.index_rules(sample_rules)
        
        results = retriever.search_rules("combat", category="magic", n_results=3)
        
        # Should only return magic-category rules
        for result in results:
            assert result.metadata.get("category") == "magic"
    
    def test_search_all_collections(self, retriever, sample_rules, sample_monsters, sample_spells):
        """Test searching across all collections."""
        retriever.index_rules(sample_rules)
        retriever.index_monsters(sample_monsters)
        retriever.index_spells(sample_spells)
        
        results = retriever.search_all(
            "magic spells",
            n_results_per_collection=2,
            collections=[CollectionType.RULES, CollectionType.SPELLS]
        )
        
        assert len(results) > 0
        assert CollectionType.RULES in results or CollectionType.SPELLS in results
    
    def test_search_returns_relevance_score(self, retriever, sample_rules):
        """Test that results have relevance scores."""
        retriever.index_rules(sample_rules)
        
        results = retriever.search_rules("combat rounds initiative", n_results=3)
        
        assert len(results) > 0
        for result in results:
            assert 0 <= result.relevance_score <= 1


# =============================================================================
# SEARCH RESULT TESTS
# =============================================================================

class TestSearchResult:
    """Test SearchResult class."""
    
    def test_relevance_score_calculation(self):
        """Test relevance score calculation from distance."""
        result = SearchResult(
            id="test",
            content="test content",
            metadata={},
            distance=0.0,  # Perfect match
            collection=CollectionType.RULES
        )
        
        assert result.relevance_score == 1.0
    
    def test_relevance_score_with_distance(self):
        """Test relevance score with non-zero distance."""
        result = SearchResult(
            id="test",
            content="test content",
            metadata={},
            distance=1.0,
            collection=CollectionType.RULES
        )
        
        assert result.relevance_score == 0.5
    
    def test_source_id_from_metadata(self):
        """Test extracting source_id from metadata."""
        result = SearchResult(
            id="test",
            content="test content",
            metadata={"source_id": "players_book"},
            distance=0.0,
            collection=CollectionType.RULES
        )
        
        assert result.source_id == "players_book"
    
    def test_to_context_string(self):
        """Test formatting result as context string."""
        result = SearchResult(
            id="test",
            content="Combat proceeds in rounds.",
            metadata={"source_id": "players_book", "page_reference": "p.42"},
            distance=0.0,
            collection=CollectionType.RULES
        )
        
        context = result.to_context_string()
        
        assert "Combat proceeds in rounds." in context
        assert "players_book" in context
        assert "p.42" in context


# =============================================================================
# CONTEXT GENERATION TESTS
# =============================================================================

class TestContextGeneration:
    """Test context generation for LLM prompts."""
    
    def test_get_context_for_query(self, retriever, sample_rules, sample_monsters):
        """Test generating context for a query."""
        retriever.index_rules(sample_rules)
        retriever.index_monsters(sample_monsters)
        
        context = retriever.get_context_for_query(
            "fighting goblins in combat",
            max_tokens=1000,
            include_rules=True,
            include_monsters=True
        )
        
        assert len(context) > 0
        assert isinstance(context, str)
    
    def test_context_respects_token_limit(self, retriever, sample_rules):
        """Test that context respects token limit."""
        retriever.index_rules(sample_rules)
        
        context = retriever.get_context_for_query(
            "combat rules",
            max_tokens=100,  # Very small limit
            include_rules=True
        )
        
        # Should be truncated
        estimated_tokens = len(context) * 0.25
        assert estimated_tokens < 200  # Some buffer for calculation variance


# =============================================================================
# UTILITY TESTS
# =============================================================================

class TestUtilities:
    """Test utility methods."""
    
    def test_get_collection_stats(self, retriever, sample_rules, sample_monsters):
        """Test getting collection statistics."""
        retriever.index_rules(sample_rules)
        retriever.index_monsters(sample_monsters)
        
        stats = retriever.get_collection_stats()
        
        assert "rules" in stats
        assert "monsters" in stats
        assert stats["rules"] == len(sample_rules)
        assert stats["monsters"] == len(sample_monsters)
    
    def test_clear_collection(self, retriever, sample_rules):
        """Test clearing a collection."""
        retriever.index_rules(sample_rules)
        
        assert retriever.get_collection_stats()["rules"] > 0
        
        retriever.clear_collection(CollectionType.RULES)
        
        assert retriever.get_collection_stats()["rules"] == 0
    
    def test_clear_all_collections(self, retriever, sample_rules, sample_monsters):
        """Test clearing all collections."""
        retriever.index_rules(sample_rules)
        retriever.index_monsters(sample_monsters)
        
        retriever.clear_all_collections()
        
        stats = retriever.get_collection_stats()
        for count in stats.values():
            assert count == 0


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Integration tests for complete workflows."""
    
    def test_full_indexing_and_search_workflow(
        self, retriever, sample_rules, sample_monsters, sample_spells, sample_items
    ):
        """Test complete workflow of indexing and searching."""
        # Index all content
        retriever.index_rules(sample_rules)
        retriever.index_monsters(sample_monsters)
        retriever.index_spells(sample_spells)
        retriever.index_items(sample_items)
        
        # Verify counts
        stats = retriever.get_collection_stats()
        assert stats["rules"] == len(sample_rules)
        assert stats["monsters"] == len(sample_monsters)
        assert stats["spells"] == len(sample_spells)
        assert stats["items"] == len(sample_items)
        
        # Search across collections
        all_results = retriever.search_all("magic", n_results_per_collection=2)
        
        # Should have results from multiple collections
        assert len(all_results) > 0
        
        # Generate context
        context = retriever.get_context_for_query(
            "casting a spell in combat",
            include_rules=True,
            include_spells=True
        )
        
        assert len(context) > 0
    
    def test_upsert_behavior(self, retriever):
        """Test that indexing the same content twice updates rather than duplicates."""
        class MockRule:
            def __init__(self):
                self.rule_id = "rule_unique"
                self.title = "Original Title"
                self.content = "Original content"
                self.category = "test"
                self.content_type = type('obj', (object,), {'value': 'rule'})()
                self.source = None
        
        rule = MockRule()
        
        # Index first time
        retriever.index_rules([rule])
        assert retriever.get_collection_stats()["rules"] == 1
        
        # Update and index again
        rule.content = "Updated content"
        retriever.index_rules([rule])
        
        # Should still have only 1 document
        assert retriever.get_collection_stats()["rules"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
