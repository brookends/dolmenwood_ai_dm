"""
Dolmenwood AI DM - Data Models v2.0

This module contains the extended data models for v2.0 of the system.
These models work alongside the existing data_models.py.

New structures include:
- PartyStateV2: Extended party tracking
- LocationState: Unified location representation
- EncounterState: Active encounter data
- FactionState: Faction tracking with clocks
- TimeTracker: Unified timekeeping
- WorldStateV2: Extended world state

Author: AI Dungeon Master Project
Version: 2.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# =============================================================================
# ENUMS
# =============================================================================

class LocationType(str, Enum):
    """Types of locations."""
    HEX = "hex"                     # Wilderness hex
    DUNGEON_ROOM = "dungeon_room"   # Room in a dungeon
    SETTLEMENT = "settlement"        # Town or village
    BUILDING = "building"            # Specific building in settlement
    SPECIAL = "special"              # Fairy realm, etc.


class SurpriseStatus(str, Enum):
    """Surprise state in encounters."""
    NONE = "none"               # Neither side surprised
    PARTY_SURPRISED = "party"   # Party is surprised
    ENEMY_SURPRISED = "enemy"   # Enemies are surprised
    MUTUAL = "mutual"           # Both sides surprised (rare)


class EncounterType(str, Enum):
    """Types of encounters."""
    MONSTER = "monster"         # Combat likely
    NPC = "npc"                 # Social likely
    PATROL = "patrol"           # Could go either way
    AMBUSH = "ambush"           # Combat likely, party disadvantage
    LAIR = "lair"               # Found a lair
    ENVIRONMENTAL = "environmental"  # Hazard, not creature


class ReactionResult(str, Enum):
    """Results of reaction rolls."""
    HOSTILE = "hostile"         # Immediate attack
    UNFRIENDLY = "unfriendly"   # Threatening
    NEUTRAL = "neutral"         # Uncertain
    INDIFFERENT = "indifferent" # Uninterested
    FRIENDLY = "friendly"       # Helpful


class FactionClockType(str, Enum):
    """Types of faction clocks."""
    PROGRESS = "progress"       # Working toward a goal
    COUNTDOWN = "countdown"     # Something bad happens at 0
    TENSION = "tension"         # Building conflict


# =============================================================================
# TIME TRACKING
# =============================================================================

class TimeTrackerV2(BaseModel):
    """
    Unified timekeeping system for all game modes.
    """
    # Exploration time (dungeon)
    exploration_turns: int = Field(default=0, ge=0, description="10-minute dungeon turns")

    # Travel time (wilderness)
    watches: int = Field(default=0, ge=0, description="4-hour wilderness watches")

    # Days elapsed
    days: int = Field(default=1, ge=1, description="Days since campaign start")

    # Current position in day
    current_watch: int = Field(default=2, ge=1, le=6, description="Current watch (1-6)")

    # Calendar
    day_of_month: int = Field(default=1, ge=1, le=28)
    month: int = Field(default=1, ge=1, le=13)
    year: int = Field(default=1, ge=1)

    # Season
    season: str = Field(default="autumn")

    def advance_turn(self, turns: int = 1) -> bool:
        """
        Advance dungeon turns.

        Returns:
            True if a watch boundary was crossed.
        """
        self.exploration_turns += turns
        # 24 turns = 4 hours = 1 watch
        if self.exploration_turns >= 24:
            watches_passed = self.exploration_turns // 24
            self.exploration_turns = self.exploration_turns % 24
            self.advance_watch(watches_passed)
            return True
        return False

    def advance_watch(self, watches: int = 1) -> bool:
        """
        Advance wilderness watches.

        Returns:
            True if a day boundary was crossed.
        """
        self.watches += watches
        self.current_watch += watches

        new_day = False
        while self.current_watch > 6:
            self.current_watch -= 6
            new_day = True
            self.advance_day()

        return new_day

    def advance_day(self, days: int = 1) -> bool:
        """
        Advance full days.

        Returns:
            True if a season boundary was crossed.
        """
        self.days += days
        self.day_of_month += days

        season_changed = False
        while self.day_of_month > 28:
            self.day_of_month -= 28
            self.month += 1

            while self.month > 13:
                self.month -= 13
                self.year += 1

            # Check for season change (every ~3 months)
            if self.month in (1, 4, 7, 10):
                self._update_season()
                season_changed = True

        return season_changed

    def _update_season(self) -> None:
        """Update season based on month."""
        season_map = {
            (1, 2, 3): "spring",
            (4, 5, 6): "summer",
            (7, 8, 9): "autumn",
            (10, 11, 12, 13): "winter",
        }
        for months, season in season_map.items():
            if self.month in months:
                self.season = season
                break

    def check_seasonal_threshold(self) -> bool:
        """Check if at a seasonal boundary."""
        return self.month in (1, 4, 7, 10) and self.day_of_month == 1

    @property
    def time_of_day(self) -> str:
        """Get time of day from current watch."""
        watch_times = {
            1: "dawn",
            2: "morning",
            3: "afternoon",
            4: "evening",
            5: "night",
            6: "late_night",
        }
        return watch_times.get(self.current_watch, "unknown")

    @property
    def is_daylight(self) -> bool:
        """Check if it's daylight."""
        return self.current_watch in (1, 2, 3, 4)


