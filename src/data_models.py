"""
Dolmenwood AI Dungeon Master - Data Models (v1.1)

This module contains all Pydantic data models for the Dolmenwood AI DM system.
These models define the structure for characters, world state, combat, locations,
NPCs, items, spells, and game rules.

VERSION 1.1 CHANGES:
- Added source tracking to all content models (SourceReference, ContentSource)
- Added adventure module support (AdventureModule, AdventureLocation)
- Added content type classification (ContentType enum)
- Added conflict resolution support (version, supersedes fields)
- Added adventure progress tracking to WorldState

Based on Old-School Essentials (OSE) / B/X D&D mechanics with Dolmenwood-specific
extensions.

Author: AI Dungeon Master Project
Version: 1.1
"""

from __future__ import annotations

import re
import uuid
import random
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# ENUMERATIONS
# =============================================================================

class Kindred(str, Enum):
    """Playable kindreds (races) in Dolmenwood."""
    HUMAN = "Human"
    ELF = "Elf"
    BREGGLE = "Breggle"
    GRIMALKIN = "Grimalkin"
    MOSSLING = "Mossling"
    WOODGRUE = "Woodgrue"


class CharacterClass(str, Enum):
    """Character classes available in Dolmenwood."""
    BARD = "Bard"
    CLERIC = "Cleric"
    ENCHANTER = "Enchanter"
    FIGHTER = "Fighter"
    FRIAR = "Friar"
    HUNTER = "Hunter"
    KNIGHT = "Knight"
    MAGICIAN = "Magician"
    THIEF = "Thief"


class ItemType(str, Enum):
    """Types of items in the game."""
    WEAPON = "weapon"
    ARMOR = "armor"
    SHIELD = "shield"
    GEAR = "gear"
    TREASURE = "treasure"
    MAGIC = "magic"
    CONSUMABLE = "consumable"


class MagicType(str, Enum):
    """Types of magic in Dolmenwood."""
    ARCANE = "arcane"
    DIVINE = "divine"
    FAIRY_GLAMOUR = "fairy_glamour"
    RUNE = "rune"
    KNACK = "knack"


class TimeOfDay(str, Enum):
    """Time of day for tracking game time."""
    DAWN = "dawn"
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    DUSK = "dusk"
    NIGHT = "night"


class Season(str, Enum):
    """Seasons in Dolmenwood."""
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"


class Weather(str, Enum):
    """Weather conditions."""
    CLEAR = "clear"
    RAIN = "rain"
    FOG = "fog"
    SNOW = "snow"
    STORM = "storm"


class LocationType(str, Enum):
    """Types of locations."""
    WILDERNESS = "wilderness"
    SETTLEMENT = "settlement"
    DUNGEON = "dungeon"
    OTHER = "other"


class TerrainType(str, Enum):
    """Terrain types for hex locations."""
    FOREST = "forest"
    HILLS = "hills"
    MOUNTAINS = "mountains"
    SWAMP = "swamp"
    WATER = "water"
    SETTLEMENT = "settlement"
    PLAINS = "plains"


class QuestStatus(str, Enum):
    """Quest completion status."""
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


class RelationshipLevel(str, Enum):
    """NPC relationship levels with party."""
    HOSTILE = "hostile"
    UNFRIENDLY = "unfriendly"
    NEUTRAL = "neutral"
    FRIENDLY = "friendly"
    ALLIED = "allied"


class SettlementSize(str, Enum):
    """Settlement size categories."""
    HAMLET = "hamlet"
    VILLAGE = "village"
    TOWN = "town"
    CITY = "city"


class SaveType(str, Enum):
    """Types of saving throws in OSE."""
    DOOM = "doom"
    RAY = "ray"
    HOLD = "hold"
    BLAST = "blast"
    SPELL = "spell"


class AdventureType(str, Enum):
    """Types of adventure modules."""
    DUNGEON_CRAWL = "dungeon_crawl"
    WILDERNESS = "wilderness"
    URBAN = "urban"
    MIXED = "mixed"


