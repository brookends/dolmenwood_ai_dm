"""
Dolmenwood AI DM - Game State Management Module (v2.0)

This module provides:
- SQLite-based persistence for game state
- Formal state machine with 8 mutually exclusive game states
- Global controller for cross-cutting concerns
- State transition detection and execution
"""

from .state_manager import GameStateManager, DatabaseError, create_manager
from .state_machine import (
    GameState,
    StateMachine,
    StateTransition,
    TransitionTrigger,
    InvalidTransitionError,
    VALID_TRANSITIONS,
)
from .global_controller import (
    GlobalController,
    GameTime,
    PartyResources,
    WorldFlags,
)
from .transition_detector import (
    StateTransitionDetector,
    TransitionEvent,
    ActionPattern,
    create_transition_detector,
    TOOL_TRIGGER_MAP,
)

__all__ = [
    # State Manager
    "GameStateManager",
    "DatabaseError",
    "create_manager",
    # State Machine
    "GameState",
    "StateMachine",
    "StateTransition",
    "TransitionTrigger",
    "InvalidTransitionError",
    "VALID_TRANSITIONS",
    # Global Controller
    "GlobalController",
    "GameTime",
    "PartyResources",
    "WorldFlags",
    # Transition Detector
    "StateTransitionDetector",
    "TransitionEvent",
    "ActionPattern",
    "create_transition_detector",
    "TOOL_TRIGGER_MAP",
]