# =============================================================================
# LOCATION STATE
# =============================================================================

class LocationState(BaseModel):
    """
    Unified representation of current physical location.
    """
    # Location identity
    location_type: LocationType
    location_id: str = Field(description="Hex ID, room ID, or settlement ID")
    name: str = ""

    # Physical properties
    terrain: str = ""           # For hexes
    dimensions: str = ""        # For rooms
    lighting: str = "normal"    # dark, dim, normal, bright

    # Content
    known_features: list[str] = Field(default_factory=list)
    hazards: list[str] = Field(default_factory=list)
    occupants: list[str] = Field(default_factory=list, description="IDs of creatures/NPCs present")

    # Discovery tracking
    discovery_flags: dict[str, bool] = Field(default_factory=dict)
    searched: bool = False
    fully_explored: bool = False

    # Exits/connections
    exits: dict[str, str] = Field(default_factory=dict, description="Direction -> destination ID")

    def add_occupant(self, occupant_id: str) -> None:
        """Add an occupant to the location."""
        if occupant_id not in self.occupants:
            self.occupants.append(occupant_id)

    def remove_occupant(self, occupant_id: str) -> None:
        """Remove an occupant from the location."""
        if occupant_id in self.occupants:
            self.occupants.remove(occupant_id)

    def reveal_feature(self, feature: str) -> None:
        """Reveal a hidden feature."""
        if feature not in self.known_features:
            self.known_features.append(feature)
        self.discovery_flags[feature] = True


# =============================================================================
# ENCOUNTER STATE
# =============================================================================

class EncounterState(BaseModel):
    """
    Temporary structure for resolving encounters.
    """
    encounter_id: str = Field(description="Unique encounter identifier")
    encounter_type: EncounterType

    # Spatial information
    distance: int = Field(description="Initial distance in feet")
    terrain: str = ""

    # Surprise
    surprise_status: SurpriseStatus = SurpriseStatus.NONE

    # Participants
    actors: list[str] = Field(default_factory=list, description="Monster/NPC IDs involved")
    actor_count: int = 1

    # Context
    activity: str = ""          # What were they doing when encountered
    context: str = ""           # Additional context

    # Resolution
    reaction_result: Optional[ReactionResult] = None
    reaction_roll: Optional[int] = None
    resolved: bool = False
    resolution: str = ""        # "combat", "fled", "negotiated", etc.

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None

    def set_reaction(self, result: ReactionResult, roll: int) -> None:
        """Set the reaction result."""
        self.reaction_result = result
        self.reaction_roll = roll

    def resolve(self, resolution: str) -> None:
        """Mark the encounter as resolved."""
        self.resolved = True
        self.resolution = resolution
        self.resolved_at = datetime.now()


# =============================================================================
# FACTION STATE
# =============================================================================

class FactionClock(BaseModel):
    """
    A clock tracking faction progress toward a goal.
    """
    clock_id: str
    name: str
    description: str
    clock_type: FactionClockType = FactionClockType.PROGRESS

    # Clock state
    segments: int = Field(default=6, ge=1, description="Total segments")
    filled: int = Field(default=0, ge=0, description="Filled segments")

    # Triggers
    trigger_events: list[str] = Field(default_factory=list, description="Events that advance clock")
    completion_effect: str = ""

    @property
    def is_complete(self) -> bool:
        """Check if clock is complete."""
        return self.filled >= self.segments

    @property
    def progress_percentage(self) -> float:
        """Get progress as percentage."""
        return (self.filled / self.segments) * 100

    def advance(self, segments: int = 1) -> bool:
        """
        Advance the clock.

        Returns:
            True if clock completed.
        """
        self.filled = min(self.segments, self.filled + segments)
        return self.is_complete

    def regress(self, segments: int = 1) -> None:
        """Move the clock backward."""
        self.filled = max(0, self.filled - segments)


