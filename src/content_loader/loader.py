"""
JSON Content Loader - Load game content from curated JSON files.

This module provides reliable content loading from manually verified JSON files,
avoiding the pitfalls of automated PDF extraction.

Directory Structure:
    data/content/
    ├── monsters/
    │   ├── monster_name.json      # Single monster
    │   └── category.json          # Multiple monsters in array
    ├── spells/
    │   ├── arcane_level_1.json    # Spells grouped by type/level
    │   └── divine_level_2.json
    ├── items/
    │   ├── weapons.json
    │   ├── armor.json
    │   └── adventuring_gear.json
    ├── hexes/
    │   └── hex_0102.json
    ├── npcs/
    │   └── npc_name.json
    └── rules/
        └── combat.json
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

# Import data models
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_models import (
    MonsterStatBlock,
    Spell,
    Item,
    HexLocation,
    NPC,
    GameRule,
    SourceReference,
    SourceType,
    ContentType,
    ItemType,
    MagicType,
    TerrainType,
)

logger = logging.getLogger(__name__)


@dataclass
class LoadResult:
    """Result of content loading operation."""
    monsters: int = 0
    spells: int = 0
    items: int = 0
    hexes: int = 0
    npcs: int = 0
    rules: int = 0
    errors: list[str] = field(default_factory=list)
    
    @property
    def total(self) -> int:
        return self.monsters + self.spells + self.items + self.hexes + self.npcs + self.rules
    
    def __str__(self) -> str:
        parts = []
        if self.monsters:
            parts.append(f"{self.monsters} monsters")
        if self.spells:
            parts.append(f"{self.spells} spells")
        if self.items:
            parts.append(f"{self.items} items")
        if self.hexes:
            parts.append(f"{self.hexes} hexes")
        if self.npcs:
            parts.append(f"{self.npcs} npcs")
        if self.rules:
            parts.append(f"{self.rules} rules")
        if self.errors:
            parts.append(f"{len(self.errors)} errors")
        return f"LoadResult({', '.join(parts)})"


class ContentLoader:
    """
    Load game content from JSON files in the content directory.
    
    Supports both single-item files and array files containing multiple items.
    All content is validated against Pydantic models before loading.
    
    Example:
        loader = ContentLoader("data/content")
        
        # Load all content
        result = loader.load_all()
        
        # Load specific type
        monsters = loader.load_monsters()
        
        # Load and import to database
        loader.load_and_import(state_manager, rules_retriever)
    """
    
    CONTENT_TYPES = {
        "monsters": MonsterStatBlock,
        "spells": Spell,
        "items": Item,
        "hexes": HexLocation,
        "npcs": NPC,
        "rules": GameRule,
    }
    
    def __init__(self, content_dir: Union[str, Path] = "data/content"):
        """
        Initialize the content loader.
        
        Args:
            content_dir: Path to the content directory.
        """
        self.content_dir = Path(content_dir)
        self._cache: dict[str, list[Any]] = {}
    
    def _ensure_directories(self) -> None:
        """Create content directories if they don't exist."""
        self.content_dir.mkdir(parents=True, exist_ok=True)
        for content_type in self.CONTENT_TYPES:
            (self.content_dir / content_type).mkdir(exist_ok=True)
    
    def _load_json_file(self, path: Path) -> Union[dict, list]:
        """Load and parse a JSON file."""
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _add_source_reference(
        self, 
        data: dict, 
        file_path: Path,
        source_id: str = "json_content"
    ) -> dict:
        """Add source reference to data if not present."""
        if 'source' not in data or data['source'] is None:
            data['source'] = {
                'source_id': source_id,
                'book_code': source_id,  # Required field
                'page_reference': None,
                'section': file_path.stem,
            }
        elif isinstance(data['source'], dict) and 'book_code' not in data['source']:
            # Ensure book_code is present if source exists but missing it
            data['source']['book_code'] = data['source'].get('source_id', source_id)
        return data
    
    def _load_content_type(
        self, 
        content_type: str,
        model_class: type
    ) -> tuple[list[Any], list[str]]:
        """
        Load all content of a specific type.
        
        Args:
            content_type: Type name (e.g., "monsters")
            model_class: Pydantic model class for validation
            
        Returns:
            Tuple of (loaded items, error messages)
        """
        items = []
        errors = []
        
        content_path = self.content_dir / content_type
        if not content_path.exists():
            return items, errors
        
        # Find all JSON files (including in subdirectories)
        json_files = list(content_path.rglob("*.json"))
        
        for file_path in json_files:
            try:
                data = self._load_json_file(file_path)
                
                # Handle both single items and arrays
                if isinstance(data, list):
                    for i, item_data in enumerate(data):
                        try:
                            item_data = self._add_source_reference(item_data, file_path)
                            item = model_class.model_validate(item_data)
                            items.append(item)
                        except Exception as e:
                            errors.append(f"{file_path}[{i}]: {e}")
                else:
                    data = self._add_source_reference(data, file_path)
                    item = model_class.model_validate(data)
                    items.append(item)
                    
            except json.JSONDecodeError as e:
                errors.append(f"{file_path}: Invalid JSON - {e}")
            except Exception as e:
                errors.append(f"{file_path}: {e}")
        
        return items, errors
    
    def load_monsters(self) -> list[MonsterStatBlock]:
        """Load all monster definitions."""
        items, errors = self._load_content_type("monsters", MonsterStatBlock)
        for error in errors:
            logger.warning(f"Monster loading error: {error}")
        self._cache["monsters"] = items
        return items
    
    def load_spells(self) -> list[Spell]:
        """Load all spell definitions."""
        items, errors = self._load_content_type("spells", Spell)
        for error in errors:
            logger.warning(f"Spell loading error: {error}")
        self._cache["spells"] = items
        return items
    
    def load_items(self) -> list[Item]:
        """Load all item definitions."""
        items, errors = self._load_content_type("items", Item)
        for error in errors:
            logger.warning(f"Item loading error: {error}")
        self._cache["items"] = items
        return items
    
    def load_hexes(self) -> list[HexLocation]:
        """Load all hex location definitions."""
        items, errors = self._load_content_type("hexes", HexLocation)
        for error in errors:
            logger.warning(f"Hex loading error: {error}")
        self._cache["hexes"] = items
        return items
    
    def load_npcs(self) -> list[NPC]:
        """Load all NPC definitions."""
        items, errors = self._load_content_type("npcs", NPC)
        for error in errors:
            logger.warning(f"NPC loading error: {error}")
        self._cache["npcs"] = items
        return items
    
    def load_rules(self) -> list[GameRule]:
        """Load all rule definitions."""
        items, errors = self._load_content_type("rules", GameRule)
        for error in errors:
            logger.warning(f"Rule loading error: {error}")
        self._cache["rules"] = items
        return items
    
    def load_all(self) -> LoadResult:
        """
        Load all content from all subdirectories.
        
        Returns:
            LoadResult with counts and any errors.
        """
        result = LoadResult()
        
        self._ensure_directories()
        
        # Load each content type
        monsters = self.load_monsters()
        result.monsters = len(monsters)
        
        spells = self.load_spells()
        result.spells = len(spells)
        
        items = self.load_items()
        result.items = len(items)
        
        hexes = self.load_hexes()
        result.hexes = len(hexes)
        
        npcs = self.load_npcs()
        result.npcs = len(npcs)
        
        rules = self.load_rules()
        result.rules = len(rules)
        
        logger.info(f"Content loaded: {result}")
        return result
    
    def load_and_import(
        self,
        state_manager: Any,
        rules_retriever: Optional[Any] = None,
        skip_indexing: bool = False
    ) -> LoadResult:
        """
        Load content and import into databases.
        
        Args:
            state_manager: GameStateManager instance for SQLite storage.
            rules_retriever: Optional RulesRetriever for vector indexing.
            skip_indexing: Skip vector DB indexing.
            
        Returns:
            LoadResult with counts.
        """
        result = self.load_all()
        
        # Import to SQLite
        for monster in self._cache.get("monsters", []):
            state_manager.save_monster(monster)
        
        for spell in self._cache.get("spells", []):
            state_manager.save_spell(spell)
        
        for item in self._cache.get("items", []):
            state_manager.save_item(item)
        
        for hex_loc in self._cache.get("hexes", []):
            state_manager.save_location(hex_loc)
        
        for npc in self._cache.get("npcs", []):
            state_manager.save_reference_npc(npc)
        
        for rule in self._cache.get("rules", []):
            state_manager.save_rule(rule)
        
        logger.info(f"Imported to SQLite: {result}")
        
        # Index in vector DB
        if rules_retriever and not skip_indexing:
            try:
                if self._cache.get("monsters"):
                    rules_retriever.index_monsters(self._cache["monsters"])
                if self._cache.get("spells"):
                    rules_retriever.index_spells(self._cache["spells"])
                if self._cache.get("items"):
                    rules_retriever.index_items(self._cache["items"])
                if self._cache.get("hexes"):
                    rules_retriever.index_locations(self._cache["hexes"])
                if self._cache.get("npcs"):
                    rules_retriever.index_npcs(self._cache["npcs"])
                if self._cache.get("rules"):
                    rules_retriever.index_rules(self._cache["rules"])
                logger.info("Indexed content in vector DB")
            except Exception as e:
                logger.error(f"Vector indexing failed: {e}")
                result.errors.append(f"Vector indexing failed: {e}")
        
        return result
    
    def get_cached(self, content_type: str) -> list[Any]:
        """Get cached content of a specific type."""
        return self._cache.get(content_type, [])
    
    def clear_cache(self) -> None:
        """Clear the content cache."""
        self._cache.clear()


def create_content_loader(content_dir: str = "data/content") -> ContentLoader:
    """Factory function to create a ContentLoader."""
    return ContentLoader(content_dir)
