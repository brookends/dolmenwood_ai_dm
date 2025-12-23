"""
Dolmenwood AI DM - Hex Crawl Engine (v2.0)

This module provides automated hex crawl management that tracks:
- Current position and movement
- Time (watches and days)
- Random encounters
- Resources (rations, light, etc.)
- Weather and environmental conditions
- Discovered locations

The engine handles all mechanical bookkeeping so Claude can focus
on narration and player interaction.

v2.0 Changes:
- Integration with StateMachine for state transitions
- Integration with GlobalController for time/resources
- Integration with TriggerHandler for procedure triggers
- Formal watch-based exploration loop
- Dolmenwood-specific regions and encounter tables
- Proper encounter handling with state transitions

Author: AI Dungeon Master Project
Version: 2.0
"""

from __future__ import annotations

import random
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Dict, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ..game_state.state_machine import StateMachine
    from ..game_state.global_controller import GlobalController
    from ..resolution.procedure_triggers import TriggerHandler

logger = logging.getLogger(__name__)


# =============================================================================
# DOLMENWOOD REGIONS
# =============================================================================

class DolmenwoodRegion(str, Enum):
    """Dolmenwood forest regions with distinct character."""
    HIGH_WOLD = "high_wold"           # Northern highlands
    ALDWEALD = "aldweald"             # Ancient central woods
    MULCHGROVE = "mulchgrove"         # Southeastern swamps
    NAGWOOD = "nagwood"               # Dark northeastern forest
    HAGS_ADDLE = "hags_addle"         # Cursed southern region
    LAKE_LONGMERE = "lake_longmere"   # Central lake
    TITHELANDS = "tithelands"         # Settled western farmlands
    DWELMFURGH = "dwelmfurgh"         # Northern mountain foothills


# =============================================================================
# ENUMS
# =============================================================================

class Terrain(str, Enum):
    """Terrain types affecting movement and encounters."""
    CLEAR = "clear"
    FOREST = "forest"
    DENSE_FOREST = "dense_forest"
    HILLS = "hills"
    MOUNTAINS = "mountains"
    SWAMP = "swamp"
    RIVER = "river"
    LAKE = "lake"
    SETTLEMENT = "settlement"
    RUINS = "ruins"
    ROAD = "road"


class Weather(str, Enum):
    """Weather conditions."""
    CLEAR = "clear"
    CLOUDY = "cloudy"
    OVERCAST = "overcast"
    LIGHT_RAIN = "light_rain"
    HEAVY_RAIN = "heavy_rain"
    FOG = "fog"
    STORM = "storm"
    SNOW = "snow"
    BLIZZARD = "blizzard"


class TimeOfDay(str, Enum):
    """Time periods."""
    DAWN = "dawn"          # Watch 1 (6am-10am)
    MORNING = "morning"    # Watch 2 (10am-2pm)
    AFTERNOON = "afternoon"  # Watch 3 (2pm-6pm)
    EVENING = "evening"    # Watch 4 (6pm-10pm)
    NIGHT = "night"        # Watch 5 (10pm-2am)
    LATE_NIGHT = "late_night"  # Watch 6 (2am-6am)


class WatchActivity(str, Enum):
    """Activities that can be done during a watch."""
    TRAVEL = "travel"
    REST = "rest"
    CAMP = "camp"
    FORAGE = "forage"
    EXPLORE = "explore"
    SEARCH = "search"
    HIDE = "hide"
    FORCED_MARCH = "forced_march"


class ResourceType(str, Enum):
    """Consumable resources."""
    RATIONS = "rations"
    WATER = "water"
    TORCHES = "torches"
    LANTERN_OIL = "lantern_oil"
    ARROWS = "arrows"
    BOLTS = "bolts"


class Season(str, Enum):
    """Seasons affecting weather and daylight."""
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class HexInfo:
    """Information about a hex."""
    hex_id: str
    terrain: Terrain = Terrain.FOREST
    name: Optional[str] = None
    description: Optional[str] = None
    settlement: Optional[str] = None
    points_of_interest: list[str] = field(default_factory=list)
    encounter_chance: int = 1  # X-in-6
    is_discovered: bool = False
    is_explored: bool = False  # Fully explored
    notes: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "hex_id": self.hex_id,
            "terrain": self.terrain.value,
            "name": self.name,
            "description": self.description,
            "settlement": self.settlement,
            "points_of_interest": self.points_of_interest,
            "encounter_chance": self.encounter_chance,
            "is_discovered": self.is_discovered,
            "is_explored": self.is_explored,
        }


@dataclass
class TravelResult:
    """Result of traveling to a new hex."""
    success: bool
    origin_hex: str
    destination_hex: str
    watches_spent: int
    new_day: bool = False
    day_number: int = 1
    current_watch: int = 1
    time_of_day: TimeOfDay = TimeOfDay.MORNING
    encounter_occurred: bool = False
    encounter_roll: Optional[int] = None
    got_lost: bool = False
    actual_destination: Optional[str] = None  # If got lost
    terrain_crossed: Terrain = Terrain.FOREST
    weather: Weather = Weather.CLEAR
    resources_consumed: dict[str, int] = field(default_factory=dict)
    exhaustion_check: bool = False  # For forced march
    exhaustion_failed: bool = False
    new_hex_discovered: bool = False
    
    @property
    def brief(self) -> str:
        """One-sentence summary for Claude to narrate."""
        parts = []
        
        if self.got_lost:
            parts.append(f"The party becomes lost in the {self.terrain_crossed.value} and ends up in hex {self.actual_destination}!")
        else:
            parts.append(f"The party travels through {self.terrain_crossed.value} terrain to hex {self.destination_hex}.")
        
        parts.append(f"({self.watches_spent} watch{'es' if self.watches_spent > 1 else ''}, now {self.time_of_day.value})")
        
        if self.new_hex_discovered:
            parts.append("This is unexplored territory!")
        
        if self.encounter_occurred:
            parts.append("⚠️ ENCOUNTER!")
        
        if self.exhaustion_failed:
            parts.append("The forced march has exhausted the party!")
        
        return " ".join(parts)


@dataclass
class ExplorationResult:
    """Result of exploring a hex."""
    hex_id: str
    activity: WatchActivity
    watches_spent: int
    discoveries: list[str] = field(default_factory=list)
    encounter_occurred: bool = False
    encounter_roll: Optional[int] = None
    foraging_success: bool = False
    foraging_amount: int = 0
    resources_consumed: dict[str, int] = field(default_factory=dict)
    weather: Weather = Weather.CLEAR
    
    @property
    def brief(self) -> str:
        """One-sentence summary."""
        parts = []
        
        if self.activity == WatchActivity.FORAGE:
            if self.foraging_success:
                parts.append(f"Foraging successful! Found {self.foraging_amount} rations worth of food.")
            else:
                parts.append("Foraging unsuccessful. No food found.")
        elif self.activity == WatchActivity.EXPLORE:
            if self.discoveries:
                parts.append(f"Exploration reveals: {', '.join(self.discoveries)}")
            else:
                parts.append("Exploration reveals nothing of note.")
        elif self.activity == WatchActivity.REST:
            parts.append("The party rests and recovers.")
        elif self.activity == WatchActivity.CAMP:
            parts.append("The party makes camp for the night.")
        
        if self.encounter_occurred:
            parts.append("⚠️ ENCOUNTER!")
        
        return " ".join(parts) if parts else "Activity completed."