class FactionState(BaseModel):
    """
    Long-term tracking of factions and political actors.
    """
    faction_id: str
    name: str
    description: str = ""

    # Goals and resources
    goals: list[str] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list, description="Resources, agents, locations")

    # Relationships
    relationships: dict[str, int] = Field(
        default_factory=dict,
        description="Faction ID -> disposition (-10 to +10)"
    )

    # Clocks
    clocks: list[FactionClock] = Field(default_factory=list)

    # PC interaction
    pc_awareness: int = Field(
        default=0, ge=0, le=10,
        description="How much faction knows about PCs"
    )
    pc_standing: int = Field(
        default=0, ge=-10, le=10,
        description="Faction's disposition toward PCs"
    )

    # Activity level
    active: bool = True
    visibility: str = Field(default="hidden", description="hidden, known, prominent")

    def modify_relationship(self, other_faction_id: str, change: int) -> int:
        """Modify relationship with another faction."""
        current = self.relationships.get(other_faction_id, 0)
        new_value = max(-10, min(10, current + change))
        self.relationships[other_faction_id] = new_value
        return new_value

    def modify_pc_standing(self, change: int) -> int:
        """Modify faction's disposition toward PCs."""
        self.pc_standing = max(-10, min(10, self.pc_standing + change))
        return self.pc_standing

    def increase_pc_awareness(self, amount: int = 1) -> int:
        """Increase faction's awareness of PCs."""
        self.pc_awareness = min(10, self.pc_awareness + amount)
        return self.pc_awareness

    def get_clock(self, clock_id: str) -> Optional[FactionClock]:
        """Get a specific clock by ID."""
        for clock in self.clocks:
            if clock.clock_id == clock_id:
                return clock
        return None

    def add_clock(self, clock: FactionClock) -> None:
        """Add a new clock."""
        self.clocks.append(clock)


# =============================================================================
# PARTY STATE V2
# =============================================================================

class PartyStateV2(BaseModel):
    """
    Extended party state tracking for v2.0.
    """
    # Party composition
    character_ids: list[str] = Field(default_factory=list)
    marching_order: list[str] = Field(default_factory=list)
    party_size: int = Field(default=0, ge=0)

    # Current location
    location: LocationState = Field(default_factory=lambda: LocationState(
        location_type=LocationType.HEX,
        location_id="0808"
    ))

    # Resources
    rations: int = Field(default=0, ge=0)
    water: int = Field(default=0, ge=0)
    torches: int = Field(default=0, ge=0)
    lantern_oil: int = Field(default=0, ge=0, description="Hours of lantern oil")
    arrows: int = Field(default=0, ge=0)
    bolts: int = Field(default=0, ge=0)
    gold_pieces: int = Field(default=0, ge=0)
    silver_pieces: int = Field(default=0, ge=0)

    # Encumbrance
    encumbrance_total: int = Field(default=0, ge=0)
    encumbrance_limit: int = Field(default=1200, ge=0, description="In coins")
    movement_rate: int = Field(default=120, ge=0, description="Feet per turn")

    # Conditions affecting whole party
    active_conditions: list[str] = Field(default_factory=list)

    # Light source tracking
    light_source: Optional[str] = None
    light_remaining: int = Field(default=0, ge=0, description="Turns/hours remaining")

    # Hirelings and retainers
    hirelings: list[str] = Field(default_factory=list, description="Hireling IDs")
    retainers: list[str] = Field(default_factory=list, description="Retainer IDs")

    @property
    def days_of_rations(self) -> float:
        """Calculate days of rations remaining."""
        if self.party_size == 0:
            return float('inf')
        return self.rations / self.party_size

    @property
    def is_encumbered(self) -> bool:
        """Check if party is encumbered."""
        return self.encumbrance_total > self.encumbrance_limit

    def consume_rations(self, days: int = 1) -> int:
        """
        Consume rations for the party.

        Returns:
            Actual amount consumed.
        """
        needed = self.party_size * days
        consumed = min(self.rations, needed)
        self.rations -= consumed
        return consumed

    def consume_light(self, turns: int = 1) -> bool:
        """
        Consume light source.

        Returns:
            True if light source exhausted.
        """
        self.light_remaining -= turns
        if self.light_remaining <= 0:
            old_source = self.light_source
            self.light_source = None
            self.light_remaining = 0
            return old_source is not None
        return False


