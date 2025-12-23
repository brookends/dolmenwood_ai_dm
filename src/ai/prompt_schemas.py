"""
Dolmenwood AI DM - LLM Prompt Schemas and Authority Boundaries (v2.0)

This module defines the contract between the game engine and the LLM:
- What the LLM CAN decide (narrative, NPC behavior, descriptions)
- What the LLM CANNOT decide (mechanical outcomes, dice rolls)
- Prompt templates for each game state
- Output schemas for structured LLM responses

The LLM serves as ADVISORY ONLY - all mechanical outcomes are determined
by the game engine through dice rolls and rule application.

Author: AI Dungeon Master Project
Version: 2.0
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Dict, List, Callable
import json


class LLMAuthority(str, Enum):
    """Defines what the LLM has authority over."""
    # Full authority - LLM decides
    NARRATIVE = "narrative"           # Scene descriptions, atmosphere
    NPC_DIALOGUE = "npc_dialogue"     # What NPCs say
    NPC_PERSONALITY = "npc_personality"  # NPC quirks, mannerisms
    DESCRIPTIONS = "descriptions"     # Item, location, creature descriptions
    WORLD_FLAVOR = "world_flavor"     # Dolmenwood lore and flavor

    # Partial authority - LLM suggests, engine validates
    NPC_INTENT = "npc_intent"         # What NPCs want to do (engine resolves)
    COMBAT_TACTICS = "combat_tactics"  # NPC combat decisions (engine resolves)
    REACTION_FLAVOR = "reaction_flavor"  # Flavor for reaction roll results

    # No authority - Engine decides, LLM narrates
    DICE_ROLLS = "dice_rolls"         # All random outcomes
    DAMAGE_AMOUNTS = "damage_amounts"  # Combat damage
    HIT_OR_MISS = "hit_or_miss"       # Attack results
    SAVE_SUCCESS = "save_success"     # Saving throw results
    MORALE_RESULTS = "morale_results"  # Morale check outcomes
    ENCOUNTER_TYPE = "encounter_type"  # What is encountered
    TREASURE_AMOUNTS = "treasure_amounts"  # Loot amounts
    SPELL_EFFECTS = "spell_effects"   # Mechanical spell results


class PromptCategory(str, Enum):
    """Categories of prompts for different game states."""
    WILDERNESS_TRAVEL = "wilderness_travel"
    WILDERNESS_ENCOUNTER = "wilderness_encounter"
    DUNGEON_EXPLORATION = "dungeon_exploration"
    DUNGEON_ENCOUNTER = "dungeon_encounter"
    COMBAT = "combat"
    SETTLEMENT = "settlement"
    SOCIAL_INTERACTION = "social_interaction"
    DOWNTIME = "downtime"


@dataclass
class PromptContext:
    """Context passed to LLM for a prompt."""
    category: PromptCategory
    game_state: Dict[str, Any]  # Current game state snapshot
    recent_events: List[str]    # Recent events for context
    mechanical_results: Dict[str, Any]  # Dice results, outcomes
    player_action: Optional[str] = None  # What the player said/did
    npc_context: Optional[Dict[str, Any]] = None  # NPC info if relevant
    location_context: Optional[Dict[str, Any]] = None  # Location info


@dataclass
class LLMResponse:
    """Structured response from LLM."""
    narrative: str              # Main narrative text
    npc_actions: List[Dict[str, str]] = field(default_factory=list)
    suggested_options: List[str] = field(default_factory=list)
    atmosphere_notes: List[str] = field(default_factory=list)
    requires_player_input: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# AUTHORITY RULES
# =============================================================================

# Clear rules about what LLM can and cannot do
AUTHORITY_RULES = {
    "LLM_CAN": [
        "Describe scenes, atmosphere, and sensory details",
        "Voice NPCs with personality and dialogue",
        "Suggest what NPCs might want to do",
        "Provide Dolmenwood lore and flavor",
        "Describe the effects of mechanical results narratively",
        "Create dramatic tension and pacing",
        "Ask clarifying questions about player intent",
        "Suggest possible player options",
    ],
    "LLM_CANNOT": [
        "Determine success or failure of any action",
        "Decide damage amounts or healing",
        "Determine what is encountered (use provided encounter)",
        "Override morale check results",
        "Change reaction roll outcomes",
        "Modify treasure amounts",
        "Adjudicate rule disputes",
        "Grant or remove mechanical benefits",
        "Skip required procedure triggers",
        "Ignore time or resource tracking",
    ],
    "ENGINE_PROVIDES": [
        "All dice roll results",
        "Hit/miss determination",
        "Damage calculations",
        "Encounter type and details",
        "Morale check outcomes",
        "Reaction roll results",
        "Time advancement",
        "Resource consumption",
        "XP awards",
        "State transitions",
    ],
}


# =============================================================================
# PROMPT TEMPLATES
# =============================================================================

SYSTEM_PROMPT_BASE = """You are the Dungeon Master for a Dolmenwood campaign using
Old-School Essentials rules. You are responsible for narration, NPC voices, and
atmosphere. The game engine handles all mechanical resolution.

