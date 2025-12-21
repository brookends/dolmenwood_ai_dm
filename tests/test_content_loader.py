"""
Tests for the JSON content loader.
"""

import json
import pytest
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from content_loader.loader import ContentLoader, LoadResult


class TestLoadResult:
    """Tests for LoadResult dataclass."""
    
    def test_empty_result(self):
        result = LoadResult()
        assert result.total == 0
        assert str(result) == "LoadResult()"
    
    def test_result_with_counts(self):
        result = LoadResult(monsters=5, spells=10, items=3)
        assert result.total == 18
        assert "5 monsters" in str(result)
        assert "10 spells" in str(result)
        assert "3 items" in str(result)
    
    def test_result_with_errors(self):
        result = LoadResult(monsters=5, errors=["error1", "error2"])
        assert "2 errors" in str(result)


class TestContentLoader:
    """Tests for ContentLoader."""
    
    @pytest.fixture
    def temp_content_dir(self):
        """Create a temporary content directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_ensure_directories(self, temp_content_dir):
        """Test that directories are created."""
        loader = ContentLoader(temp_content_dir)
        loader._ensure_directories()
        
        for content_type in loader.CONTENT_TYPES:
            assert (temp_content_dir / content_type).exists()
    
    def test_load_empty_directory(self, temp_content_dir):
        """Test loading from empty directory."""
        loader = ContentLoader(temp_content_dir)
        result = loader.load_all()
        
        assert result.total == 0
        assert result.errors == []
    
    def test_load_single_monster(self, temp_content_dir):
        """Test loading a single monster file."""
        # Create monsters directory
        monsters_dir = temp_content_dir / "monsters"
        monsters_dir.mkdir(parents=True)
        
        # Create a valid monster JSON (using actual field names from data_models.py)
        monster_data = {
            "name": "Test Monster",
            "monster_id": "monster_test",
            "hit_dice": "2",
            "armor_class": 7,
            "movement": "90' (30')",
            "attacks": ["1 × claw (1d4)"],
            "damage": ["1d4"],
            "saves_as": "F2",
            "morale": 8,
            "alignment": "Neutral",
            "description": "A test monster for unit testing.",
            "number_appearing": "1d6",
            "xp_value": 20
        }
        
        with open(monsters_dir / "test_monster.json", "w") as f:
            json.dump(monster_data, f)
        
        loader = ContentLoader(temp_content_dir)
        monsters = loader.load_monsters()
        
        assert len(monsters) == 1
        assert monsters[0].name == "Test Monster"
        assert monsters[0].hit_dice == "2"
    
    def test_load_monster_array(self, temp_content_dir):
        """Test loading multiple monsters from array file."""
        monsters_dir = temp_content_dir / "monsters"
        monsters_dir.mkdir(parents=True)
        
        monsters_data = [
            {
                "name": "Monster A",
                "monster_id": "monster_a",
                "hit_dice": "1",
                "armor_class": 8,
                "movement": "120' (40')",
                "attacks": ["1 × bite (1d6)"],
                "damage": ["1d6"],
                "saves_as": "F1",
                "morale": 6,
                "alignment": "Chaotic",
                "description": "First test monster.",
                "number_appearing": "2d6",
                "xp_value": 10
            },
            {
                "name": "Monster B",
                "monster_id": "monster_b",
                "hit_dice": "3",
                "armor_class": 5,
                "movement": "60' (20')",
                "attacks": ["2 × claw (1d4)"],
                "damage": ["1d4"],
                "saves_as": "F3",
                "morale": 9,
                "alignment": "Lawful",
                "description": "Second test monster.",
                "number_appearing": "1d4",
                "xp_value": 50
            }
        ]
        
        with open(monsters_dir / "monsters.json", "w") as f:
            json.dump(monsters_data, f)
        
        loader = ContentLoader(temp_content_dir)
        monsters = loader.load_monsters()
        
        assert len(monsters) == 2
        assert {m.name for m in monsters} == {"Monster A", "Monster B"}
    
    def test_load_invalid_json(self, temp_content_dir):
        """Test handling of invalid JSON."""
        monsters_dir = temp_content_dir / "monsters"
        monsters_dir.mkdir(parents=True)
        
        with open(monsters_dir / "invalid.json", "w") as f:
            f.write("{ invalid json }")
        
        loader = ContentLoader(temp_content_dir)
        monsters = loader.load_monsters()
        
        assert len(monsters) == 0
        # Errors are logged but not stored in result for individual type loading
    
    def test_load_missing_required_fields(self, temp_content_dir):
        """Test handling of missing required fields."""
        monsters_dir = temp_content_dir / "monsters"
        monsters_dir.mkdir(parents=True)
        
        # Monster missing required 'name' field
        monster_data = {
            "monster_id": "monster_incomplete",
            "hd": "1"
        }
        
        with open(monsters_dir / "incomplete.json", "w") as f:
            json.dump(monster_data, f)
        
        loader = ContentLoader(temp_content_dir)
        monsters = loader.load_monsters()
        
        assert len(monsters) == 0
    
    def test_load_spell(self, temp_content_dir):
        """Test loading a spell."""
        spells_dir = temp_content_dir / "spells"
        spells_dir.mkdir(parents=True)
        
        spell_data = {
            "name": "Test Spell",
            "spell_id": "spell_test",
            "level": 1,
            "magic_type": "arcane",
            "description": "A test spell"
        }
        
        with open(spells_dir / "test_spell.json", "w") as f:
            json.dump(spell_data, f)
        
        loader = ContentLoader(temp_content_dir)
        spells = loader.load_spells()
        
        assert len(spells) == 1
        assert spells[0].name == "Test Spell"
        assert spells[0].level == 1
    
    def test_load_item(self, temp_content_dir):
        """Test loading an item."""
        items_dir = temp_content_dir / "items"
        items_dir.mkdir(parents=True)
        
        item_data = {
            "name": "Test Sword",
            "item_id": "item_test_sword",
            "type": "weapon",
            "cost_sp": 100,
            "damage": "1d8"
        }
        
        with open(items_dir / "test_item.json", "w") as f:
            json.dump(item_data, f)
        
        loader = ContentLoader(temp_content_dir)
        items = loader.load_items()
        
        assert len(items) == 1
        assert items[0].name == "Test Sword"
    
    def test_load_all(self, temp_content_dir):
        """Test loading all content types."""
        # Create one item of each type
        monsters_dir = temp_content_dir / "monsters"
        monsters_dir.mkdir(parents=True, exist_ok=True)
        with open(monsters_dir / "test.json", "w") as f:
            json.dump({
                "name": "M", 
                "monster_id": "m1", 
                "hit_dice": "1", 
                "armor_class": 7, 
                "movement": "90'", 
                "attacks": [], 
                "damage": [],
                "saves_as": "F1",
                "morale": 7, 
                "alignment": "Neutral",
                "description": "Test monster",
                "number_appearing": "1d6",
                "xp_value": 10
            }, f)
        
        spells_dir = temp_content_dir / "spells"
        spells_dir.mkdir(parents=True, exist_ok=True)
        with open(spells_dir / "test.json", "w") as f:
            json.dump({
                "name": "S", 
                "spell_id": "s1", 
                "level": 1, 
                "magic_type": "arcane", 
                "description": "test"
            }, f)
        
        items_dir = temp_content_dir / "items"
        items_dir.mkdir(parents=True, exist_ok=True)
        with open(items_dir / "test.json", "w") as f:
            json.dump({
                "name": "I", 
                "item_id": "i1", 
                "type": "weapon"
            }, f)
        
        loader = ContentLoader(temp_content_dir)
        result = loader.load_all()
        
        assert result.monsters == 1
        assert result.spells == 1
        assert result.items == 1
        assert result.total == 3
    
    def test_subdirectory_loading(self, temp_content_dir):
        """Test loading from subdirectories."""
        # Create nested structure
        arcane_dir = temp_content_dir / "spells" / "arcane"
        arcane_dir.mkdir(parents=True)
        
        divine_dir = temp_content_dir / "spells" / "divine"
        divine_dir.mkdir(parents=True)
        
        # Create spells in subdirs
        for subdir, name, magic_type in [
            (arcane_dir, "Arcane Spell", "arcane"),
            (divine_dir, "Divine Spell", "divine"),
        ]:
            data = {
                "name": name,
                "spell_id": f"spell_{name.lower().replace(' ', '_')}",
                "level": 1,
                "magic_type": magic_type,
                "description": "test"
            }
            with open(subdir / f"{magic_type}.json", "w") as f:
                json.dump(data, f)
        
        loader = ContentLoader(temp_content_dir)
        spells = loader.load_spells()
        
        assert len(spells) == 2
        assert {s.magic_type.value for s in spells} == {"arcane", "divine"}
    
    def test_add_source_reference(self, temp_content_dir):
        """Test that source references are added automatically."""
        monsters_dir = temp_content_dir / "monsters"
        monsters_dir.mkdir(parents=True)
        
        # Monster without source
        monster_data = {
            "name": "No Source Monster",
            "monster_id": "monster_no_source",
            "hit_dice": "1",
            "armor_class": 7,
            "movement": "90'",
            "attacks": [],
            "damage": [],
            "saves_as": "F1",
            "morale": 7,
            "alignment": "Neutral",
            "description": "Test monster without source",
            "number_appearing": "1d6",
            "xp_value": 10
        }
        
        with open(monsters_dir / "no_source.json", "w") as f:
            json.dump(monster_data, f)
        
        loader = ContentLoader(temp_content_dir)
        monsters = loader.load_monsters()
        
        assert len(monsters) == 1
        assert monsters[0].source is not None
        assert monsters[0].source.source_id == "json_content"
    
    def test_cache(self, temp_content_dir):
        """Test content caching."""
        monsters_dir = temp_content_dir / "monsters"
        monsters_dir.mkdir(parents=True)
        
        monster_data = {
            "name": "Cached Monster",
            "monster_id": "monster_cached",
            "hit_dice": "1",
            "armor_class": 7,
            "movement": "90'",
            "attacks": [],
            "damage": [],
            "saves_as": "F1",
            "morale": 7,
            "alignment": "Neutral",
            "description": "Test monster for caching",
            "number_appearing": "1d6",
            "xp_value": 10
        }
        
        with open(monsters_dir / "cached.json", "w") as f:
            json.dump(monster_data, f)
        
        loader = ContentLoader(temp_content_dir)
        
        # Load once
        monsters1 = loader.load_monsters()
        
        # Check cache
        cached = loader.get_cached("monsters")
        assert len(cached) == 1
        
        # Clear cache
        loader.clear_cache()
        assert loader.get_cached("monsters") == []