# =============================================================================
# WORLD STATE V2
# =============================================================================

class WorldStateV2(BaseModel):
    """
    Extended world state for v2.0.
    """
    campaign_id: str
    campaign_name: str

    # Time
    time_tracker: TimeTrackerV2 = Field(default_factory=TimeTrackerV2)

    # Weather
    weather: str = Field(default="clear")
    weather_duration: int = Field(default=1, description="Watches of current weather")

    # Party
    party: PartyStateV2 = Field(default_factory=PartyStateV2)

    # World flags
    global_flags: dict[str, Any] = Field(default_factory=dict)
    omens_active: list[str] = Field(default_factory=list)
    curses_active: list[str] = Field(default_factory=list)
    regional_effects: dict[str, str] = Field(default_factory=dict)

    # Discovery tracking
    cleared_locations: set[str] = Field(default_factory=set)
    discovered_secrets: set[str] = Field(default_factory=set)
    discovered_hexes: set[str] = Field(default_factory=set)

    # Active threats
    active_threats: list[dict[str, Any]] = Field(default_factory=list)

    # Factions
    factions: dict[str, FactionState] = Field(default_factory=dict)

    # Active encounter (if any)
    active_encounter: Optional[EncounterState] = None

    # History
    major_events: list[dict[str, Any]] = Field(default_factory=list)

    def add_faction(self, faction: FactionState) -> None:
        """Add a faction to the world."""
        self.factions[faction.faction_id] = faction

    def get_faction(self, faction_id: str) -> Optional[FactionState]:
        """Get a faction by ID."""
        return self.factions.get(faction_id)

    def clear_location(self, location_id: str) -> None:
        """Mark a location as cleared."""
        self.cleared_locations.add(location_id)

    def discover_hex(self, hex_id: str) -> bool:
        """
        Discover a hex.

        Returns:
            True if newly discovered.
        """
        if hex_id in self.discovered_hexes:
            return False
        self.discovered_hexes.add(hex_id)
        return True

    def add_omen(self, omen: str) -> None:
        """Add an active omen."""
        if omen not in self.omens_active:
            self.omens_active.append(omen)

    def remove_omen(self, omen: str) -> None:
        """Remove an omen."""
        if omen in self.omens_active:
            self.omens_active.remove(omen)

    def add_threat(self, threat: dict[str, Any]) -> None:
        """Add an active threat."""
        self.active_threats.append(threat)

    def remove_threat(self, threat_id: str) -> bool:
        """Remove a threat by ID."""
        for i, threat in enumerate(self.active_threats):
            if threat.get("id") == threat_id:
                self.active_threats.pop(i)
                return True
        return False

    def log_event(self, event: dict[str, Any]) -> None:
        """Log a major event."""
        event["timestamp"] = datetime.now().isoformat()
        event["day"] = self.time_tracker.days
        self.major_events.append(event)


# =============================================================================
# THREAT TRACKING
# =============================================================================

@dataclass
class ActiveThreat:
    """
    An active threat that may affect the party.
    """
    threat_id: str
    name: str
    description: str
    threat_type: str = "pursuit"  # pursuit, timer, ambient

    # For pursuits
    distance: int = 0           # Abstract distance units
    speed: int = 1              # How fast it closes

    # For timers
    countdown: int = 0          # Turns/watches until event
    event_description: str = ""

    # Status
    active: bool = True
    detected_by_party: bool = False

    def advance(self) -> bool:
        """
        Advance the threat.

        Returns:
            True if threat triggers.
        """
        if self.threat_type == "pursuit":
            self.distance = max(0, self.distance - self.speed)
            return self.distance <= 0
        elif self.threat_type == "timer":
            self.countdown = max(0, self.countdown - 1)
            return self.countdown <= 0
        return False
