"""
Dolmenwood AI DM - Formal State Machine (v2.0)

This module implements the canonical game state machine with mutually exclusive
primary states and validated transitions. Only ONE state can be active at a time.

The state machine ensures:
- All state transitions are valid and logged
- Previous states are tracked for return transitions
- Time advances with every transition
- World state is preserved across transitions

Author: AI Dungeon Master Project
Version: 2.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# PRIMARY GAME STATES
# =============================================================================

class GameState(str, Enum):
    """
    Mutually exclusive primary game states.

    Only ONE state can be active at any time. The state determines
    which procedural loop is executing and what actions are valid.
    """
    WILDERNESS_TRAVEL = "wilderness_travel"
    WILDERNESS_ENCOUNTER = "wilderness_encounter"
    DUNGEON_EXPLORATION = "dungeon_exploration"
    DUNGEON_ENCOUNTER = "dungeon_encounter"
    COMBAT = "combat"
    SETTLEMENT_EXPLORATION = "settlement_exploration"
    SOCIAL_INTERACTION = "social_interaction"
    DOWNTIME = "downtime"

    @property
    def is_exploration(self) -> bool:
        """Check if state is an exploration state."""
        return self in (
            GameState.WILDERNESS_TRAVEL,
            GameState.DUNGEON_EXPLORATION,
            GameState.SETTLEMENT_EXPLORATION
        )

    @property
    def is_encounter(self) -> bool:
        """Check if state is an encounter state."""
        return self in (
            GameState.WILDERNESS_ENCOUNTER,
            GameState.DUNGEON_ENCOUNTER
        )

    @property
    def is_dangerous(self) -> bool:
        """Check if state involves potential danger."""
        return self in (
            GameState.WILDERNESS_TRAVEL,
            GameState.WILDERNESS_ENCOUNTER,
            GameState.DUNGEON_EXPLORATION,
            GameState.DUNGEON_ENCOUNTER,
            GameState.COMBAT
        )


class TransitionTrigger(str, Enum):
    """
    Events that can trigger state transitions.

    Each trigger has specific source and target states.
    """
    # Wilderness Travel triggers
    ENCOUNTER_ROLL_SUCCESS = "encounter_roll_success"
    ENTER_DUNGEON = "enter_dungeon"
    ENTER_SETTLEMENT = "enter_settlement"

    # Encounter triggers
    REACTION_HOSTILE = "reaction_hostile"
    REACTION_PARLEY = "reaction_parley"
    ENCOUNTER_AVOIDED = "encounter_avoided"

    # Dungeon triggers
    WANDERING_MONSTER = "wandering_monster"

    # Combat triggers
    ENEMIES_DEFEATED = "enemies_defeated"
    ENEMIES_FLEE = "enemies_flee"
    PARTY_RETREAT = "party_retreat"

    # Settlement triggers
    CONVERSATION_START = "conversation_start"
    LEAVE_SETTLEMENT = "leave_settlement"

    # Social triggers
    SOCIAL_CONCLUDE = "social_conclude"
    SOCIAL_ESCALATE = "social_escalate"

    # Global triggers
    REST_INITIATED = "rest_initiated"
    DOWNTIME_END = "downtime_end"


# =============================================================================
# TRANSITION TABLE
# =============================================================================

# Define valid state transitions: (from_state, trigger) -> to_state
VALID_TRANSITIONS: dict[tuple[GameState, TransitionTrigger], GameState] = {
    # From WILDERNESS_TRAVEL
    (GameState.WILDERNESS_TRAVEL, TransitionTrigger.ENCOUNTER_ROLL_SUCCESS): GameState.WILDERNESS_ENCOUNTER,
    (GameState.WILDERNESS_TRAVEL, TransitionTrigger.ENTER_DUNGEON): GameState.DUNGEON_EXPLORATION,
    (GameState.WILDERNESS_TRAVEL, TransitionTrigger.ENTER_SETTLEMENT): GameState.SETTLEMENT_EXPLORATION,
    (GameState.WILDERNESS_TRAVEL, TransitionTrigger.REST_INITIATED): GameState.DOWNTIME,

    # From WILDERNESS_ENCOUNTER
    (GameState.WILDERNESS_ENCOUNTER, TransitionTrigger.REACTION_HOSTILE): GameState.COMBAT,
    (GameState.WILDERNESS_ENCOUNTER, TransitionTrigger.REACTION_PARLEY): GameState.SOCIAL_INTERACTION,
    (GameState.WILDERNESS_ENCOUNTER, TransitionTrigger.ENCOUNTER_AVOIDED): GameState.WILDERNESS_TRAVEL,

    # From DUNGEON_EXPLORATION
    (GameState.DUNGEON_EXPLORATION, TransitionTrigger.WANDERING_MONSTER): GameState.DUNGEON_ENCOUNTER,
    (GameState.DUNGEON_EXPLORATION, TransitionTrigger.LEAVE_SETTLEMENT): GameState.WILDERNESS_TRAVEL,  # Exit dungeon
    (GameState.DUNGEON_EXPLORATION, TransitionTrigger.REST_INITIATED): GameState.DOWNTIME,

    # From DUNGEON_ENCOUNTER
    (GameState.DUNGEON_ENCOUNTER, TransitionTrigger.REACTION_HOSTILE): GameState.COMBAT,
    (GameState.DUNGEON_ENCOUNTER, TransitionTrigger.REACTION_PARLEY): GameState.SOCIAL_INTERACTION,
    (GameState.DUNGEON_ENCOUNTER, TransitionTrigger.ENCOUNTER_AVOIDED): GameState.DUNGEON_EXPLORATION,

    # From COMBAT - returns to previous exploration state (handled specially)
    (GameState.COMBAT, TransitionTrigger.ENEMIES_DEFEATED): GameState.WILDERNESS_TRAVEL,  # Default, overridden by previous_state
    (GameState.COMBAT, TransitionTrigger.ENEMIES_FLEE): GameState.WILDERNESS_TRAVEL,
    (GameState.COMBAT, TransitionTrigger.PARTY_RETREAT): GameState.WILDERNESS_TRAVEL,

    # From SETTLEMENT_EXPLORATION
    (GameState.SETTLEMENT_EXPLORATION, TransitionTrigger.CONVERSATION_START): GameState.SOCIAL_INTERACTION,
    (GameState.SETTLEMENT_EXPLORATION, TransitionTrigger.LEAVE_SETTLEMENT): GameState.WILDERNESS_TRAVEL,
    (GameState.SETTLEMENT_EXPLORATION, TransitionTrigger.ENTER_DUNGEON): GameState.DUNGEON_EXPLORATION,  # Dungeon under settlement
    (GameState.SETTLEMENT_EXPLORATION, TransitionTrigger.REST_INITIATED): GameState.DOWNTIME,

    # From SOCIAL_INTERACTION - returns to calling state (handled specially)
    (GameState.SOCIAL_INTERACTION, TransitionTrigger.SOCIAL_CONCLUDE): GameState.WILDERNESS_TRAVEL,  # Default
    (GameState.SOCIAL_INTERACTION, TransitionTrigger.SOCIAL_ESCALATE): GameState.COMBAT,

    # From DOWNTIME
    (GameState.DOWNTIME, TransitionTrigger.DOWNTIME_END): GameState.WILDERNESS_TRAVEL,  # Default, overridden
}


# =============================================================================
# STATE TRANSITION DATA
# =============================================================================

@dataclass
class StateTransition:
    """
    Record of a state transition.

    Captures the complete context of when and why a state change occurred.
    """
    from_state: GameState
    to_state: GameState
    trigger: TransitionTrigger
    timestamp: datetime = field(default_factory=datetime.now)
    time_advanced: int = 0  # Turns or watches advanced
    context: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize transition to dict."""
        return {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "trigger": self.trigger.value,
            "timestamp": self.timestamp.isoformat(),
            "time_advanced": self.time_advanced,
            "context": self.context,
            "reason": self.reason,
        }


