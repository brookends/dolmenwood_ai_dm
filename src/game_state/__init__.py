"""
Dolmenwood AI DM - Game State Management Module

This module provides SQLite-based persistence for game state.
"""

from .state_manager import GameStateManager, DatabaseError, create_manager

__all__ = ["GameStateManager", "DatabaseError", "create_manager"]