@dataclass 
class ResourceStatus:
    """Current resource levels."""
    rations: int = 0
    water: int = 0
    torches: int = 0
    lantern_oil: int = 0  # Hours of light
    arrows: int = 0
    bolts: int = 0
    
    def to_dict(self) -> dict[str, int]:
        return {
            "rations": self.rations,
            "water": self.water,
            "torches": self.torches,
            "lantern_oil": self.lantern_oil,
            "arrows": self.arrows,
            "bolts": self.bolts,
        }
    
    def get(self, resource: ResourceType) -> int:
        """Get amount of a resource."""
        return getattr(self, resource.value, 0)
    
    def consume(self, resource: ResourceType, amount: int = 1) -> int:
        """Consume resource, return actual amount consumed."""
        current = self.get(resource)
        consumed = min(current, amount)
        setattr(self, resource.value, current - consumed)
        return consumed
    
    def add(self, resource: ResourceType, amount: int) -> None:
        """Add to a resource."""
        current = self.get(resource)
        setattr(self, resource.value, current + amount)


@dataclass
class HexCrawlStatus:
    """Current state of the hex crawl for Claude."""
    current_hex: str
    current_terrain: Terrain
    day_number: int
    watch_number: int
    time_of_day: TimeOfDay
    weather: Weather
    season: Season
    resources: dict[str, int]
    party_size: int
    discovered_hexes: int
    current_hex_explored: bool
    settlement_nearby: Optional[str]
    region: Optional[DolmenwoodRegion] = None
    fairy_influence: int = 0

    @property
    def brief(self) -> str:
        """Concise status."""
        return (
            f"Hex {self.current_hex} ({self.current_terrain.value}) | "
            f"Day {self.day_number}, {self.time_of_day.value} | "
            f"Weather: {self.weather.value} | "
            f"Rations: {self.resources.get('rations', 0)}"
        )

    @property
    def full_status(self) -> str:
        """Detailed status."""
        lines = [
            f"=== HEX CRAWL STATUS ===",
            f"Location: Hex {self.current_hex} ({self.current_terrain.value})",
            f"Time: Day {self.day_number}, Watch {self.watch_number} ({self.time_of_day.value})",
            f"Season: {self.season.value.capitalize()}",
            f"Weather: {self.weather.value.replace('_', ' ').capitalize()}",
            f"",
            f"Resources:",
            f"  Rations: {self.resources.get('rations', 0)}",
            f"  Water: {self.resources.get('water', 0)}",
            f"  Torches: {self.resources.get('torches', 0)}",
            f"  Lantern Oil: {self.resources.get('lantern_oil', 0)} hours",
            f"",
            f"Party Size: {self.party_size}",
            f"Hexes Discovered: {self.discovered_hexes}",
        ]

        if self.settlement_nearby:
            lines.append(f"Nearby Settlement: {self.settlement_nearby}")

        if self.region:
            lines.append(f"Region: {self.region.value.replace('_', ' ').title()}")

        if self.fairy_influence > 0:
            lines.append(f"Fairy Influence: {'🧚' * min(5, self.fairy_influence)}")

        return "\n".join(lines)


class WildernessPhase(str, Enum):
    """Phases of the wilderness exploration loop."""
    WATCH_START = "watch_start"
    CHOOSE_ACTIVITY = "choose_activity"
    EXECUTE_ACTIVITY = "execute_activity"
    ENCOUNTER_CHECK = "encounter_check"
    ENCOUNTER_ACTIVE = "encounter_active"
    RESOURCE_CHECK = "resource_check"
    WATCH_END = "watch_end"


@dataclass
class WatchResult:
    """Result of a single watch of wilderness exploration."""
    watch_number: int
    day_number: int
    phase: WildernessPhase
    activity: WatchActivity
    hex_id: str
    terrain: Terrain
    weather: Weather
    time_of_day: TimeOfDay

    # Activity results
    activity_success: bool = True
    movement_result: Optional[TravelResult] = None
    exploration_result: Optional[ExplorationResult] = None

    # Encounter
    encounter_check_roll: Optional[int] = None
    encounter_chance: int = 0
    encounter_triggered: bool = False
    encounter_type: Optional[str] = None
    encounter_distance: Optional[int] = None  # In tens of yards
    encounter_surprised: bool = False
    party_surprised: bool = False

    # Resources
    resources_consumed: Dict[str, int] = field(default_factory=dict)
    resource_warnings: List[str] = field(default_factory=list)

    # State transitions
    state_transition: Optional[str] = None
    requires_combat: bool = False

    # Events and notes
    events: List[str] = field(default_factory=list)
    fairy_signs: List[str] = field(default_factory=list)

    @property
    def brief(self) -> str:
        """One-sentence summary."""
        parts = [f"Watch {self.watch_number} ({self.time_of_day.value}):"]

        if self.activity == WatchActivity.TRAVEL and self.movement_result:
            if self.movement_result.got_lost:
                parts.append(f"Lost! Ended up in {self.movement_result.actual_destination}")
            else:
                parts.append(f"Traveled to {self.movement_result.destination_hex}")
        elif self.activity == WatchActivity.FORAGE and self.exploration_result:
            if self.exploration_result.foraging_success:
                parts.append(f"Foraged {self.exploration_result.foraging_amount} rations")
            else:
                parts.append("Foraging failed")
        elif self.activity == WatchActivity.EXPLORE:
            parts.append("Explored the hex")
        elif self.activity == WatchActivity.REST:
            parts.append("Rested")
        elif self.activity == WatchActivity.CAMP:
            parts.append("Made camp")

        if self.encounter_triggered:
            parts.append("⚠️ ENCOUNTER!")

        return " ".join(parts)


@dataclass
class WildernessDayResult:
    """Complete result of a wilderness day."""
    day_number: int
    watches: List[WatchResult] = field(default_factory=list)
    starting_hex: str = ""
    ending_hex: str = ""
    weather: Weather = Weather.CLEAR
    encounters_occurred: int = 0
    total_resources_consumed: Dict[str, int] = field(default_factory=dict)
    hexes_traveled: List[str] = field(default_factory=list)
    discoveries: List[str] = field(default_factory=list)


# =============================================================================
# TERRAIN CONFIGURATION
# =============================================================================

# Movement cost in watches per hex
TERRAIN_MOVEMENT_COST = {
    Terrain.CLEAR: 1,
    Terrain.ROAD: 1,  # Faster on roads
    Terrain.FOREST: 2,
    Terrain.DENSE_FOREST: 3,
    Terrain.HILLS: 2,
    Terrain.MOUNTAINS: 3,
    Terrain.SWAMP: 3,
    Terrain.RIVER: 2,  # If crossing
    Terrain.LAKE: 4,  # Must go around or boat
    Terrain.SETTLEMENT: 1,
    Terrain.RUINS: 1,
}