@dataclass
class StateMachineSnapshot:
    """
    Complete snapshot of state machine for persistence.
    """
    current_state: GameState
    previous_state: Optional[GameState]
    pre_combat_state: Optional[GameState]
    pre_social_state: Optional[GameState]
    history: list[StateTransition]

    def to_dict(self) -> dict[str, Any]:
        """Serialize snapshot to dict."""
        return {
            "current_state": self.current_state.value,
            "previous_state": self.previous_state.value if self.previous_state else None,
            "pre_combat_state": self.pre_combat_state.value if self.pre_combat_state else None,
            "pre_social_state": self.pre_social_state.value if self.pre_social_state else None,
            "history": [t.to_dict() for t in self.history[-50:]],  # Keep last 50
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StateMachineSnapshot":
        """Deserialize snapshot from dict."""
        return cls(
            current_state=GameState(data["current_state"]),
            previous_state=GameState(data["previous_state"]) if data.get("previous_state") else None,
            pre_combat_state=GameState(data["pre_combat_state"]) if data.get("pre_combat_state") else None,
            pre_social_state=GameState(data["pre_social_state"]) if data.get("pre_social_state") else None,
            history=[],  # History not restored for simplicity
        )


# =============================================================================
# STATE MACHINE
# =============================================================================

class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


class StateMachine:
    """
    Canonical game state machine.

    Ensures:
    - Only ONE state active at a time
    - All transitions are validated
    - Previous states tracked for return transitions
    - All transitions logged
    - State change events emitted

    Example:
        >>> machine = StateMachine()
        >>> machine.current_state
        GameState.WILDERNESS_TRAVEL
        >>>
        >>> # Encounter occurs
        >>> result = machine.transition(TransitionTrigger.ENCOUNTER_ROLL_SUCCESS)
        >>> machine.current_state
        GameState.WILDERNESS_ENCOUNTER
        >>>
        >>> # Combat starts
        >>> result = machine.transition(TransitionTrigger.REACTION_HOSTILE)
        >>> machine.current_state
        GameState.COMBAT
        >>>
        >>> # Combat ends - returns to previous exploration state
        >>> result = machine.transition(TransitionTrigger.ENEMIES_DEFEATED)
        >>> machine.current_state
        GameState.WILDERNESS_ENCOUNTER  # Not WILDERNESS_TRAVEL!
    """

    def __init__(
        self,
        initial_state: GameState = GameState.WILDERNESS_TRAVEL,
        on_transition: Optional[Callable[[StateTransition], None]] = None
    ):
        """
        Initialize state machine.

        Args:
            initial_state: Starting state.
            on_transition: Optional callback for state changes.
        """
        self._current_state = initial_state
        self._previous_state: Optional[GameState] = None

        # Track states for return transitions
        self._pre_combat_state: Optional[GameState] = None
        self._pre_social_state: Optional[GameState] = None

        # Transition history
        self._history: list[StateTransition] = []

        # Callback for state changes
        self._on_transition = on_transition

        logger.info(f"State machine initialized in state: {initial_state.value}")

    @property
    def current_state(self) -> GameState:
        """Get current game state."""
        return self._current_state

    @property
    def previous_state(self) -> Optional[GameState]:
        """Get previous game state."""
        return self._previous_state

    @property
    def is_in_combat(self) -> bool:
        """Check if currently in combat."""
        return self._current_state == GameState.COMBAT

    @property
    def is_in_exploration(self) -> bool:
        """Check if in an exploration state."""
        return self._current_state.is_exploration

    @property
    def is_in_encounter(self) -> bool:
        """Check if in an encounter state."""
        return self._current_state.is_encounter

    @property
    def history(self) -> list[StateTransition]:
        """Get transition history."""
        return self._history.copy()

    def can_transition(self, trigger: TransitionTrigger) -> bool:
        """
        Check if a transition is valid from current state.

        Args:
            trigger: The transition trigger to check.

        Returns:
            True if the transition is valid.
        """
        return (self._current_state, trigger) in VALID_TRANSITIONS

    def get_valid_triggers(self) -> list[TransitionTrigger]:
        """
        Get all valid triggers from current state.

        Returns:
            List of valid transition triggers.
        """
        return [
            trigger for (state, trigger) in VALID_TRANSITIONS.keys()
            if state == self._current_state
        ]

    def transition(
        self,
        trigger: TransitionTrigger,
        context: Optional[dict[str, Any]] = None,
        time_advanced: int = 0,
        reason: str = ""
    ) -> StateTransition:
        """
        Execute a state transition.

        Args:
            trigger: The event triggering the transition.
            context: Optional context data for the transition.
            time_advanced: Number of time units (turns/watches) advanced.
            reason: Human-readable reason for the transition.

        Returns:
            StateTransition record.

        Raises:
            InvalidTransitionError: If the transition is not valid.
        """
        context = context or {}

        # Validate transition
        key = (self._current_state, trigger)
        if key not in VALID_TRANSITIONS:
            valid = self.get_valid_triggers()
            raise InvalidTransitionError(
                f"Invalid transition: {self._current_state.value} + {trigger.value}. "
                f"Valid triggers: {[t.value for t in valid]}"
            )

        # Get base target state
        target_state = VALID_TRANSITIONS[key]

        # Handle return transitions for combat and social
        target_state = self._resolve_return_state(trigger, target_state)

        # Track pre-combat/social states
        self._track_return_state(trigger)

        # Create transition record
        transition = StateTransition(
            from_state=self._current_state,
            to_state=target_state,
            trigger=trigger,
            time_advanced=time_advanced,
            context=context,
            reason=reason
        )

        # Execute transition
        self._previous_state = self._current_state
        self._current_state = target_state
        self._history.append(transition)

        # Log transition
        logger.info(
            f"State transition: {transition.from_state.value} -> "
            f"{transition.to_state.value} (trigger: {trigger.value})"
        )

        # Fire callback
        if self._on_transition:
            self._on_transition(transition)

        return transition

    def _resolve_return_state(
        self,
        trigger: TransitionTrigger,
        default_state: GameState
    ) -> GameState:
        """
        Resolve the correct return state for combat/social exits.

        Combat and social states should return to the state they were
        entered from, not a default state.
        """
        # Combat exit - return to pre-combat state
        if self._current_state == GameState.COMBAT:
            if trigger in (
                TransitionTrigger.ENEMIES_DEFEATED,
                TransitionTrigger.ENEMIES_FLEE,
                TransitionTrigger.PARTY_RETREAT
            ):
                if self._pre_combat_state:
                    return self._pre_combat_state

        # Social exit - return to pre-social state
        if self._current_state == GameState.SOCIAL_INTERACTION:
            if trigger == TransitionTrigger.SOCIAL_CONCLUDE:
                if self._pre_social_state:
                    return self._pre_social_state

        return default_state

    def _track_return_state(self, trigger: TransitionTrigger) -> None:
        """
        Track states for return transitions.

        When entering combat or social, remember where we came from.
        """
        # Entering combat
        if trigger in (
            TransitionTrigger.REACTION_HOSTILE,
            TransitionTrigger.SOCIAL_ESCALATE
        ):
            self._pre_combat_state = self._current_state

        # Entering social
        if trigger in (
            TransitionTrigger.REACTION_PARLEY,
            TransitionTrigger.CONVERSATION_START
        ):
            self._pre_social_state = self._current_state

    def force_state(
        self,
        state: GameState,
        reason: str = "forced transition"
    ) -> None:
        """
        Force a state change without validation.

        Use sparingly - primarily for loading saved games or error recovery.

        Args:
            state: The state to force.
            reason: Reason for the forced transition.
        """
        logger.warning(f"Forcing state change to {state.value}: {reason}")

        transition = StateTransition(
            from_state=self._current_state,
            to_state=state,
            trigger=TransitionTrigger.DOWNTIME_END,  # Placeholder
            context={"forced": True},
            reason=reason
        )

        self._previous_state = self._current_state
        self._current_state = state
        self._history.append(transition)

    def get_snapshot(self) -> StateMachineSnapshot:
        """
        Get a complete snapshot for persistence.

        Returns:
            StateMachineSnapshot with current machine state.
        """
        return StateMachineSnapshot(
            current_state=self._current_state,
            previous_state=self._previous_state,
            pre_combat_state=self._pre_combat_state,
            pre_social_state=self._pre_social_state,
            history=self._history.copy()
        )

    def restore_snapshot(self, snapshot: StateMachineSnapshot) -> None:
        """
        Restore state machine from a snapshot.

        Args:
            snapshot: The snapshot to restore from.
        """
        self._current_state = snapshot.current_state
        self._previous_state = snapshot.previous_state
        self._pre_combat_state = snapshot.pre_combat_state
        self._pre_social_state = snapshot.pre_social_state
        self._history = snapshot.history.copy()

        logger.info(f"State machine restored to state: {self._current_state.value}")

    def get_state_info(self) -> dict[str, Any]:
        """
        Get human-readable state information.

        Returns:
            Dict with current state details.
        """
        return {
            "current_state": self._current_state.value,
            "previous_state": self._previous_state.value if self._previous_state else None,
            "is_combat": self.is_in_combat,
            "is_exploration": self.is_in_exploration,
            "is_encounter": self.is_in_encounter,
            "is_dangerous": self._current_state.is_dangerous,
            "valid_triggers": [t.value for t in self.get_valid_triggers()],
            "transition_count": len(self._history),
        }

    def __repr__(self) -> str:
        return f"StateMachine(state={self._current_state.value})"


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_state_machine(
    initial_state: GameState = GameState.WILDERNESS_TRAVEL,
    on_transition: Optional[Callable[[StateTransition], None]] = None
) -> StateMachine:
    """
    Create a new state machine.

    Args:
        initial_state: Starting state (default: WILDERNESS_TRAVEL).
        on_transition: Optional callback for state changes.

    Returns:
        Configured StateMachine instance.
    """
    return StateMachine(initial_state=initial_state, on_transition=on_transition)


def restore_state_machine(
    snapshot_dict: dict[str, Any],
    on_transition: Optional[Callable[[StateTransition], None]] = None
) -> StateMachine:
    """
    Restore a state machine from saved data.

    Args:
        snapshot_dict: Serialized snapshot data.
        on_transition: Optional callback for state changes.

    Returns:
        Restored StateMachine instance.
    """
    snapshot = StateMachineSnapshot.from_dict(snapshot_dict)
    machine = StateMachine(
        initial_state=snapshot.current_state,
        on_transition=on_transition
    )
    machine.restore_snapshot(snapshot)
    return machine