# =============================================================================
# NEW v1.1: SOURCE TRACKING ENUMERATIONS
# =============================================================================

class SourceType(str, Enum):
    """
    Content source types with implicit priority.
    
    Priority order (lower = higher priority):
    1. CORE_RULEBOOK - Player's Book, Monster Book
    2. CAMPAIGN_SETTING - Campaign Book
    3. ADVENTURE_MODULE - Published adventures
    4. HOMEBREW - User-created content
    """
    CORE_RULEBOOK = "core_rulebook"
    CAMPAIGN_SETTING = "campaign_setting"
    ADVENTURE_MODULE = "adventure_module"
    HOMEBREW = "homebrew"


class ContentType(str, Enum):
    """
    Types of game content for classification.
    
    Used to categorize content for context-aware retrieval
    and conflict resolution.
    """
    CORE_RULE = "core_rule"
    SETTING_LORE = "setting_lore"
    MONSTER_STAT = "monster_stat"
    SPELL = "spell"
    ITEM = "item"
    LOCATION = "location"
    NPC = "npc"
    ADVENTURE_CONTENT = "adventure_content"


# =============================================================================
# TYPE ALIASES AND ANNOTATED TYPES
# =============================================================================

AbilityScore = Annotated[int, Field(ge=3, le=18)]
SaveTarget = Annotated[int, Field(ge=2, le=20)]
SkillValue = Annotated[int, Field(ge=0, le=6)]
MoraleScore = Annotated[int, Field(ge=2, le=12)]
HexId = Annotated[str, Field(pattern=r"^\d{4}$")]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def generate_id(prefix: str = "id") -> str:
    """Generate a unique identifier with a prefix."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def calculate_ability_modifier(score: int) -> int:
    """Calculate the modifier for an ability score using OSE/B/X rules."""
    if score <= 3:
        return -3
    elif score <= 5:
        return -2
    elif score <= 8:
        return -1
    elif score <= 12:
        return 0
    elif score <= 15:
        return 1
    elif score <= 17:
        return 2
    else:
        return 3


# =============================================================================
# NEW v1.1: SOURCE TRACKING MODELS
# =============================================================================

class SourceReference(BaseModel):
    """
    Lightweight reference to a content source.
    
    Used to attribute content to its original source without
    duplicating the full ContentSource information.
    """
    source_id: str
    book_code: str
    page_reference: Optional[str] = None
    section: Optional[str] = None


class ContentSource(BaseModel):
    """
    Track where content came from.
    
    Represents a complete source book or PDF file that content
    has been extracted from.
    """
    source_id: str = Field(description="Unique identifier for this source")
    source_type: SourceType
    book_name: str = Field(description="Human-readable name")
    book_code: str = Field(description="Short code for reference")
    version: str = Field(default="1.0", description="Book version/edition")
    publication_date: Optional[str] = None
    publisher: str = Field(default="Necrotic Gnome")
    
    file_path: str = Field(description="Path to PDF file")
    file_hash: Optional[str] = Field(default=None, description="SHA-256 hash")
    
    page_count: Optional[int] = None
    imported_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)
    
    def get_priority(self) -> int:
        """Get priority level (lower = higher priority)."""
        priority_map = {
            SourceType.CORE_RULEBOOK: 1,
            SourceType.CAMPAIGN_SETTING: 2,
            SourceType.ADVENTURE_MODULE: 3,
            SourceType.HOMEBREW: 4
        }
        return priority_map[self.source_type]


# =============================================================================
# ITEM MODELS
# =============================================================================

class Item(BaseModel):
    """Item/equipment representation."""
    
    item_id: str = Field(default_factory=lambda: generate_id("item"))
    name: str
    type: ItemType
    weight: float = Field(ge=0, default=0)
    cost_sp: int = Field(ge=0, default=0)
    
    damage: Optional[str] = Field(default=None)
    is_melee: bool = True
    is_ranged: bool = False
    range_short: Optional[int] = None
    range_medium: Optional[int] = None
    range_long: Optional[int] = None
    two_handed: bool = False
    
    ac_bonus: Optional[int] = None
    
    is_magical: bool = False
    magical_properties: Optional[str] = None
    charges: Optional[int] = Field(default=None, ge=0)
    
    description: str = ""
    quantity: int = Field(default=1, ge=1)
    
    source: Optional[SourceReference] = None
    foundry_item_id: Optional[str] = None
    
    @field_validator("damage")
    @classmethod
    def validate_damage_notation(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        pattern = r"^\d+d\d+([+-]\d+)?$"
        if not re.match(pattern, v):
            raise ValueError(f"Invalid damage notation: {v}")
        return v


# =============================================================================
# SPELL MODELS
# =============================================================================

class KnackAbility(BaseModel):
    """A single ability within a knack, unlocked at a specific character level."""
    level: int = Field(ge=1, le=14, description="Character level when this ability is gained")
    name: str
    description: str


class Spell(BaseModel):
    """
    Spell representation for magic-using characters.
    
    Also supports knacks (racial abilities) and other special magic types.
    For knacks, use magic_type="knack" and populate the abilities list.
    """
    
    spell_id: str = Field(default_factory=lambda: generate_id("spell"))
    name: str
    level: Optional[int] = Field(default=None, ge=0, le=9, description="Spell level (None for knacks)")
    school: str = ""
    magic_type: MagicType
    casting_time: str = "1 round"
    range: Optional[str] = "Self"
    duration: Optional[str] = "Instantaneous"
    description: str
    reversible: bool = False
    components: Optional[str] = None
    
    # For knacks and racial abilities
    kindred: Optional[str] = Field(default=None, description="Race/kindred that has this ability")
    abilities: Optional[list[KnackAbility]] = Field(default=None, description="Tiered abilities for knacks")
    
    source: Optional[SourceReference] = None
    foundry_item_id: Optional[str] = None
    
    @model_validator(mode='after')
    def validate_spell_or_knack(self) -> 'Spell':
        """Validate that spells have levels and knacks have abilities."""
        if self.magic_type == MagicType.KNACK:
            # Knacks should have abilities list
            if not self.abilities:
                # Allow empty abilities for now, but log warning
                pass
        else:
            # Regular spells should have a level
            if self.level is None:
                self.level = 1  # Default to level 1
        return self


# =============================================================================
# CHARACTER MODELS
# =============================================================================

class DolmenwoodCharacter(BaseModel):
    """Complete character representation for Dolmenwood/OSE."""
    
    character_id: str = Field(default_factory=lambda: generate_id("char"))
    name: str
    player_name: str = "Player"
    kindred: Kindred
    character_class: CharacterClass
    level: int = Field(ge=1, le=14, default=1)
    
    strength: AbilityScore
    intelligence: AbilityScore
    wisdom: AbilityScore
    dexterity: AbilityScore
    constitution: AbilityScore
    charisma: AbilityScore
    
    hp_current: int = Field(ge=0)
    hp_max: int = Field(ge=1)
    ac: int = Field(ge=0, default=10)
    xp_current: int = Field(ge=0, default=0)
    xp_next_level: int = Field(ge=0, default=2000)
    
    save_doom: SaveTarget = 14
    save_ray: SaveTarget = 15
    save_hold: SaveTarget = 16
    save_blast: SaveTarget = 17
    save_spell: SaveTarget = 17
    
    skill_listen: SkillValue = 2
    skill_search: SkillValue = 2
    skill_survival: SkillValue = 2
    class_skills: dict[str, int] = Field(default_factory=dict)
    
    attack_bonus: int = Field(default=0)
    damage_bonus: int = Field(default=0)
    
    inventory: list[Item] = Field(default_factory=list)
    equipped_armor: Optional[Item] = None
    equipped_weapon: Optional[Item] = None
    equipped_shield: bool = False
    
    spells_known: list[Spell] = Field(default_factory=list)
    spells_memorized: list[Spell] = Field(default_factory=list)
    spell_slots: dict[int, int] = Field(default_factory=dict)
    
    class_features: list[str] = Field(default_factory=list)
    currency_sp: int = Field(ge=0, default=0)
    conditions: list[str] = Field(default_factory=list)
    notes: str = Field(default="")
    
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    foundry_actor_id: Optional[str] = None
    
    @property
    def str_mod(self) -> int:
        return calculate_ability_modifier(self.strength)
    
    @property
    def int_mod(self) -> int:
        return calculate_ability_modifier(self.intelligence)
    
    @property
    def wis_mod(self) -> int:
        return calculate_ability_modifier(self.wisdom)
    
    @property
    def dex_mod(self) -> int:
        return calculate_ability_modifier(self.dexterity)
    
    @property
    def con_mod(self) -> int:
        return calculate_ability_modifier(self.constitution)
    
    @property
    def cha_mod(self) -> int:
        return calculate_ability_modifier(self.charisma)
    
    @property
    def is_alive(self) -> bool:
        return self.hp_current > 0
    
    @property
    def encumbrance(self) -> float:
        total = sum(item.weight * item.quantity for item in self.inventory)
        if self.equipped_armor:
            total += self.equipped_armor.weight
        if self.equipped_weapon:
            total += self.equipped_weapon.weight
        return total
    
    def take_damage(self, amount: int) -> int:
        actual = min(amount, self.hp_current)
        self.hp_current = max(0, self.hp_current - amount)
        return actual
    
    def heal(self, amount: int) -> int:
        actual = min(amount, self.hp_max - self.hp_current)
        self.hp_current = min(self.hp_max, self.hp_current + amount)
        return actual
    
    def add_xp(self, amount: int) -> bool:
        self.xp_current += amount
        return self.xp_current >= self.xp_next_level


# =============================================================================
# QUEST MODELS
# =============================================================================

class QuestObjective(BaseModel):
    """Individual quest objective."""
    objective_id: str = Field(default_factory=lambda: generate_id("obj"))
    description: str
    completed: bool = False


class Quest(BaseModel):
    """Quest/adventure tracking."""
    quest_id: str = Field(default_factory=lambda: generate_id("quest"))
    title: str
    description: str
    giver_npc: Optional[str] = None
    status: QuestStatus = QuestStatus.ACTIVE
    objectives: list[QuestObjective] = Field(default_factory=list)
    rewards: str = ""
    
    source: Optional[SourceReference] = None
    
    @property
    def progress(self) -> float:
        if not self.objectives:
            return 0.0
        completed = sum(1 for obj in self.objectives if obj.completed)
        return completed / len(self.objectives)


# =============================================================================
# WORLD EVENT MODELS
# =============================================================================

class WorldEvent(BaseModel):
    """Major world event record."""
    event_id: str = Field(default_factory=lambda: generate_id("event"))
    timestamp: datetime = Field(default_factory=datetime.now)
    turn_number: int
    description: str
    affected_locations: list[str] = Field(default_factory=list)
    affected_factions: list[str] = Field(default_factory=list)


# =============================================================================
# WORLD STATE MODELS
# =============================================================================

class WorldState(BaseModel):
    """Complete world/campaign state."""
    campaign_id: str = Field(default_factory=lambda: generate_id("camp"))
    campaign_name: str
    
    current_date: str = "1st of Longgrass, Year 1"
    time_of_day: TimeOfDay = TimeOfDay.MORNING
    turn_count: int = Field(default=0, ge=0)
    
    current_hex: HexId = "0808"
    current_location_name: str = "Dolmenwood"
    current_location_type: LocationType = LocationType.WILDERNESS
    
    weather: Weather = Weather.CLEAR
    season: Season = Season.SPRING
    
    party_characters: list[str] = Field(default_factory=list)
    party_marching_order: list[str] = Field(default_factory=list)
    
    discovered_hexes: set[str] = Field(default_factory=set)
    discovered_locations: list[str] = Field(default_factory=list)
    met_npcs: list[str] = Field(default_factory=list)
    
    active_quests: list[Quest] = Field(default_factory=list)
    completed_quests: list[str] = Field(default_factory=list)
    
    # v1.1: Active adventure tracking
    active_adventure: Optional[str] = Field(
        default=None,
        description="Source ID of currently running adventure module"
    )
    adventure_progress: dict[str, Any] = Field(
        default_factory=dict,
        description="Track progress through adventure"
    )
    
    faction_standings: dict[str, int] = Field(default_factory=dict)
    world_flags: dict[str, bool] = Field(default_factory=dict)
    major_events: list[WorldEvent] = Field(default_factory=list)
    
    foundry_scene_id: Optional[str] = None
    
    @field_validator("faction_standings")
    @classmethod
    def validate_faction_standings(cls, v: dict[str, int]) -> dict[str, int]:
        return {k: max(-10, min(10, val)) for k, val in v.items()}
    
    def advance_time(self, turns: int = 1) -> None:
        self.turn_count += turns
        hour = (self.turn_count // 6) % 24
        
        if 5 <= hour < 7:
            self.time_of_day = TimeOfDay.DAWN
        elif 7 <= hour < 12:
            self.time_of_day = TimeOfDay.MORNING
        elif 12 <= hour < 17:
            self.time_of_day = TimeOfDay.AFTERNOON
        elif 17 <= hour < 19:
            self.time_of_day = TimeOfDay.EVENING
        elif 19 <= hour < 21:
            self.time_of_day = TimeOfDay.DUSK
        else:
            self.time_of_day = TimeOfDay.NIGHT
    
    def modify_faction_standing(self, faction: str, change: int) -> int:
        current = self.faction_standings.get(faction, 0)
        new_standing = max(-10, min(10, current + change))
        self.faction_standings[faction] = new_standing
        return new_standing
    
    def discover_hex(self, hex_id: str) -> bool:
        if hex_id in self.discovered_hexes:
            return False
        self.discovered_hexes.add(hex_id)
        return True


# =============================================================================
# COMBAT MODELS
# =============================================================================

class Enemy(BaseModel):
    """Enemy combatant in combat encounters."""
    
    enemy_id: str = Field(default_factory=lambda: generate_id("enemy"))
    name: str
    monster_type: str
    
    hp_current: int = Field(ge=0)
    hp_max: int = Field(ge=1)
    ac: int = Field(ge=0)
    
    attack_bonus: int = 0
    damage: str = "1d6"
    num_attacks: int = Field(default=1, ge=1)
    special_attacks: list[str] = Field(default_factory=list)
    
    morale_score: MoraleScore = 7
    morale_checked: bool = False
    morale_broken: bool = False
    
    conditions: list[str] = Field(default_factory=list)
    initiative_modifier: int = 0
    
    foundry_token_id: Optional[str] = None
    
    @property
    def is_alive(self) -> bool:
        return self.hp_current > 0 and not self.morale_broken
    
    def take_damage(self, amount: int) -> int:
        actual = min(amount, self.hp_current)
        self.hp_current = max(0, self.hp_current - amount)
        return actual


class CombatState(BaseModel):
    """Active combat encounter state."""
    
    combat_id: str = Field(default_factory=lambda: generate_id("combat"))
    campaign_id: str = ""
    is_active: bool = False
    round_number: int = Field(default=0, ge=0)
    
    party_initiative: Optional[int] = None
    enemy_initiative: Optional[int] = None
    current_turn: Literal["party", "enemy", "none"] = "none"
    
    party_combatants: list[str] = Field(default_factory=list)
    enemies: list[Enemy] = Field(default_factory=list)
    
    combat_log: list[str] = Field(default_factory=list)
    
    surprised: Optional[Literal["party", "enemy"]] = None
    morale_broken: set[str] = Field(default_factory=set)
    
    environment: str = "Standard terrain"
    special_conditions: list[str] = Field(default_factory=list)
    
    def add_log_entry(self, entry: str) -> None:
        timestamp = f"[R{self.round_number}]"
        self.combat_log.append(f"{timestamp} {entry}")
    
    def get_active_enemies(self) -> list[Enemy]:
        return [e for e in self.enemies if e.is_alive]
    
    def check_combat_end(self) -> Optional[str]:
        active_enemies = self.get_active_enemies()
        if not active_enemies:
            return "party_victory"
        if not self.party_combatants:
            return "enemy_victory"
        return None
    
    def next_round(self) -> None:
        self.round_number += 1
        self.party_initiative = None
        self.enemy_initiative = None


# =============================================================================
# LOCATION MODELS
# =============================================================================

class Building(BaseModel):
    """Building in a settlement."""
    building_id: str = Field(default_factory=lambda: generate_id("bldg"))
    name: str
    type: str
    description: str
    proprietor_npc: Optional[str] = None
    
    source: Optional[SourceReference] = None


class Settlement(BaseModel):
    """Town/village data."""
    
    settlement_id: str = Field(default_factory=lambda: generate_id("settle"))
    name: str
    hex_id: HexId
    size: SettlementSize
    population: int = Field(ge=0)
    
    buildings: list[Building] = Field(default_factory=list)
    npcs: list[str] = Field(default_factory=list)
    
    has_inn: bool = False
    has_temple: bool = False
    has_market: bool = False
    has_blacksmith: bool = False
    
    ruling_faction: Optional[str] = None
    
    description: str = ""
    rumors: list[str] = Field(default_factory=list)
    
    source: Optional[SourceReference] = None
    foundry_scene_id: Optional[str] = None


class HexLocation(BaseModel):
    """Hex location from Dolmenwood campaign book."""
    
    hex_id: HexId
    coordinates: tuple[int, int]
    
    terrain_type: TerrainType
    terrain_description: str = ""
    
    location_name: Optional[str] = None
    location_type: Optional[str] = None
    description: str
    
    encounter_table: Optional[str] = None
    special_encounters: list[str] = Field(default_factory=list)
    
    npcs: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)
    
    secrets: list[str] = Field(default_factory=list)
    dm_notes: str = ""
    
    adjacent_hexes: list[str] = Field(default_factory=list)
    
    discovered: bool = False
    visited_count: int = Field(default=0, ge=0)
    
    source: Optional[SourceReference] = None
    foundry_scene_id: Optional[str] = None
    foundry_journal_id: Optional[str] = None
    
    def visit(self) -> bool:
        first_visit = not self.discovered
        self.discovered = True
        self.visited_count += 1
        return first_visit


# =============================================================================
# NPC MODELS
# =============================================================================

class NPC(BaseModel):
    """Non-player character."""
    
    npc_id: str = Field(default_factory=lambda: generate_id("npc"))
    name: str
    kindred: str = "Human"
    occupation: str = ""
    
    personality_traits: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    
    is_combatant: bool = False
    character_class: Optional[str] = None
    level: Optional[int] = None
    hp: Optional[int] = None
    ac: Optional[int] = None
    
    current_location: str = ""
    
    faction: Optional[str] = None
    relationship_party: RelationshipLevel = RelationshipLevel.NEUTRAL
    
    initial_dialogue: str = ""
    dialogue_topics: dict[str, str] = Field(default_factory=dict)
    
    description: str = ""
    offers_quests: list[str] = Field(default_factory=list)
    inventory: list[Item] = Field(default_factory=list)
    
    source: Optional[SourceReference] = None
    foundry_actor_id: Optional[str] = None
    
    def improve_relationship(self) -> RelationshipLevel:
        levels = list(RelationshipLevel)
        current_idx = levels.index(self.relationship_party)
        if current_idx < len(levels) - 1:
            self.relationship_party = levels[current_idx + 1]
        return self.relationship_party
    
    def worsen_relationship(self) -> RelationshipLevel:
        levels = list(RelationshipLevel)
        current_idx = levels.index(self.relationship_party)
        if current_idx > 0:
            self.relationship_party = levels[current_idx - 1]
        return self.relationship_party


# =============================================================================
# RULES AND MONSTER MODELS
# =============================================================================

class GameRule(BaseModel):
    """
    Game rule or rule section for vector search.

    Can represent either a discrete rule or a full-context section/page
    that preserves the original presentation and all explanatory text.
    """

    rule_id: str = Field(default_factory=lambda: generate_id("rule"))
    category: str = Field(description="Major category: combat, exploration, magic, character, equipment, monsters, setting, procedures")
    subcategory: Optional[str] = Field(default=None, description="Subcategory for finer organization")
    title: str = Field(description="Section title or rule name")
    content: str = Field(description="Full rule text with all context, examples, and explanatory content preserved")

    # Section organization
    section_type: Optional[str] = Field(
        default=None,
        description="Type of content: 'full_page', 'major_section', 'subsection', 'discrete_rule', 'table', 'procedure'"
    )

    # v1.1: Source attribution
    source: Optional[SourceReference] = None
    content_type: ContentType = Field(default=ContentType.CORE_RULE)

    # v1.1: Versioning
    version: str = Field(default="1.0")
    supersedes: Optional[str] = Field(default=None)

    page_reference: Optional[str] = None
    examples: list[str] = Field(default_factory=list, description="Extracted examples (optional if already in content)")
    related_rules: list[str] = Field(default_factory=list, description="IDs of related rules/sections")
    source_book: str = "Dolmenwood"

    # v1.1: Metadata
    tags: list[str] = Field(default_factory=list, description="Keywords for searchability")
    created_at: datetime = Field(default_factory=datetime.now)


class MonsterStatBlock(BaseModel):
    """Monster statistics from the monster book."""

    monster_id: str = Field(default_factory=lambda: generate_id("mon"))
    name: str

    # Core stats
    armor_class: int
    hit_dice: str
    hp: Optional[int] = Field(default=None, ge=0)
    level: Optional[int] = Field(default=None, ge=0, description="Monster level (HD equivalent)")
    movement: str
    speed: Optional[int] = Field(default=None, description="Base speed in feet")
    burrow_speed: Optional[int] = Field(default=None, description="Burrow speed in feet")
    fly_speed: Optional[int] = Field(default=None, description="Fly speed in feet")
    swim_speed: Optional[int] = Field(default=None, description="Swim speed in feet")

    # Combat
    attacks: list[str] = Field(default_factory=list)
    damage: list[str] = Field(default_factory=list)

    # Saving throws - individual values (Dolmenwood/OSE format)
    save_doom: Optional[SaveTarget] = Field(default=None, description="Save vs Doom")
    save_ray: Optional[SaveTarget] = Field(default=None, description="Save vs Ray")
    save_hold: Optional[SaveTarget] = Field(default=None, description="Save vs Hold")
    save_blast: Optional[SaveTarget] = Field(default=None, description="Save vs Blast")
    save_spell: Optional[SaveTarget] = Field(default=None, description="Save vs Spell")
    saves_as: Optional[str] = Field(default=None, description="Legacy save format (e.g., 'F2')")

    morale: MoraleScore

    # Treasure
    treasure_type: Optional[str] = None
    hoard: Optional[str] = Field(default=None, description="Hoard composition (e.g., 'C6 + R7 + M4')")
    possessions: Optional[str] = Field(default=None, description="Individual possessions")

    # Monster classification
    size: Optional[str] = Field(default=None, description="Size category (Small, Medium, Large, etc.)")
    monster_type: Optional[str] = Field(default=None, description="Type (Dragon, Undead, Beast, etc.)")
    sentience: Optional[str] = Field(default=None, description="Sentient, Semi-Sentient, Non-Sentient")
    alignment: Optional[str] = None
    intelligence: Optional[str] = None

    # Abilities and features
    special_abilities: list[str] = Field(default_factory=list)
    immunities: list[str] = Field(default_factory=list, description="Damage immunities")
    resistances: list[str] = Field(default_factory=list, description="Damage resistances")
    vulnerabilities: list[str] = Field(default_factory=list, description="Damage vulnerabilities")

    # Roleplaying information
    description: str
    behavior: Optional[str] = Field(default=None, description="Typical behavior traits")
    speech: Optional[str] = Field(default=None, description="Speech patterns and languages")
    traits: list[str] = Field(default_factory=list, description="Physical/descriptive traits")

    # Encounter information
    number_appearing: str
    lair_percentage: Optional[int] = Field(default=None, ge=0, le=100, description="% appearing in lair")
    encounter_scenarios: list[str] = Field(default_factory=list, description="Sample encounter descriptions")
    lair_descriptions: list[str] = Field(default_factory=list, description="Sample lair descriptions")

    xp_value: int = Field(default=0, ge=0)
    habitat: list[str] = Field(default_factory=list)

    # v1.1: Source tracking
    source: Optional[SourceReference] = None

    # v1.1: Variant tracking
    is_variant: bool = False
    base_monster_id: Optional[str] = None

    foundry_actor_id: Optional[str] = None

    def roll_hp(self) -> int:
        match = re.match(r"(\d+)([+-]\d+)?", self.hit_dice)
        if not match:
            return 4

        num_dice = int(match.group(1))
        modifier = int(match.group(2) or 0)

        total = sum(random.randint(1, 8) for _ in range(num_dice))
        total += modifier

        return max(1, total)


# =============================================================================
# NEW v1.1: ADVENTURE CONTENT MODELS
# =============================================================================

class AdventureLocation(BaseModel):
    """A location within an adventure module."""
    
    location_id: str = Field(default_factory=lambda: generate_id("advloc"))
    adventure_id: str
    
    name: str
    short_name: str
    number: Optional[str] = None
    
    read_aloud_text: Optional[str] = None
    dm_notes: str = ""
    
    dimensions: Optional[str] = None
    lighting: Optional[str] = None
    features: list[str] = Field(default_factory=list)
    
    creatures: list[str] = Field(default_factory=list)
    npcs: list[str] = Field(default_factory=list)
    treasure: list[str] = Field(default_factory=list)
    traps: list[str] = Field(default_factory=list)
    
    exits: dict[str, str] = Field(default_factory=dict)
    
    visited: bool = False
    looted: bool = False
    creatures_defeated: bool = False
    
    source: Optional[SourceReference] = None


class AdventureModule(BaseModel):
    """Complete adventure module metadata."""
    
    adventure_id: str = Field(default_factory=lambda: generate_id("adv"))
    title: str
    subtitle: Optional[str] = None
    
    recommended_levels: str = "1-3"
    estimated_sessions: Optional[int] = None
    adventure_type: AdventureType = AdventureType.DUNGEON_CRAWL
    
    locations: list[str] = Field(default_factory=list)
    starting_location: Optional[str] = None
    
    hook: str = ""
    synopsis: str = ""
    conclusion: str = ""
    
    total_xp: Optional[int] = None
    major_treasure: list[str] = Field(default_factory=list)
    
    source: Optional[ContentSource] = None
    recommended_hex: Optional[str] = None


# =============================================================================
# SESSION MANAGEMENT MODELS
# =============================================================================

class HistoryEntry(BaseModel):
    """Entry in the game history log."""
    entry_id: str = Field(default_factory=lambda: generate_id("hist"))
    campaign_id: str
    turn_number: int
    timestamp: datetime = Field(default_factory=datetime.now)
    event_type: str
    player_input: Optional[str] = None
    dm_response: Optional[str] = None
    state_changes: dict[str, Any] = Field(default_factory=dict)
    dice_rolls: list[str] = Field(default_factory=list)


class SessionSave(BaseModel):
    """Complete session save state."""
    save_id: str = Field(default_factory=lambda: generate_id("save"))
    campaign_id: str
    save_name: str
    description: str = ""
    world_state: dict[str, Any] = Field(default_factory=dict)
    characters: list[dict[str, Any]] = Field(default_factory=list)
    combat_state: Optional[dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.now)
