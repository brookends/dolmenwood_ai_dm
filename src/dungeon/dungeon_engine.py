"""
Dolmenwood AI DM - Dungeon Exploration Engine (v2.0)

This module implements the dungeon exploration loop with proper
procedural controls.

The dungeon loop (per 10-minute turn):
1. Advance time
2. Deplete light sources
3. Resolve declared player action
4. Check wandering monsters
5. If encounter → transition to DUNGEON_ENCOUNTER
6. Apply noise & consequence flags
7. Update dungeon state
8. Request LLM description (room details only)

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
    from game_state.state_machine import StateMachine, TransitionTrigger
    from game_state.global_controller import GlobalController
    from resolution.procedure_triggers import TriggerHandler

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class DungeonPhase(str, Enum):
    """Current phase of dungeon exploration."""
    IDLE = "idle"
    EXPLORING = "exploring"
    ENCOUNTER = "encounter"
    RESTING = "resting"


class RoomType(str, Enum):
    """Types of dungeon rooms."""
    CORRIDOR = "corridor"
    CHAMBER = "chamber"
    CAVE = "cave"
    SPECIAL = "special"
    ENTRANCE = "entrance"
    STAIRS = "stairs"


class DoorType(str, Enum):
    """Types of doors."""
    OPEN = "open"
    CLOSED = "closed"
    LOCKED = "locked"
    STUCK = "stuck"
    SECRET = "secret"
    TRAPPED = "trapped"


class LightLevel(str, Enum):
    """Lighting conditions."""
    BRIGHT = "bright"       # Full daylight/magical
    NORMAL = "normal"       # Torches, lanterns
    DIM = "dim"             # Distant light
    DARK = "dark"           # No light


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DungeonRoom:
    """
    A room in the dungeon.
    """
    room_id: str
    name: str
    room_type: RoomType = RoomType.CHAMBER

    # Dimensions
    width: int = 30         # feet
    length: int = 30        # feet
    height: int = 10        # feet

    # Lighting
    light_level: LightLevel = LightLevel.DARK
    light_sources: list[str] = field(default_factory=list)

    # Contents
    description: str = ""
    features: list[str] = field(default_factory=list)
    creatures: list[str] = field(default_factory=list)
    treasure: list[str] = field(default_factory=list)
    traps: list[str] = field(default_factory=list)

    # Exits
    exits: dict[str, str] = field(default_factory=dict)  # direction -> room_id or "door"
    doors: dict[str, DoorType] = field(default_factory=dict)  # direction -> door type

    # State tracking
    visited: bool = False
    searched: bool = False
    cleared: bool = False
    noise_level: int = 0

    def visit(self) -> bool:
        """
        Mark room as visited.

        Returns:
            True if first visit.
        """
        first_visit = not self.visited
        self.visited = True
        return first_visit

    def add_noise(self, amount: int = 1) -> None:
        """Add noise to the room (affects wandering monsters)."""
        self.noise_level = min(5, self.noise_level + amount)

    def decay_noise(self) -> None:
        """Decay noise over time."""
        self.noise_level = max(0, self.noise_level - 1)


@dataclass
class TurnResult:
    """
    Result of a dungeon exploration turn.
    """
    turn_number: int
    action_taken: str
    action_result: dict[str, Any]

    # Time and resources
    time_spent: int = 1  # turns
    light_consumed: bool = False
    light_remaining: int = 0

    # Encounter
    wandering_monster_check: bool = False
    wandering_monster_roll: int = 0
    encounter_occurred: bool = False
    encounter_data: Optional[dict[str, Any]] = None

    # State changes
    noise_change: int = 0
    discoveries: list[str] = field(default_factory=list)

    @property
    def brief(self) -> str:
        """Get brief summary."""
        parts = [f"Turn {self.turn_number}: {self.action_taken}"]

        if self.encounter_occurred:
            parts.append("ENCOUNTER!")

        if self.discoveries:
            parts.append(f"Discovered: {', '.join(self.discoveries)}")

        if self.light_consumed and self.light_remaining <= 0:
            parts.append("Light source exhausted!")

        return " | ".join(parts)


@dataclass
class DungeonStatus:
    """
    Current dungeon exploration status.
    """
    phase: DungeonPhase
    current_room_id: str
    current_room_name: str
    turn_number: int
    time_elapsed: int  # turns

    # Party status
    light_source: Optional[str]
    light_remaining: int
    party_conditions: list[str]

    # Room status
    room_searched: bool
    room_cleared: bool
    visible_exits: list[str]

    # Alerts
    noise_level: int
    warnings: list[str]

    @property
    def brief(self) -> str:
        """Get concise status."""
        return (
            f"Room: {self.current_room_name} | "
            f"Turn {self.turn_number} | "
            f"Light: {self.light_remaining} turns | "
            f"Noise: {self.noise_level}"
        )

    @property
    def full_status(self) -> str:
        """Get detailed status."""
        lines = [
            f"=== DUNGEON EXPLORATION ===",
            f"Location: {self.current_room_name} ({self.current_room_id})",
            f"Turn: {self.turn_number} ({self.time_elapsed * 10} minutes elapsed)",
            f"",
            f"Light: {self.light_source or 'None'} ({self.light_remaining} turns remaining)",
            f"Noise Level: {self.noise_level}/5",
            f"",
            f"Room Status:",
            f"  Searched: {'Yes' if self.room_searched else 'No'}",
            f"  Cleared: {'Yes' if self.room_cleared else 'No'}",
            f"  Exits: {', '.join(self.visible_exits)}",
        ]

        if self.warnings:
            lines.append("")
            lines.append("WARNINGS:")
            for w in self.warnings:
                lines.append(f"  ! {w}")

        return "\n".join(lines)


# =============================================================================
# DUNGEON ENGINE
# =============================================================================

class DungeonEngine:
    """
    Dungeon exploration state machine.

    Handles the procedural dungeon exploration loop:
    1. Time advancement (10-minute turns)
    2. Light source management
    3. Wandering monster checks
    4. Noise tracking
    5. Room-by-room exploration

    Example:
        >>> engine = DungeonEngine()
        >>> engine.enter_dungeon("dungeon_1", "room_1")
        >>> result = engine.explore_turn("search")
        >>> print(result.brief)
    """

    def __init__(
        self,
        state_machine: Optional["StateMachine"] = None,
        controller: Optional["GlobalController"] = None,
        trigger_handler: Optional["TriggerHandler"] = None
    ):
        """
        Initialize dungeon engine.

        Args:
            state_machine: Optional state machine for transitions.
            controller: Optional global controller for state.
            trigger_handler: Optional trigger handler for procedures.
        """
        self.state_machine = state_machine
        self.controller = controller
        self.trigger_handler = trigger_handler

        # Dungeon state
        self.dungeon_id: Optional[str] = None
        self.rooms: dict[str, DungeonRoom] = {}
        self.current_room_id: Optional[str] = None

        # Exploration state
        self.phase = DungeonPhase.IDLE
        self.turn_number = 0
        self.total_turns = 0

        # Party state (synced with controller if available)
        self.light_source: Optional[str] = None
        self.light_remaining: int = 0

        # Wandering monster tracking
        self.wandering_monster_timer: int = 0
        self.base_wandering_chance: int = 1  # X-in-6

        logger.info("DungeonEngine initialized")

    # =========================================================================
    # DUNGEON LIFECYCLE
    # =========================================================================

    def enter_dungeon(
        self,
        dungeon_id: str,
        entrance_room_id: str,
        rooms: Optional[dict[str, DungeonRoom]] = None
    ) -> DungeonStatus:
        """
        Enter a dungeon.

        Args:
            dungeon_id: ID of the dungeon.
            entrance_room_id: ID of the entrance room.
            rooms: Optional pre-loaded room data.

        Returns:
            Initial dungeon status.
        """
        self.dungeon_id = dungeon_id
        self.rooms = rooms or {}
        self.current_room_id = entrance_room_id
        self.phase = DungeonPhase.EXPLORING
        self.turn_number = 0
        self.total_turns = 0

        # Ensure entrance room exists
        if entrance_room_id not in self.rooms:
            self.rooms[entrance_room_id] = DungeonRoom(
                room_id=entrance_room_id,
                name="Dungeon Entrance",
                room_type=RoomType.ENTRANCE
            )

        # Mark entrance visited
        self.rooms[entrance_room_id].visit()

        # Sync with controller if available
        if self.controller:
            party = self.controller.get_party_state()
            self.light_source = party.light_source
            self.light_remaining = party.light_remaining

        logger.info(f"Entered dungeon {dungeon_id} at room {entrance_room_id}")

        return self.get_status()

    def exit_dungeon(self) -> dict[str, Any]:
        """
        Exit the dungeon.

        Returns:
            Summary of dungeon exploration.
        """
        summary = {
            "dungeon_id": self.dungeon_id,
            "turns_spent": self.total_turns,
            "rooms_visited": len([r for r in self.rooms.values() if r.visited]),
            "rooms_cleared": len([r for r in self.rooms.values() if r.cleared]),
        }

        self.phase = DungeonPhase.IDLE
        self.dungeon_id = None
        self.current_room_id = None

        logger.info(f"Exited dungeon after {summary['turns_spent']} turns")

        return summary

    # =========================================================================
    # TURN EXECUTION
    # =========================================================================

    def explore_turn(
        self,
        action: str,
        action_params: Optional[dict[str, Any]] = None
    ) -> TurnResult:
        """
        Execute one exploration turn (10 minutes).

        This is the core dungeon loop:
        1. Advance time
        2. Deplete light sources
        3. Resolve declared player action
        4. Check wandering monsters
        5. Apply noise & consequence flags
        6. Update dungeon state

        Args:
            action: The action to take ("move", "search", "listen", etc.)
            action_params: Parameters for the action.

        Returns:
            TurnResult with turn outcome.
        """
        if self.phase != DungeonPhase.EXPLORING:
            return TurnResult(
                turn_number=self.turn_number,
                action_taken="none",
                action_result={"error": "Not in exploration mode"}
            )

        action_params = action_params or {}
        self.turn_number += 1
        self.total_turns += 1

        # 1. Advance time
        time_spent = 1  # Standard turn
        if self.controller:
            self.controller.advance_time("turn", time_spent)

        # 2. Deplete light sources
        light_consumed, light_remaining = self._consume_light(time_spent)

        # 3. Resolve declared action
        action_result = self._resolve_action(action, action_params)

        # 4. Check wandering monsters
        wandering_check, wandering_roll, encounter_occurred = self._check_wandering_monsters()

        # 5. Apply noise
        current_room = self.rooms.get(self.current_room_id)
        noise_change = 0
        if current_room:
            if action in ("search", "open_door", "break_down", "combat"):
                noise_change = 1
                current_room.add_noise(1)
            else:
                current_room.decay_noise()
                noise_change = -1 if current_room.noise_level > 0 else 0

        # 6. Build result
        result = TurnResult(
            turn_number=self.turn_number,
            action_taken=action,
            action_result=action_result,
            time_spent=time_spent,
            light_consumed=light_consumed,
            light_remaining=light_remaining,
            wandering_monster_check=wandering_check,
            wandering_monster_roll=wandering_roll,
            encounter_occurred=encounter_occurred,
            noise_change=noise_change,
            discoveries=action_result.get("discoveries", [])
        )

        # Handle encounter transition
        if encounter_occurred and self.state_machine:
            try:
                from game_state.state_machine import TransitionTrigger
                self.state_machine.transition(TransitionTrigger.WANDERING_MONSTER)
                self.phase = DungeonPhase.ENCOUNTER
            except Exception as e:
                logger.warning(f"Could not transition to encounter: {e}")

        return result

    def _consume_light(self, turns: int) -> tuple[bool, int]:
        """
        Consume light source for turns passed.

        Returns:
            Tuple of (light_consumed, remaining_turns)
        """
        if self.light_source is None:
            return False, 0

        consumed = False
        old_remaining = self.light_remaining

        if self.light_source == "torch":
            self.light_remaining = max(0, self.light_remaining - turns)
            consumed = self.light_remaining < old_remaining

            if self.light_remaining <= 0:
                self.light_source = None

        elif self.light_source == "lantern":
            # Lantern uses oil more slowly (1 unit per 2 turns)
            if turns >= 2:
                self.light_remaining = max(0, self.light_remaining - 1)
                consumed = True

                if self.light_remaining <= 0:
                    self.light_source = None

        # Sync with controller
        if self.controller:
            party = self.controller.get_party_state()
            party.light_source = self.light_source
            party.light_remaining = self.light_remaining

        return consumed, self.light_remaining

    def _resolve_action(
        self,
        action: str,
        params: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve the player's declared action."""
        result = {"action": action, "success": False}

        if action == "move":
            result = self._action_move(params.get("direction", "north"))

        elif action == "search":
            result = self._action_search()

        elif action == "listen":
            result = self._action_listen()

        elif action == "open_door":
            result = self._action_open_door(params.get("direction", "north"))

        elif action == "examine":
            result = self._action_examine(params.get("target", "room"))

        elif action == "rest":
            result = self._action_rest()

        else:
            result["error"] = f"Unknown action: {action}"

        return result

    def _check_wandering_monsters(self) -> tuple[bool, int, bool]:
        """
        Check for wandering monsters.

        Returns:
            Tuple of (check_made, roll, encounter_occurred)
        """
        # Check every 2 turns
        self.wandering_monster_timer += 1
        if self.wandering_monster_timer < 2:
            return False, 0, False

        self.wandering_monster_timer = 0

        # Get noise modifier from current room
        current_room = self.rooms.get(self.current_room_id)
        noise_mod = current_room.noise_level if current_room else 0

        # Calculate chance
        chance = min(5, self.base_wandering_chance + noise_mod)

        # Roll
        roll = random.randint(1, 6)
        encounter = roll <= chance

        return True, roll, encounter

    # =========================================================================
    # ACTIONS
    # =========================================================================

    def _action_move(self, direction: str) -> dict[str, Any]:
        """Move to an adjacent room."""
        current_room = self.rooms.get(self.current_room_id)
        if not current_room:
            return {"success": False, "error": "No current room"}

        # Check for exit in that direction
        if direction not in current_room.exits:
            return {
                "success": False,
                "error": f"No exit to the {direction}",
                "visible_exits": list(current_room.exits.keys())
            }

        # Check for door
        if direction in current_room.doors:
            door_type = current_room.doors[direction]
            if door_type in (DoorType.LOCKED, DoorType.STUCK):
                return {
                    "success": False,
                    "error": f"The door to the {direction} is {door_type.value}",
                    "door_type": door_type.value
                }

        # Move to new room
        new_room_id = current_room.exits[direction]

        # Create room if it doesn't exist
        if new_room_id not in self.rooms:
            self.rooms[new_room_id] = DungeonRoom(
                room_id=new_room_id,
                name=f"Room {new_room_id}",
                room_type=RoomType.CHAMBER
            )

        # Update state
        old_room_id = self.current_room_id
        self.current_room_id = new_room_id
        new_room = self.rooms[new_room_id]

        first_visit = new_room.visit()

        return {
            "success": True,
            "moved_from": old_room_id,
            "moved_to": new_room_id,
            "first_visit": first_visit,
            "new_room_name": new_room.name,
        }

    def _action_search(self) -> dict[str, Any]:
        """Search the current room."""
        current_room = self.rooms.get(self.current_room_id)
        if not current_room:
            return {"success": False, "error": "No current room"}

        # Search skill check (2-in-6 base)
        search_skill = 2
        roll = random.randint(1, 6)
        success = roll <= search_skill

        discoveries = []

        if success:
            # Check for secret doors
            for direction, door_type in current_room.doors.items():
                if door_type == DoorType.SECRET:
                    discoveries.append(f"secret door to the {direction}")
                    current_room.doors[direction] = DoorType.CLOSED

            # Check for hidden treasure
            if current_room.treasure and not current_room.searched:
                discoveries.append("hidden items")

        current_room.searched = True

        return {
            "success": True,
            "search_roll": roll,
            "found_something": success,
            "discoveries": discoveries,
        }

    def _action_listen(self) -> dict[str, Any]:
        """Listen at current location."""
        # Listen skill check (2-in-6 base)
        listen_skill = 2
        roll = random.randint(1, 6)
        success = roll <= listen_skill

        sounds_heard = []

        if success:
            current_room = self.rooms.get(self.current_room_id)
            if current_room:
                # Check adjacent rooms for creatures
                for direction, room_id in current_room.exits.items():
                    if room_id in self.rooms:
                        adj_room = self.rooms[room_id]
                        if adj_room.creatures:
                            sounds_heard.append(f"sounds from the {direction}")

        return {
            "success": True,
            "listen_roll": roll,
            "heard_something": success and len(sounds_heard) > 0,
            "sounds": sounds_heard,
        }

    def _action_open_door(self, direction: str) -> dict[str, Any]:
        """Attempt to open a door."""
        current_room = self.rooms.get(self.current_room_id)
        if not current_room:
            return {"success": False, "error": "No current room"}

        if direction not in current_room.doors:
            return {"success": False, "error": f"No door to the {direction}"}

        door_type = current_room.doors[direction]

        if door_type == DoorType.OPEN:
            return {"success": True, "already_open": True}

        if door_type == DoorType.STUCK:
            # 2-in-6 to force open, modified by STR
            roll = random.randint(1, 6)
            if roll <= 2:
                current_room.doors[direction] = DoorType.OPEN
                return {"success": True, "forced_open": True, "roll": roll}
            else:
                return {"success": False, "stuck": True, "roll": roll}

        if door_type == DoorType.LOCKED:
            return {"success": False, "locked": True, "needs_key_or_pick": True}

        if door_type == DoorType.SECRET:
            return {"success": False, "error": "No door visible there"}

        if door_type == DoorType.TRAPPED:
            # Trap triggers!
            return {"success": False, "trap_triggered": True}

        # Normal closed door
        current_room.doors[direction] = DoorType.OPEN
        return {"success": True}

    def _action_examine(self, target: str) -> dict[str, Any]:
        """Examine something in the room."""
        current_room = self.rooms.get(self.current_room_id)
        if not current_room:
            return {"success": False, "error": "No current room"}

        if target == "room":
            return {
                "success": True,
                "description": current_room.description,
                "features": current_room.features,
                "visible_exits": list(current_room.exits.keys()),
            }

        # Check if target is a feature
        for feature in current_room.features:
            if target.lower() in feature.lower():
                return {
                    "success": True,
                    "target": target,
                    "feature": feature,
                }

        return {"success": False, "error": f"Cannot examine '{target}'"}

    def _action_rest(self) -> dict[str, Any]:
        """Rest in the current room."""
        self.phase = DungeonPhase.RESTING

        return {
            "success": True,
            "resting": True,
            "warning": "Resting in a dungeon is dangerous!"
        }

    # =========================================================================
    # ROOM MANAGEMENT
    # =========================================================================

    def add_room(self, room: DungeonRoom) -> None:
        """Add a room to the dungeon."""
        self.rooms[room.room_id] = room

    def get_room(self, room_id: str) -> Optional[DungeonRoom]:
        """Get a room by ID."""
        return self.rooms.get(room_id)

    def get_current_room(self) -> Optional[DungeonRoom]:
        """Get the current room."""
        return self.rooms.get(self.current_room_id) if self.current_room_id else None

    def connect_rooms(
        self,
        room1_id: str,
        direction1: str,
        room2_id: str,
        direction2: str,
        door_type: DoorType = DoorType.OPEN
    ) -> None:
        """
        Create a bidirectional connection between rooms.

        Args:
            room1_id: First room ID.
            direction1: Direction from room1 to room2.
            room2_id: Second room ID.
            direction2: Direction from room2 to room1.
            door_type: Type of door between them.
        """
        if room1_id in self.rooms:
            self.rooms[room1_id].exits[direction1] = room2_id
            if door_type != DoorType.OPEN:
                self.rooms[room1_id].doors[direction1] = door_type

        if room2_id in self.rooms:
            self.rooms[room2_id].exits[direction2] = room1_id
            if door_type != DoorType.OPEN:
                self.rooms[room2_id].doors[direction2] = door_type

    # =========================================================================
    # LIGHT MANAGEMENT
    # =========================================================================

    def set_light_source(self, source: str, duration: int) -> None:
        """Set the party's light source."""
        self.light_source = source
        self.light_remaining = duration

    def light_torch(self) -> bool:
        """
        Light a new torch.

        Returns:
            True if successful.
        """
        # Check if party has torches
        if self.controller:
            party = self.controller.get_party_state()
            if party.resources.get("torches", 0) <= 0:
                return False
            self.controller.consume_resource("torches", 1)

        self.light_source = "torch"
        self.light_remaining = 6  # 6 turns per torch

        return True

    def light_lantern(self) -> bool:
        """
        Light a lantern.

        Returns:
            True if successful.
        """
        # Check if party has lantern oil
        if self.controller:
            party = self.controller.get_party_state()
            if party.resources.get("lantern_oil", 0) <= 0:
                return False

        self.light_source = "lantern"
        self.light_remaining = 24  # 4 hours (24 turns)

        return True

    # =========================================================================
    # STATUS
    # =========================================================================

    def get_status(self) -> DungeonStatus:
        """Get current dungeon status."""
        current_room = self.get_current_room()

        warnings = []

        # Light warnings
        if self.light_source is None:
            warnings.append("No light source! Movement dangerous.")
        elif self.light_remaining <= 2:
            warnings.append(f"Light source nearly exhausted ({self.light_remaining} turns)")

        # Room warnings
        if current_room and current_room.noise_level >= 3:
            warnings.append("High noise level attracting attention!")

        return DungeonStatus(
            phase=self.phase,
            current_room_id=self.current_room_id or "unknown",
            current_room_name=current_room.name if current_room else "Unknown",
            turn_number=self.turn_number,
            time_elapsed=self.total_turns,
            light_source=self.light_source,
            light_remaining=self.light_remaining,
            party_conditions=[],
            room_searched=current_room.searched if current_room else False,
            room_cleared=current_room.cleared if current_room else False,
            visible_exits=list(current_room.exits.keys()) if current_room else [],
            noise_level=current_room.noise_level if current_room else 0,
            warnings=warnings
        )

    # =========================================================================
    # SERIALIZATION
    # =========================================================================

    def get_snapshot(self) -> dict[str, Any]:
        """Get complete snapshot for persistence."""
        return {
            "dungeon_id": self.dungeon_id,
            "current_room_id": self.current_room_id,
            "phase": self.phase.value,
            "turn_number": self.turn_number,
            "total_turns": self.total_turns,
            "light_source": self.light_source,
            "light_remaining": self.light_remaining,
            "rooms": {
                room_id: {
                    "room_id": room.room_id,
                    "name": room.name,
                    "room_type": room.room_type.value,
                    "visited": room.visited,
                    "searched": room.searched,
                    "cleared": room.cleared,
                    "noise_level": room.noise_level,
                    "exits": room.exits,
                    "doors": {k: v.value for k, v in room.doors.items()},
                }
                for room_id, room in self.rooms.items()
            }
        }

    def restore_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Restore from a snapshot."""
        self.dungeon_id = snapshot.get("dungeon_id")
        self.current_room_id = snapshot.get("current_room_id")
        self.phase = DungeonPhase(snapshot.get("phase", "idle"))
        self.turn_number = snapshot.get("turn_number", 0)
        self.total_turns = snapshot.get("total_turns", 0)
        self.light_source = snapshot.get("light_source")
        self.light_remaining = snapshot.get("light_remaining", 0)

        # Restore rooms
        self.rooms = {}
        for room_id, room_data in snapshot.get("rooms", {}).items():
            room = DungeonRoom(
                room_id=room_data["room_id"],
                name=room_data["name"],
                room_type=RoomType(room_data.get("room_type", "chamber")),
            )
            room.visited = room_data.get("visited", False)
            room.searched = room_data.get("searched", False)
            room.cleared = room_data.get("cleared", False)
            room.noise_level = room_data.get("noise_level", 0)
            room.exits = room_data.get("exits", {})
            room.doors = {
                k: DoorType(v) for k, v in room_data.get("doors", {}).items()
            }
            self.rooms[room_id] = room


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_dungeon_engine(
    state_machine: Optional["StateMachine"] = None,
    controller: Optional["GlobalController"] = None,
    trigger_handler: Optional["TriggerHandler"] = None
) -> DungeonEngine:
    """
    Create a new dungeon engine.

    Args:
        state_machine: Optional state machine.
        controller: Optional global controller.
        trigger_handler: Optional trigger handler.

    Returns:
        Configured DungeonEngine.
    """
    return DungeonEngine(
        state_machine=state_machine,
        controller=controller,
        trigger_handler=trigger_handler
    )
