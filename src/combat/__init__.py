"""
Dolmenwood AI DM - Combat Engine Module

This module provides automated combat state management including
initiative tracking, turn order, HP management, and morale checks.
"""

from .combat_engine import (
    CombatEngine,
    Combatant,
    CombatStatus,
    AttackResult,
    TurnResult,
    CombatPhase,
    CombatEndReason,
    create_combatant_from_character,
    create_combatant_from_monster,
)

from .combat_tools import (
    COMBAT_TOOL_DEFINITIONS,
    CombatToolHandler,
    CombatToolResult,
    create_combat_handler,
)

__all__ = [
    # Engine
    "CombatEngine",
    "Combatant",
    "CombatStatus",
    "AttackResult",
    "TurnResult",
    "CombatPhase",
    "CombatEndReason",
    "create_combatant_from_character",
    "create_combatant_from_monster",
    # Tools
    "COMBAT_TOOL_DEFINITIONS",
    "CombatToolHandler",
    "CombatToolResult",
    "create_combat_handler",
]