# Road reduces cost by 1 (minimum 1)
ROAD_BONUS = 1

# Encounter chance (X in 6) by terrain
TERRAIN_ENCOUNTER_CHANCE = {
    Terrain.CLEAR: 1,
    Terrain.ROAD: 1,
    Terrain.FOREST: 2,
    Terrain.DENSE_FOREST: 3,
    Terrain.HILLS: 2,
    Terrain.MOUNTAINS: 2,
    Terrain.SWAMP: 3,
    Terrain.RIVER: 1,
    Terrain.LAKE: 1,
    Terrain.SETTLEMENT: 1,
    Terrain.RUINS: 3,
}

# Getting lost chance (X in 6) by terrain
TERRAIN_LOST_CHANCE = {
    Terrain.CLEAR: 1,
    Terrain.ROAD: 0,  # Can't get lost on road
    Terrain.FOREST: 2,
    Terrain.DENSE_FOREST: 3,
    Terrain.HILLS: 2,
    Terrain.MOUNTAINS: 2,
    Terrain.SWAMP: 3,
    Terrain.RIVER: 1,
    Terrain.LAKE: 1,
    Terrain.SETTLEMENT: 0,
    Terrain.RUINS: 1,
}

# Foraging modifier by terrain
TERRAIN_FORAGE_MODIFIER = {
    Terrain.CLEAR: 0,
    Terrain.ROAD: -1,
    Terrain.FOREST: +2,
    Terrain.DENSE_FOREST: +1,
    Terrain.HILLS: 0,
    Terrain.MOUNTAINS: -2,
    Terrain.SWAMP: +1,
    Terrain.RIVER: +1,
    Terrain.LAKE: +1,
    Terrain.SETTLEMENT: -2,
    Terrain.RUINS: -2,
}


# =============================================================================
# HEX UTILITIES
# =============================================================================

def parse_hex_id(hex_id: str) -> tuple[int, int]:
    """Parse hex ID (e.g., '0808') into column, row."""
    hex_id = hex_id.strip()
    if len(hex_id) != 4:
        raise ValueError(f"Invalid hex ID format: {hex_id}")
    
    try:
        col = int(hex_id[:2])
        row = int(hex_id[2:])
        return col, row
    except ValueError:
        raise ValueError(f"Invalid hex ID: {hex_id}")


def make_hex_id(col: int, row: int) -> str:
    """Create hex ID from column and row."""
    return f"{col:02d}{row:02d}"


def get_adjacent_hexes(hex_id: str) -> list[str]:
    """
    Get all adjacent hex IDs.
    
    Uses offset coordinates where odd columns are shifted down.
    """
    col, row = parse_hex_id(hex_id)
    
    # Offset coordinates - odd columns are shifted
    if col % 2 == 0:  # Even column
        adjacents = [
            (col - 1, row - 1),  # NW
            (col, row - 1),      # N
            (col + 1, row - 1),  # NE
            (col + 1, row),      # SE
            (col, row + 1),      # S
            (col - 1, row),      # SW
        ]
    else:  # Odd column
        adjacents = [
            (col - 1, row),      # NW
            (col, row - 1),      # N
            (col + 1, row),      # NE
            (col + 1, row + 1),  # SE
            (col, row + 1),      # S
            (col - 1, row + 1),  # SW
        ]
    
    # Filter valid hexes (positive coordinates, reasonable bounds)
    valid = []
    for c, r in adjacents:
        if 0 <= c <= 99 and 0 <= r <= 99:
            valid.append(make_hex_id(c, r))
    
    return valid


def hex_distance(hex1: str, hex2: str) -> int:
    """Calculate distance between two hexes in hex units."""
    c1, r1 = parse_hex_id(hex1)
    c2, r2 = parse_hex_id(hex2)
    
    # Convert to cube coordinates for easier distance calculation
    def offset_to_cube(col, row):
        x = col
        z = row - (col - (col & 1)) // 2
        y = -x - z
        return x, y, z
    
    x1, y1, z1 = offset_to_cube(c1, r1)
    x2, y2, z2 = offset_to_cube(c2, r2)
    
    return (abs(x1 - x2) + abs(y1 - y2) + abs(z1 - z2)) // 2


def get_random_adjacent_hex(hex_id: str) -> str:
    """Get a random adjacent hex (for getting lost)."""
    adjacents = get_adjacent_hexes(hex_id)
    return random.choice(adjacents) if adjacents else hex_id


# =============================================================================
# TIME UTILITIES
# =============================================================================

WATCH_TO_TIME = {
    1: TimeOfDay.DAWN,
    2: TimeOfDay.MORNING,
    3: TimeOfDay.AFTERNOON,
    4: TimeOfDay.EVENING,
    5: TimeOfDay.NIGHT,
    6: TimeOfDay.LATE_NIGHT,
}

def is_daylight(watch: int, season: Season = Season.SUMMER) -> bool:
    """Check if it's daylight during this watch."""
    # Summer has longer days
    if season == Season.SUMMER:
        return watch in (1, 2, 3, 4)
    elif season == Season.WINTER:
        return watch in (2, 3)
    else:
        return watch in (1, 2, 3, 4)


# =============================================================================
# WEATHER GENERATION
# =============================================================================

WEATHER_TABLE = {
    Season.SPRING: [
        (1, 3, Weather.CLEAR),
        (4, 5, Weather.CLOUDY),
        (6, 7, Weather.OVERCAST),
        (8, 9, Weather.LIGHT_RAIN),
        (10, 11, Weather.HEAVY_RAIN),
        (12, 14, Weather.FOG),
        (15, 17, Weather.STORM),
        (18, 20, Weather.CLEAR),
    ],
    Season.SUMMER: [
        (1, 6, Weather.CLEAR),
        (7, 10, Weather.CLOUDY),
        (11, 13, Weather.OVERCAST),
        (14, 16, Weather.LIGHT_RAIN),
        (17, 18, Weather.STORM),
        (19, 20, Weather.CLEAR),
    ],
    Season.AUTUMN: [
        (1, 3, Weather.CLEAR),
        (4, 6, Weather.CLOUDY),
        (7, 10, Weather.OVERCAST),
        (11, 13, Weather.LIGHT_RAIN),
        (14, 16, Weather.HEAVY_RAIN),
        (17, 18, Weather.FOG),
        (19, 20, Weather.STORM),
    ],
    Season.WINTER: [
        (1, 2, Weather.CLEAR),
        (3, 5, Weather.CLOUDY),
        (6, 9, Weather.OVERCAST),
        (10, 12, Weather.SNOW),
        (13, 15, Weather.HEAVY_RAIN),
        (16, 17, Weather.BLIZZARD),
        (18, 20, Weather.FOG),
    ],
}


def roll_weather(season: Season = Season.AUTUMN) -> Weather:
    """Roll for weather based on season."""
    roll = random.randint(1, 20)
    
    for low, high, weather in WEATHER_TABLE.get(season, WEATHER_TABLE[Season.AUTUMN]):
        if low <= roll <= high:
            return weather
    
    return Weather.CLEAR


# =============================================================================
# HEX CRAWL ENGINE
# =============================================================================

