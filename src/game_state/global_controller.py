"""
Dolmenwood AI DM - Global Controller (v2.0)

This module implements the always-active Global Control Layer that manages
cross-cutting concerns across all game states.

The Global Controller handles:
- World state management (time, weather, season)
- Party state tracking (resources, conditions, encumbrance)
- Rule arbitration and action validation
- Information gating (what characters can see/know)
- Random table access through a consistent interface

Author: AI Dungeon Master Project
Version: 2.0
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .state_machine import StateMachine, GameState

logger = logging.getLogger(__name__)


# =============================================================================
# TIME TRACKING
# =============================================================================

class TimeUnit(str, Enum):
    """Units of game time."""
    ROUND = "round"        # 10 seconds (combat)
    TURN = "turn"          # 10 minutes (dungeon)
    WATCH = "watch"        # 4 hours (wilderness)
    DAY = "day"            # 24 hours


class TimeOfDay(str, Enum):
    """Time periods within a day."""
    DAWN = "dawn"           # Watch 1 (6am-10am)
    MORNING = "morning"     # Watch 2 (10am-2pm)
    AFTERNOON = "afternoon" # Watch 3 (2pm-6pm)
    EVENING = "evening"     # Watch 4 (6pm-10pm)
    NIGHT = "night"         # Watch 5 (10pm-2am)
    LATE_NIGHT = "late_night"  # Watch 6 (2am-6am)


class Season(str, Enum):
    """Seasons affecting weather, daylight, and encounters."""
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"


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


@dataclass
class GameTime:
    """
    Canonical time representation.

    Tracks time at multiple granularities for different game modes.
    """
    # Cumulative counters
    total_rounds: int = 0     # Combat rounds
    total_turns: int = 0      # Dungeon exploration turns (10 min)
    total_watches: int = 0    # Wilderness watches (4 hours)

    # Calendar time
    day: int = 1
    month: int = 1  # 1-13 for Dolmenwood calendar
    year: int = 1

    # Current position in day
    watch: int = 2  # 1-6, start at morning

    def advance_round(self, rounds: int = 1) -> None:
        """Advance combat time."""
        self.total_rounds += rounds

    def advance_turn(self, turns: int = 1) -> None:
        """Advance dungeon exploration time."""
        self.total_turns += turns
        # 6 turns = 1 hour, 24 hours = 4 watches per day (approximately)
        # Convert turns to watch advancement if needed
        hours = turns / 6
        if hours >= 4:
            watches = int(hours // 4)
            self.advance_watch(watches)

    def advance_watch(self, watches: int = 1) -> bool:
        """
        Advance wilderness time.

        Returns:
            True if a new day started.
        """
        self.total_watches += watches
        self.watch += watches

        new_day = False
        while self.watch > 6:
            self.watch -= 6
            self.day += 1
            new_day = True

        # Handle month/year advancement
        while self.day > 28:  # Simplified month length
            self.day -= 28
            self.month += 1
            while self.month > 13:
                self.month -= 13
                self.year += 1

        return new_day

    def advance_day(self, days: int = 1) -> None:
        """Advance by full days."""
        self.day += days
        self.watch = 2  # Reset to morning

        while self.day > 28:
            self.day -= 28
            self.month += 1
            while self.month > 13:
                self.month -= 13
                self.year += 1

    @property
    def time_of_day(self) -> TimeOfDay:
        """Get current time of day from watch."""
        watch_to_time = {
            1: TimeOfDay.DAWN,
            2: TimeOfDay.MORNING,
            3: TimeOfDay.AFTERNOON,
            4: TimeOfDay.EVENING,
            5: TimeOfDay.NIGHT,
            6: TimeOfDay.LATE_NIGHT,
        }
        return watch_to_time.get(self.watch, TimeOfDay.MORNING)

    @property
    def is_daylight(self) -> bool:
        """Check if it's daylight (for light source tracking)."""
        return self.watch in (1, 2, 3, 4)

    @property
    def is_night(self) -> bool:
        """Check if it's nighttime."""
        return self.watch in (5, 6)

    def to_dict(self) -> dict[str, Any]:
        """Serialize time state."""
        return {
            "total_rounds": self.total_rounds,
            "total_turns": self.total_turns,
            "total_watches": self.total_watches,
            "day": self.day,
            "month": self.month,
            "year": self.year,
            "watch": self.watch,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GameTime":
        """Deserialize time state."""
        return cls(
            total_rounds=data.get("total_rounds", 0),
            total_turns=data.get("total_turns", 0),
            total_watches=data.get("total_watches", 0),
            day=data.get("day", 1),
            month=data.get("month", 1),
            year=data.get("year", 1),
            watch=data.get("watch", 2),
        )

    def format_calendar(self) -> str:
        """Get human-readable date string."""
        # Dolmenwood uses unique month names
        month_names = [
            "Longgrass", "Highsummer", "Harvestide", "Fallowfall",
            "Frostmoot", "Coldmoon", "Deepwinter", "Wolfmoon",
            "Springrise", "Bloomtide", "Raindew", "Midsummer", "Greenmonth"
        ]
        month_name = month_names[self.month - 1] if 1 <= self.month <= 13 else f"Month {self.month}"
        return f"{self.day} {month_name}, Year {self.year}"

    def __repr__(self) -> str:
        return f"GameTime(day={self.day}, watch={self.watch}, {self.time_of_day.value})"


# =============================================================================
# PARTY STATE
# =============================================================================

@dataclass
class PartyResources:
    """
    Consumable resources tracked for the party.
    """
    rations: int = 0
    water: int = 0
    torches: int = 0
    lantern_oil: int = 0  # Hours of light
    arrows: int = 0
    bolts: int = 0
    gold_pieces: int = 0
    silver_pieces: int = 0

    def consume(self, resource: str, amount: int = 1) -> int:
        """
        Consume a resource.

        Returns:
            Actual amount consumed.
        """
        current = getattr(self, resource, 0)
        consumed = min(current, amount)
        setattr(self, resource, current - consumed)
        return consumed

    def add(self, resource: str, amount: int) -> None:
        """Add to a resource."""
        current = getattr(self, resource, 0)
        setattr(self, resource, current + amount)

    def get(self, resource: str) -> int:
        """Get amount of a resource."""
        return getattr(self, resource, 0)

    def to_dict(self) -> dict[str, int]:
        """Serialize resources."""
        return {
            "rations": self.rations,
            "water": self.water,
            "torches": self.torches,
            "lantern_oil": self.lantern_oil,
            "arrows": self.arrows,
            "bolts": self.bolts,
            "gold_pieces": self.gold_pieces,
            "silver_pieces": self.silver_pieces,
        }

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> "PartyResources":
        """Deserialize resources."""
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})