CRITICAL RULES:
1. NEVER determine success/failure - use the provided mechanical results
2. NEVER roll dice or generate random numbers - use provided rolls
3. NEVER skip or modify resource tracking - use provided values
4. ALWAYS respect morale and reaction results from the engine
5. ALWAYS use the exact damage/healing amounts provided

YOUR ROLE:
- Describe scenes vividly using Dolmenwood's fairy-tale horror atmosphere
- Voice NPCs with distinct personalities
- Create tension and drama around mechanical results
- Ask players what they want to do
- Suggest (don't decide) NPC actions

DOLMENWOOD TONE:
- Mysterious, eerie, and whimsical
- Folk horror meets fairy tale
- Ancient secrets lurk in every shadow
- The Fair Folk are real and dangerous
- Nature is wild and unpredictable
"""

PROMPT_TEMPLATES = {
    PromptCategory.WILDERNESS_TRAVEL: """
CURRENT STATE: Wilderness Travel
Location: {location}
Time: Day {day}, {time_of_day}
Weather: {weather}

MECHANICAL RESULTS:
{mechanical_results}

PARTY STATUS:
{party_status}

RECENT EVENTS:
{recent_events}

Describe the party's travel through Dolmenwood. Include:
- Atmospheric descriptions of the terrain
- Signs of fairy influence if appropriate
- Any notable landmarks or curiosities
- The changing light and weather

End by asking what the party wants to do for the next watch.
""",

    PromptCategory.WILDERNESS_ENCOUNTER: """
CURRENT STATE: Wilderness Encounter
Location: {location}
Encounter: {encounter_type}
Distance: {distance} yards
Surprise: {surprise_status}

REACTION ROLL RESULT: {reaction_result}

CREATURE DETAILS:
{creature_details}

Narrate the encounter based on the reaction result:
- Describe the creatures and their initial disposition
- Voice any intelligent creatures appropriately
- Create tension based on the reaction
- Present options to the party

Remember: The reaction result is FINAL - narrate to match it.
""",

    PromptCategory.DUNGEON_EXPLORATION: """
CURRENT STATE: Dungeon Exploration
Dungeon: {dungeon_name}
Current Room: {room_description}
Turn: {turn_number}
Light: {light_status}

MECHANICAL RESULTS:
{mechanical_results}

PARTY STATUS:
{party_status}

Describe the dungeon environment. Include:
- Sensory details (sounds, smells, textures)
- Visible exits and features
- Any creatures or objects present
- The oppressive atmosphere

Ask what the party wants to do.
""",

    PromptCategory.DUNGEON_ENCOUNTER: """
CURRENT STATE: Dungeon Encounter
Location: {room_description}
Encounter: {encounter_type}
Distance: {distance} feet
Surprise: {surprise_status}

REACTION ROLL RESULT: {reaction_result}

CREATURE DETAILS:
{creature_details}

Narrate this dungeon encounter using the reaction result.
Create appropriate tension for the underground environment.
""",

    PromptCategory.COMBAT: """
CURRENT STATE: Combat
Round: {round_number}
Current Turn: {current_combatant}

COMBAT STATUS:
Party: {party_status}
Enemies: {enemy_status}
Initiative Order: {initiative_order}

LAST ACTION RESULTS:
{last_action_results}

Narrate the combat action that just occurred. Use the exact results provided.
If it's a player's turn, ask what they want to do.
If it's an NPC's turn, suggest their likely action based on tactics and morale.

Available actions: Attack, Cast Spell, Use Item, Move, Defend, Flee
""",

    PromptCategory.SETTLEMENT: """
CURRENT STATE: Settlement Exploration
Settlement: {settlement_name}
Mood: {settlement_mood}
Reputation: {party_reputation}

AVAILABLE SERVICES:
{available_services}

CURRENT LOCATION:
{current_location}

Describe the settlement scene. Include:
- Local color and atmosphere
- Notable NPCs present
- Current activity and mood
- Rumors and hooks (if gathered)

Ask what the party wants to do.
""",

    PromptCategory.SOCIAL_INTERACTION: """
CURRENT STATE: Social Interaction
NPC: {npc_name}
NPC Disposition: {npc_disposition}
Topic: {interaction_topic}

NPC DETAILS:
{npc_details}

REACTION ROLL RESULT: {reaction_result}

Voice this NPC based on their disposition and the reaction result.
The NPC's general attitude is determined by the reaction - narrate accordingly.
""",

    PromptCategory.DOWNTIME: """
CURRENT STATE: Downtime
Location: {location}
Day: {day_number}
Activity: {current_activity}

ACTIVITY RESULTS:
{activity_results}

PROGRESS:
{progress_summary}

Describe the results of this downtime activity.
Provide flavor for training, research, or other activities.
""",
}


# =============================================================================
# OUTPUT SCHEMAS
# =============================================================================

@dataclass
class NPCAction:
    """Suggested NPC action for engine to resolve."""
    npc_name: str
    action_type: str  # "attack", "cast", "move", "flee", "other"
    target: Optional[str] = None
    details: str = ""


@dataclass
class CombatNarration:
    """Structured combat narration output."""
    action_description: str  # Narrative of the action
    hit_description: Optional[str] = None  # If hit, description of impact
    miss_description: Optional[str] = None  # If miss, description of near-miss
    death_description: Optional[str] = None  # If target killed
    morale_description: Optional[str] = None  # If morale triggered
    suggested_next_action: Optional[NPCAction] = None  # For NPC turns


@dataclass
class EncounterNarration:
    """Structured encounter narration output."""
    initial_description: str  # First sighting
    creature_appearance: str  # What they look like
    creature_behavior: str    # How they act (based on reaction)
    dialogue: Optional[str] = None  # If creatures speak
    options_for_party: List[str] = field(default_factory=list)


@dataclass
class ExplorationNarration:
    """Structured exploration narration output."""
    room_description: str     # What the party sees
    sensory_details: str      # Sounds, smells, feelings
    notable_features: List[str] = field(default_factory=list)
    hints_and_clues: List[str] = field(default_factory=list)
    atmosphere_notes: str = ""


# =============================================================================
# PROMPT BUILDER
# =============================================================================

class PromptBuilder:
    """
    Builds prompts for the LLM based on game state.

    Ensures all mechanical results are clearly communicated
    and authority boundaries are maintained.
    """

    def __init__(self):
        self.system_prompt = SYSTEM_PROMPT_BASE
        self.templates = PROMPT_TEMPLATES

    def build_prompt(
        self,
        context: PromptContext,
    ) -> Dict[str, str]:
        """
        Build a prompt for the LLM.

        Args:
            context: PromptContext with all relevant information

        Returns:
            Dict with 'system' and 'user' prompt components
        """
        template = self.templates.get(context.category, "")

        # Format the template with context
        user_prompt = self._format_template(template, context)

        return {
            "system": self.system_prompt,
            "user": user_prompt,
        }

    def _format_template(
        self,
        template: str,
        context: PromptContext,
    ) -> str:
        """Format a template with context values."""
        # Build format dict from context
        format_dict = {}

        # Add game state values
        for key, value in context.game_state.items():
            format_dict[key] = self._format_value(value)

        # Add mechanical results
        format_dict["mechanical_results"] = self._format_mechanical_results(
            context.mechanical_results
        )

        # Add recent events
        format_dict["recent_events"] = "\n".join(
            f"- {event}" for event in context.recent_events
        )

        # Add player action if present
        if context.player_action:
            format_dict["player_action"] = context.player_action

        # Add NPC context if present
        if context.npc_context:
            format_dict.update({
                f"npc_{k}": self._format_value(v)
                for k, v in context.npc_context.items()
            })

        # Add location context if present
        if context.location_context:
            format_dict.update({
                f"location_{k}": self._format_value(v)
                for k, v in context.location_context.items()
            })

        # Format template, leaving unfilled placeholders as-is
        try:
            return template.format_map(SafeDict(format_dict))
        except KeyError:
            return template

    def _format_value(self, value: Any) -> str:
        """Format a value for template insertion."""
        if isinstance(value, list):
            return "\n".join(f"- {item}" for item in value)
        elif isinstance(value, dict):
            return "\n".join(f"  {k}: {v}" for k, v in value.items())
        else:
            return str(value)

    def _format_mechanical_results(
        self,
        results: Dict[str, Any],
    ) -> str:
        """Format mechanical results clearly for the LLM."""
        if not results:
            return "No mechanical actions this turn."

        lines = ["MECHANICAL RESULTS (USE THESE EXACTLY):"]
        for key, value in results.items():
            if isinstance(value, dict):
                lines.append(f"  {key}:")
                for k, v in value.items():
                    lines.append(f"    {k}: {v}")
            else:
                lines.append(f"  {key}: {value}")

        return "\n".join(lines)

    def build_combat_prompt(
        self,
        round_number: int,
        current_combatant: str,
        is_player_turn: bool,
        party_status: List[str],
        enemy_status: List[str],
        last_action: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """Build a combat-specific prompt."""
        context = PromptContext(
            category=PromptCategory.COMBAT,
            game_state={
                "round_number": round_number,
                "current_combatant": current_combatant,
                "party_status": party_status,
                "enemy_status": enemy_status,
                "initiative_order": "See status above",
            },
            recent_events=[],
            mechanical_results=last_action or {},
        )

        prompt = self.build_prompt(context)

        # Add turn-specific instructions
        if is_player_turn:
            prompt["user"] += "\n\nIt is the player's turn. Ask what they want to do."
        else:
            prompt["user"] += "\n\nIt is an NPC's turn. Suggest their action based on tactics."

        return prompt

    def build_encounter_prompt(
        self,
        encounter_type: str,
        reaction_result: Dict[str, Any],
        distance: int,
        surprise: str,
        creature_details: Dict[str, Any],
        location: str,
    ) -> Dict[str, str]:
        """Build an encounter-specific prompt."""
        context = PromptContext(
            category=PromptCategory.WILDERNESS_ENCOUNTER,
            game_state={
                "location": location,
                "encounter_type": encounter_type,
                "distance": distance,
                "surprise_status": surprise,
                "reaction_result": f"{reaction_result['reaction'].upper()}: {reaction_result['description']}",
                "creature_details": creature_details,
            },
            recent_events=[],
            mechanical_results=reaction_result,
        )

        return self.build_prompt(context)


class SafeDict(dict):
    """Dict that returns placeholder for missing keys."""
    def __missing__(self, key):
        return f"{{{key}}}"


# =============================================================================
# RESPONSE PARSER
# =============================================================================

class ResponseParser:
    """
    Parses LLM responses and validates authority boundaries.

    Ensures the LLM hasn't overstepped its authority by making
    mechanical decisions.
    """

    FORBIDDEN_PATTERNS = [
        "you succeed",
        "you fail",
        "you hit",
        "you miss",
        "you take",
        "damage",
        "you roll",
        "rolling",
        "die/dice",
        "d20",
        "d6",
        "saving throw succeeds",
        "saving throw fails",
    ]

    def parse_response(
        self,
        raw_response: str,
        expected_category: PromptCategory,
    ) -> LLMResponse:
        """
        Parse an LLM response into structured format.

        Args:
            raw_response: Raw text from LLM
            expected_category: What category we expected

        Returns:
            Structured LLMResponse
        """
        # Check for authority violations
        violations = self._check_authority_violations(raw_response)

        response = LLMResponse(
            narrative=raw_response,
            metadata={
                "category": expected_category.value,
                "authority_violations": violations,
            }
        )

        return response

    def _check_authority_violations(
        self,
        text: str,
    ) -> List[str]:
        """Check for patterns that suggest authority overreach."""
        violations = []
        text_lower = text.lower()

        for pattern in self.FORBIDDEN_PATTERNS:
            if pattern in text_lower:
                violations.append(f"Possible authority violation: '{pattern}'")

        return violations

    def validate_npc_action(
        self,
        action: NPCAction,
    ) -> bool:
        """Validate that an NPC action can be resolved by the engine."""
        valid_action_types = ["attack", "cast", "move", "flee", "defend", "other"]
        return action.action_type in valid_action_types


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_prompt_builder() -> PromptBuilder:
    """Create a configured PromptBuilder."""
    return PromptBuilder()


def create_response_parser() -> ResponseParser:
    """Create a configured ResponseParser."""
    return ResponseParser()


def get_authority_rules() -> Dict[str, List[str]]:
    """Get the authority rules for documentation."""
    return AUTHORITY_RULES.copy()
