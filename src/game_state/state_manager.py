"""
Dolmenwood AI Dungeon Master - Game State Manager (v1.1)

This module provides SQLite-based persistence for game state,
including characters, world state, combat, and session history.

v1.1 Features:
- Adventure module and location management
- Source tracking integration with ContentManager
- Source-aware queries for content attribution
- Content conflict resolution support

Features:
- CRUD operations for all game entities
- History logging for game events
- Save/load session functionality
- Foundry VTT export compatibility
- Automatic database schema initialization

Author: AI Dungeon Master Project
Version: 1.1
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Optional

from data_models import (
    CombatState,
    DolmenwoodCharacter,
    Enemy,
    GameRule,
    HistoryEntry,
    HexLocation,
    Item,
    MonsterStatBlock,
    NPC,
    Quest,
    SessionSave,
    Settlement,
    Spell,
    WorldState,
    # v1.1 models
    AdventureLocation,
    AdventureModule,
    SourceReference,
    ContentSource,
    SourceType,
    ContentType,
    AdventureType,
)

# Configure logging
logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Custom exception for database operations."""
    pass


class GameStateManager:
    """
    Manage persistent game state using SQLite.
    
    v1.1 adds support for:
    - Adventure modules and keyed locations
    - Source tracking for content attribution
    - Integration with ContentManager
    
    Attributes:
        db_path: Path to the SQLite database file.
        conn: SQLite connection (lazy initialized).
        content_manager: Optional ContentManager for source tracking.
        
    Example:
        >>> manager = GameStateManager("./data/game_state.db")
        >>> character = DolmenwoodCharacter(name="Aldric", ...)
        >>> manager.create_character(character)
        >>> loaded = manager.get_character(character.character_id)
        
        # v1.1: Adventure support
        >>> adventure = AdventureModule(title="The Haunted Mill", ...)
        >>> manager.save_adventure_module(adventure)
        >>> locations = manager.list_adventure_locations(adventure.adventure_id)
    """
    
    # SQL Schema definitions
    SCHEMA_VERSION = 2  # Updated for v1.1
    
    SCHEMA_SQL = """
    -- Schema version tracking
    CREATE TABLE IF NOT EXISTS schema_info (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    
    -- Characters table
    CREATE TABLE IF NOT EXISTS characters (
        character_id TEXT PRIMARY KEY,
        campaign_id TEXT,
        name TEXT NOT NULL,
        data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_characters_campaign ON characters(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_characters_name ON characters(name);
    
    -- World state table (one per campaign)
    CREATE TABLE IF NOT EXISTS world_state (
        campaign_id TEXT PRIMARY KEY,
        campaign_name TEXT NOT NULL,
        data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- Combat state table
    CREATE TABLE IF NOT EXISTS combat_state (
        combat_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        data TEXT NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ended_at TIMESTAMP,
        FOREIGN KEY (campaign_id) REFERENCES world_state(campaign_id)
    );
    CREATE INDEX IF NOT EXISTS idx_combat_campaign ON combat_state(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_combat_active ON combat_state(is_active);
    
    -- NPCs table
    CREATE TABLE IF NOT EXISTS npcs (
        npc_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        name TEXT NOT NULL,
        source_id TEXT,
        data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (campaign_id) REFERENCES world_state(campaign_id)
    );
    CREATE INDEX IF NOT EXISTS idx_npcs_campaign ON npcs(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_npcs_name ON npcs(name);
    CREATE INDEX IF NOT EXISTS idx_npcs_source ON npcs(source_id);
    
    -- Locations table (hexes)
    CREATE TABLE IF NOT EXISTS locations (
        hex_id TEXT PRIMARY KEY,
        source_id TEXT,
        data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_locations_source ON locations(source_id);
    
    -- Settlements table
    CREATE TABLE IF NOT EXISTS settlements (
        settlement_id TEXT PRIMARY KEY,
        hex_id TEXT NOT NULL,
        name TEXT NOT NULL,
        data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_settlements_hex ON settlements(hex_id);
    
    -- Monsters table (reference data)
    CREATE TABLE IF NOT EXISTS monsters (
        monster_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        source_id TEXT,
        data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_monsters_name ON monsters(name);
    CREATE INDEX IF NOT EXISTS idx_monsters_source ON monsters(source_id);
    
    -- Items table (reference data)
    CREATE TABLE IF NOT EXISTS items (
        item_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        source_id TEXT,
        data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_items_name ON items(name);
    CREATE INDEX IF NOT EXISTS idx_items_type ON items(type);
    CREATE INDEX IF NOT EXISTS idx_items_source ON items(source_id);
    
    -- Spells table (reference data)
    CREATE TABLE IF NOT EXISTS spells (
        spell_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        level INTEGER NOT NULL,
        magic_type TEXT NOT NULL,
        source_id TEXT,
        data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_spells_name ON spells(name);
    CREATE INDEX IF NOT EXISTS idx_spells_level ON spells(level);
    CREATE INDEX IF NOT EXISTS idx_spells_source ON spells(source_id);
    
    -- Reference NPCs table (NPCs from rulebooks/adventures, not campaign-specific)
    CREATE TABLE IF NOT EXISTS reference_npcs (
        npc_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        location_id TEXT,
        source_id TEXT,
        data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_ref_npcs_name ON reference_npcs(name);
    CREATE INDEX IF NOT EXISTS idx_ref_npcs_location ON reference_npcs(location_id);
    CREATE INDEX IF NOT EXISTS idx_ref_npcs_source ON reference_npcs(source_id);
    
    -- Game rules table
    CREATE TABLE IF NOT EXISTS rules (
        rule_id TEXT PRIMARY KEY,
        category TEXT NOT NULL,
        title TEXT NOT NULL,
        source_id TEXT,
        content_type TEXT,
        data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_rules_category ON rules(category);
    CREATE INDEX IF NOT EXISTS idx_rules_source ON rules(source_id);
    CREATE INDEX IF NOT EXISTS idx_rules_content_type ON rules(content_type);
    
    -- History log table
    CREATE TABLE IF NOT EXISTS history_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_id TEXT UNIQUE NOT NULL,
        campaign_id TEXT NOT NULL,
        turn_number INTEGER NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        event_type TEXT NOT NULL,
        player_input TEXT,
        dm_response TEXT,
        state_changes TEXT,
        dice_rolls TEXT,
        FOREIGN KEY (campaign_id) REFERENCES world_state(campaign_id)
    );
    CREATE INDEX IF NOT EXISTS idx_history_campaign ON history_log(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_history_turn ON history_log(turn_number);
    CREATE INDEX IF NOT EXISTS idx_history_event ON history_log(event_type);
    
    -- Session saves table
    CREATE TABLE IF NOT EXISTS session_saves (
        save_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        save_name TEXT NOT NULL,
        description TEXT,
        save_data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (campaign_id) REFERENCES world_state(campaign_id)
    );
    CREATE INDEX IF NOT EXISTS idx_saves_campaign ON session_saves(campaign_id);
    
    -- v1.1: Adventure modules table
    CREATE TABLE IF NOT EXISTS adventure_modules (
        adventure_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        adventure_type TEXT NOT NULL,
        source_id TEXT,
        data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_adventures_title ON adventure_modules(title);
    CREATE INDEX IF NOT EXISTS idx_adventures_type ON adventure_modules(adventure_type);
    CREATE INDEX IF NOT EXISTS idx_adventures_source ON adventure_modules(source_id);
    
    -- v1.1: Adventure locations table (keyed rooms/areas)
    CREATE TABLE IF NOT EXISTS adventure_locations (
        location_id TEXT PRIMARY KEY,
        adventure_id TEXT NOT NULL,
        name TEXT NOT NULL,
        number TEXT,
        source_id TEXT,
        data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (adventure_id) REFERENCES adventure_modules(adventure_id)
    );
    CREATE INDEX IF NOT EXISTS idx_adv_locations_adventure ON adventure_locations(adventure_id);
    CREATE INDEX IF NOT EXISTS idx_adv_locations_number ON adventure_locations(number);
    CREATE INDEX IF NOT EXISTS idx_adv_locations_source ON adventure_locations(source_id);
    
    -- v1.1: Campaign-adventure association (which adventures are active in a campaign)
    CREATE TABLE IF NOT EXISTS campaign_adventures (
        campaign_id TEXT NOT NULL,
        adventure_id TEXT NOT NULL,
        status TEXT DEFAULT 'active',
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP,
        current_location_id TEXT,
        notes TEXT,
        PRIMARY KEY (campaign_id, adventure_id),
        FOREIGN KEY (campaign_id) REFERENCES world_state(campaign_id),
        FOREIGN KEY (adventure_id) REFERENCES adventure_modules(adventure_id)
    );
    """
    
    def __init__(
        self, 
        db_path: str = "./data/game_state.db",
        content_manager: Optional[Any] = None
    ):
        """
        Initialize the Game State Manager.
        
        Args:
            db_path: Path to the SQLite database file.
                    Will be created if it doesn't exist.
            content_manager: Optional ContentManager for source tracking integration.
        """
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self.content_manager = content_manager
        
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_database()
    
    @property
    def conn(self) -> sqlite3.Connection:
        """Get database connection, creating if necessary."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            )
            self._conn.row_factory = sqlite3.Row
            # Enable foreign keys
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn
    
    @contextmanager
    def transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """
        Context manager for database transactions.
        
        Automatically commits on success, rolls back on error.
        
        Example:
            with manager.transaction() as cursor:
                cursor.execute("INSERT INTO ...")
        """
        cursor = self.conn.cursor()
        try:
            yield cursor
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Transaction failed: {e}")
            raise DatabaseError(f"Transaction failed: {e}") from e
    
    def _init_database(self) -> None:
        """Initialize database schema."""
        try:
            with self.transaction() as cursor:
                cursor.executescript(self.SCHEMA_SQL)
                
                # Set schema version
                cursor.execute(
                    "INSERT OR REPLACE INTO schema_info (key, value) VALUES (?, ?)",
                    ("version", str(self.SCHEMA_VERSION))
                )
            logger.info(f"Database initialized at {self.db_path}")
        except Exception as e:
            raise DatabaseError(f"Failed to initialize database: {e}") from e
    
    def _migrate_schema(self) -> None:
        """Migrate database schema if needed."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM schema_info WHERE key = 'version'")
        result = cursor.fetchone()
        
        current_version = int(result["value"]) if result else 1
        
        if current_version < self.SCHEMA_VERSION:
            logger.info(f"Migrating schema from v{current_version} to v{self.SCHEMA_VERSION}")
            
            # v1 -> v2 migrations
            if current_version < 2:
                with self.transaction() as cursor:
                    # Add source_id columns to existing tables
                    migrations = [
                        "ALTER TABLE npcs ADD COLUMN source_id TEXT",
                        "ALTER TABLE locations ADD COLUMN source_id TEXT",
                        "ALTER TABLE monsters ADD COLUMN source_id TEXT",
                        "ALTER TABLE items ADD COLUMN source_id TEXT",
                        "ALTER TABLE spells ADD COLUMN source_id TEXT",
                        "ALTER TABLE rules ADD COLUMN source_id TEXT",
                        "ALTER TABLE rules ADD COLUMN content_type TEXT",
                    ]
                    
                    for sql in migrations:
                        try:
                            cursor.execute(sql)
                        except sqlite3.OperationalError:
                            pass  # Column may already exist
                    
                    # Create new v1.1 tables
                    cursor.executescript("""
                        CREATE TABLE IF NOT EXISTS adventure_modules (
                            adventure_id TEXT PRIMARY KEY,
                            title TEXT NOT NULL,
                            adventure_type TEXT NOT NULL,
                            source_id TEXT,
                            data TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                        
                        CREATE TABLE IF NOT EXISTS adventure_locations (
                            location_id TEXT PRIMARY KEY,
                            adventure_id TEXT NOT NULL,
                            name TEXT NOT NULL,
                            number TEXT,
                            source_id TEXT,
                            data TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (adventure_id) REFERENCES adventure_modules(adventure_id)
                        );
                        
                        CREATE TABLE IF NOT EXISTS campaign_adventures (
                            campaign_id TEXT NOT NULL,
                            adventure_id TEXT NOT NULL,
                            status TEXT DEFAULT 'active',
                            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            completed_at TIMESTAMP,
                            current_location_id TEXT,
                            notes TEXT,
                            PRIMARY KEY (campaign_id, adventure_id)
                        );
                    """)
                    
                    # Update version
                    cursor.execute(
                        "UPDATE schema_info SET value = ? WHERE key = 'version'",
                        (str(self.SCHEMA_VERSION),)
                    )
            
            logger.info("Schema migration complete")
    
    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
    
    def __enter__(self) -> "GameStateManager":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
    
    # =========================================================================
    # SOURCE TRACKING HELPERS (v1.1)
    # =========================================================================
    
    def _extract_source_id(self, obj: Any) -> Optional[str]:
        """Extract source_id from an object's source reference."""
        if hasattr(obj, 'source') and obj.source:
            return obj.source.source_id
        return None
    
    def _get_source_priority(self, source_id: Optional[str]) -> int:
        """Get priority for a source (lower = higher priority)."""
        if not source_id or not self.content_manager:
            return 999
        return self.content_manager.get_source_priority(source_id)
    
    def resolve_content_conflict(
        self,
        items: list[Any],
        id_field: str = "name"
    ) -> list[Any]:
        """
        Resolve conflicts between items from different sources.
        
        Items from higher-priority sources win.
        
        Args:
            items: List of items that may have duplicates.
            id_field: Field to use for identifying duplicates.
            
        Returns:
            List with conflicts resolved.
        """
        if not self.content_manager:
            return items
        
        # Group by identifier
        groups: dict[str, list[Any]] = {}
        for item in items:
            key = getattr(item, id_field, None)
            if key:
                if key not in groups:
                    groups[key] = []
                groups[key].append(item)
        
        # Resolve conflicts
        resolved = []
        for key, group in groups.items():
            if len(group) == 1:
                resolved.append(group[0])
            else:
                # Sort by source priority and take highest
                sorted_items = sorted(
                    group,
                    key=lambda x: self._get_source_priority(self._extract_source_id(x))
                )
                resolved.append(sorted_items[0])
                
                # Log conflict
                if len(group) > 1:
                    logger.debug(
                        f"Content conflict resolved for {key}: "
                        f"chose source {self._extract_source_id(sorted_items[0])}"
                    )
        
        return resolved
    
    # =========================================================================
    # CHARACTER OPERATIONS
    # =========================================================================
    
    def create_character(
        self, 
        character: DolmenwoodCharacter,
        campaign_id: Optional[str] = None
    ) -> str:
        """
        Save a new character to the database.
        
        Args:
            character: The character to save.
            campaign_id: Optional campaign association.
            
        Returns:
            The character's ID.
            
        Raises:
            DatabaseError: If the character already exists or save fails.
        """
        try:
            with self.transaction() as cursor:
                cursor.execute(
                    """INSERT INTO characters 
                       (character_id, campaign_id, name, data, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        character.character_id,
                        campaign_id,
                        character.name,
                        character.model_dump_json(),
                        character.created_at,
                        character.updated_at,
                    )
                )
            logger.info(f"Created character: {character.name} ({character.character_id})")
            return character.character_id
        except sqlite3.IntegrityError as e:
            raise DatabaseError(f"Character already exists: {character.character_id}") from e
    
    def get_character(self, character_id: str) -> Optional[DolmenwoodCharacter]:
        """
        Load a character by ID.
        
        Args:
            character_id: The character's unique ID.
            
        Returns:
            The character if found, None otherwise.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT data FROM characters WHERE character_id = ?",
            (character_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return DolmenwoodCharacter.model_validate_json(result["data"])
        return None
    
    def update_character(self, character: DolmenwoodCharacter) -> bool:
        """
        Update an existing character.
        
        Args:
            character: The character with updated data.
            
        Returns:
            True if update succeeded, False if character not found.
        """
        character.updated_at = datetime.now()
        
        with self.transaction() as cursor:
            cursor.execute(
                """UPDATE characters 
                   SET name = ?, data = ?, updated_at = ?
                   WHERE character_id = ?""",
                (
                    character.name,
                    character.model_dump_json(),
                    character.updated_at,
                    character.character_id,
                )
            )
            if cursor.rowcount > 0:
                logger.debug(f"Updated character: {character.character_id}")
                return True
        return False
    
    def delete_character(self, character_id: str) -> bool:
        """
        Delete a character.
        
        Args:
            character_id: The character's unique ID.
            
        Returns:
            True if deleted, False if not found.
        """
        with self.transaction() as cursor:
            cursor.execute(
                "DELETE FROM characters WHERE character_id = ?",
                (character_id,)
            )
            return cursor.rowcount > 0
    
    def list_characters(
        self, 
        campaign_id: Optional[str] = None
    ) -> list[DolmenwoodCharacter]:
        """
        List all characters, optionally filtered by campaign.
        
        Args:
            campaign_id: Optional campaign to filter by.
            
        Returns:
            List of characters.
        """
        cursor = self.conn.cursor()
        
        if campaign_id:
            cursor.execute(
                "SELECT data FROM characters WHERE campaign_id = ? ORDER BY name",
                (campaign_id,)
            )
        else:
            cursor.execute("SELECT data FROM characters ORDER BY name")
        
        return [
            DolmenwoodCharacter.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    # =========================================================================
    # CAMPAIGN/WORLD STATE OPERATIONS
    # =========================================================================
    
    def create_campaign(self, world_state: WorldState) -> str:
        """
        Create a new campaign with its world state.
        
        Args:
            world_state: The initial world state.
            
        Returns:
            The campaign ID.
        """
        try:
            with self.transaction() as cursor:
                cursor.execute(
                    """INSERT INTO world_state 
                       (campaign_id, campaign_name, data, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        world_state.campaign_id,
                        world_state.campaign_name,
                        world_state.model_dump_json(),
                        datetime.now(),
                        datetime.now(),
                    )
                )
            logger.info(f"Created campaign: {world_state.campaign_name}")
            return world_state.campaign_id
        except sqlite3.IntegrityError as e:
            raise DatabaseError(f"Campaign already exists: {world_state.campaign_id}") from e
    
    def get_campaign(self, campaign_id: str) -> Optional[WorldState]:
        """Load a campaign's world state."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT data FROM world_state WHERE campaign_id = ?",
            (campaign_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return WorldState.model_validate_json(result["data"])
        return None
    
    # Backward compatibility alias
    def get_world_state(self, campaign_id: str) -> Optional[WorldState]:
        """Alias for get_campaign (backward compatibility)."""
        return self.get_campaign(campaign_id)
    
    def update_campaign(self, world_state: WorldState) -> bool:
        """Update a campaign's world state."""
        with self.transaction() as cursor:
            cursor.execute(
                """UPDATE world_state 
                   SET campaign_name = ?, data = ?, updated_at = ?
                   WHERE campaign_id = ?""",
                (
                    world_state.campaign_name,
                    world_state.model_dump_json(),
                    datetime.now(),
                    world_state.campaign_id,
                )
            )
            return cursor.rowcount > 0
    
    # Backward compatibility alias
    def update_world_state(self, world_state: WorldState) -> bool:
        """Alias for update_campaign (backward compatibility)."""
        return self.update_campaign(world_state)
    
    def list_campaigns(self) -> list[WorldState]:
        """List all campaigns."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT data FROM world_state ORDER BY campaign_name")
        return [
            WorldState.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    def delete_campaign(self, campaign_id: str, cascade: bool = True) -> bool:
        """
        Delete a campaign and optionally all associated data.
        
        This also deletes (if cascade=True):
        - All characters in the campaign
        - All NPCs in the campaign
        - All combat states
        - All history entries
        - All session saves
        - All adventure associations
        
        Args:
            campaign_id: Campaign to delete.
            cascade: If True, delete all associated data (default: True).
        """
        with self.transaction() as cursor:
            if cascade:
                # Delete associated data
                cursor.execute("DELETE FROM characters WHERE campaign_id = ?", (campaign_id,))
                cursor.execute("DELETE FROM npcs WHERE campaign_id = ?", (campaign_id,))
                cursor.execute("DELETE FROM combat_state WHERE campaign_id = ?", (campaign_id,))
                cursor.execute("DELETE FROM history_log WHERE campaign_id = ?", (campaign_id,))
                cursor.execute("DELETE FROM session_saves WHERE campaign_id = ?", (campaign_id,))
                cursor.execute("DELETE FROM campaign_adventures WHERE campaign_id = ?", (campaign_id,))
            
            # Delete campaign
            cursor.execute("DELETE FROM world_state WHERE campaign_id = ?", (campaign_id,))
            
            return cursor.rowcount > 0
    
    # =========================================================================
    # COMBAT OPERATIONS
    # =========================================================================
    
    def create_combat(self, combat: CombatState, campaign_id: str) -> str:
        """
        Create a new combat encounter.
        
        Args:
            combat: The combat state.
            campaign_id: The campaign this combat belongs to.
            
        Returns:
            The combat ID.
        """
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT INTO combat_state 
                   (combat_id, campaign_id, data, is_active, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    combat.combat_id,
                    campaign_id,
                    combat.model_dump_json(),
                    combat.is_active,
                    datetime.now(),
                )
            )
        return combat.combat_id
    
    # Backward compatibility alias
    def start_combat(self, combat: CombatState) -> str:
        """Alias for create_combat using combat.campaign_id (backward compatibility)."""
        return self.create_combat(combat, combat.campaign_id)
    
    def get_combat(self, combat_id: str) -> Optional[CombatState]:
        """Load a combat by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT data FROM combat_state WHERE combat_id = ?",
            (combat_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return CombatState.model_validate_json(result["data"])
        return None
    
    def get_active_combat(self, campaign_id: str) -> Optional[CombatState]:
        """Get the active combat for a campaign, if any."""
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT data FROM combat_state 
               WHERE campaign_id = ? AND is_active = 1
               ORDER BY created_at DESC LIMIT 1""",
            (campaign_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return CombatState.model_validate_json(result["data"])
        return None
    
    def update_combat(self, combat: CombatState) -> bool:
        """Update a combat state."""
        with self.transaction() as cursor:
            cursor.execute(
                """UPDATE combat_state 
                   SET data = ?, is_active = ?, ended_at = ?
                   WHERE combat_id = ?""",
                (
                    combat.model_dump_json(),
                    combat.is_active,
                    datetime.now() if not combat.is_active else None,
                    combat.combat_id,
                )
            )
            return cursor.rowcount > 0
    
    # Backward compatibility aliases
    def get_combat_state(self, combat_id: str) -> Optional[CombatState]:
        """Alias for get_combat (backward compatibility)."""
        return self.get_combat(combat_id)
    
    def update_combat_state(self, combat: CombatState) -> bool:
        """Alias for update_combat (backward compatibility)."""
        return self.update_combat(combat)
    
    def end_combat(self, combat_id: str) -> bool:
        """Mark a combat as ended."""
        with self.transaction() as cursor:
            cursor.execute(
                """UPDATE combat_state 
                   SET is_active = 0, ended_at = ?
                   WHERE combat_id = ?""",
                (datetime.now(), combat_id)
            )
            return cursor.rowcount > 0
    
    def list_combats(self, campaign_id: str, limit: int = 10) -> list[CombatState]:
        """List recent combats for a campaign."""
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT data FROM combat_state 
               WHERE campaign_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (campaign_id, limit)
        )
        return [
            CombatState.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    # =========================================================================
    # NPC OPERATIONS
    # =========================================================================
    
    def create_npc(self, npc: NPC, campaign_id: str) -> str:
        """
        Save a new NPC.
        
        Args:
            npc: The NPC to save.
            campaign_id: The campaign this NPC belongs to.
            
        Returns:
            The NPC's ID.
        """
        source_id = self._extract_source_id(npc)
        
        try:
            with self.transaction() as cursor:
                cursor.execute(
                    """INSERT INTO npcs 
                       (npc_id, campaign_id, name, source_id, data, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        npc.npc_id,
                        campaign_id,
                        npc.name,
                        source_id,
                        npc.model_dump_json(),
                        datetime.now(),
                        datetime.now(),
                    )
                )
            return npc.npc_id
        except sqlite3.IntegrityError as e:
            raise DatabaseError(f"NPC already exists: {npc.npc_id}") from e
    
    def get_npc(self, npc_id: str) -> Optional[NPC]:
        """Load an NPC by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT data FROM npcs WHERE npc_id = ?",
            (npc_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return NPC.model_validate_json(result["data"])
        return None
    
    def update_npc(self, npc: NPC) -> bool:
        """Update an existing NPC."""
        source_id = self._extract_source_id(npc)
        
        with self.transaction() as cursor:
            cursor.execute(
                """UPDATE npcs 
                   SET name = ?, source_id = ?, data = ?, updated_at = ?
                   WHERE npc_id = ?""",
                (npc.name, source_id, npc.model_dump_json(), datetime.now(), npc.npc_id)
            )
            return cursor.rowcount > 0
    
    def list_npcs(
        self, 
        campaign_id: str,
        source_id: Optional[str] = None
    ) -> list[NPC]:
        """
        List all NPCs for a campaign.
        
        Args:
            campaign_id: Campaign to filter by.
            source_id: Optional source to filter by (v1.1).
            
        Returns:
            List of NPCs.
        """
        cursor = self.conn.cursor()
        
        if source_id:
            cursor.execute(
                """SELECT data FROM npcs 
                   WHERE campaign_id = ? AND source_id = ? 
                   ORDER BY name""",
                (campaign_id, source_id)
            )
        else:
            cursor.execute(
                "SELECT data FROM npcs WHERE campaign_id = ? ORDER BY name",
                (campaign_id,)
            )
        
        return [
            NPC.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    # =========================================================================
    # LOCATION OPERATIONS
    # =========================================================================
    
    def save_location(self, location: HexLocation) -> str:
        """
        Save or update a hex location.
        
        Args:
            location: The location to save.
            
        Returns:
            The hex ID.
        """
        source_id = self._extract_source_id(location)
        
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT OR REPLACE INTO locations 
                   (hex_id, source_id, data, created_at, updated_at)
                   VALUES (?, ?, ?, COALESCE((SELECT created_at FROM locations WHERE hex_id = ?), ?), ?)""",
                (
                    location.hex_id,
                    source_id,
                    location.model_dump_json(),
                    location.hex_id,
                    datetime.now(),
                    datetime.now(),
                )
            )
        return location.hex_id
    
    def get_location(self, hex_id: str) -> Optional[HexLocation]:
        """Load a hex location by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT data FROM locations WHERE hex_id = ?",
            (hex_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return HexLocation.model_validate_json(result["data"])
        return None
    
    def list_locations(self, source_id: Optional[str] = None) -> list[HexLocation]:
        """
        List all hex locations.
        
        Args:
            source_id: Optional source to filter by (v1.1).
        """
        cursor = self.conn.cursor()
        
        if source_id:
            cursor.execute(
                "SELECT data FROM locations WHERE source_id = ? ORDER BY hex_id",
                (source_id,)
            )
        else:
            cursor.execute("SELECT data FROM locations ORDER BY hex_id")
        
        return [
            HexLocation.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    # =========================================================================
    # REFERENCE DATA OPERATIONS (Monsters, Items, Spells, Rules)
    # =========================================================================
    
    def save_monster(self, monster: MonsterStatBlock) -> str:
        """Save or update a monster stat block."""
        source_id = self._extract_source_id(monster)
        
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT OR REPLACE INTO monsters 
                   (monster_id, name, source_id, data, created_at)
                   VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM monsters WHERE monster_id = ?), ?))""",
                (
                    monster.monster_id,
                    monster.name,
                    source_id,
                    monster.model_dump_json(),
                    monster.monster_id,
                    datetime.now(),
                )
            )
        return monster.monster_id
    
    def get_monster(self, monster_id: str) -> Optional[MonsterStatBlock]:
        """Load a monster by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT data FROM monsters WHERE monster_id = ?",
            (monster_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return MonsterStatBlock.model_validate_json(result["data"])
        return None
    
    def search_monsters(
        self, 
        name_query: str,
        source_id: Optional[str] = None
    ) -> list[MonsterStatBlock]:
        """
        Search monsters by name.
        
        Args:
            name_query: Name pattern to search.
            source_id: Optional source to filter by (v1.1).
        """
        cursor = self.conn.cursor()
        
        if source_id:
            cursor.execute(
                """SELECT data FROM monsters 
                   WHERE name LIKE ? AND source_id = ? 
                   ORDER BY name""",
                (f"%{name_query}%", source_id)
            )
        else:
            cursor.execute(
                "SELECT data FROM monsters WHERE name LIKE ? ORDER BY name",
                (f"%{name_query}%",)
            )
        
        return [
            MonsterStatBlock.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    def list_monsters(self, source_id: Optional[str] = None) -> list[MonsterStatBlock]:
        """List all monsters, optionally filtered by source."""
        cursor = self.conn.cursor()
        
        if source_id:
            cursor.execute(
                "SELECT data FROM monsters WHERE source_id = ? ORDER BY name",
                (source_id,)
            )
        else:
            cursor.execute("SELECT data FROM monsters ORDER BY name")
        
        return [
            MonsterStatBlock.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    def save_reference_npc(self, npc: NPC) -> str:
        """Save or update a reference NPC (from rulebook/adventure)."""
        source_id = self._extract_source_id(npc)
        location_id = getattr(npc, 'location_id', None)
        
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT OR REPLACE INTO reference_npcs 
                   (npc_id, name, location_id, source_id, data, created_at)
                   VALUES (?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM reference_npcs WHERE npc_id = ?), ?))""",
                (
                    npc.npc_id,
                    npc.name,
                    location_id,
                    source_id,
                    npc.model_dump_json(),
                    npc.npc_id,
                    datetime.now(),
                )
            )
        return npc.npc_id
    
    def get_reference_npc(self, npc_id: str) -> Optional[NPC]:
        """Load a reference NPC by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT data FROM reference_npcs WHERE npc_id = ?",
            (npc_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return NPC.model_validate_json(result["data"])
        return None
    
    def search_reference_npcs(
        self, 
        name_query: str,
        source_id: Optional[str] = None,
        location_id: Optional[str] = None
    ) -> list[NPC]:
        """
        Search reference NPCs by name.
        
        Args:
            name_query: Name pattern to search.
            source_id: Optional source to filter by.
            location_id: Optional location to filter by.
        """
        cursor = self.conn.cursor()
        
        query = "SELECT data FROM reference_npcs WHERE name LIKE ?"
        params = [f"%{name_query}%"]
        
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        
        if location_id:
            query += " AND location_id = ?"
            params.append(location_id)
        
        query += " ORDER BY name"
        cursor.execute(query, params)
        
        return [
            NPC.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    def list_reference_npcs(
        self, 
        source_id: Optional[str] = None,
        location_id: Optional[str] = None
    ) -> list[NPC]:
        """List all reference NPCs, optionally filtered by source or location."""
        cursor = self.conn.cursor()
        
        query = "SELECT data FROM reference_npcs WHERE 1=1"
        params = []
        
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        
        if location_id:
            query += " AND location_id = ?"
            params.append(location_id)
        
        query += " ORDER BY name"
        cursor.execute(query, params)
        
        return [
            NPC.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    def save_item(self, item: Item) -> str:
        """Save or update an item."""
        source_id = self._extract_source_id(item)
        
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT OR REPLACE INTO items 
                   (item_id, name, type, source_id, data, created_at)
                   VALUES (?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM items WHERE item_id = ?), ?))""",
                (
                    item.item_id,
                    item.name,
                    item.type.value,
                    source_id,
                    item.model_dump_json(),
                    item.item_id,
                    datetime.now(),
                )
            )
        return item.item_id
    
    def get_item(self, item_id: str) -> Optional[Item]:
        """Load an item by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT data FROM items WHERE item_id = ?",
            (item_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return Item.model_validate_json(result["data"])
        return None
    
    def search_items(
        self, 
        name_query: str,
        item_type: Optional[str] = None,
        source_id: Optional[str] = None
    ) -> list[Item]:
        """
        Search items by name and optionally type.
        
        Args:
            name_query: Name pattern to search.
            item_type: Optional item type to filter.
            source_id: Optional source to filter by (v1.1).
        """
        cursor = self.conn.cursor()
        
        query = "SELECT data FROM items WHERE name LIKE ?"
        params: list[Any] = [f"%{name_query}%"]
        
        if item_type:
            query += " AND type = ?"
            params.append(item_type)
        
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        
        query += " ORDER BY name"
        cursor.execute(query, params)
        
        return [
            Item.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    def list_items(
        self, 
        item_type: Optional[str] = None,
        source_id: Optional[str] = None
    ) -> list[Item]:
        """List items, optionally filtered by type and/or source."""
        cursor = self.conn.cursor()
        
        query = "SELECT data FROM items WHERE 1=1"
        params: list[Any] = []
        
        if item_type:
            query += " AND type = ?"
            params.append(item_type)
        
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        
        query += " ORDER BY name"
        cursor.execute(query, params)
        
        return [
            Item.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    def save_spell(self, spell: Spell) -> str:
        """Save or update a spell."""
        source_id = self._extract_source_id(spell)
        
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT OR REPLACE INTO spells 
                   (spell_id, name, level, magic_type, source_id, data, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM spells WHERE spell_id = ?), ?))""",
                (
                    spell.spell_id,
                    spell.name,
                    spell.level,
                    spell.magic_type.value,
                    source_id,
                    spell.model_dump_json(),
                    spell.spell_id,
                    datetime.now(),
                )
            )
        return spell.spell_id
    
    def get_spell(self, spell_id: str) -> Optional[Spell]:
        """Load a spell by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT data FROM spells WHERE spell_id = ?",
            (spell_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return Spell.model_validate_json(result["data"])
        return None
    
    def search_spells(
        self, 
        name_query: str,
        level: Optional[int] = None,
        magic_type: Optional[str] = None,
        source_id: Optional[str] = None
    ) -> list[Spell]:
        """Search spells with various filters."""
        cursor = self.conn.cursor()
        
        query = "SELECT data FROM spells WHERE name LIKE ?"
        params: list[Any] = [f"%{name_query}%"]
        
        if level is not None:
            query += " AND level = ?"
            params.append(level)
        
        if magic_type:
            query += " AND magic_type = ?"
            params.append(magic_type)
        
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        
        query += " ORDER BY level, name"
        cursor.execute(query, params)
        
        return [
            Spell.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    def list_spells(
        self,
        level: Optional[int] = None,
        magic_type: Optional[str] = None,
        source_id: Optional[str] = None
    ) -> list[Spell]:
        """List spells with optional filters."""
        cursor = self.conn.cursor()
        
        query = "SELECT data FROM spells WHERE 1=1"
        params: list[Any] = []
        
        if level is not None:
            query += " AND level = ?"
            params.append(level)
        
        if magic_type:
            query += " AND magic_type = ?"
            params.append(magic_type)
        
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        
        query += " ORDER BY level, name"
        cursor.execute(query, params)
        
        return [
            Spell.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    def save_rule(self, rule: GameRule) -> str:
        """Save or update a game rule."""
        source_id = self._extract_source_id(rule)
        content_type = rule.content_type.value if hasattr(rule, 'content_type') and rule.content_type else None
        
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT OR REPLACE INTO rules 
                   (rule_id, category, title, source_id, content_type, data, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM rules WHERE rule_id = ?), ?))""",
                (
                    rule.rule_id,
                    rule.category,
                    rule.title,
                    source_id,
                    content_type,
                    rule.model_dump_json(),
                    rule.rule_id,
                    datetime.now(),
                )
            )
        return rule.rule_id
    
    def get_rule(self, rule_id: str) -> Optional[GameRule]:
        """Load a rule by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT data FROM rules WHERE rule_id = ?",
            (rule_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return GameRule.model_validate_json(result["data"])
        return None
    
    def search_rules(
        self, 
        query_text: str,
        category: Optional[str] = None,
        source_id: Optional[str] = None,
        content_type: Optional[str] = None
    ) -> list[GameRule]:
        """Search rules with various filters."""
        cursor = self.conn.cursor()
        
        query = "SELECT data FROM rules WHERE (title LIKE ? OR category LIKE ?)"
        params: list[Any] = [f"%{query_text}%", f"%{query_text}%"]
        
        if category:
            query += " AND category = ?"
            params.append(category)
        
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        
        if content_type:
            query += " AND content_type = ?"
            params.append(content_type)
        
        query += " ORDER BY category, title"
        cursor.execute(query, params)
        
        return [
            GameRule.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    def list_rules(
        self,
        category: Optional[str] = None,
        source_id: Optional[str] = None,
        content_type: Optional[str] = None
    ) -> list[GameRule]:
        """List rules with optional filters."""
        cursor = self.conn.cursor()
        
        query = "SELECT data FROM rules WHERE 1=1"
        params: list[Any] = []
        
        if category:
            query += " AND category = ?"
            params.append(category)
        
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        
        if content_type:
            query += " AND content_type = ?"
            params.append(content_type)
        
        query += " ORDER BY category, title"
        cursor.execute(query, params)
        
        return [
            GameRule.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    # =========================================================================
    # ADVENTURE MODULE OPERATIONS (v1.1)
    # =========================================================================
    
    def save_adventure_module(self, adventure: AdventureModule) -> str:
        """
        Save or update an adventure module.
        
        Args:
            adventure: The adventure module to save.
            
        Returns:
            The adventure ID.
        """
        source_id = adventure.source.source_id if adventure.source else adventure.adventure_id
        
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT OR REPLACE INTO adventure_modules 
                   (adventure_id, title, adventure_type, source_id, data, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 
                           COALESCE((SELECT created_at FROM adventure_modules WHERE adventure_id = ?), ?), ?)""",
                (
                    adventure.adventure_id,
                    adventure.title,
                    adventure.adventure_type.value,
                    source_id,
                    adventure.model_dump_json(),
                    adventure.adventure_id,
                    datetime.now(),
                    datetime.now(),
                )
            )
        logger.info(f"Saved adventure module: {adventure.title}")
        return adventure.adventure_id
    
    def get_adventure_module(self, adventure_id: str) -> Optional[AdventureModule]:
        """Load an adventure module by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT data FROM adventure_modules WHERE adventure_id = ?",
            (adventure_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return AdventureModule.model_validate_json(result["data"])
        return None
    
    def list_adventure_modules(
        self,
        adventure_type: Optional[AdventureType] = None,
        source_id: Optional[str] = None
    ) -> list[AdventureModule]:
        """
        List adventure modules with optional filters.
        
        Args:
            adventure_type: Optional type filter.
            source_id: Optional source filter.
        """
        cursor = self.conn.cursor()
        
        query = "SELECT data FROM adventure_modules WHERE 1=1"
        params: list[Any] = []
        
        if adventure_type:
            query += " AND adventure_type = ?"
            params.append(adventure_type.value)
        
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        
        query += " ORDER BY title"
        cursor.execute(query, params)
        
        return [
            AdventureModule.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    def delete_adventure_module(self, adventure_id: str) -> bool:
        """
        Delete an adventure module and its locations.
        
        Args:
            adventure_id: The adventure to delete.
            
        Returns:
            True if deleted.
        """
        with self.transaction() as cursor:
            # Delete locations first
            cursor.execute(
                "DELETE FROM adventure_locations WHERE adventure_id = ?",
                (adventure_id,)
            )
            
            # Delete campaign associations
            cursor.execute(
                "DELETE FROM campaign_adventures WHERE adventure_id = ?",
                (adventure_id,)
            )
            
            # Delete module
            cursor.execute(
                "DELETE FROM adventure_modules WHERE adventure_id = ?",
                (adventure_id,)
            )
            
            return cursor.rowcount > 0
    
    # =========================================================================
    # ADVENTURE LOCATION OPERATIONS (v1.1)
    # =========================================================================
    
    def save_adventure_location(self, location: AdventureLocation) -> str:
        """
        Save or update an adventure location.
        
        Args:
            location: The location to save.
            
        Returns:
            The location ID.
        """
        source_id = self._extract_source_id(location)
        
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT OR REPLACE INTO adventure_locations 
                   (location_id, adventure_id, name, number, source_id, data, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 
                           COALESCE((SELECT created_at FROM adventure_locations WHERE location_id = ?), ?), ?)""",
                (
                    location.location_id,
                    location.adventure_id,
                    location.name,
                    location.number,
                    source_id,
                    location.model_dump_json(),
                    location.location_id,
                    datetime.now(),
                    datetime.now(),
                )
            )
        return location.location_id
    
    def get_adventure_location(self, location_id: str) -> Optional[AdventureLocation]:
        """Load an adventure location by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT data FROM adventure_locations WHERE location_id = ?",
            (location_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return AdventureLocation.model_validate_json(result["data"])
        return None
    
    def get_adventure_location_by_number(
        self, 
        adventure_id: str, 
        number: str
    ) -> Optional[AdventureLocation]:
        """Load an adventure location by adventure ID and room number."""
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT data FROM adventure_locations 
               WHERE adventure_id = ? AND number = ?""",
            (adventure_id, number)
        )
        result = cursor.fetchone()
        
        if result:
            return AdventureLocation.model_validate_json(result["data"])
        return None
    
    def list_adventure_locations(
        self, 
        adventure_id: str
    ) -> list[AdventureLocation]:
        """
        List all locations for an adventure.
        
        Args:
            adventure_id: Adventure to get locations for.
            
        Returns:
            List of locations ordered by number.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT data FROM adventure_locations 
               WHERE adventure_id = ? 
               ORDER BY number""",
            (adventure_id,)
        )
        
        return [
            AdventureLocation.model_validate_json(row["data"])
            for row in cursor.fetchall()
        ]
    
    def update_adventure_location(self, location: AdventureLocation) -> bool:
        """Update an adventure location."""
        source_id = self._extract_source_id(location)
        
        with self.transaction() as cursor:
            cursor.execute(
                """UPDATE adventure_locations 
                   SET name = ?, number = ?, source_id = ?, data = ?, updated_at = ?
                   WHERE location_id = ?""",
                (
                    location.name,
                    location.number,
                    source_id,
                    location.model_dump_json(),
                    datetime.now(),
                    location.location_id,
                )
            )
            return cursor.rowcount > 0
    
    # =========================================================================
    # CAMPAIGN-ADVENTURE ASSOCIATION (v1.1)
    # =========================================================================
    
    def add_adventure_to_campaign(
        self,
        campaign_id: str,
        adventure_id: str,
        starting_location_id: Optional[str] = None
    ) -> None:
        """
        Associate an adventure module with a campaign.
        
        Args:
            campaign_id: The campaign.
            adventure_id: The adventure to add.
            starting_location_id: Optional starting location.
        """
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT OR REPLACE INTO campaign_adventures 
                   (campaign_id, adventure_id, status, started_at, current_location_id)
                   VALUES (?, ?, 'active', ?, ?)""",
                (campaign_id, adventure_id, datetime.now(), starting_location_id)
            )
    
    def get_campaign_adventures(
        self, 
        campaign_id: str,
        status: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """
        Get adventures associated with a campaign.
        
        Args:
            campaign_id: Campaign to query.
            status: Optional status filter ('active', 'completed').
            
        Returns:
            List of adventure info dicts.
        """
        cursor = self.conn.cursor()
        
        if status:
            cursor.execute(
                """SELECT ca.*, am.title, am.adventure_type 
                   FROM campaign_adventures ca
                   JOIN adventure_modules am ON ca.adventure_id = am.adventure_id
                   WHERE ca.campaign_id = ? AND ca.status = ?""",
                (campaign_id, status)
            )
        else:
            cursor.execute(
                """SELECT ca.*, am.title, am.adventure_type 
                   FROM campaign_adventures ca
                   JOIN adventure_modules am ON ca.adventure_id = am.adventure_id
                   WHERE ca.campaign_id = ?""",
                (campaign_id,)
            )
        
        return [dict(row) for row in cursor.fetchall()]
    
    def update_campaign_adventure_progress(
        self,
        campaign_id: str,
        adventure_id: str,
        current_location_id: Optional[str] = None,
        notes: Optional[str] = None,
        status: Optional[str] = None
    ) -> bool:
        """
        Update progress in an adventure.
        
        Args:
            campaign_id: The campaign.
            adventure_id: The adventure.
            current_location_id: Current location in adventure.
            notes: DM notes about progress.
            status: New status ('active', 'completed', 'abandoned').
        """
        updates = []
        params: list[Any] = []
        
        if current_location_id is not None:
            updates.append("current_location_id = ?")
            params.append(current_location_id)
        
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)
        
        if status is not None:
            updates.append("status = ?")
            params.append(status)
            if status == 'completed':
                updates.append("completed_at = ?")
                params.append(datetime.now())
        
        if not updates:
            return False
        
        params.extend([campaign_id, adventure_id])
        
        with self.transaction() as cursor:
            cursor.execute(
                f"""UPDATE campaign_adventures 
                   SET {', '.join(updates)}
                   WHERE campaign_id = ? AND adventure_id = ?""",
                params
            )
            return cursor.rowcount > 0
    
    # =========================================================================
    # HISTORY OPERATIONS
    # =========================================================================
    
    def log_history(
        self, 
        entry: Optional[HistoryEntry] = None, 
        campaign_id: Optional[str] = None,
        *,
        turn_number: Optional[int] = None,
        event_type: Optional[str] = None,
        player_input: Optional[str] = None,
        dm_response: Optional[str] = None,
        state_changes: Optional[dict] = None,
        dice_rolls: Optional[list] = None
    ) -> str:
        """
        Log a history entry.
        
        Can be called with a HistoryEntry object or with keyword arguments:
        
        Args:
            entry: The history entry to log (if provided, ignores other args).
            campaign_id: Campaign this entry belongs to.
            turn_number: Turn number when event occurred.
            event_type: Type of event (action, combat, social, etc.)
            player_input: What the player said/did.
            dm_response: DM's response.
            state_changes: Dictionary of state changes.
            dice_rolls: List of dice rolls.
            
        Returns:
            The entry ID.
        """
        # If entry object provided, use it directly
        if entry is not None:
            hist_entry = entry
            cid = campaign_id or entry.campaign_id
        else:
            # Construct entry from keyword arguments
            if not campaign_id:
                raise ValueError("campaign_id is required")
            cid = campaign_id
            
            from data_models import generate_id
            hist_entry = HistoryEntry(
                entry_id=generate_id("hist"),
                campaign_id=cid,
                turn_number=turn_number or 0,
                event_type=event_type or "action",
                player_input=player_input,
                dm_response=dm_response,
                state_changes=state_changes or {},
                dice_rolls=dice_rolls or [],
            )
        
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT INTO history_log 
                   (entry_id, campaign_id, turn_number, timestamp, event_type,
                    player_input, dm_response, state_changes, dice_rolls)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    hist_entry.entry_id,
                    cid,
                    hist_entry.turn_number,
                    hist_entry.timestamp,
                    hist_entry.event_type.value if hasattr(hist_entry.event_type, 'value') else hist_entry.event_type,
                    hist_entry.player_input,
                    hist_entry.dm_response,
                    json.dumps(hist_entry.state_changes) if hist_entry.state_changes else None,
                    json.dumps(hist_entry.dice_rolls) if hist_entry.dice_rolls else None,
                )
            )
        return hist_entry.entry_id
    
    def get_history(
        self, 
        campaign_id: str, 
        limit: int = 50,
        event_type: Optional[str] = None
    ) -> list[HistoryEntry]:
        """
        Get history entries for a campaign.
        
        Args:
            campaign_id: Campaign to get history for.
            limit: Maximum entries to return.
            event_type: Optional event type filter.
            
        Returns:
            List of history entries, most recent first.
        """
        cursor = self.conn.cursor()
        
        if event_type:
            cursor.execute(
                """SELECT * FROM history_log 
                   WHERE campaign_id = ? AND event_type = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (campaign_id, event_type, limit)
            )
        else:
            cursor.execute(
                """SELECT * FROM history_log 
                   WHERE campaign_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (campaign_id, limit)
            )
        
        entries = []
        for row in cursor.fetchall():
            entries.append(HistoryEntry(
                entry_id=row["entry_id"],
                campaign_id=campaign_id,
                turn_number=row["turn_number"],
                timestamp=row["timestamp"],
                event_type=row["event_type"],
                player_input=row["player_input"],
                dm_response=row["dm_response"],
                state_changes=json.loads(row["state_changes"]) if row["state_changes"] else {},
                dice_rolls=json.loads(row["dice_rolls"]) if row["dice_rolls"] else [],
            ))
        
        return entries
    
    # Backward compatibility aliases
    def get_recent_history(self, campaign_id: str, limit: int = 50) -> list[HistoryEntry]:
        """Alias for get_history (backward compatibility)."""
        return self.get_history(campaign_id, limit)
    
    def get_history_by_type(self, campaign_id: str, event_type: str) -> list[HistoryEntry]:
        """Get history filtered by event type (backward compatibility)."""
        return self.get_history(campaign_id, event_type=event_type)
    
    def clear_history(self, campaign_id: str) -> int:
        """
        Clear all history for a campaign.
        
        Returns:
            Number of entries deleted.
        """
        with self.transaction() as cursor:
            cursor.execute(
                "DELETE FROM history_log WHERE campaign_id = ?",
                (campaign_id,)
            )
            return cursor.rowcount
    
    # =========================================================================
    # SESSION SAVE/LOAD
    # =========================================================================
    
    def create_save(
        self, 
        campaign_id: str, 
        save_name: str,
        description: Optional[str] = None
    ) -> str:
        """
        Create a session save point.
        
        Args:
            campaign_id: Campaign to save.
            save_name: Name for this save.
            description: Optional description.
            
        Returns:
            The save ID.
        """
        # Gather all campaign data
        world_state = self.get_campaign(campaign_id)
        if not world_state:
            raise DatabaseError(f"Campaign not found: {campaign_id}")
        
        characters = self.list_characters(campaign_id)
        npcs = self.list_npcs(campaign_id)
        active_combat = self.get_active_combat(campaign_id)
        history = self.get_history(campaign_id, limit=100)
        adventures = self.get_campaign_adventures(campaign_id)
        
        # Convert to dicts for SessionSave
        save = SessionSave(
            campaign_id=campaign_id,
            save_name=save_name,
            description=description or "",
            world_state=world_state.model_dump(),
            characters=[c.model_dump() for c in characters],
            combat_state=active_combat.model_dump() if active_combat else None,
        )
        
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT INTO session_saves 
                   (save_id, campaign_id, save_name, description, save_data, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    save.save_id,
                    campaign_id,
                    save_name,
                    description,
                    save.model_dump_json(),
                    datetime.now(),
                )
            )
        
        logger.info(f"Created save: {save_name} ({save.save_id})")
        return save.save_id
    
    def load_save(self, save_id: str) -> Optional[SessionSave]:
        """
        Load a session save.
        
        Args:
            save_id: ID of the save to load.
            
        Returns:
            The SessionSave if found.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT save_data FROM session_saves WHERE save_id = ?",
            (save_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return SessionSave.model_validate_json(result["save_data"])
        return None
    
    def list_saves(self, campaign_id: str) -> list[dict[str, Any]]:
        """
        List saves for a campaign.
        
        Returns:
            List of save metadata (not full save data).
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT save_id, save_name, description, created_at
               FROM session_saves WHERE campaign_id = ?
               ORDER BY created_at DESC""",
            (campaign_id,)
        )
        
        return [dict(row) for row in cursor.fetchall()]
    
    def delete_save(self, save_id: str) -> bool:
        """Delete a session save."""
        with self.transaction() as cursor:
            cursor.execute(
                "DELETE FROM session_saves WHERE save_id = ?",
                (save_id,)
            )
            return cursor.rowcount > 0
    
    # Backward compatibility methods
    def save_session(
        self,
        campaign_id: str,
        save_name: str,
        description: Optional[str] = None
    ) -> str:
        """Alias for create_save (backward compatibility)."""
        return self.create_save(campaign_id, save_name, description)
    
    def load_session(self, save_id: str) -> Optional[dict[str, Any]]:
        """
        Load a session save and return as dict (backward compatibility).
        
        Returns:
            Dict with save_name and data keys.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT save_name, save_data FROM session_saves WHERE save_id = ?",
            (save_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return {
                "save_name": result["save_name"],
                "data": json.loads(result["save_data"]),
            }
        return None
    
    def restore_session(self, save_id: str) -> bool:
        """
        Restore game state from a save.
        
        Args:
            save_id: ID of the save to restore.
            
        Returns:
            True if restore succeeded.
        """
        save = self.load_save(save_id)
        if not save:
            return False
        
        try:
            # Restore world state
            if save.world_state:
                world_state = WorldState.model_validate(save.world_state)
                self.update_campaign(world_state)
            
            # Restore characters
            for char_data in save.characters:
                character = DolmenwoodCharacter.model_validate(char_data)
                if self.get_character(character.character_id):
                    self.update_character(character)
            
            logger.info(f"Restored session from save: {save_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to restore session: {e}")
            return False
    
    # =========================================================================
    # BULK IMPORT OPERATIONS (v1.1)
    # =========================================================================
    
    def import_extraction_result(
        self,
        result: Any,  # ExtractionResult from PDF processor
        resolve_conflicts: bool = True
    ) -> dict[str, int]:
        """
        Import content from a PDF extraction result.
        
        Args:
            result: ExtractionResult from DolmenwoodPDFProcessor.
            resolve_conflicts: Whether to resolve conflicts by source priority.
            
        Returns:
            Dict with counts of imported items.
        """
        counts = {
            "rules": 0,
            "spells": 0,
            "items": 0,
            "monsters": 0,
            "hexes": 0,
            "npcs": 0,
            "adventure_locations": 0,
            "adventure_modules": 0,
        }
        
        # Import rules
        rules = result.rules
        if resolve_conflicts:
            rules = self.resolve_content_conflict(rules, "title")
        for rule in rules:
            self.save_rule(rule)
            counts["rules"] += 1
        
        # Import spells
        spells = result.spells
        if resolve_conflicts:
            spells = self.resolve_content_conflict(spells, "name")
        for spell in spells:
            self.save_spell(spell)
            counts["spells"] += 1
        
        # Import items
        items = result.items
        if resolve_conflicts:
            items = self.resolve_content_conflict(items, "name")
        for item in items:
            self.save_item(item)
            counts["items"] += 1
        
        # Import monsters
        monsters = result.monsters
        if resolve_conflicts:
            monsters = self.resolve_content_conflict(monsters, "name")
        for monster in monsters:
            self.save_monster(monster)
            counts["monsters"] += 1
        
        # Import hex locations
        for location in result.hexes:
            self.save_location(location)
            counts["hexes"] += 1
        
        # Import NPCs (v1.1)
        if hasattr(result, 'npcs') and result.npcs:
            npcs = result.npcs
            if resolve_conflicts:
                npcs = self.resolve_content_conflict(npcs, "name")
            for npc in npcs:
                self.save_reference_npc(npc)
                counts["npcs"] += 1
        
        # Import adventure modules (v1.1)
        if hasattr(result, 'adventure_modules'):
            for module in result.adventure_modules:
                self.save_adventure_module(module)
                counts["adventure_modules"] += 1
        
        # Import adventure locations (v1.1)
        if hasattr(result, 'adventure_locations'):
            for location in result.adventure_locations:
                self.save_adventure_location(location)
                counts["adventure_locations"] += 1
        
        logger.info(f"Imported content: {counts}")
        return counts
    
    # =========================================================================
    # FOUNDRY VTT EXPORT
    # =========================================================================
    
    def export_to_foundry(self, campaign_id: str) -> dict[str, Any]:
        """
        Export campaign data in Foundry VTT format.
        
        Args:
            campaign_id: Campaign to export.
            
        Returns:
            Dictionary in Foundry VTT compatible format.
        """
        world_state = self.get_campaign(campaign_id)
        if not world_state:
            raise DatabaseError(f"Campaign not found: {campaign_id}")
        
        characters = self.list_characters(campaign_id)
        npcs = self.list_npcs(campaign_id)
        
        return {
            "name": world_state.campaign_name,
            "system": "ose",  # Old-School Essentials system
            "actors": [
                self._character_to_foundry(char)
                for char in characters
            ] + [
                self._npc_to_foundry(npc)
                for npc in npcs
            ],
            "items": [
                self._item_to_foundry(item)
                for item in self.list_items()
            ],
            "journal": self._quests_to_foundry_journals(world_state.active_quests),
            "scenes": [],  # TODO: Add scene export
        }
    
    # Backward compatibility alias
    def export_for_foundry(self, campaign_id: str) -> dict[str, Any]:
        """Alias for export_to_foundry (backward compatibility)."""
        return self.export_to_foundry(campaign_id)
    
    def _character_to_foundry(self, character: DolmenwoodCharacter) -> dict[str, Any]:
        """Convert character to Foundry actor format."""
        # Helper to get ability score value (handles both int and objects with .value)
        def get_ability_value(ability):
            if hasattr(ability, 'value'):
                return ability.value
            return ability
        
        return {
            "_id": character.foundry_actor_id or character.character_id,
            "name": character.name,
            "type": "character",
            "system": {
                "abilities": {
                    "str": {"value": get_ability_value(character.strength)},
                    "dex": {"value": get_ability_value(character.dexterity)},
                    "con": {"value": get_ability_value(character.constitution)},
                    "int": {"value": get_ability_value(character.intelligence)},
                    "wis": {"value": get_ability_value(character.wisdom)},
                    "cha": {"value": get_ability_value(character.charisma)},
                },
                "attributes": {
                    "hp": {
                        "value": character.hp_current,
                        "max": character.hp_max,
                    },
                    "ac": {"value": character.ac},
                },
                "details": {
                    "race": character.kindred.value,
                    "class": character.character_class.value,
                    "level": {"value": character.level},
                    "xp": {"value": character.xp_current},
                },
                "saves": {
                    "doom": {"value": character.save_doom},
                    "ray": {"value": character.save_ray},
                    "hold": {"value": character.save_hold},
                    "blast": {"value": character.save_blast},
                    "spell": {"value": character.save_spell},
                },
                "currency": {
                    "sp": character.currency_sp,
                },
            },
            "items": [
                self._item_to_foundry(item) for item in character.inventory
            ],
        }
    
    def _npc_to_foundry(self, npc: NPC) -> dict[str, Any]:
        """Convert NPC to Foundry actor format."""
        return {
            "_id": npc.foundry_actor_id or npc.npc_id,
            "name": npc.name,
            "type": "npc" if not npc.is_combatant else "character",
            "system": {
                "details": {
                    "race": npc.kindred,
                    "class": npc.character_class or "",
                    "level": {"value": npc.level or 0},
                },
                "attributes": {
                    "hp": {"value": npc.hp or 0, "max": npc.hp or 0},
                    "ac": {"value": npc.ac or 10},
                } if npc.is_combatant else {},
                "biography": npc.initial_dialogue,
            },
        }
    
    def _item_to_foundry(self, item: Item) -> dict[str, Any]:
        """Convert item to Foundry item format."""
        return {
            "_id": item.foundry_item_id or item.item_id,
            "name": item.name,
            "type": item.type.value,
            "system": {
                "weight": item.weight,
                "cost": item.cost_sp,
                "damage": item.damage or "",
                "ac": item.ac_bonus or 0,
                "description": item.description,
                "quantity": {"value": item.quantity},
            },
        }
    
    def _quests_to_foundry_journals(self, quests: list[Quest]) -> list[dict[str, Any]]:
        """Convert quests to Foundry journal entries."""
        return [
            {
                "_id": quest.quest_id,
                "name": quest.title,
                "pages": [
                    {
                        "name": "Description",
                        "type": "text",
                        "text": {
                            "content": f"<p>{quest.description}</p>"
                            + "<h2>Objectives</h2><ul>"
                            + "".join(
                                f"<li>{'✓ ' if obj.completed else ''}{obj.description}</li>"
                                for obj in quest.objectives
                            )
                            + "</ul>"
                            + f"<h2>Rewards</h2><p>{quest.rewards}</p>"
                        },
                    }
                ],
            }
            for quest in quests
        ]
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    def get_statistics(self, campaign_id: str) -> dict[str, Any]:
        """
        Get statistics for a campaign.
        
        Returns counts and summaries for various game elements.
        """
        cursor = self.conn.cursor()
        
        stats = {}
        
        # Character count
        cursor.execute(
            "SELECT COUNT(*) FROM characters WHERE campaign_id = ?",
            (campaign_id,)
        )
        stats["character_count"] = cursor.fetchone()[0]
        
        # NPC count
        cursor.execute(
            "SELECT COUNT(*) FROM npcs WHERE campaign_id = ?",
            (campaign_id,)
        )
        stats["npc_count"] = cursor.fetchone()[0]
        
        # Combat count
        cursor.execute(
            "SELECT COUNT(*) FROM combat_state WHERE campaign_id = ?",
            (campaign_id,)
        )
        stats["combat_count"] = cursor.fetchone()[0]
        
        # History entry count
        cursor.execute(
            "SELECT COUNT(*) FROM history_log WHERE campaign_id = ?",
            (campaign_id,)
        )
        stats["history_entries"] = cursor.fetchone()[0]
        
        # Save count
        cursor.execute(
            "SELECT COUNT(*) FROM session_saves WHERE campaign_id = ?",
            (campaign_id,)
        )
        stats["save_count"] = cursor.fetchone()[0]
        
        # v1.1: Adventure counts
        cursor.execute(
            "SELECT COUNT(*) FROM campaign_adventures WHERE campaign_id = ?",
            (campaign_id,)
        )
        stats["adventure_count"] = cursor.fetchone()[0]
        
        return stats
    
    def get_global_statistics(self) -> dict[str, Any]:
        """Get global database statistics."""
        cursor = self.conn.cursor()
        
        stats = {}
        
        tables = [
            ("campaigns", "world_state"),
            ("characters", "characters"),
            ("npcs", "npcs"),
            ("monsters", "monsters"),
            ("items", "items"),
            ("spells", "spells"),
            ("rules", "rules"),
            ("locations", "locations"),
            ("adventure_modules", "adventure_modules"),
            ("adventure_locations", "adventure_locations"),
        ]
        
        for name, table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            stats[f"total_{name}"] = cursor.fetchone()[0]
        
        return stats
    
    def vacuum(self) -> None:
        """Optimize database by running VACUUM."""
        self.conn.execute("VACUUM")
        logger.info("Database vacuumed")
    
    def backup(self, backup_path: str) -> None:
        """
        Create a backup of the database.
        
        Args:
            backup_path: Path for the backup file.
        """
        import shutil
        self.conn.commit()
        shutil.copy2(self.db_path, backup_path)
        logger.info(f"Database backed up to {backup_path}")


# Module-level convenience function
def create_manager(
    db_path: str = "./data/game_state.db",
    content_manager: Optional[Any] = None
) -> GameStateManager:
    """Create a new GameStateManager instance."""
    return GameStateManager(db_path, content_manager)
