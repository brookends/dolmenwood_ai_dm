"""
Dolmenwood AI DM - AI Agent Module (v2.0)

This module provides the AI Dungeon Master agent powered by Claude,
including tool definitions, dice rolling, and game mechanics.

v2.0 adds prompt schemas and authority boundaries for LLM integration.
"""

from .dm_agent import (
    DolmenwoodDM,
    DMResponse,
    DMConfig,
    ToolResult,
    create_dm,
)

from .prompt_schemas import (
    LLMAuthority,
    PromptCategory,
    PromptContext,
    LLMResponse,
    PromptBuilder,
    ResponseParser,
    NPCAction,
    CombatNarration,
    EncounterNarration,
    ExplorationNarration,
    create_prompt_builder,
    create_response_parser,
    get_authority_rules,
    AUTHORITY_RULES,
    PROMPT_TEMPLATES,
)

__all__ = [
    # DM Agent
    "DolmenwoodDM",
    "DMResponse",
    "DMConfig",
    "ToolResult",
    "create_dm",
    # Prompt Schemas (v2.0)
    "LLMAuthority",
    "PromptCategory",
    "PromptContext",
    "LLMResponse",
    "PromptBuilder",
    "ResponseParser",
    "NPCAction",
    "CombatNarration",
    "EncounterNarration",
    "ExplorationNarration",
    "create_prompt_builder",
    "create_response_parser",
    "get_authority_rules",
    "AUTHORITY_RULES",
    "PROMPT_TEMPLATES",
]