@dataclass
class PartyState:
    """
    Aggregate state of the player party.
    """
    # Location
    current_hex: str = "0808"
    current_location_name: str = ""
    current_location_type: str = "wilderness"  # wilderness, dungeon, settlement
    dungeon_room: Optional[str] = None  # Current room in dungeon

    # Formation
    marching_order: list[str] = field(default_factory=list)  # Character IDs

    # Resources
    resources: PartyResources = field(default_factory=PartyResources)

    # Party status
    party_size: int = 4
    encumbrance_total: int = 0
    active_conditions: list[str] = field(default_factory=list)

    # Light tracking
    light_source: Optional[str] = None  # "torch", "lantern", "magical", None
    light_remaining: int = 0  # Turns/hours remaining

    def to_dict(self) -> dict[str, Any]:
        """Serialize party state."""
        return {
            "current_hex": self.current_hex,
            "current_location_name": self.current_location_name,
            "current_location_type": self.current_location_type,
            "dungeon_room": self.dungeon_room,
            "marching_order": self.marching_order,
            "resources": self.resources.to_dict(),
            "party_size": self.party_size,
            "encumbrance_total": self.encumbrance_total,
            "active_conditions": self.active_conditions,
            "light_source": self.light_source,
            "light_remaining": self.light_remaining,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PartyState":
        """Deserialize party state."""
        instance = cls(
            current_hex=data.get("current_hex", "0808"),
            current_location_name=data.get("current_location_name", ""),
            current_location_type=data.get("current_location_type", "wilderness"),
            dungeon_room=data.get("dungeon_room"),
            marching_order=data.get("marching_order", []),
            party_size=data.get("party_size", 4),
            encumbrance_total=data.get("encumbrance_total", 0),
            active_conditions=data.get("active_conditions", []),
            light_source=data.get("light_source"),
            light_remaining=data.get("light_remaining", 0),
        )
        if "resources" in data:
            instance.resources = PartyResources.from_dict(data["resources"])
        return instance


# =============================================================================
# WORLD STATE
# =============================================================================

@dataclass
class WorldFlags:
    """
    Global flags affecting the game world.
    """
    # Major world events
    omens_active: list[str] = field(default_factory=list)
    curses_active: list[str] = field(default_factory=list)
    regional_effects: dict[str, str] = field(default_factory=dict)

    # Discovery tracking
    cleared_locations: set[str] = field(default_factory=set)
    discovered_secrets: set[str] = field(default_factory=set)

    # Faction relations (faction_id -> relation level -10 to +10)
    faction_standings: dict[str, int] = field(default_factory=dict)

    def add_omen(self, omen: str) -> None:
        """Add an active omen."""
        if omen not in self.omens_active:
            self.omens_active.append(omen)

    def remove_omen(self, omen: str) -> None:
        """Remove an omen."""
        if omen in self.omens_active:
            self.omens_active.remove(omen)

    def modify_faction(self, faction_id: str, change: int) -> int:
        """
        Modify faction standing.

        Returns:
            New standing value.
        """
        current = self.faction_standings.get(faction_id, 0)
        new_value = max(-10, min(10, current + change))
        self.faction_standings[faction_id] = new_value
        return new_value

    def to_dict(self) -> dict[str, Any]:
        """Serialize world flags."""
        return {
            "omens_active": self.omens_active,
            "curses_active": self.curses_active,
            "regional_effects": self.regional_effects,
            "cleared_locations": list(self.cleared_locations),
            "discovered_secrets": list(self.discovered_secrets),
            "faction_standings": self.faction_standings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldFlags":
        """Deserialize world flags."""
        return cls(
            omens_active=data.get("omens_active", []),
            curses_active=data.get("curses_active", []),
            regional_effects=data.get("regional_effects", {}),
            cleared_locations=set(data.get("cleared_locations", [])),
            discovered_secrets=set(data.get("discovered_secrets", [])),
            faction_standings=data.get("faction_standings", {}),
        )


# =============================================================================
# VALIDATION RESULTS
# =============================================================================

@dataclass
class ValidationResult:
    """
    Result of action validation.
    """
    valid: bool
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    modifiers: dict[str, int] = field(default_factory=dict)

    @classmethod
    def success(cls, warnings: Optional[list[str]] = None) -> "ValidationResult":
        """Create a successful validation result."""
        return cls(valid=True, warnings=warnings or [])

    @classmethod
    def failure(cls, reason: str) -> "ValidationResult":
        """Create a failed validation result."""
        return cls(valid=False, reason=reason)


@dataclass
class EncumbranceResult:
    """
    Result of encumbrance calculation.
    """
    total_weight: float
    encumbrance_level: str  # "unencumbered", "lightly", "heavily", "max"
    movement_penalty: float  # Multiplier (1.0 = no penalty)
    can_act: bool
    warnings: list[str] = field(default_factory=list)


# =============================================================================
# RANDOM TABLE RESULT
# =============================================================================

@dataclass
class TableResult:
    """
    Result from rolling on a random table.
    """
    table_name: str
    roll: int
    result: Any
    modifiers_applied: dict[str, int] = field(default_factory=dict)
    description: str = ""

    @property
    def brief(self) -> str:
        """Get brief description of result."""
        return self.description or f"{self.table_name}: {self.result}"


# =============================================================================
# GLOBAL CONTROLLER
# =============================================================================

class GlobalController:
    """
    Always-active layer managing cross-cutting concerns.

    The Global Controller is active in ALL game states and handles:
    - Time tracking and advancement
    - Weather and seasonal effects
    - Party resource management
    - Action validation
    - Information gating
    - Random table access

    Example:
        >>> controller = GlobalController()
        >>> controller.advance_time(TimeUnit.WATCH, 2)
        >>> print(controller.get_current_time())
        GameTime(day=1, watch=4, afternoon)
        >>>
        >>> result = controller.validate_action("travel", {"destination": "0809"})
        >>> print(result.valid)
        True
    """

    def __init__(
        self,
        state_machine: Optional["StateMachine"] = None,
    ):
        """
        Initialize the global controller.

        Args:
            state_machine: Optional state machine to integrate with.
        """
        self.state_machine = state_machine

        # Core state
        self._time = GameTime()
        self._season = Season.AUTUMN
        self._weather = Weather.CLEAR
        self._party = PartyState()
        self._world_flags = WorldFlags()

        # Threat tracking
        self._active_threats: list[dict[str, Any]] = []

        logger.info("GlobalController initialized")

    # =========================================================================
    # TIME MANAGEMENT
    # =========================================================================

    def get_current_time(self) -> GameTime:
        """Get current game time."""
        return self._time

    def get_time_of_day(self) -> TimeOfDay:
        """Get current time of day."""
        return self._time.time_of_day

    def get_weather(self) -> Weather:
        """Get current weather."""
        return self._weather

    def get_season(self) -> Season:
        """Get current season."""
        return self._season

    def advance_time(
        self,
        unit: TimeUnit,
        amount: int = 1,
        consume_resources: bool = True
    ) -> dict[str, Any]:
        """
        Advance game time and trigger appropriate effects.

        Args:
            unit: Time unit to advance.
            amount: Number of units to advance.
            consume_resources: Whether to consume resources (rations, light, etc.)

        Returns:
            Dict with time advancement results.
        """
        old_day = self._time.day
        old_watch = self._time.watch
        new_day = False

        if unit == TimeUnit.ROUND:
            self._time.advance_round(amount)
        elif unit == TimeUnit.TURN:
            self._time.advance_turn(amount)
            if consume_resources:
                self._consume_light(amount)
        elif unit == TimeUnit.WATCH:
            new_day = self._time.advance_watch(amount)
            if consume_resources:
                self._consume_daily_resources(amount)
        elif unit == TimeUnit.DAY:
            self._time.advance_day(amount)
            new_day = True
            if consume_resources:
                self._consume_daily_resources(amount * 6)  # 6 watches per day

        # Roll new weather if day changed
        if new_day:
            self._roll_weather()

        result = {
            "unit": unit.value,
            "amount": amount,
            "new_day": new_day,
            "old_time": {"day": old_day, "watch": old_watch},
            "new_time": {"day": self._time.day, "watch": self._time.watch},
            "time_of_day": self._time.time_of_day.value,
            "weather": self._weather.value,
        }

        logger.debug(f"Time advanced: {unit.value} x{amount}")
        return result

    def set_time(
        self,
        day: Optional[int] = None,
        watch: Optional[int] = None,
        month: Optional[int] = None,
        year: Optional[int] = None
    ) -> None:
        """Set specific time values."""
        if day is not None:
            self._time.day = day
        if watch is not None:
            self._time.watch = max(1, min(6, watch))
        if month is not None:
            self._time.month = month
        if year is not None:
            self._time.year = year

    def set_season(self, season: Season) -> None:
        """Set current season."""
        self._season = season
        self._roll_weather()  # Reroll weather for new season

    def set_weather(self, weather: Weather) -> None:
        """Manually set weather."""
        self._weather = weather

    def _roll_weather(self) -> None:
        """Roll for new weather based on season."""
        weather_tables = {
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

        table = weather_tables.get(self._season, weather_tables[Season.AUTUMN])
        roll = random.randint(1, 20)

        for low, high, weather in table:
            if low <= roll <= high:
                self._weather = weather
                break

    def _consume_light(self, turns: int) -> None:
        """Consume light source for dungeon turns."""
        if self._party.light_source == "torch":
            self._party.light_remaining -= turns
            if self._party.light_remaining <= 0:
                self._party.light_source = None
                # Try to light new torch
                if self._party.resources.torches > 0:
                    self._party.resources.consume("torches", 1)
                    self._party.light_source = "torch"
                    self._party.light_remaining = 6  # 6 turns per torch

        elif self._party.light_source == "lantern":
            # Lantern uses 1 hour of oil per hour (6 turns)
            oil_used = turns / 6
            actual = self._party.resources.consume("lantern_oil", int(oil_used))
            if actual < oil_used:
                self._party.light_source = None

    def _consume_daily_resources(self, watches: int) -> None:
        """Consume daily resources based on watches passed."""
        # Consume rations (1 per person per day, so 1 per 6 watches)
        if watches >= 6:
            days = watches // 6
            ration_cost = self._party.party_size * days
            self._party.resources.consume("rations", ration_cost)

    # =========================================================================
    # PARTY STATE
    # =========================================================================

    def get_party_state(self) -> PartyState:
        """Get current party state."""
        return self._party

    def set_party_location(
        self,
        hex_id: str,
        location_name: str = "",
        location_type: str = "wilderness"
    ) -> None:
        """Set party's current location."""
        self._party.current_hex = hex_id
        self._party.current_location_name = location_name
        self._party.current_location_type = location_type

    def set_dungeon_room(self, room_id: Optional[str]) -> None:
        """Set current dungeon room."""
        self._party.dungeon_room = room_id

    def set_marching_order(self, character_ids: list[str]) -> None:
        """Set party marching order."""
        self._party.marching_order = character_ids
        self._party.party_size = len(character_ids)

    def add_party_condition(self, condition: str) -> None:
        """Add a condition affecting the whole party."""
        if condition not in self._party.active_conditions:
            self._party.active_conditions.append(condition)

    def remove_party_condition(self, condition: str) -> None:
        """Remove a party condition."""
        if condition in self._party.active_conditions:
            self._party.active_conditions.remove(condition)

    def consume_resource(self, resource: str, amount: int = 1) -> int:
        """
        Consume a party resource.

        Returns:
            Actual amount consumed.
        """
        return self._party.resources.consume(resource, amount)

    def add_resource(self, resource: str, amount: int) -> None:
        """Add to a party resource."""
        self._party.resources.add(resource, amount)

    def get_resource(self, resource: str) -> int:
        """Get amount of a party resource."""
        return self._party.resources.get(resource)

    def get_resource_warnings(self) -> list[str]:
        """Get warnings about low resources."""
        warnings = []

        days_of_rations = self._party.resources.rations // max(1, self._party.party_size)
        if days_of_rations <= 0:
            warnings.append("OUT OF RATIONS! The party is starving!")
        elif days_of_rations <= 2:
            warnings.append(f"Low on rations ({days_of_rations} days remaining)")

        if self._party.resources.torches <= 0 and self._party.resources.lantern_oil <= 0:
            warnings.append("No light sources available!")

        return warnings

    # =========================================================================
    # WORLD FLAGS
    # =========================================================================

    def get_world_flags(self) -> WorldFlags:
        """Get current world flags."""
        return self._world_flags

    def add_omen(self, omen: str) -> None:
        """Add an active omen."""
        self._world_flags.add_omen(omen)

    def clear_location(self, location_id: str) -> None:
        """Mark a location as cleared."""
        self._world_flags.cleared_locations.add(location_id)

    def is_location_cleared(self, location_id: str) -> bool:
        """Check if a location is cleared."""
        return location_id in self._world_flags.cleared_locations

    def modify_faction_standing(self, faction_id: str, change: int) -> int:
        """Modify a faction standing."""
        return self._world_flags.modify_faction(faction_id, change)

    def get_faction_standing(self, faction_id: str) -> int:
        """Get current faction standing."""
        return self._world_flags.faction_standings.get(faction_id, 0)

    # =========================================================================
    # ACTION VALIDATION
    # =========================================================================

    def validate_action(
        self,
        action_type: str,
        context: dict[str, Any]
    ) -> ValidationResult:
        """
        Validate if an action is possible in the current state.

        Args:
            action_type: Type of action (travel, attack, cast_spell, etc.)
            context: Context for the action.

        Returns:
            ValidationResult indicating if action is valid.
        """
        warnings = []
        modifiers = {}

        # Check state-specific restrictions
        if self.state_machine:
            current_state = self.state_machine.current_state

            # Combat restrictions
            if current_state.value == "combat":
                if action_type in ("travel", "rest", "forage"):
                    return ValidationResult.failure(
                        f"Cannot {action_type} during combat"
                    )

            # Non-combat restrictions
            if current_state.value != "combat":
                if action_type == "attack":
                    return ValidationResult.failure(
                        "Cannot attack outside of combat"
                    )

        # Check resource requirements
        if action_type == "travel":
            if self._party.resources.rations <= 0:
                warnings.append("No rations! Risk of exhaustion.")

            if not self._time.is_daylight:
                if self._party.resources.torches <= 0 and self._party.resources.lantern_oil <= 0:
                    warnings.append("No light source for night travel!")
                    modifiers["lost_chance"] = 2  # Increased lost chance

        if action_type == "cast_spell":
            # Spell-specific validation would go here
            pass

        # Check party conditions
        if "exhausted" in self._party.active_conditions:
            modifiers["action_penalty"] = -2
            warnings.append("Party is exhausted (-2 to actions)")

        return ValidationResult(
            valid=True,
            warnings=warnings,
            modifiers=modifiers
        )

    def enforce_encumbrance(self, character: Any) -> EncumbranceResult:
        """
        Calculate encumbrance effects for a character.

        Args:
            character: Character to check (must have encumbrance property).

        Returns:
            EncumbranceResult with penalties.
        """
        total_weight = getattr(character, 'encumbrance', 0)
        strength = getattr(character, 'strength', 10)

        # OSE encumbrance thresholds based on STR
        light_threshold = strength * 10
        heavy_threshold = strength * 20
        max_threshold = strength * 30

        if total_weight <= light_threshold:
            return EncumbranceResult(
                total_weight=total_weight,
                encumbrance_level="unencumbered",
                movement_penalty=1.0,
                can_act=True
            )
        elif total_weight <= heavy_threshold:
            return EncumbranceResult(
                total_weight=total_weight,
                encumbrance_level="lightly",
                movement_penalty=0.75,
                can_act=True,
                warnings=["Lightly encumbered: 3/4 movement"]
            )
        elif total_weight <= max_threshold:
            return EncumbranceResult(
                total_weight=total_weight,
                encumbrance_level="heavily",
                movement_penalty=0.5,
                can_act=True,
                warnings=["Heavily encumbered: 1/2 movement"]
            )
        else:
            return EncumbranceResult(
                total_weight=total_weight,
                encumbrance_level="max",
                movement_penalty=0.0,
                can_act=False,
                warnings=["Over encumbrance limit! Cannot move"]
            )

    # =========================================================================
    # INFORMATION GATING
    # =========================================================================

    def get_visible_information(
        self,
        character_id: str,
        location_id: str
    ) -> dict[str, Any]:
        """
        Get information visible to a character at a location.

        This gates what information the LLM should reveal based on
        what the character can actually perceive.

        Args:
            character_id: Character requesting information.
            location_id: Current location.

        Returns:
            Dict of visible information.
        """
        visible = {
            "time": self._time.time_of_day.value,
            "weather": self._weather.value,
            "lighting": "daylight" if self._time.is_daylight else "darkness",
        }

        # Check for light source in darkness
        if not self._time.is_daylight:
            if self._party.light_source:
                visible["lighting"] = f"illuminated ({self._party.light_source})"
                visible["visibility_range"] = 30 if self._party.light_source == "torch" else 60
            else:
                visible["visibility_range"] = 0

        # Add weather effects on visibility
        if self._weather in (Weather.FOG, Weather.STORM, Weather.BLIZZARD):
            visible["visibility_modifier"] = "reduced"

        return visible

    def filter_for_player(self, info: dict[str, Any]) -> dict[str, Any]:
        """
        Filter game information for player consumption.

        Removes DM-only information like hidden traps, monster motivations,
        and unrevealed secrets.

        Args:
            info: Full information dict.

        Returns:
            Filtered dict safe for players.
        """
        dm_only_keys = {
            "dm_notes", "secrets", "hidden_traps", "treasure_contents",
            "monster_motivations", "trap_dc", "secret_door_dc",
            "npc_true_intentions", "hidden_features"
        }

        return {k: v for k, v in info.items() if k not in dm_only_keys}

    # =========================================================================
    # RANDOM TABLE ACCESS
    # =========================================================================

    def roll_on_table(
        self,
        table_name: str,
        modifiers: Optional[dict[str, int]] = None
    ) -> TableResult:
        """
        Roll on a random table.

        This provides a consistent interface for all randomization,
        ensuring the LLM never generates random results.

        Args:
            table_name: Name of the table to roll on.
            modifiers: Optional modifiers to apply.

        Returns:
            TableResult with the rolled result.
        """
        modifiers = modifiers or {}

        # Placeholder implementation - actual tables would be in dolmenwood_tables.py
        roll = random.randint(1, 20)

        # Apply modifiers
        total_modifier = sum(modifiers.values())
        modified_roll = roll + total_modifier

        return TableResult(
            table_name=table_name,
            roll=modified_roll,
            result=f"Result for roll {modified_roll}",
            modifiers_applied=modifiers,
            description=f"Rolled {roll} + {total_modifier} = {modified_roll} on {table_name}"
        )

    # =========================================================================
    # THREAT TRACKING
    # =========================================================================

    def add_threat(self, threat: dict[str, Any]) -> None:
        """Add an active threat (pursuing enemies, timed events, etc.)."""
        self._active_threats.append(threat)

    def get_active_threats(self) -> list[dict[str, Any]]:
        """Get list of active threats."""
        return self._active_threats.copy()

    def remove_threat(self, threat_id: str) -> bool:
        """Remove a threat by ID."""
        for i, threat in enumerate(self._active_threats):
            if threat.get("id") == threat_id:
                self._active_threats.pop(i)
                return True
        return False

    # =========================================================================
    # SERIALIZATION
    # =========================================================================

    def get_snapshot(self) -> dict[str, Any]:
        """Get complete snapshot for persistence."""
        return {
            "time": self._time.to_dict(),
            "season": self._season.value,
            "weather": self._weather.value,
            "party": self._party.to_dict(),
            "world_flags": self._world_flags.to_dict(),
            "active_threats": self._active_threats,
        }

    def restore_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Restore from a snapshot."""
        if "time" in snapshot:
            self._time = GameTime.from_dict(snapshot["time"])
        if "season" in snapshot:
            self._season = Season(snapshot["season"])
        if "weather" in snapshot:
            self._weather = Weather(snapshot["weather"])
        if "party" in snapshot:
            self._party = PartyState.from_dict(snapshot["party"])
        if "world_flags" in snapshot:
            self._world_flags = WorldFlags.from_dict(snapshot["world_flags"])
        if "active_threats" in snapshot:
            self._active_threats = snapshot["active_threats"]

        logger.info("GlobalController restored from snapshot")

    def get_status_summary(self) -> str:
        """Get human-readable status summary."""
        lines = [
            f"=== GLOBAL STATUS ===",
            f"Time: {self._time.format_calendar()}, {self._time.time_of_day.value}",
            f"Season: {self._season.value.capitalize()}",
            f"Weather: {self._weather.value.replace('_', ' ').capitalize()}",
            f"",
            f"Location: Hex {self._party.current_hex}",
            f"Party Size: {self._party.party_size}",
            f"Rations: {self._party.resources.rations}",
        ]

        warnings = self.get_resource_warnings()
        if warnings:
            lines.append("")
            lines.append("WARNINGS:")
            for w in warnings:
                lines.append(f"  ! {w}")

        return "\n".join(lines)


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_global_controller(
    state_machine: Optional["StateMachine"] = None
) -> GlobalController:
    """
    Create a new global controller.

    Args:
        state_machine: Optional state machine to integrate with.

    Returns:
        Configured GlobalController instance.
    """
    return GlobalController(state_machine=state_machine)


def restore_global_controller(
    snapshot: dict[str, Any],
    state_machine: Optional["StateMachine"] = None
) -> GlobalController:
    """
    Restore a global controller from saved data.

    Args:
        snapshot: Serialized snapshot data.
        state_machine: Optional state machine to integrate with.

    Returns:
        Restored GlobalController instance.
    """
    controller = GlobalController(state_machine=state_machine)
    controller.restore_snapshot(snapshot)
    return controller