class HexCrawlEngine:
    """
    Automated hex crawl state machine (v2.0).

    Handles movement, time, encounters, resources, and exploration.
    Provides clear status summaries for the AI DM.

    v2.0 Integration Points:
    - StateMachine: Operates in WILDERNESS_TRAVEL and WILDERNESS_ENCOUNTER states
    - GlobalController: Time tracking, resource management, party state
    - TriggerHandler: Fires TRAVEL_SEGMENT triggers each watch
    - DolmenwoodTables: Uses Dolmenwood-specific encounter tables

    Example:
        >>> engine = HexCrawlEngine()
        >>> engine.set_party_size(4)
        >>> engine.set_starting_position("0808", Terrain.SETTLEMENT)
        >>> result = engine.execute_watch(WatchActivity.TRAVEL, destination="0809")
        >>> print(result.brief)
    """

    # Encounter distance by terrain (in tens of yards)
    ENCOUNTER_DISTANCE = {
        Terrain.CLEAR: (4, 24),      # 4d6 x 10 yards
        Terrain.ROAD: (4, 24),
        Terrain.FOREST: (2, 12),     # 2d6 x 10 yards
        Terrain.DENSE_FOREST: (1, 6),  # 1d6 x 10 yards
        Terrain.HILLS: (3, 18),
        Terrain.MOUNTAINS: (3, 18),
        Terrain.SWAMP: (2, 12),
        Terrain.RIVER: (3, 18),
        Terrain.LAKE: (4, 24),
        Terrain.SETTLEMENT: (2, 12),
        Terrain.RUINS: (1, 6),
    }

    # Region mapping for Dolmenwood hexes
    REGION_MAP = {
        # High Wold (northern highlands) - rows 01-04
        # Aldweald (central) - rows 05-08
        # Nagwood (northeast) - cols 11+, rows 03-07
        # Mulchgrove (southeast) - cols 09+, rows 08-11
        # Hag's Addle (south) - rows 10-12
        # Tithelands (west) - cols 01-04
        # Lake Longmere - specific hexes around 0707
    }

    def __init__(
        self,
        state_machine: Optional["StateMachine"] = None,
        global_controller: Optional["GlobalController"] = None,
        trigger_handler: Optional["TriggerHandler"] = None,
    ):
        """
        Initialize the hex crawl engine.

        Args:
            state_machine: Reference to StateMachine for state transitions
            global_controller: Reference to GlobalController for time/resources
            trigger_handler: Reference to TriggerHandler for procedure triggers
        """
        # v2.0 Integration references
        self.state_machine = state_machine
        self.global_controller = global_controller
        self.trigger_handler = trigger_handler

        # Current position
        self.current_hex: str = "0808"
        self.current_terrain: Terrain = Terrain.SETTLEMENT
        self.current_region: Optional[DolmenwoodRegion] = None

        # Time tracking (legacy - prefer global_controller)
        self.day_number: int = 1
        self.watch_number: int = 2  # Start at morning
        self.season: Season = Season.AUTUMN

        # Weather
        self.current_weather: Weather = Weather.CLEAR

        # Party info
        self.party_size: int = 4
        self.base_movement: int = 3  # Hexes per day in clear terrain

        # Resources
        self.resources: ResourceStatus = ResourceStatus()

        # Discovered hexes
        self.discovered_hexes: dict[str, HexInfo] = {}

        # Current hex info
        self._mark_hex_discovered(self.current_hex, self.current_terrain)

        # Wilderness exploration state
        self.current_phase: WildernessPhase = WildernessPhase.WATCH_START
        self.current_day_result: Optional[WildernessDayResult] = None
        self.active_encounter: Optional[Dict[str, Any]] = None

        # Fairy influence tracking (Dolmenwood specific)
        self.fairy_influence_level: int = 0
        self.last_fairy_sign_day: int = 0

        # Log
        self.travel_log: list[str] = []

        logger.info("HexCrawlEngine v2.0 initialized")
    
    # =========================================================================
    # SETUP
    # =========================================================================
    
    def set_starting_position(
        self, 
        hex_id: str, 
        terrain: Terrain = Terrain.SETTLEMENT,
        hex_name: Optional[str] = None
    ) -> None:
        """Set the starting hex."""
        self.current_hex = hex_id
        self.current_terrain = terrain
        self._mark_hex_discovered(hex_id, terrain, name=hex_name)
        self._log(f"Starting position set: {hex_id} ({terrain.value})")
    
    def set_party_size(self, size: int) -> None:
        """Set party size for resource consumption."""
        self.party_size = max(1, size)
    
    def set_season(self, season: Season) -> None:
        """Set current season."""
        self.season = season
        self.current_weather = roll_weather(season)
    
    def set_time(self, day: int, watch: int) -> None:
        """Set current time."""
        self.day_number = max(1, day)
        self.watch_number = max(1, min(6, watch))
    
    def set_resources(self, **resources) -> None:
        """Set resource levels."""
        for resource, amount in resources.items():
            if hasattr(self.resources, resource):
                setattr(self.resources, resource, amount)
    
    def add_resources(self, resource_type: ResourceType, amount: int) -> None:
        """Add to resources."""
        self.resources.add(resource_type, amount)
    
    # =========================================================================
    # MOVEMENT
    # =========================================================================
    
    def travel_to_hex(
        self,
        destination: str,
        terrain: Optional[Terrain] = None,
        has_guide: bool = False,
        forced_march: bool = False,
        on_road: bool = False
    ) -> TravelResult:
        """
        Travel to an adjacent hex.
        
        Args:
            destination: Target hex ID.
            terrain: Terrain of destination (if known).
            has_guide: Party has a guide (reduces lost chance).
            forced_march: Push through exhaustion for faster travel.
            on_road: Traveling on a road.
        
        Returns:
            TravelResult with travel outcome.
        """
        # Validate destination is adjacent
        adjacent = get_adjacent_hexes(self.current_hex)
        if destination not in adjacent:
            # Allow non-adjacent travel but it takes multiple watches
            distance = hex_distance(self.current_hex, destination)
            if distance > 3:
                return TravelResult(
                    success=False,
                    origin_hex=self.current_hex,
                    destination_hex=destination,
                    watches_spent=0,
                    day_number=self.day_number,
                    current_watch=self.watch_number,
                    time_of_day=self._get_time_of_day(),
                    weather=self.current_weather
                )
        
        # Determine terrain
        if terrain is None:
            terrain = self._guess_terrain(destination)
        
        # Calculate movement cost
        base_cost = TERRAIN_MOVEMENT_COST.get(terrain, 2)
        if on_road:
            base_cost = max(1, base_cost - ROAD_BONUS)
        
        # Weather modifiers
        if self.current_weather in (Weather.HEAVY_RAIN, Weather.STORM, Weather.BLIZZARD):
            base_cost += 1
        elif self.current_weather == Weather.FOG:
            base_cost += 1
        
        watches_to_spend = base_cost
        
        # Check if we have enough watches left today (or use forced march)
        watches_remaining = 6 - self.watch_number + 1
        exhaustion_check = False
        exhaustion_failed = False
        
        if forced_march and watches_to_spend > watches_remaining:
            exhaustion_check = True
            # CON check would happen here - 50% chance for simplicity
            exhaustion_failed = random.randint(1, 6) <= 2
        
        # Check for getting lost
        lost_chance = TERRAIN_LOST_CHANCE.get(terrain, 1)
        if has_guide:
            lost_chance = max(0, lost_chance - 1)
        if self.current_weather == Weather.FOG:
            lost_chance += 1
        
        got_lost = lost_chance > 0 and random.randint(1, 6) <= lost_chance
        actual_destination = destination
        
        if got_lost:
            # End up in random adjacent hex instead
            actual_destination = get_random_adjacent_hex(self.current_hex)
            terrain = self._guess_terrain(actual_destination)
        
        # Check for random encounter
        encounter_chance = TERRAIN_ENCOUNTER_CHANCE.get(terrain, 2)
        if not is_daylight(self.watch_number, self.season):
            encounter_chance += 1
        
        encounter_roll = random.randint(1, 6)
        encounter_occurred = encounter_roll <= encounter_chance
        
        # Advance time
        starting_watch = self.watch_number
        starting_day = self.day_number
        self._advance_time(watches_to_spend)
        new_day = self.day_number > starting_day
        
        # Consume resources
        resources_consumed = self._consume_travel_resources(watches_to_spend)
        
        # Update position
        self.current_hex = actual_destination
        self.current_terrain = terrain
        
        # Mark hex discovered
        new_hex_discovered = actual_destination not in self.discovered_hexes
        self._mark_hex_discovered(actual_destination, terrain)
        
        # Log
        self._log(f"Traveled from {self.current_hex} to {actual_destination}")
        
        # Roll new weather if new day
        if new_day:
            self.current_weather = roll_weather(self.season)
        
        return TravelResult(
            success=True,
            origin_hex=self.current_hex,
            destination_hex=destination,
            watches_spent=watches_to_spend,
            new_day=new_day,
            day_number=self.day_number,
            current_watch=self.watch_number,
            time_of_day=self._get_time_of_day(),
            encounter_occurred=encounter_occurred,
            encounter_roll=encounter_roll,
            got_lost=got_lost,
            actual_destination=actual_destination if got_lost else None,
            terrain_crossed=terrain,
            weather=self.current_weather,
            resources_consumed=resources_consumed,
            exhaustion_check=exhaustion_check,
            exhaustion_failed=exhaustion_failed,
            new_hex_discovered=new_hex_discovered
        )
    
    def _guess_terrain(self, hex_id: str) -> Terrain:
        """Guess terrain for unknown hex (or get from discovered)."""
        if hex_id in self.discovered_hexes:
            return self.discovered_hexes[hex_id].terrain
        
        # Default to forest (Dolmenwood is mostly forest)
        return Terrain.FOREST
    
    # =========================================================================
    # EXPLORATION
    # =========================================================================
    
    def explore_hex(self, detailed: bool = False) -> ExplorationResult:
        """
        Explore the current hex.
        
        Args:
            detailed: Spend extra time for thorough exploration.
        
        Returns:
            ExplorationResult with discoveries.
        """
        watches_spent = 2 if detailed else 1
        
        # Check for encounter
        encounter_chance = TERRAIN_ENCOUNTER_CHANCE.get(self.current_terrain, 2)
        encounter_roll = random.randint(1, 6)
        encounter_occurred = encounter_roll <= encounter_chance
        
        # Make discoveries
        discoveries = []
        
        # Base discovery chance
        discovery_roll = random.randint(1, 6)
        if detailed:
            discovery_roll += 1
        
        if discovery_roll >= 4:
            # Found something
            discovery_type = random.choice([
                "a hidden path",
                "an old campsite",
                "unusual tracks",
                "a small stream",
                "strange markings on a tree",
                "a hollow tree with carvings",
                "mushroom circle",
                "abandoned equipment",
            ])
            discoveries.append(discovery_type)
        
        # Mark as explored if detailed
        if detailed and self.current_hex in self.discovered_hexes:
            self.discovered_hexes[self.current_hex].is_explored = True
        
        # Advance time and consume resources
        self._advance_time(watches_spent)
        resources_consumed = self._consume_travel_resources(watches_spent)
        
        return ExplorationResult(
            hex_id=self.current_hex,
            activity=WatchActivity.EXPLORE,
            watches_spent=watches_spent,
            discoveries=discoveries,
            encounter_occurred=encounter_occurred,
            encounter_roll=encounter_roll,
            resources_consumed=resources_consumed,
            weather=self.current_weather
        )
    
    def forage(self) -> ExplorationResult:
        """
        Spend a watch foraging for food.
        
        Returns:
            ExplorationResult with foraging outcome.
        """
        watches_spent = 1
        
        # Foraging roll (WIS check, simplified as d6)
        modifier = TERRAIN_FORAGE_MODIFIER.get(self.current_terrain, 0)
        roll = random.randint(1, 6) + modifier
        
        success = roll >= 4
        amount = 0
        
        if success:
            # Found 1d3 rations worth of food
            amount = random.randint(1, 3)
            self.resources.add(ResourceType.RATIONS, amount)
        
        # Check for encounter (foraging makes noise)
        encounter_chance = TERRAIN_ENCOUNTER_CHANCE.get(self.current_terrain, 2)
        encounter_roll = random.randint(1, 6)
        encounter_occurred = encounter_roll <= encounter_chance
        
        # Advance time
        self._advance_time(watches_spent)
        resources_consumed = self._consume_travel_resources(watches_spent, traveling=False)
        
        return ExplorationResult(
            hex_id=self.current_hex,
            activity=WatchActivity.FORAGE,
            watches_spent=watches_spent,
            foraging_success=success,
            foraging_amount=amount,
            encounter_occurred=encounter_occurred,
            encounter_roll=encounter_roll,
            resources_consumed=resources_consumed,
            weather=self.current_weather
        )
    
    def rest(self, full_rest: bool = False) -> ExplorationResult:
        """
        Rest for a watch or make camp.
        
        Args:
            full_rest: Make camp for the night (multiple watches).
        
        Returns:
            ExplorationResult.
        """
        if full_rest:
            # Camp until dawn
            watches_to_dawn = 6 - self.watch_number + 1
            watches_spent = max(2, watches_to_dawn)
            activity = WatchActivity.CAMP
        else:
            watches_spent = 1
            activity = WatchActivity.REST
        
        # Reduced encounter chance while resting (if watches are set)
        encounter_roll = random.randint(1, 6)
        encounter_occurred = encounter_roll == 1  # 1-in-6 only
        
        # Advance time
        self._advance_time(watches_spent)
        
        # Consume resources
        resources_consumed = self._consume_travel_resources(watches_spent, traveling=False)
        
        # Full rest at new day means new weather
        if full_rest and self.watch_number <= 2:
            self.current_weather = roll_weather(self.season)
        
        return ExplorationResult(
            hex_id=self.current_hex,
            activity=activity,
            watches_spent=watches_spent,
            encounter_occurred=encounter_occurred,
            encounter_roll=encounter_roll,
            resources_consumed=resources_consumed,
            weather=self.current_weather
        )

    # =========================================================================
    # v2.0 FORMAL WILDERNESS EXPLORATION LOOP
    # =========================================================================

    def execute_watch(
        self,
        activity: WatchActivity,
        destination: Optional[str] = None,
        terrain: Optional[Terrain] = None,
        **kwargs
    ) -> WatchResult:
        """
        Execute a single watch of wilderness exploration.

        This is the formal wilderness loop entry point for v2.0.
        Each watch follows the sequence:
        1. Watch starts
        2. Choose and execute activity
        3. Check for encounters
        4. Check resources
        5. Watch ends (or encounter occurs)

        Args:
            activity: The activity to perform this watch
            destination: Target hex for travel activity
            terrain: Known terrain of destination
            **kwargs: Additional activity parameters

        Returns:
            WatchResult with all outcomes
        """
        # Initialize day tracking if needed
        if self.current_day_result is None:
            self.current_day_result = WildernessDayResult(
                day_number=self.day_number,
                starting_hex=self.current_hex,
                weather=self.current_weather,
            )

        # Fire TRAVEL_SEGMENT trigger if handler available
        if self.trigger_handler:
            self.trigger_handler.fire_trigger("TRAVEL_SEGMENT", {
                "hex_id": self.current_hex,
                "watch": self.watch_number,
                "day": self.day_number,
                "activity": activity.value,
            })

        # Initialize result
        result = WatchResult(
            watch_number=self.watch_number,
            day_number=self.day_number,
            phase=WildernessPhase.EXECUTE_ACTIVITY,
            activity=activity,
            hex_id=self.current_hex,
            terrain=self.current_terrain,
            weather=self.current_weather,
            time_of_day=self._get_time_of_day(),
        )

        # Execute the activity
        if activity == WatchActivity.TRAVEL:
            if not destination:
                result.activity_success = False
                result.events.append("No destination specified for travel")
            else:
                travel_result = self.travel_to_hex(
                    destination=destination,
                    terrain=terrain,
                    has_guide=kwargs.get("has_guide", False),
                    forced_march=kwargs.get("forced_march", False),
                    on_road=kwargs.get("on_road", False),
                )
                result.movement_result = travel_result
                result.activity_success = travel_result.success

                if travel_result.encounter_occurred:
                    result.encounter_triggered = True
                    result.encounter_check_roll = travel_result.encounter_roll

                # Track hex traveled
                if travel_result.success:
                    actual_dest = travel_result.actual_destination or destination
                    self.current_day_result.hexes_traveled.append(actual_dest)

        elif activity == WatchActivity.FORAGE:
            forage_result = self.forage()
            result.exploration_result = forage_result
            result.activity_success = forage_result.foraging_success

            if forage_result.encounter_occurred:
                result.encounter_triggered = True
                result.encounter_check_roll = forage_result.encounter_roll

        elif activity == WatchActivity.EXPLORE:
            explore_result = self.explore_hex(detailed=kwargs.get("detailed", False))
            result.exploration_result = explore_result

            if explore_result.discoveries:
                self.current_day_result.discoveries.extend(explore_result.discoveries)

            if explore_result.encounter_occurred:
                result.encounter_triggered = True
                result.encounter_check_roll = explore_result.encounter_roll

        elif activity == WatchActivity.REST:
            rest_result = self.rest(full_rest=False)
            result.exploration_result = rest_result

            if rest_result.encounter_occurred:
                result.encounter_triggered = True
                result.encounter_check_roll = rest_result.encounter_roll

        elif activity == WatchActivity.CAMP:
            rest_result = self.rest(full_rest=True)
            result.exploration_result = rest_result

            if rest_result.encounter_occurred:
                result.encounter_triggered = True
                result.encounter_check_roll = rest_result.encounter_roll

        elif activity == WatchActivity.SEARCH:
            explore_result = self.explore_hex(detailed=True)
            result.exploration_result = explore_result

            if explore_result.encounter_occurred:
                result.encounter_triggered = True
                result.encounter_check_roll = explore_result.encounter_roll

        elif activity == WatchActivity.HIDE:
            # Hiding reduces encounter chance but takes a watch
            self._advance_time(1)
            result.activity_success = True
            result.events.append("Party concealed themselves")
            # No encounter check while hiding

        # Handle encounter if triggered
        if result.encounter_triggered:
            result = self._process_encounter(result)

        # Check resources
        result.resource_warnings = self.get_resource_warnings()

        # Check for fairy signs (Dolmenwood specific)
        fairy_signs = self._check_fairy_signs()
        if fairy_signs:
            result.fairy_signs = fairy_signs

        # Update day result
        self.current_day_result.watches.append(result)
        if result.encounter_triggered:
            self.current_day_result.encounters_occurred += 1

        # Check for new day
        if self.watch_number == 1:
            # Day has rolled over, finalize the previous day
            self.current_day_result.ending_hex = self.current_hex
            self.current_day_result = WildernessDayResult(
                day_number=self.day_number,
                starting_hex=self.current_hex,
                weather=self.current_weather,
            )

        result.phase = WildernessPhase.WATCH_END
        return result

    def _process_encounter(self, result: WatchResult) -> WatchResult:
        """
        Process an encounter, determining distance, surprise, and type.

        Args:
            result: The current WatchResult to update

        Returns:
            Updated WatchResult with encounter details
        """
        # Determine encounter distance
        distance_range = self.ENCOUNTER_DISTANCE.get(self.current_terrain, (2, 12))
        num_dice = distance_range[0] // 6 + 1
        result.encounter_distance = sum(random.randint(1, 6) for _ in range(num_dice)) * 10

        # Check for surprise (2-in-6 for each side)
        party_surprise_roll = random.randint(1, 6)
        encounter_surprise_roll = random.randint(1, 6)

        result.party_surprised = party_surprise_roll <= 2
        result.encounter_surprised = encounter_surprise_roll <= 2

        # Determine encounter type based on region
        region = self._get_region_for_hex(self.current_hex)
        result.encounter_type = self._roll_encounter_type(region)

        # State transition if we have a state machine
        if self.state_machine:
            try:
                self.state_machine.transition_to(
                    "WILDERNESS_ENCOUNTER",
                    trigger="ENCOUNTER_TRIGGERED",
                    metadata={
                        "hex_id": self.current_hex,
                        "encounter_type": result.encounter_type,
                        "distance": result.encounter_distance,
                    }
                )
                result.state_transition = "WILDERNESS_ENCOUNTER"
            except Exception as e:
                result.events.append(f"State transition failed: {e}")

        result.events.append(
            f"Encounter: {result.encounter_type} at {result.encounter_distance} yards"
        )

        return result

    def _roll_encounter_type(self, region: Optional[DolmenwoodRegion]) -> str:
        """
        Roll for encounter type based on region.

        Args:
            region: The Dolmenwood region

        Returns:
            String describing the encounter type
        """
        # This would integrate with DolmenwoodTables in a full implementation
        # For now, return a placeholder based on region
        if region == DolmenwoodRegion.ALDWEALD:
            encounters = [
                "Wood Elves (patrol)",
                "Fairy Creatures",
                "Bandits",
                "Wild Animals",
                "Lost Traveler",
                "Drune Cultists",
            ]
        elif region == DolmenwoodRegion.NAGWOOD:
            encounters = [
                "Undead",
                "Dark Fairy",
                "Giant Spiders",
                "Wolves",
                "Witch",
                "Lost Soul",
            ]
        elif region == DolmenwoodRegion.MULCHGROVE:
            encounters = [
                "Bog Creatures",
                "Swamp Trolls",
                "Giant Toads",
                "Fungi Folk",
                "Will-o-Wisps",
                "Hermit",
            ]
        else:
            encounters = [
                "Travelers",
                "Wild Animals",
                "Bandits",
                "Fairy Creatures",
                "Monster",
                "Unusual Sight",
            ]

        return random.choice(encounters)

    def _get_region_for_hex(self, hex_id: str) -> Optional[DolmenwoodRegion]:
        """
        Determine the Dolmenwood region for a hex.

        Args:
            hex_id: The hex ID (e.g., "0808")

        Returns:
            The DolmenwoodRegion or None if unknown
        """
        try:
            col, row = parse_hex_id(hex_id)
        except ValueError:
            return None

        # Simplified region determination based on hex coordinates
        # Dolmenwood is roughly a 12x12 hex grid
        if row <= 4:
            if col >= 11:
                return DolmenwoodRegion.NAGWOOD
            return DolmenwoodRegion.HIGH_WOLD
        elif row <= 8:
            if col <= 4:
                return DolmenwoodRegion.TITHELANDS
            elif col >= 11:
                return DolmenwoodRegion.NAGWOOD
            else:
                return DolmenwoodRegion.ALDWEALD
        else:
            if col >= 9:
                return DolmenwoodRegion.MULCHGROVE
            else:
                return DolmenwoodRegion.HAGS_ADDLE

        return None

    def _check_fairy_signs(self) -> List[str]:
        """
        Check for fairy influence signs (Dolmenwood specific).

        Fairy signs may appear when traveling through areas with high
        fairy influence, especially at dawn/dusk or in ancient parts
        of the wood.

        Returns:
            List of fairy sign descriptions
        """
        signs = []

        # Only check once per day
        if self.day_number == self.last_fairy_sign_day:
            return signs

        # Higher chance at liminal times
        base_chance = 1  # 1-in-6
        if self._get_time_of_day() in (TimeOfDay.DAWN, TimeOfDay.EVENING):
            base_chance += 1

        # Higher in certain regions
        region = self._get_region_for_hex(self.current_hex)
        if region in (DolmenwoodRegion.ALDWEALD, DolmenwoodRegion.NAGWOOD):
            base_chance += 1

        # Roll for fairy sign
        if random.randint(1, 6) <= base_chance:
            fairy_signs_table = [
                "A ring of mushrooms appears where there was none before",
                "Distant, unearthly music drifts through the trees",
                "A will-o-wisp flickers in the distance",
                "Strange laughter echoes from nowhere",
                "The party finds a small gift left on a stump",
                "Time seems to pass differently - the sun moves strangely",
                "A talking animal delivers a cryptic message",
                "Footprints appear in the mud that weren't there before",
                "The trees seem to whisper secrets",
                "A door appears in an ancient tree",
            ]
            signs.append(random.choice(fairy_signs_table))
            self.last_fairy_sign_day = self.day_number
            self.fairy_influence_level += 1

        return signs

    def resolve_encounter(
        self,
        reaction: str = "neutral",
        party_action: str = "parley",
    ) -> Dict[str, Any]:
        """
        Resolve an active encounter based on reaction and party action.

        Args:
            reaction: Result of reaction roll ("hostile", "unfriendly", "neutral", "friendly")
            party_action: What the party does ("fight", "flee", "parley", "hide")

        Returns:
            Dict with resolution result
        """
        if not self.active_encounter:
            return {"error": "No active encounter to resolve"}

        result = {
            "encounter_type": self.active_encounter.get("type"),
            "reaction": reaction,
            "party_action": party_action,
            "resolved": True,
        }

        if party_action == "fight" or reaction == "hostile":
            result["combat_initiated"] = True
            result["state_transition"] = "COMBAT"

            if self.state_machine:
                try:
                    self.state_machine.transition_to(
                        "COMBAT",
                        trigger="COMBAT_INITIATED",
                        metadata=self.active_encounter,
                    )
                except Exception as e:
                    result["error"] = str(e)

        elif party_action == "flee":
            # Flee check - each character needs to make it
            flee_success = random.randint(1, 6) >= 3  # 4-in-6 chance
            result["fled_successfully"] = flee_success
            if flee_success:
                result["state_transition"] = "WILDERNESS_TRAVEL"
            else:
                result["combat_initiated"] = True
                result["state_transition"] = "COMBAT"

        elif party_action == "parley":
            if reaction in ("friendly", "neutral"):
                result["social_interaction"] = True
                result["state_transition"] = "SOCIAL_INTERACTION"

                if self.state_machine:
                    try:
                        self.state_machine.transition_to(
                            "SOCIAL_INTERACTION",
                            trigger="SOCIAL_INITIATED",
                            metadata=self.active_encounter,
                        )
                    except Exception as e:
                        result["error"] = str(e)
            else:
                result["parley_failed"] = True
                result["combat_initiated"] = True

        elif party_action == "hide":
            # Hide check - 2-in-6 base, modified by terrain
            hide_chance = 2
            if self.current_terrain in (Terrain.DENSE_FOREST, Terrain.RUINS):
                hide_chance += 1
            hide_success = random.randint(1, 6) <= hide_chance
            result["hidden_successfully"] = hide_success
            if not hide_success:
                result["combat_initiated"] = True

        # Clear active encounter
        self.active_encounter = None

        return result

    # =========================================================================
    # RANDOM ENCOUNTERS
    # =========================================================================
    
    def check_encounter(self, modifier: int = 0) -> dict[str, Any]:
        """
        Check for a random encounter.
        
        Args:
            modifier: Modifier to encounter chance.
        
        Returns:
            Dict with encounter check results.
        """
        base_chance = TERRAIN_ENCOUNTER_CHANCE.get(self.current_terrain, 2)
        
        # Night increases chance
        if not is_daylight(self.watch_number, self.season):
            base_chance += 1
        
        # Weather can affect
        if self.current_weather in (Weather.FOG, Weather.STORM):
            base_chance += 1
        
        total_chance = max(1, min(5, base_chance + modifier))
        roll = random.randint(1, 6)
        encounter = roll <= total_chance
        
        return {
            "roll": roll,
            "chance": total_chance,
            "encounter": encounter,
            "terrain": self.current_terrain.value,
            "time": self._get_time_of_day().value,
            "brief": f"Encounter check: {roll} vs {total_chance}-in-6 = {'ENCOUNTER!' if encounter else 'No encounter'}"
        }
    
    # =========================================================================
    # TIME MANAGEMENT
    # =========================================================================
    
    def _advance_time(self, watches: int) -> None:
        """Advance time by given number of watches."""
        self.watch_number += watches
        
        while self.watch_number > 6:
            self.watch_number -= 6
            self.day_number += 1
            self._log(f"Day {self.day_number} begins")
    
    def _get_time_of_day(self) -> TimeOfDay:
        """Get current time of day."""
        return WATCH_TO_TIME.get(self.watch_number, TimeOfDay.MORNING)
    
    def advance_watch(self, watches: int = 1) -> dict[str, Any]:
        """
        Manually advance time.
        
        Returns:
            Dict with new time info.
        """
        old_day = self.day_number
        self._advance_time(watches)
        new_day = self.day_number > old_day
        
        if new_day:
            self.current_weather = roll_weather(self.season)
        
        return {
            "day": self.day_number,
            "watch": self.watch_number,
            "time_of_day": self._get_time_of_day().value,
            "new_day": new_day,
            "weather": self.current_weather.value,
            "brief": f"Time advances to Day {self.day_number}, {self._get_time_of_day().value}"
        }
    
    # =========================================================================
    # RESOURCES
    # =========================================================================
    
    def _consume_travel_resources(
        self, 
        watches: int, 
        traveling: bool = True
    ) -> dict[str, int]:
        """Consume resources for travel/activity."""
        consumed = {}
        
        # Consume rations at end of day or every 6 watches
        # Simplified: consume 1 ration per day per person
        if self.watch_number <= watches or self.watch_number == 1:
            ration_cost = self.party_size
            actual = self.resources.consume(ResourceType.RATIONS, ration_cost)
            if actual > 0:
                consumed["rations"] = actual
        
        # Water in hot weather or desert
        if self.current_terrain in (Terrain.MOUNTAINS, Terrain.CLEAR) and self.season == Season.SUMMER:
            water_cost = self.party_size
            actual = self.resources.consume(ResourceType.WATER, water_cost)
            if actual > 0:
                consumed["water"] = actual
        
        # Light sources at night
        if not is_daylight(self.watch_number, self.season) and traveling:
            # Use 1 torch per watch, or lantern oil
            if self.resources.get(ResourceType.LANTERN_OIL) > 0:
                actual = self.resources.consume(ResourceType.LANTERN_OIL, watches * 4)
                if actual > 0:
                    consumed["lantern_oil"] = actual
            elif self.resources.get(ResourceType.TORCHES) > 0:
                actual = self.resources.consume(ResourceType.TORCHES, watches)
                if actual > 0:
                    consumed["torches"] = actual
        
        return consumed
    
    def consume_resource(
        self, 
        resource: ResourceType, 
        amount: int
    ) -> dict[str, Any]:
        """
        Manually consume a resource.
        
        Returns:
            Dict with consumption result.
        """
        before = self.resources.get(resource)
        consumed = self.resources.consume(resource, amount)
        after = self.resources.get(resource)
        
        return {
            "resource": resource.value,
            "consumed": consumed,
            "remaining": after,
            "brief": f"Used {consumed} {resource.value} ({after} remaining)"
        }
    
    def get_resource_warnings(self) -> list[str]:
        """Get warnings about low resources."""
        warnings = []
        
        days_of_rations = self.resources.rations // max(1, self.party_size)
        if days_of_rations <= 0:
            warnings.append("⚠️ OUT OF RATIONS! The party is starving!")
        elif days_of_rations <= 2:
            warnings.append(f"⚠️ Low on rations ({days_of_rations} days remaining)")
        
        if self.resources.torches <= 0 and self.resources.lantern_oil <= 0:
            warnings.append("⚠️ No light sources! Travel at night will be dangerous.")
        
        return warnings
    
    # =========================================================================
    # HEX TRACKING
    # =========================================================================
    
    def _mark_hex_discovered(
        self, 
        hex_id: str, 
        terrain: Terrain,
        name: Optional[str] = None
    ) -> None:
        """Mark a hex as discovered."""
        if hex_id not in self.discovered_hexes:
            self.discovered_hexes[hex_id] = HexInfo(
                hex_id=hex_id,
                terrain=terrain,
                name=name,
                is_discovered=True
            )
        else:
            self.discovered_hexes[hex_id].is_discovered = True
            if terrain:
                self.discovered_hexes[hex_id].terrain = terrain
            if name:
                self.discovered_hexes[hex_id].name = name
    
    def add_hex_info(
        self,
        hex_id: str,
        terrain: Optional[Terrain] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        settlement: Optional[str] = None,
        points_of_interest: Optional[list[str]] = None,
        encounter_chance: Optional[int] = None
    ) -> None:
        """Add or update hex information."""
        if hex_id not in self.discovered_hexes:
            self.discovered_hexes[hex_id] = HexInfo(
                hex_id=hex_id,
                terrain=terrain or Terrain.FOREST
            )
        
        hex_info = self.discovered_hexes[hex_id]
        
        if terrain:
            hex_info.terrain = terrain
        if name:
            hex_info.name = name
        if description:
            hex_info.description = description
        if settlement:
            hex_info.settlement = settlement
        if points_of_interest:
            hex_info.points_of_interest = points_of_interest
        if encounter_chance is not None:
            hex_info.encounter_chance = encounter_chance
    
    def get_hex_info(self, hex_id: str) -> Optional[HexInfo]:
        """Get info about a hex."""
        return self.discovered_hexes.get(hex_id)
    
    def get_adjacent_info(self) -> list[dict[str, Any]]:
        """Get info about adjacent hexes."""
        adjacents = get_adjacent_hexes(self.current_hex)
        result = []
        
        for adj in adjacents:
            if adj in self.discovered_hexes:
                info = self.discovered_hexes[adj]
                result.append({
                    "hex_id": adj,
                    "terrain": info.terrain.value,
                    "name": info.name,
                    "known": True
                })
            else:
                result.append({
                    "hex_id": adj,
                    "terrain": "unknown",
                    "name": None,
                    "known": False
                })
        
        return result
    
    # =========================================================================
    # STATUS
    # =========================================================================
    
    def get_status(self) -> HexCrawlStatus:
        """Get current hex crawl status."""
        current_info = self.discovered_hexes.get(self.current_hex)
        region = self._get_region_for_hex(self.current_hex)

        return HexCrawlStatus(
            current_hex=self.current_hex,
            current_terrain=self.current_terrain,
            day_number=self.day_number,
            watch_number=self.watch_number,
            time_of_day=self._get_time_of_day(),
            weather=self.current_weather,
            season=self.season,
            resources=self.resources.to_dict(),
            party_size=self.party_size,
            discovered_hexes=len(self.discovered_hexes),
            region=region,
            fairy_influence=self.fairy_influence_level,
            current_hex_explored=current_info.is_explored if current_info else False,
            settlement_nearby=current_info.settlement if current_info else None
        )
    
    # =========================================================================
    # LOGGING
    # =========================================================================
    
    def _log(self, message: str) -> None:
        """Add to travel log."""
        timestamp = f"Day {self.day_number}, W{self.watch_number}"
        self.travel_log.append(f"[{timestamp}] {message}")
        logger.debug(message)
    
    def get_log(self) -> list[str]:
        """Get travel log."""
        return self.travel_log.copy()
