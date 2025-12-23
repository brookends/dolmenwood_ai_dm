"""
Game Orchestration module for Dolmenwood AI DM v2.0

The orchestrator is the central coordinator that routes parsed player
actions to the appropriate game engines and returns structured results
for the narrator.
"""

from .game_orchestrator import (
    GameOrchestrator,
    OrchestratorResult,
    MechanicalResult,
    DiceRollResult,
    ResultType,
    create_game_orchestrator,
)

__all__ = [
    "GameOrchestrator",
    "OrchestratorResult",
    "MechanicalResult",
    "DiceRollResult",
    "ResultType",
    "create_game_orchestrator",
]
