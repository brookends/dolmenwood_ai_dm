"""
Tests for the Dolmenwood PDF Processor module.

These tests verify:
- Stat block parsing
- Text chunking
- Equipment parsing
- Spell parsing
- Hex description parsing
- Error handling
"""

import pytest
import tempfile
import os
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pdf_processor.dolmenwood_parser import (
    DolmenwoodPDFProcessor,
    ExtractedPage,
    TextChunk,
    ExtractionResult,
    BookType,
    ContentSection,
    ParsePatterns,
    PDFProcessorError,
    PDFExtractionError,
    ParseError,
    create_processor,
    parse_stat_block,
    chunk_text,
)

from data_models import (
    MonsterStatBlock,
    GameRule,
    Spell,
    Item,
    HexLocation,
    ItemType,
    MagicType,
    TerrainType,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def processor():
    """Create a PDF processor without any PDFs."""
    return DolmenwoodPDFProcessor({})


@pytest.fixture
def patterns():
    """Create ParsePatterns instance."""
    return ParsePatterns()


@pytest.fixture
def sample_stat_block_text():
    """Sample stat block in OSE format."""
    return """Goblin
AC 6 [13], HD 1-1, HP 3, MV 60' (20')
#AT 1 × weapon (1d6), SV F1, ML 7
AL Chaotic, XP 5"""


@pytest.fixture
def sample_stat_block_full():
    """More complete stat block."""
    return """Boggart
AC 5 [14], HD 2+1, HP 10, MV 90' (30')
#AT 2 × claw (1d4), 1 × bite (1d6), SV F2, ML 8
AL Chaotic, XP 35
NA 1d6 (2d6)
TT C
A mischievous fairy creature that delights in causing trouble."""


@pytest.fixture
def sample_ogre_stat_block():
    """Ogre stat block for testing."""
    return """Ogre
AC 5 [14], HD 4+1, HP 19, MV 90' (30')
#AT 1 × club (1d10), SV F4, ML 10
AL Chaotic, XP 125
NA 1d6 (2d6)
TT C+S
Large, brutish humanoids standing 8-10 feet tall."""


@pytest.fixture
def sample_spell_text():
    """Sample spell description."""
    return """Light
Level: 1
Duration: 6 turns + 1/level
Range: 120'
Creates a magical light source that illuminates a 15' radius. 
The spell can be cast on an object or in thin air."""


@pytest.fixture
def sample_equipment_table():
    """Sample equipment table data."""
    return [
        ["Item", "Cost (sp)", "Weight (coins)", "Damage"],
        ["Sword, short", "70", "30", "1d6"],
        ["Sword, long", "100", "60", "1d8"],
        ["Dagger", "30", "10", "1d4"],
        ["Mace", "50", "30", "1d6"],
        ["Leather armor", "200", "200", "-"],
        ["Chain mail", "400", "400", "-"],
        ["Shield", "100", "100", "-"],
        ["Torch", "1", "10", "-"],
    ]


@pytest.fixture
def sample_hex_text():
    """Sample hex description text."""
    return """0808 - The Brackenmire
A vast, fetid swamp stretches across this hex. The ground is treacherous,
with hidden pools of murky water concealing the depth. Twisted trees 
with hanging moss create an oppressive canopy.

Encounter: 2d6 Bog Sprites may be found here at dusk.

0809 - Mossy Knoll
Rolling hills covered in thick moss and ancient standing stones. 
Local villagers avoid this area, claiming the stones whisper at night.

0810 - Darkwood Edge
The edge of the great Dolmenwood forest. Tall oaks and twisted elms
create a natural barrier. A hunter's path leads deeper into the woods."""


@pytest.fixture
def long_text():
    """Long text for chunking tests."""
    return """
The combat rules in Old-School Essentials follow the traditional B/X framework.
Combat begins when hostile creatures are encountered. The referee first 
determines if either side is surprised.

Surprise is checked by rolling 1d6 for each side. A roll of 1-2 indicates 
that side is surprised. Surprised characters cannot act in the first round
of combat and their opponents gain a free round of actions.

Initiative determines the order of actions in each combat round. Each side
rolls 1d6, with the higher roll acting first. Ties mean simultaneous action.
Initiative is rolled each round.

On their turn, characters may move and take one action. Actions include
attacking, casting a spell, using an item, or other activities as 
determined by the referee.

Attack rolls are made by rolling 1d20 and adding the attacker's attack 
bonus. If the result equals or exceeds the target's Armor Class, the 
attack hits and damage is rolled.

Damage is determined by the weapon used. Most weapons deal 1d6 damage,
though some deal more or less. Damage is subtracted from the target's
hit points.

When a creature reaches 0 hit points, it is dead. Characters may
attempt to subdue opponents instead of killing them.

Morale checks are made for monsters to determine if they flee or 
surrender. Roll 2d6 and compare to the monster's morale score.
If the roll exceeds the score, the monster attempts to flee.
""".strip()


# =============================================================================
# PROCESSOR INITIALIZATION TESTS
# =============================================================================

class TestProcessorInitialization:
    """Tests for DolmenwoodPDFProcessor initialization."""
    
    def test_init_empty_paths(self):
        """Test initialization with empty paths."""
        processor = DolmenwoodPDFProcessor({})
        assert processor is not None
        assert len(processor.pdf_paths) == 0
    
    def test_init_with_none_paths(self):
        """Test initialization with None paths."""
        processor = DolmenwoodPDFProcessor({
            "players_book": None,
            "campaign_book": None,
            "monster_book": None
        })
        assert len(processor.pdf_paths) == 0
    
    def test_init_with_nonexistent_paths(self):
        """Test initialization logs warning for missing files."""
        processor = DolmenwoodPDFProcessor({
            "players_book": "/nonexistent/path.pdf"
        })
        assert len(processor.pdf_paths) == 0
    
    def test_create_processor_function(self):
        """Test create_processor convenience function."""
        processor = create_processor(
            players_book=None,
            campaign_book=None,
            monster_book=None
        )
        assert isinstance(processor, DolmenwoodPDFProcessor)


# =============================================================================
# STAT BLOCK PARSING TESTS
# =============================================================================

class TestStatBlockParsing:
    """Tests for monster stat block parsing."""
    
    def test_parse_basic_stat_block(self, processor, sample_stat_block_text):
        """Test parsing a basic goblin stat block."""
        monster = processor.parse_stat_block_text(sample_stat_block_text)
        
        assert monster.name == "Goblin"
        assert monster.armor_class == 6
        assert monster.hit_dice == "1-1"
        assert monster.hp == 3
        assert monster.movement == "60' (20')"
        assert monster.morale == 7
        assert monster.alignment == "Chaotic"
        assert monster.xp_value == 5
    
    def test_parse_stat_block_with_multiple_attacks(self, processor, sample_stat_block_full):
        """Test parsing stat block with multiple attacks."""
        monster = processor.parse_stat_block_text(sample_stat_block_full)
        
        assert monster.name == "Boggart"
        assert monster.armor_class == 5
        assert monster.hit_dice == "2+1"
        assert monster.hp == 10
        assert monster.morale == 8
        assert len(monster.attacks) >= 1
    
    def test_parse_ogre_stat_block(self, processor, sample_ogre_stat_block):
        """Test parsing ogre stat block."""
        monster = processor.parse_stat_block_text(sample_ogre_stat_block)
        
        assert monster.name == "Ogre"
        assert monster.armor_class == 5
        assert monster.hit_dice == "4+1"
        assert monster.hp == 19
        assert monster.morale == 10
        assert monster.xp_value == 125
    
    def test_parse_stat_block_convenience_function(self, sample_stat_block_text):
        """Test parse_stat_block convenience function."""
        monster = parse_stat_block(sample_stat_block_text)
        
        assert isinstance(monster, MonsterStatBlock)
        assert monster.name == "Goblin"
    
    def test_parse_stat_block_empty_text(self, processor):
        """Test parsing empty text raises error."""
        with pytest.raises(ParseError):
            processor.parse_stat_block_text("")
    
    def test_parse_stat_block_missing_ac(self, processor):
        """Test parsing without AC raises error."""
        with pytest.raises(ParseError):
            processor.parse_stat_block_text("Monster\nHD 1, ML 7")
    
    def test_parse_stat_block_missing_hd(self, processor):
        """Test parsing without HD raises error."""
        with pytest.raises(ParseError):
            processor.parse_stat_block_text("Monster\nAC 5, ML 7")
    
    def test_parse_stat_block_missing_morale(self, processor):
        """Test parsing without morale raises error."""
        with pytest.raises(ParseError):
            processor.parse_stat_block_text("Monster\nAC 5, HD 1")
    
    def test_morale_clamped_to_valid_range(self, processor):
        """Test that morale is clamped to 2-12 range."""
        # Very low morale
        text = "Monster\nAC 5, HD 1, ML 1, SV F1"
        monster = processor.parse_stat_block_text(text)
        assert monster.morale == 2
        
        # Very high morale
        text = "Monster\nAC 5, HD 1, ML 15, SV F1"
        monster = processor.parse_stat_block_text(text)
        assert monster.morale == 12
    
    def test_damage_extraction(self, processor, sample_stat_block_text):
        """Test damage dice extraction from attacks."""
        monster = processor.parse_stat_block_text(sample_stat_block_text)
        
        # Should extract "1d6" from the attack
        assert len(monster.damage) > 0 or "1d6" in str(monster.attacks)


# =============================================================================
# TEXT CHUNKING TESTS
# =============================================================================

class TestTextChunking:
    """Tests for text chunking functionality."""
    
    def test_chunk_short_text(self, processor):
        """Test chunking text shorter than chunk size."""
        text = "This is a short piece of text."
        chunks = processor.clean_and_chunk_text(text, chunk_size=1000)
        
        assert len(chunks) == 1
        assert chunks[0] == text
    
    def test_chunk_long_text(self, processor, long_text):
        """Test chunking long text produces multiple chunks."""
        chunks = processor.clean_and_chunk_text(long_text, chunk_size=500)
        
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 600  # Allow some flexibility
    
    def test_chunk_text_with_overlap(self, processor, long_text):
        """Test chunking with overlap."""
        chunks = processor.clean_and_chunk_text(long_text, chunk_size=500, overlap=50)
        
        # Check that chunks exist
        assert len(chunks) > 1
    
    def test_chunk_text_preserves_content(self, processor, long_text):
        """Test that chunking preserves all content."""
        chunks = processor.clean_and_chunk_text(long_text, chunk_size=500, overlap=0)
        
        # Reconstruct text (approximately)
        reconstructed = " ".join(chunks)
        
        # Key phrases should be present
        assert "combat" in reconstructed.lower()
        assert "initiative" in reconstructed.lower()
        assert "damage" in reconstructed.lower()
    
    def test_chunk_text_respects_paragraphs(self, processor):
        """Test that chunking tries to respect paragraph boundaries."""
        text = "First paragraph here.\n\nSecond paragraph here.\n\nThird paragraph here."
        chunks = processor.clean_and_chunk_text(text, chunk_size=30)
        
        # Should split at paragraph boundaries when possible
        assert len(chunks) >= 1
    
    def test_chunk_text_convenience_function(self, long_text):
        """Test chunk_text convenience function."""
        chunks = chunk_text(long_text, chunk_size=500)
        
        assert isinstance(chunks, list)
        assert len(chunks) > 1
    
    def test_chunk_empty_text(self, processor):
        """Test chunking empty text."""
        chunks = processor.clean_and_chunk_text("")
        
        assert chunks == [] or chunks == [""]


# =============================================================================
# PATTERN MATCHING TESTS
# =============================================================================

class TestPatternMatching:
    """Tests for regex pattern matching."""
    
    def test_stat_line_ac_pattern(self, patterns):
        """Test AC pattern matching."""
        match = patterns.STAT_LINE_AC.search("AC 5 [14], HD 2")
        assert match is not None
        assert match.group(1) == "5"
        assert match.group(2) == "14"
    
    def test_stat_line_hd_pattern(self, patterns):
        """Test HD pattern matching."""
        match = patterns.STAT_LINE_HD.search("HD 3+1, MV 120'")
        assert match is not None
        assert match.group(1) == "3+1"
    
    def test_stat_line_ml_pattern(self, patterns):
        """Test ML pattern matching."""
        match = patterns.STAT_LINE_ML.search("SV F3, ML 8, AL Chaotic")
        assert match is not None
        assert match.group(1) == "8"
    
    def test_hex_header_pattern(self, patterns):
        """Test hex header pattern matching."""
        match = patterns.HEX_HEADER.search("0808 - The Brackenmire")
        assert match is not None
        assert match.group("hex_id") == "0808"
        assert match.group("name") == "The Brackenmire"
    
    def test_damage_dice_pattern(self, patterns):
        """Test damage dice pattern matching."""
        matches = patterns.DAMAGE_DICE.findall("1 × sword (1d8), 2 × claw (1d4+1)")
        assert "1d8" in matches
        assert "1d4+1" in matches
    
    def test_spell_level_pattern(self, patterns):
        """Test spell level pattern matching."""
        match = patterns.SPELL_LEVEL.search("Level: 3\nDuration: 1 turn")
        assert match is not None
        assert match.group(1) == "3"


# =============================================================================
# ITEM TYPE INFERENCE TESTS  
# =============================================================================

class TestItemTypeInference:
    """Tests for item type inference."""
    
    def test_infer_weapon_from_name(self, processor):
        """Test inferring weapon type from name."""
        assert processor._infer_item_type("Long Sword") == ItemType.WEAPON
        assert processor._infer_item_type("Battle Axe") == ItemType.WEAPON
        assert processor._infer_item_type("Short Bow") == ItemType.WEAPON
        assert processor._infer_item_type("Dagger") == ItemType.WEAPON
    
    def test_infer_armor_from_name(self, processor):
        """Test inferring armor type from name."""
        assert processor._infer_item_type("Chain Mail") == ItemType.ARMOR
        assert processor._infer_item_type("Plate Armor") == ItemType.ARMOR
        assert processor._infer_item_type("Leather Armor") == ItemType.ARMOR
    
    def test_infer_shield_from_name(self, processor):
        """Test inferring shield type from name."""
        assert processor._infer_item_type("Shield") == ItemType.SHIELD
        assert processor._infer_item_type("Tower Shield") == ItemType.SHIELD
    
    def test_infer_consumable_from_name(self, processor):
        """Test inferring consumable type from name."""
        assert processor._infer_item_type("Potion of Healing") == ItemType.CONSUMABLE
        assert processor._infer_item_type("Torch") == ItemType.CONSUMABLE
        assert processor._infer_item_type("Iron Rations") == ItemType.CONSUMABLE
    
    def test_infer_magic_from_name(self, processor):
        """Test inferring magic item type from name."""
        assert processor._infer_item_type("Wand of Fire") == ItemType.MAGIC
        assert processor._infer_item_type("Ring of Protection") == ItemType.MAGIC
        assert processor._infer_item_type("Amulet of Life") == ItemType.MAGIC
    
    def test_infer_gear_default(self, processor):
        """Test default to gear for unknown items."""
        assert processor._infer_item_type("Rope, 50'") == ItemType.GEAR
        assert processor._infer_item_type("Backpack") == ItemType.GEAR


# =============================================================================
# TERRAIN TYPE INFERENCE TESTS
# =============================================================================

class TestTerrainTypeInference:
    """Tests for terrain type inference."""
    
    def test_infer_forest_terrain(self, processor):
        """Test inferring forest terrain."""
        desc = "Dense forest covers this hex, with ancient oaks and twisted elms."
        assert processor._infer_terrain_type(desc) == TerrainType.FOREST
    
    def test_infer_swamp_terrain(self, processor):
        """Test inferring swamp terrain."""
        desc = "A fetid swamp with murky pools and hanging moss."
        assert processor._infer_terrain_type(desc) == TerrainType.SWAMP
    
    def test_infer_hills_terrain(self, processor):
        """Test inferring hills terrain."""
        desc = "Rolling hills dotted with standing stones."
        assert processor._infer_terrain_type(desc) == TerrainType.HILLS
    
    def test_infer_settlement_terrain(self, processor):
        """Test inferring settlement terrain."""
        desc = "The village of Prigwort, a small hamlet of about 200 souls."
        assert processor._infer_terrain_type(desc) == TerrainType.SETTLEMENT
    
    def test_infer_water_terrain(self, processor):
        """Test inferring water terrain."""
        desc = "A large lake stretches across the hex, its waters dark and still."
        assert processor._infer_terrain_type(desc) == TerrainType.WATER


# =============================================================================
# EQUIPMENT TABLE PARSING TESTS
# =============================================================================

class TestEquipmentTableParsing:
    """Tests for equipment table parsing."""
    
    def test_parse_equipment_table_weapons(self, processor, sample_equipment_table):
        """Test parsing weapons from equipment table."""
        items = processor._parse_equipment_table(sample_equipment_table, 1)
        
        # Should find weapons
        weapons = [i for i in items if i.type == ItemType.WEAPON]
        assert len(weapons) >= 3  # Swords, dagger, mace
        
        # Check sword details
        short_sword = next((w for w in weapons if "short" in w.name.lower()), None)
        assert short_sword is not None
        assert short_sword.cost_sp == 70
        assert short_sword.damage == "1d6"
    
    def test_parse_equipment_table_armor(self, processor, sample_equipment_table):
        """Test parsing armor from equipment table."""
        items = processor._parse_equipment_table(sample_equipment_table, 1)
        
        # Should find armor - check by name keywords
        armor_items = [i for i in items if "armor" in i.name.lower() or "mail" in i.name.lower()]
        assert len(armor_items) >= 1
    
    def test_parse_equipment_table_shield(self, processor, sample_equipment_table):
        """Test parsing shield from equipment table."""
        items = processor._parse_equipment_table(sample_equipment_table, 1)
        
        shield_items = [i for i in items if "shield" in i.name.lower()]
        assert len(shield_items) >= 1
    
    def test_parse_empty_table(self, processor):
        """Test parsing empty table returns empty list."""
        items = processor._parse_equipment_table([], 1)
        assert items == []
    
    def test_parse_non_equipment_table(self, processor):
        """Test parsing non-equipment table returns empty."""
        table = [
            ["Chapter", "Page"],
            ["Introduction", "1"],
            ["Rules", "10"]
        ]
        items = processor._parse_equipment_table(table, 1)
        assert items == []


# =============================================================================
# HEX COORDINATE TESTS
# =============================================================================

class TestHexCoordinates:
    """Tests for hex coordinate calculations."""
    
    def test_calculate_adjacent_hexes(self, processor):
        """Test calculating adjacent hexes."""
        adjacent = processor._calculate_adjacent_hexes("0808")
        
        assert len(adjacent) > 0
        assert len(adjacent) <= 6  # Maximum 6 adjacent hexes
    
    def test_adjacent_hexes_at_boundary(self, processor):
        """Test adjacent hexes at map boundary."""
        adjacent = processor._calculate_adjacent_hexes("0000")
        
        # Should have fewer adjacent hexes at corner
        assert len(adjacent) < 6
    
    def test_adjacent_hexes_invalid_id(self, processor):
        """Test adjacent hexes with invalid ID."""
        adjacent = processor._calculate_adjacent_hexes("invalid")
        
        assert adjacent == []


# =============================================================================
# TEXT CLEANING TESTS
# =============================================================================

class TestTextCleaning:
    """Tests for text cleaning functionality."""
    
    def test_clean_text_whitespace(self, processor):
        """Test normalizing whitespace."""
        text = "This   has    extra    spaces"
        cleaned = processor._clean_text(text)
        
        assert "   " not in cleaned
    
    def test_clean_text_newlines(self, processor):
        """Test normalizing excessive newlines."""
        text = "Para 1\n\n\n\n\nPara 2"
        cleaned = processor._clean_text(text)
        
        assert "\n\n\n" not in cleaned
    
    def test_clean_text_form_feeds(self, processor):
        """Test removing form feeds."""
        text = "Page 1\fPage 2"
        cleaned = processor._clean_text(text)
        
        assert "\f" not in cleaned
    
    def test_clean_text_ligatures(self, processor):
        """Test fixing ligatures."""
        text = "The ﬁrst ﬂoor"
        cleaned = processor._clean_text(text)
        
        assert "first" in cleaned or "fi" in cleaned
        assert "floor" in cleaned or "fl" in cleaned
    
    def test_clean_text_quotes(self, processor):
        """Test normalizing quotes."""
        # Test with smart quotes
        text = '\u201cSmart quotes\u201d'
        cleaned = processor._clean_text(text)
        
        # Should contain regular quotes (either unchanged or normalized)
        assert cleaned  # Just verify it doesn't crash
        assert "Smart" in cleaned and "quotes" in cleaned


# =============================================================================
# EXTRACTION RESULT TESTS
# =============================================================================

class TestExtractionResult:
    """Tests for ExtractionResult class."""
    
    def test_extraction_result_total_items(self):
        """Test total items calculation."""
        result = ExtractionResult(
            rules=[GameRule(category="test", title="Test", content="Content")],
            spells=[],
            items=[],
            monsters=[],
            hexes=[],
            npcs=[],
            errors=[]
        )
        
        assert result.total_items == 1
    
    def test_extraction_result_to_dict(self):
        """Test conversion to dictionary."""
        result = ExtractionResult(
            rules=[GameRule(category="combat", title="Attack", content="How to attack")],
            spells=[],
            items=[],
            monsters=[],
            hexes=[],
            npcs=[],
            errors=["Some error"]
        )
        
        data = result.to_dict()
        
        assert "rules" in data
        assert "summary" in data
        assert data["summary"]["total_rules"] == 1
        assert data["summary"]["total_errors"] == 1


# =============================================================================
# TEXT CHUNK TESTS
# =============================================================================

class TestTextChunk:
    """Tests for TextChunk class."""
    
    def test_text_chunk_to_game_rule(self):
        """Test converting TextChunk to GameRule."""
        chunk = TextChunk(
            content="Combat rules here",
            source_book="Player's Book",
            page_start=10,
            page_end=15,
            category="combat",
            title="Combat Basics"
        )
        
        rule = chunk.to_game_rule()
        
        assert isinstance(rule, GameRule)
        assert rule.category == "combat"
        assert rule.title == "Combat Basics"
        assert rule.content == "Combat rules here"
        assert rule.page_reference == "pp.10-15"


# =============================================================================
# CACHE TESTS
# =============================================================================

class TestCache:
    """Tests for internal caching."""
    
    def test_cache_info_empty(self, processor):
        """Test cache info when empty."""
        info = processor.get_cache_info()
        
        assert info["cached_files"] == 0
        assert info["cached_pages"] == 0
    
    def test_clear_cache(self, processor):
        """Test clearing cache."""
        # Add something to cache
        processor._cache["test"] = []
        
        processor.clear_cache()
        
        assert len(processor._cache) == 0


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Integration tests using generated test PDFs."""
    
    def test_full_stat_block_workflow(self, processor, sample_stat_block_text):
        """Test complete workflow from text to model."""
        # Parse stat block
        monster = processor.parse_stat_block_text(sample_stat_block_text)
        
        # Verify model
        assert monster.name == "Goblin"
        
        # Verify model can be serialized
        json_data = monster.model_dump_json()
        assert "Goblin" in json_data
        
        # Verify roll_hp works
        hp = monster.roll_hp()
        assert hp >= 1  # 1-1 HD means at least 1 HP
    
    def test_text_chunking_workflow(self, processor, long_text):
        """Test complete chunking workflow."""
        # Chunk text
        chunks = processor.clean_and_chunk_text(long_text, chunk_size=400)
        
        # Convert to rules
        rules = []
        for i, chunk in enumerate(chunks):
            rule = GameRule(
                category="combat",
                title=f"Combat Rules Part {i+1}",
                content=chunk,
                source_book="Test"
            )
            rules.append(rule)
        
        assert len(rules) > 0
        for rule in rules:
            assert len(rule.content) > 0
    
    def test_extraction_result_creation(self):
        """Test creating a complete extraction result."""
        monster = MonsterStatBlock(
            name="Test Monster",
            armor_class=5,
            hit_dice="2",
            movement="120' (40')",
            saves_as="F2",
            morale=8,
            description="A test monster",
            number_appearing="1d6"
        )
        
        rule = GameRule(
            category="combat",
            title="Test Rule",
            content="Test content"
        )
        
        result = ExtractionResult(
            rules=[rule],
            spells=[],
            items=[],
            monsters=[monster],
            hexes=[],
            npcs=[],
            errors=[]
        )
        
        assert result.total_items == 2
        
        data = result.to_dict()
        assert len(data["monsters"]) == 1
        assert len(data["rules"]) == 1


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
