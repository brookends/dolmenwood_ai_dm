"""
State Transition Detector for Dolmenwood AI DM v2.0

This module provides automatic detection of game state transitions based on:
- Tool calls from the LLM (e.g., initiate_combat → COMBAT state)
- Game events (e.g., encounter roll success → WILDERNESS_ENCOUNTER state)
- Player actions parsed from input
- Engine callbacks (e.g., wandering monster triggered)

The detector maps these events to TransitionTriggers and executes
the appropriate state machine transitions.

Author: AI Dungeon Master Project
Version: 2.0
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .state_machine import StateMachine, GameState, TransitionTrigger

from .state_machine import (
    GameState,
    StateMachine,
    TransitionTrigger,
    StateTransition,
    InvalidTransitionError,
    VALID_TRANSITIONS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# TOOL TO TRIGGER MAPPINGS
# =============================================================================

# Maps tool names to the transition triggers they should fire
TOOL_TRIGGER_MAP: dict[str, TransitionTrigger] = {
    # Combat initiation tools
    "initiate_combat": TransitionTrigger.REACTION_HOSTILE,
    "start_combat": TransitionTrigger.REACTION_HOSTILE,
    "attack": TransitionTrigger.REACTION_HOSTILE,
    "combat_attack": TransitionTrigger.REACTION_HOSTILE,

    # Combat resolution tools
    "end_combat": TransitionTrigger.ENEMIES_DEFEATED,
    "combat_victory": TransitionTrigger.ENEMIES_DEFEATED,
    "enemies_flee": TransitionTrigger.ENEMIES_FLEE,
    "party_retreat": TransitionTrigger.PARTY_RETREAT,
    "flee_combat": TransitionTrigger.PARTY_RETREAT,

    # Location transition tools
    "enter_dungeon": TransitionTrigger.ENTER_DUNGEON,
    "enter_cave": TransitionTrigger.ENTER_DUNGEON,
    "enter_ruins": TransitionTrigger.ENTER_DUNGEON,
    "descend": TransitionTrigger.ENTER_DUNGEON,
    "enter_settlement": TransitionTrigger.ENTER_SETTLEMENT,
    "enter_town": TransitionTrigger.ENTER_SETTLEMENT,
    "enter_village": TransitionTrigger.ENTER_SETTLEMENT,
    "arrive_at_settlement": TransitionTrigger.ENTER_SETTLEMENT,
    "leave_settlement": TransitionTrigger.LEAVE_SETTLEMENT,
    "exit_town": TransitionTrigger.LEAVE_SETTLEMENT,
    "depart": TransitionTrigger.LEAVE_SETTLEMENT,

    # Social interaction tools
    "talk_to_npc": TransitionTrigger.CONVERSATION_START,
    "speak_with": TransitionTrigger.CONVERSATION_START,
    "converse": TransitionTrigger.CONVERSATION_START,
    "negotiate": TransitionTrigger.REACTION_PARLEY,
    "parley": TransitionTrigger.REACTION_PARLEY,
    "end_conversation": TransitionTrigger.SOCIAL_CONCLUDE,

    # Rest and downtime tools
    "rest": TransitionTrigger.REST_INITIATED,
    "make_camp": TransitionTrigger.REST_INITIATED,
    "long_rest": TransitionTrigger.REST_INITIATED,
    "take_downtime": TransitionTrigger.REST_INITIATED,
    "end_rest": TransitionTrigger.DOWNTIME_END,
    "break_camp": TransitionTrigger.DOWNTIME_END,

    # Encounter tools
    "trigger_encounter": TransitionTrigger.ENCOUNTER_ROLL_SUCCESS,
    "random_encounter": TransitionTrigger.ENCOUNTER_ROLL_SUCCESS,
    "wandering_monster": TransitionTrigger.WANDERING_MONSTER,
    "avoid_encounter": TransitionTrigger.ENCOUNTER_AVOIDED,
    "evade": TransitionTrigger.ENCOUNTER_AVOIDED,
    "sneak_past": TransitionTrigger.ENCOUNTER_AVOIDED,
}

# Maps certain tool results to triggers (result-based transitions)
TOOL_RESULT_TRIGGER_MAP: dict[str, dict[str, TransitionTrigger]] = {
    "roll_reaction": {
        "hostile": TransitionTrigger.REACTION_HOSTILE,
        "attacks": TransitionTrigger.REACTION_HOSTILE,
        "friendly": TransitionTrigger.REACTION_PARLEY,
        "neutral": TransitionTrigger.REACTION_PARLEY,
    },
    "check_morale": {
        "flee": TransitionTrigger.ENEMIES_FLEE,
        "rout": TransitionTrigger.ENEMIES_FLEE,
        "retreat": TransitionTrigger.ENEMIES_FLEE,
    },
    "check_encounter": {
        "encounter": TransitionTrigger.ENCOUNTER_ROLL_SUCCESS,
        "monster": TransitionTrigger.ENCOUNTER_ROLL_SUCCESS,
    },
}


# =============================================================================
# ACTION PATTERN DETECTION
# =============================================================================

@dataclass
class ActionPattern:
    """Pattern for detecting player actions that trigger state changes."""
    pattern: re.Pattern
    trigger: TransitionTrigger
    required_state: Optional[GameState] = None  # Only match in this state
    priority: int = 0  # Higher priority patterns checked first


# Patterns for detecting player intent from natural language
ACTION_PATTERNS: list[ActionPattern] = [
    # Combat initiation patterns - from encounter states
    ActionPattern(
        pattern=re.compile(r"\b(attack|strike|hit|fight|charge|assault)\b", re.I),
        trigger=TransitionTrigger.REACTION_HOSTILE,
        required_state=GameState.WILDERNESS_ENCOUNTER,
        priority=10,
    ),
    ActionPattern(
        pattern=re.compile(r"\b(attack|strike|hit|fight|charge|assault)\b", re.I),
        trigger=TransitionTrigger.REACTION_HOSTILE,
        required_state=GameState.DUNGEON_ENCOUNTER,
        priority=10,
    ),
    # Combat initiation patterns - from exploration states (direct attack)
    ActionPattern(
        pattern=re.compile(r"\b(attack|strike|hit|fight|charge|assault)\b", re.I),
        trigger=TransitionTrigger.REACTION_HOSTILE,
        required_state=GameState.WILDERNESS_TRAVEL,
        priority=10,
    ),
    ActionPattern(
        pattern=re.compile(r"\b(attack|strike|hit|fight|charge|assault)\b", re.I),
        trigger=TransitionTrigger.REACTION_HOSTILE,
        required_state=GameState.DUNGEON_EXPLORATION,
        priority=10,
    ),
    ActionPattern(
        pattern=re.compile(r"\b(attack|strike|hit|fight|charge|assault)\b", re.I),
        trigger=TransitionTrigger.REACTION_HOSTILE,
        required_state=GameState.SETTLEMENT_EXPLORATION,
        priority=10,
    ),

    # Flee/avoid patterns
    ActionPattern(
        pattern=re.compile(r"\b(flee|run away|escape|retreat|hide|sneak past)\b", re.I),
        trigger=TransitionTrigger.ENCOUNTER_AVOIDED,
        required_state=GameState.WILDERNESS_ENCOUNTER,
        priority=8,
    ),
    ActionPattern(
        pattern=re.compile(r"\b(flee|run away|escape|retreat)\b", re.I),
        trigger=TransitionTrigger.PARTY_RETREAT,
        required_state=GameState.COMBAT,
        priority=8,
    ),

    # Parley patterns
    ActionPattern(
        pattern=re.compile(r"\b(talk|speak|negotiate|parley|greet|hail)\b", re.I),
        trigger=TransitionTrigger.REACTION_PARLEY,
        required_state=GameState.WILDERNESS_ENCOUNTER,
        priority=5,
    ),
    ActionPattern(
        pattern=re.compile(r"\b(talk|speak|negotiate|parley|greet|hail)\b", re.I),
        trigger=TransitionTrigger.REACTION_PARLEY,
        required_state=GameState.DUNGEON_ENCOUNTER,
        priority=5,
    ),

    # Location transition patterns
    ActionPattern(
        pattern=re.compile(r"\b(enter|go into|walk into|step into)\s+(the\s+)?(cave|dungeon|ruins|tomb|crypt|mine|tower|castle)\b", re.I),
        trigger=TransitionTrigger.ENTER_DUNGEON,
        required_state=GameState.WILDERNESS_TRAVEL,
        priority=10,
    ),
    ActionPattern(
        pattern=re.compile(r"\b(enter|go into|arrive at|reach)\s+(the\s+)?(town|village|city|settlement|hamlet|inn|tavern)\b", re.I),
        trigger=TransitionTrigger.ENTER_SETTLEMENT,
        required_state=GameState.WILDERNESS_TRAVEL,
        priority=10,
    ),
    ActionPattern(
        pattern=re.compile(r"\b(leave|exit|depart|head out|set out)\b", re.I),
        trigger=TransitionTrigger.LEAVE_SETTLEMENT,
        required_state=GameState.SETTLEMENT_EXPLORATION,
        priority=8,
    ),

    # Rest patterns
    ActionPattern(
        pattern=re.compile(r"\b(rest|make camp|set up camp|sleep|take a break)\b", re.I),
        trigger=TransitionTrigger.REST_INITIATED,
        priority=3,
    ),

    # Social patterns in settlement
    ActionPattern(
        pattern=re.compile(r"\b(talk to|speak with|ask|approach|greet)\s+(the\s+)?(\w+)\b", re.I),
        trigger=TransitionTrigger.CONVERSATION_START,
        required_state=GameState.SETTLEMENT_EXPLORATION,
        priority=5,
    ),
]


# =============================================================================
# TRANSITION DETECTOR
# =============================================================================

@dataclass
class TransitionEvent:
    """Record of a detected transition event."""
    trigger: TransitionTrigger
    source: str  # "tool", "action", "event", "engine"
    details: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0  # 0.0-1.0, how confident we are this should fire


class StateTransitionDetector:
    """
    Detects and executes state transitions based on game events.

    The detector monitors:
    - Tool calls from the LLM
    - Player action text
    - Engine callbacks
    - Game events

    And automatically triggers appropriate state machine transitions.

    Example:
        >>> detector = StateTransitionDetector(state_machine)
        >>>
        >>> # Detect from tool call
        >>> event = detector.detect_from_tool("initiate_combat", {})
        >>> if event:
        ...     detector.execute_transition(event)
        >>>
        >>> # Detect from player action
        >>> events = detector.detect_from_action("I attack the goblin")
        >>> for event in events:
        ...     if detector.can_transition(event.trigger):
        ...         detector.execute_transition(event)
    """

    def __init__(
        self,
        state_machine: StateMachine,
        auto_execute: bool = False,
    ):
        """
        Initialize the transition detector.

        Args:
            state_machine: The game state machine to control.
            auto_execute: If True, automatically execute valid transitions.
        """
        self.state_machine = state_machine
        self.auto_execute = auto_execute
        self._pending_events: list[TransitionEvent] = []
        self._transition_callbacks: list[Callable[[StateTransition], None]] = []

        logger.info("StateTransitionDetector initialized")

    def add_transition_callback(self, callback: Callable[[StateTransition], None]) -> None:
        """Add a callback to be called after each transition."""
        self._transition_callbacks.append(callback)

    # =========================================================================
    # DETECTION METHODS
    # =========================================================================

    def detect_from_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: Optional[str] = None,
    ) -> Optional[TransitionEvent]:
        """
        Detect transition trigger from a tool call.

        Args:
            tool_name: Name of the tool that was called.
            tool_args: Arguments passed to the tool.
            tool_result: Optional result string from the tool.

        Returns:
            TransitionEvent if a trigger was detected, None otherwise.
        """
        # Check direct tool mapping
        if tool_name in TOOL_TRIGGER_MAP:
            trigger = TOOL_TRIGGER_MAP[tool_name]

            # Verify this transition is valid from current state
            if self.can_transition(trigger):
                event = TransitionEvent(
                    trigger=trigger,
                    source="tool",
                    details={"tool_name": tool_name, "args": tool_args},
                    confidence=1.0,
                )
                logger.debug(f"Detected transition from tool '{tool_name}': {trigger.value}")
                return event

        # Check result-based mapping
        if tool_result and tool_name in TOOL_RESULT_TRIGGER_MAP:
            result_lower = tool_result.lower()
            for keyword, trigger in TOOL_RESULT_TRIGGER_MAP[tool_name].items():
                if keyword in result_lower:
                    if self.can_transition(trigger):
                        event = TransitionEvent(
                            trigger=trigger,
                            source="tool_result",
                            details={
                                "tool_name": tool_name,
                                "result": tool_result,
                                "matched_keyword": keyword,
                            },
                            confidence=0.9,
                        )
                        logger.debug(
                            f"Detected transition from tool result '{tool_name}': "
                            f"{trigger.value} (matched '{keyword}')"
                        )
                        return event

        return None

    def detect_from_action(
        self,
        player_input: str,
    ) -> list[TransitionEvent]:
        """
        Detect transition triggers from player action text.

        Args:
            player_input: The player's input text.

        Returns:
            List of potential TransitionEvents (may be empty).
        """
        events = []
        current_state = self.state_machine.current_state

        # Sort patterns by priority (highest first)
        sorted_patterns = sorted(ACTION_PATTERNS, key=lambda p: -p.priority)

        for pattern in sorted_patterns:
            # Check state requirement
            if pattern.required_state and pattern.required_state != current_state:
                continue

            # Check pattern match
            if pattern.pattern.search(player_input):
                if self.can_transition(pattern.trigger):
                    event = TransitionEvent(
                        trigger=pattern.trigger,
                        source="action",
                        details={
                            "input": player_input,
                            "pattern": pattern.pattern.pattern,
                        },
                        confidence=0.7,  # Action detection is less certain
                    )
                    events.append(event)
                    logger.debug(
                        f"Detected potential transition from action: "
                        f"{pattern.trigger.value} (pattern: {pattern.pattern.pattern})"
                    )

        return events

    def detect_from_event(
        self,
        event_type: str,
        event_data: dict[str, Any],
    ) -> Optional[TransitionEvent]:
        """
        Detect transition from a game event.

        Args:
            event_type: Type of game event (e.g., "encounter_triggered", "combat_end")
            event_data: Data associated with the event.

        Returns:
            TransitionEvent if detected, None otherwise.
        """
        # Map event types to triggers
        event_trigger_map = {
            "encounter_triggered": TransitionTrigger.ENCOUNTER_ROLL_SUCCESS,
            "encounter_rolled": TransitionTrigger.ENCOUNTER_ROLL_SUCCESS,
            "wandering_monster": TransitionTrigger.WANDERING_MONSTER,
            "combat_victory": TransitionTrigger.ENEMIES_DEFEATED,
            "combat_end_victory": TransitionTrigger.ENEMIES_DEFEATED,
            "enemies_routed": TransitionTrigger.ENEMIES_FLEE,
            "party_fled": TransitionTrigger.PARTY_RETREAT,
            "rest_started": TransitionTrigger.REST_INITIATED,
            "rest_complete": TransitionTrigger.DOWNTIME_END,
            "conversation_started": TransitionTrigger.CONVERSATION_START,
            "conversation_ended": TransitionTrigger.SOCIAL_CONCLUDE,
            "location_enter_dungeon": TransitionTrigger.ENTER_DUNGEON,
            "location_enter_settlement": TransitionTrigger.ENTER_SETTLEMENT,
            "location_leave_settlement": TransitionTrigger.LEAVE_SETTLEMENT,
        }

        if event_type in event_trigger_map:
            trigger = event_trigger_map[event_type]
            if self.can_transition(trigger):
                event = TransitionEvent(
                    trigger=trigger,
                    source="event",
                    details={"event_type": event_type, "data": event_data},
                    confidence=1.0,
                )
                logger.debug(f"Detected transition from event '{event_type}': {trigger.value}")
                return event

        return None

    # =========================================================================
    # TRANSITION EXECUTION
    # =========================================================================

    def can_transition(self, trigger: TransitionTrigger) -> bool:
        """Check if a transition is valid from the current state."""
        return self.state_machine.can_transition(trigger)

    def execute_transition(
        self,
        event: TransitionEvent,
        reason: str = "",
    ) -> Optional[StateTransition]:
        """
        Execute a state transition.

        Args:
            event: The transition event to execute.
            reason: Optional human-readable reason for the transition.

        Returns:
            StateTransition record if successful, None if transition invalid.
        """
        if not self.can_transition(event.trigger):
            logger.warning(
                f"Cannot execute transition {event.trigger.value} from state "
                f"{self.state_machine.current_state.value}"
            )
            return None

        try:
            transition = self.state_machine.transition(
                trigger=event.trigger,
                context=event.details,
                reason=reason or f"Triggered by {event.source}: {event.trigger.value}",
            )

            # Call transition callbacks
            for callback in self._transition_callbacks:
                try:
                    callback(transition)
                except Exception as e:
                    logger.error(f"Transition callback error: {e}")

            logger.info(
                f"State transition executed: {transition.from_state.value} -> "
                f"{transition.to_state.value} (trigger: {event.trigger.value})"
            )

            return transition

        except InvalidTransitionError as e:
            logger.error(f"Invalid transition: {e}")
            return None

    def process_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: Optional[str] = None,
    ) -> Optional[StateTransition]:
        """
        Process a tool call and execute any resulting state transition.

        This is a convenience method that combines detection and execution.

        Args:
            tool_name: Name of the tool called.
            tool_args: Arguments to the tool.
            tool_result: Optional result from the tool.

        Returns:
            StateTransition if one was executed, None otherwise.
        """
        event = self.detect_from_tool(tool_name, tool_args, tool_result)
        if event:
            return self.execute_transition(event)
        return None

    def process_player_action(
        self,
        player_input: str,
        require_high_confidence: bool = True,
    ) -> Optional[StateTransition]:
        """
        Process player input and execute any resulting state transition.

        Args:
            player_input: The player's action text.
            require_high_confidence: Only execute if confidence >= 0.8.

        Returns:
            StateTransition if one was executed, None otherwise.
        """
        events = self.detect_from_action(player_input)

        if not events:
            return None

        # Get highest confidence event
        best_event = max(events, key=lambda e: e.confidence)

        if require_high_confidence and best_event.confidence < 0.8:
            logger.debug(
                f"Action transition not executed (confidence {best_event.confidence:.2f} < 0.8): "
                f"{best_event.trigger.value}"
            )
            return None

        return self.execute_transition(best_event)

    def process_game_event(
        self,
        event_type: str,
        event_data: dict[str, Any],
    ) -> Optional[StateTransition]:
        """
        Process a game event and execute any resulting state transition.

        Args:
            event_type: Type of game event.
            event_data: Event data.

        Returns:
            StateTransition if one was executed, None otherwise.
        """
        event = self.detect_from_event(event_type, event_data)
        if event:
            return self.execute_transition(event)
        return None

    # =========================================================================
    # STATE QUERIES
    # =========================================================================

    @property
    def current_state(self) -> GameState:
        """Get the current game state."""
        return self.state_machine.current_state

    @property
    def valid_triggers(self) -> list[TransitionTrigger]:
        """Get all valid triggers from the current state."""
        return self.state_machine.get_valid_triggers()

    def get_state_info(self) -> dict[str, Any]:
        """Get information about the current state and valid transitions."""
        current = self.current_state
        valid = self.valid_triggers

        return {
            "current_state": current.value,
            "valid_triggers": [t.value for t in valid],
            "possible_next_states": [
                VALID_TRANSITIONS.get((current, t), current).value
                for t in valid
            ],
        }


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_transition_detector(
    state_machine: StateMachine,
    auto_execute: bool = False,
) -> StateTransitionDetector:
    """
    Create a configured StateTransitionDetector.

    Args:
        state_machine: The state machine to control.
        auto_execute: Whether to auto-execute transitions.

    Returns:
        Configured StateTransitionDetector instance.
    """
    return StateTransitionDetector(
        state_machine=state_machine,
        auto_execute=auto_execute,
    )
