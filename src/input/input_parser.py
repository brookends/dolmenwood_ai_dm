"""
Input Parser for Dolmenwood AI DM v2.0

This module converts player natural language input into structured Action objects
that can be processed by the game engines. The parser is the FIRST step in the
"Python decides everything" architecture.

The flow is:
    Player text → InputParser → Action → GameOrchestrator → Engine → Result → Narrator

The parser does NOT make game decisions. It only identifies player INTENT.

Author: AI Dungeon Master Project
Version: 2.0
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from game_state.state_machine import GameState

logger = logging.getLogger(__name__)


# =============================================================================
# ACTION TYPES
# =============================================================================

class ActionCategory(str, Enum):
    """High-level action categories."""
    COMBAT = "combat"
    MOVEMENT = "movement"
    EXPLORATION = "exploration"
    SOCIAL = "social"
    MAGIC = "magic"
    REST = "rest"
    INVENTORY = "inventory"
    INFORMATION = "information"  # Player asking for info, not taking action
    AMBIGUOUS = "ambiguous"  # Need clarification


class ActionType(str, Enum):
    """Specific action types that map to game mechanics."""
    # Combat actions
    ATTACK_MELEE = "attack_melee"
    ATTACK_RANGED = "attack_ranged"
    CAST_OFFENSIVE_SPELL = "cast_offensive_spell"
    FLEE = "flee"
    DEFEND = "defend"
    USE_COMBAT_ITEM = "use_combat_item"
    GRAPPLE = "grapple"
    SHOVE = "shove"

    # Movement actions
    TRAVEL_TO_HEX = "travel_to_hex"
    TRAVEL_DIRECTION = "travel_direction"
    ENTER_LOCATION = "enter_location"
    EXIT_LOCATION = "exit_location"
    MOVE_IN_DUNGEON = "move_in_dungeon"
    CLIMB = "climb"
    SWIM = "swim"
    JUMP = "jump"

    # Exploration actions
    SEARCH_AREA = "search_area"
    SEARCH_OBJECT = "search_object"
    EXAMINE = "examine"
    LISTEN = "listen"
    OPEN_DOOR = "open_door"
    OPEN_CONTAINER = "open_container"
    PICK_LOCK = "pick_lock"
    DISARM_TRAP = "disarm_trap"
    FORAGE = "forage"
    HUNT = "hunt"
    MAKE_CAMP = "make_camp"

    # Social actions
    TALK_TO_NPC = "talk_to_npc"
    PERSUADE = "persuade"
    INTIMIDATE = "intimidate"
    DECEIVE = "deceive"
    BARTER = "barter"
    GATHER_RUMORS = "gather_rumors"

    # Magic actions
    CAST_UTILITY_SPELL = "cast_utility_spell"
    CAST_HEALING_SPELL = "cast_healing_spell"
    IDENTIFY_MAGIC = "identify_magic"

    # Rest actions
    SHORT_REST = "short_rest"
    LONG_REST = "long_rest"
    SLEEP = "sleep"

    # Inventory actions
    USE_ITEM = "use_item"
    EQUIP_ITEM = "equip_item"
    DROP_ITEM = "drop_item"
    PICK_UP_ITEM = "pick_up_item"
    GIVE_ITEM = "give_item"

    # Information (no mechanical effect)
    ASK_STATUS = "ask_status"
    ASK_LOCATION = "ask_location"
    ASK_TIME = "ask_time"
    ASK_INVENTORY = "ask_inventory"
    ASK_OPTIONS = "ask_options"

    # Fallback
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"


# =============================================================================
# ACTION DATA
# =============================================================================

@dataclass
class ParsedAction:
    """
    A parsed player action ready for game engine processing.

    This represents what the player WANTS to do, not the outcome.
    """
    action_type: ActionType
    category: ActionCategory
    raw_input: str

    # Target information
    target: Optional[str] = None  # "goblin", "the door", "chest", "merchant"
    target_type: Optional[str] = None  # "creature", "object", "npc", "direction"

    # Action parameters
    parameters: dict[str, Any] = field(default_factory=dict)
    # Examples:
    # - {"weapon": "sword"} for attacks
    # - {"direction": "north"} for travel
    # - {"spell": "fireball"} for casting
    # - {"item": "potion of healing"} for item use

    # Confidence and alternatives
    confidence: float = 1.0  # 0.0-1.0, how certain we are of the parse
    alternatives: list["ParsedAction"] = field(default_factory=list)

    # Context hints for disambiguation
    requires_target_selection: bool = False
    requires_clarification: bool = False
    clarification_prompt: Optional[str] = None

    def is_valid(self) -> bool:
        """Check if this is a valid, actionable parse."""
        return (
            self.action_type != ActionType.INVALID
            and self.action_type != ActionType.AMBIGUOUS
            and self.confidence >= 0.5
            and not self.requires_clarification
        )


# =============================================================================
# PATTERN DEFINITIONS
# =============================================================================

@dataclass
class ActionPattern:
    """A regex pattern that maps to an action type."""
    pattern: re.Pattern
    action_type: ActionType
    category: ActionCategory
    target_group: Optional[int] = None  # Regex group containing target
    param_groups: dict[str, int] = field(default_factory=dict)  # param_name -> group
    priority: int = 0  # Higher = checked first
    valid_states: Optional[list[str]] = None  # Only match in these states


# Combat patterns
COMBAT_PATTERNS = [
    ActionPattern(
        pattern=re.compile(
            r"\b(attack|strike|hit|slash|stab|swing at|fight)\b"
            r"(?:\s+(?:the\s+)?(?P<target>\w+(?:\s+\w+)?))?",
            re.I
        ),
        action_type=ActionType.ATTACK_MELEE,
        category=ActionCategory.COMBAT,
        priority=10,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(shoot|fire|loose|throw)\b"
            r"(?:\s+(?:at\s+)?(?:the\s+)?(?P<target>\w+(?:\s+\w+)?))?",
            re.I
        ),
        action_type=ActionType.ATTACK_RANGED,
        category=ActionCategory.COMBAT,
        priority=10,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(flee|run away|escape|retreat|disengage)\b",
            re.I
        ),
        action_type=ActionType.FLEE,
        category=ActionCategory.COMBAT,
        priority=8,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(defend|dodge|block|parry|take cover|protect myself)\b",
            re.I
        ),
        action_type=ActionType.DEFEND,
        category=ActionCategory.COMBAT,
        priority=7,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(grapple|grab|wrestle|tackle)\b"
            r"(?:\s+(?:the\s+)?(?P<target>\w+(?:\s+\w+)?))?",
            re.I
        ),
        action_type=ActionType.GRAPPLE,
        category=ActionCategory.COMBAT,
        priority=6,
    ),
]

# Movement patterns
MOVEMENT_PATTERNS = [
    ActionPattern(
        pattern=re.compile(
            r"\b(?:go|travel|walk|head|move|journey)\b"
            r"\s+(?P<direction>north|south|east|west|"
            r"northeast|northwest|southeast|southwest|ne|nw|se|sw|n|s|e|w)\b",
            re.I
        ),
        action_type=ActionType.TRAVEL_DIRECTION,
        category=ActionCategory.MOVEMENT,
        priority=10,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:go|travel|head)\s+to\b"
            r"\s+(?:the\s+)?(?P<location>.+)",
            re.I
        ),
        action_type=ActionType.TRAVEL_TO_HEX,
        category=ActionCategory.MOVEMENT,
        priority=9,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:enter|go into|step into|walk into)\b"
            r"\s+(?:the\s+)?(?P<location>\w+(?:\s+\w+)?)",
            re.I
        ),
        action_type=ActionType.ENTER_LOCATION,
        category=ActionCategory.MOVEMENT,
        priority=10,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:leave|exit|depart|head out|go outside)\b"
            r"(?:\s+(?:the\s+)?(?P<location>\w+(?:\s+\w+)?))?",
            re.I
        ),
        action_type=ActionType.EXIT_LOCATION,
        category=ActionCategory.MOVEMENT,
        priority=9,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:climb|scale|ascend|descend)\b"
            r"(?:\s+(?:the\s+)?(?P<target>\w+(?:\s+\w+)?))?",
            re.I
        ),
        action_type=ActionType.CLIMB,
        category=ActionCategory.MOVEMENT,
        priority=7,
    ),
]

# Exploration patterns
EXPLORATION_PATTERNS = [
    ActionPattern(
        pattern=re.compile(
            r"\b(?:search|look for|check for)\b"
            r"(?:\s+(?:the\s+)?(?P<target>.+))?",
            re.I
        ),
        action_type=ActionType.SEARCH_AREA,
        category=ActionCategory.EXPLORATION,
        priority=8,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:examine|inspect|study|look at|look closely at)\b"
            r"\s+(?:the\s+)?(?P<target>.+)",
            re.I
        ),
        action_type=ActionType.EXAMINE,
        category=ActionCategory.EXPLORATION,
        priority=9,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:listen|hear|eavesdrop)\b"
            r"(?:\s+(?:at|to|through)\s+(?:the\s+)?(?P<target>\w+(?:\s+\w+)?))?",
            re.I
        ),
        action_type=ActionType.LISTEN,
        category=ActionCategory.EXPLORATION,
        priority=7,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:open)\b"
            r"\s+(?:the\s+)?(?P<target>door|gate|portcullis|hatch|trapdoor)",
            re.I
        ),
        action_type=ActionType.OPEN_DOOR,
        category=ActionCategory.EXPLORATION,
        priority=10,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:open)\b"
            r"\s+(?:the\s+)?(?P<target>chest|box|crate|barrel|container|sack|bag)",
            re.I
        ),
        action_type=ActionType.OPEN_CONTAINER,
        category=ActionCategory.EXPLORATION,
        priority=10,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:pick|unlock)\b"
            r"\s+(?:the\s+)?(?:lock\s+on\s+)?(?P<target>\w+(?:\s+\w+)?)",
            re.I
        ),
        action_type=ActionType.PICK_LOCK,
        category=ActionCategory.EXPLORATION,
        priority=8,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:disarm|disable|deactivate)\b"
            r"\s+(?:the\s+)?(?P<target>trap|mechanism)",
            re.I
        ),
        action_type=ActionType.DISARM_TRAP,
        category=ActionCategory.EXPLORATION,
        priority=9,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:forage|gather|collect)\b"
            r"(?:\s+(?:for\s+)?(?P<target>food|berries|herbs|mushrooms|plants))?",
            re.I
        ),
        action_type=ActionType.FORAGE,
        category=ActionCategory.EXPLORATION,
        priority=7,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:hunt|trap|catch)\b"
            r"(?:\s+(?:for\s+)?(?P<target>game|animals|food))?",
            re.I
        ),
        action_type=ActionType.HUNT,
        category=ActionCategory.EXPLORATION,
        priority=7,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:make camp|set up camp|pitch tent|camp here)\b",
            re.I
        ),
        action_type=ActionType.MAKE_CAMP,
        category=ActionCategory.EXPLORATION,
        priority=8,
    ),
]

# Social patterns
SOCIAL_PATTERNS = [
    ActionPattern(
        pattern=re.compile(
            r"\b(?:talk to|speak to|speak with|approach|greet|hail)\b"
            r"\s+(?:the\s+)?(?P<target>.+)",
            re.I
        ),
        action_type=ActionType.TALK_TO_NPC,
        category=ActionCategory.SOCIAL,
        priority=10,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:persuade|convince|reason with)\b"
            r"\s+(?:the\s+)?(?P<target>.+)",
            re.I
        ),
        action_type=ActionType.PERSUADE,
        category=ActionCategory.SOCIAL,
        priority=9,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:threaten|intimidate|scare|menace)\b"
            r"\s+(?:the\s+)?(?P<target>.+)",
            re.I
        ),
        action_type=ActionType.INTIMIDATE,
        category=ActionCategory.SOCIAL,
        priority=9,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:lie to|deceive|trick|bluff|mislead)\b"
            r"\s+(?:the\s+)?(?P<target>.+)",
            re.I
        ),
        action_type=ActionType.DECEIVE,
        category=ActionCategory.SOCIAL,
        priority=9,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:buy|sell|trade|barter|haggle|purchase)\b"
            r"(?:\s+(?:with\s+)?(?:the\s+)?(?P<target>.+))?",
            re.I
        ),
        action_type=ActionType.BARTER,
        category=ActionCategory.SOCIAL,
        priority=8,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:ask about|inquire|gather rumors|ask for news)\b",
            re.I
        ),
        action_type=ActionType.GATHER_RUMORS,
        category=ActionCategory.SOCIAL,
        priority=7,
    ),
]

# Magic patterns
MAGIC_PATTERNS = [
    ActionPattern(
        pattern=re.compile(
            r"\b(?:cast|use)\b"
            r"\s+(?P<spell>fireball|magic missile|lightning bolt|burning hands|"
            r"sleep|charm person|hold person|web|cloudkill|finger of death)\b"
            r"(?:\s+(?:on|at)\s+(?:the\s+)?(?P<target>.+))?",
            re.I
        ),
        action_type=ActionType.CAST_OFFENSIVE_SPELL,
        category=ActionCategory.MAGIC,
        priority=10,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:cast|use)\b"
            r"\s+(?P<spell>cure wounds|healing word|cure light wounds|"
            r"cure serious wounds|heal|restoration)\b"
            r"(?:\s+(?:on)\s+(?:the\s+)?(?P<target>.+))?",
            re.I
        ),
        action_type=ActionType.CAST_HEALING_SPELL,
        category=ActionCategory.MAGIC,
        priority=10,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:cast|use)\b"
            r"\s+(?P<spell>light|detect magic|identify|knock|invisibility|"
            r"levitate|fly|dispel magic|dimension door|teleport)\b"
            r"(?:\s+(?:on)\s+(?:the\s+)?(?P<target>.+))?",
            re.I
        ),
        action_type=ActionType.CAST_UTILITY_SPELL,
        category=ActionCategory.MAGIC,
        priority=10,
    ),
]

# Rest patterns
REST_PATTERNS = [
    ActionPattern(
        pattern=re.compile(
            r"\b(?:take a short rest|rest briefly|catch my breath|short rest)\b",
            re.I
        ),
        action_type=ActionType.SHORT_REST,
        category=ActionCategory.REST,
        priority=8,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:rest|take a long rest|rest for the night|long rest|"
            r"camp|make camp|sleep|bed down)\b",
            re.I
        ),
        action_type=ActionType.LONG_REST,
        category=ActionCategory.REST,
        priority=7,
    ),
]

# Inventory patterns
INVENTORY_PATTERNS = [
    ActionPattern(
        pattern=re.compile(
            r"\b(?:use|drink|eat|apply|consume)\b"
            r"\s+(?:the\s+)?(?:my\s+)?(?P<item>.+)",
            re.I
        ),
        action_type=ActionType.USE_ITEM,
        category=ActionCategory.INVENTORY,
        priority=8,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:equip|wield|wear|put on|draw)\b"
            r"\s+(?:the\s+)?(?:my\s+)?(?P<item>.+)",
            re.I
        ),
        action_type=ActionType.EQUIP_ITEM,
        category=ActionCategory.INVENTORY,
        priority=8,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:drop|discard|throw away|leave behind)\b"
            r"\s+(?:the\s+)?(?:my\s+)?(?P<item>.+)",
            re.I
        ),
        action_type=ActionType.DROP_ITEM,
        category=ActionCategory.INVENTORY,
        priority=7,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:pick up|take|grab|collect|loot)\b"
            r"\s+(?:the\s+)?(?P<item>.+)",
            re.I
        ),
        action_type=ActionType.PICK_UP_ITEM,
        category=ActionCategory.INVENTORY,
        priority=8,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:give|hand|offer)\b"
            r"\s+(?:the\s+)?(?:my\s+)?(?P<item>.+?)"
            r"\s+to\s+(?:the\s+)?(?P<target>.+)",
            re.I
        ),
        action_type=ActionType.GIVE_ITEM,
        category=ActionCategory.INVENTORY,
        priority=9,
    ),
]

# Information patterns (no game effect)
INFO_PATTERNS = [
    ActionPattern(
        pattern=re.compile(
            r"\b(?:what(?:'s| is) my status|how am i doing|check health|"
            r"check my character|what(?:'s| is) my hp)\b",
            re.I
        ),
        action_type=ActionType.ASK_STATUS,
        category=ActionCategory.INFORMATION,
        priority=5,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:where am i|what(?:'s| is) this place|look around|"
            r"describe (?:the )?(?:area|room|surroundings))\b",
            re.I
        ),
        action_type=ActionType.ASK_LOCATION,
        category=ActionCategory.INFORMATION,
        priority=5,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:what time|what day|how long|check time)\b",
            re.I
        ),
        action_type=ActionType.ASK_TIME,
        category=ActionCategory.INFORMATION,
        priority=5,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:check inventory|what do i have|my items|my equipment)\b",
            re.I
        ),
        action_type=ActionType.ASK_INVENTORY,
        category=ActionCategory.INFORMATION,
        priority=5,
    ),
    ActionPattern(
        pattern=re.compile(
            r"\b(?:what can i do|my options|what(?:'s| is) available|"
            r"what are my choices)\b",
            re.I
        ),
        action_type=ActionType.ASK_OPTIONS,
        category=ActionCategory.INFORMATION,
        priority=5,
    ),
]

# All patterns combined, sorted by priority
ALL_PATTERNS = sorted(
    COMBAT_PATTERNS + MOVEMENT_PATTERNS + EXPLORATION_PATTERNS +
    SOCIAL_PATTERNS + MAGIC_PATTERNS + REST_PATTERNS +
    INVENTORY_PATTERNS + INFO_PATTERNS,
    key=lambda p: -p.priority
)


# =============================================================================
# INPUT PARSER
# =============================================================================

class InputParser:
    """
    Parses player natural language input into structured Action objects.

    This is the first step in the game loop. The parser identifies player
    INTENT but does not make any game decisions. All mechanical resolution
    happens in the game engines.

    Example:
        >>> parser = InputParser()
        >>> action = parser.parse("I attack the goblin with my sword")
        >>> print(action.action_type)
        ActionType.ATTACK_MELEE
        >>> print(action.target)
        "goblin"
        >>> print(action.parameters)
        {"weapon": "sword"}
    """

    def __init__(self, patterns: Optional[list[ActionPattern]] = None):
        """
        Initialize the parser.

        Args:
            patterns: Custom patterns to use. Defaults to ALL_PATTERNS.
        """
        self.patterns = patterns or ALL_PATTERNS
        logger.info(f"InputParser initialized with {len(self.patterns)} patterns")

    def parse(
        self,
        player_input: str,
        current_state: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> ParsedAction:
        """
        Parse player input into a structured action.

        Args:
            player_input: Raw player input text.
            current_state: Current game state (for context-aware parsing).
            context: Additional context (available targets, items, etc.).

        Returns:
            ParsedAction representing the player's intent.
        """
        if not player_input or not player_input.strip():
            return ParsedAction(
                action_type=ActionType.INVALID,
                category=ActionCategory.AMBIGUOUS,
                raw_input=player_input or "",
                confidence=0.0,
                requires_clarification=True,
                clarification_prompt="What would you like to do?",
            )

        input_clean = player_input.strip()
        context = context or {}

        # Try each pattern in priority order
        for pattern in self.patterns:
            # Check state restriction
            if pattern.valid_states and current_state:
                if current_state not in pattern.valid_states:
                    continue

            match = pattern.pattern.search(input_clean)
            if match:
                return self._build_action_from_match(
                    match, pattern, input_clean, context
                )

        # No pattern matched - try to extract partial information
        return self._handle_ambiguous_input(input_clean, context)

    def _build_action_from_match(
        self,
        match: re.Match,
        pattern: ActionPattern,
        raw_input: str,
        context: dict[str, Any],
    ) -> ParsedAction:
        """Build a ParsedAction from a regex match."""
        # Extract target from named group
        target = None
        target_type = None

        try:
            target = match.group("target")
            if target:
                target = target.strip()
                target_type = self._infer_target_type(target, context)
        except IndexError:
            pass

        # Extract other parameters
        parameters = {}

        # Check for weapon mentions in attack
        if pattern.action_type in (ActionType.ATTACK_MELEE, ActionType.ATTACK_RANGED):
            weapon = self._extract_weapon(raw_input)
            if weapon:
                parameters["weapon"] = weapon

        # Check for direction in movement
        try:
            direction = match.group("direction")
            if direction:
                parameters["direction"] = self._normalize_direction(direction)
        except IndexError:
            pass

        # Check for location in travel
        try:
            location = match.group("location")
            if location:
                parameters["location"] = location.strip()
        except IndexError:
            pass

        # Check for spell in magic
        try:
            spell = match.group("spell")
            if spell:
                parameters["spell"] = spell.strip().lower()
        except IndexError:
            pass

        # Check for item in inventory
        try:
            item = match.group("item")
            if item:
                parameters["item"] = item.strip()
        except IndexError:
            pass

        # Determine if we need target selection
        requires_target = (
            pattern.category == ActionCategory.COMBAT
            and pattern.action_type != ActionType.FLEE
            and pattern.action_type != ActionType.DEFEND
            and not target
        )

        return ParsedAction(
            action_type=pattern.action_type,
            category=pattern.category,
            raw_input=raw_input,
            target=target,
            target_type=target_type,
            parameters=parameters,
            confidence=0.9 if target or not requires_target else 0.7,
            requires_target_selection=requires_target,
            clarification_prompt="What do you want to attack?" if requires_target else None,
        )

    def _handle_ambiguous_input(
        self,
        raw_input: str,
        context: dict[str, Any],
    ) -> ParsedAction:
        """Handle input that didn't match any pattern."""
        # Check for obvious action words
        action_hints = {
            "attack": (ActionType.ATTACK_MELEE, ActionCategory.COMBAT),
            "fight": (ActionType.ATTACK_MELEE, ActionCategory.COMBAT),
            "go": (ActionType.TRAVEL_DIRECTION, ActionCategory.MOVEMENT),
            "move": (ActionType.TRAVEL_DIRECTION, ActionCategory.MOVEMENT),
            "search": (ActionType.SEARCH_AREA, ActionCategory.EXPLORATION),
            "look": (ActionType.EXAMINE, ActionCategory.EXPLORATION),
            "talk": (ActionType.TALK_TO_NPC, ActionCategory.SOCIAL),
            "speak": (ActionType.TALK_TO_NPC, ActionCategory.SOCIAL),
            "rest": (ActionType.LONG_REST, ActionCategory.REST),
            "sleep": (ActionType.LONG_REST, ActionCategory.REST),
            "cast": (ActionType.CAST_UTILITY_SPELL, ActionCategory.MAGIC),
        }

        input_lower = raw_input.lower()
        for word, (action_type, category) in action_hints.items():
            if word in input_lower:
                return ParsedAction(
                    action_type=action_type,
                    category=category,
                    raw_input=raw_input,
                    confidence=0.5,
                    requires_clarification=True,
                    clarification_prompt=f"I understood you want to {word}. Can you be more specific?",
                )

        # Complete ambiguity
        return ParsedAction(
            action_type=ActionType.AMBIGUOUS,
            category=ActionCategory.AMBIGUOUS,
            raw_input=raw_input,
            confidence=0.0,
            requires_clarification=True,
            clarification_prompt="I'm not sure what you want to do. Try being more specific.",
        )

    def _extract_weapon(self, text: str) -> Optional[str]:
        """Extract weapon name from text."""
        weapon_patterns = [
            r"with (?:my |the )?(?P<weapon>sword|axe|mace|hammer|dagger|"
            r"spear|bow|crossbow|staff|club|flail|halberd|pike|lance|"
            r"shortsword|longsword|greatsword|battleaxe|handaxe|warhammer|"
            r"morning star|rapier|scimitar|whip|sling)",
            r"using (?:my |the )?(?P<weapon>\w+)",
        ]

        for pattern in weapon_patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return match.group("weapon")

        return None

    def _normalize_direction(self, direction: str) -> str:
        """Normalize direction abbreviations."""
        direction_map = {
            "n": "north", "s": "south", "e": "east", "w": "west",
            "ne": "northeast", "nw": "northwest",
            "se": "southeast", "sw": "southwest",
        }
        return direction_map.get(direction.lower(), direction.lower())

    def _infer_target_type(self, target: str, context: dict[str, Any]) -> str:
        """Infer the type of target from name and context."""
        target_lower = target.lower()

        # Check context for known entities
        if "creatures" in context and target_lower in [c.lower() for c in context["creatures"]]:
            return "creature"
        if "npcs" in context and target_lower in [n.lower() for n in context["npcs"]]:
            return "npc"
        if "objects" in context and target_lower in [o.lower() for o in context["objects"]]:
            return "object"

        # Infer from common words
        creature_words = {"goblin", "orc", "troll", "dragon", "skeleton", "zombie",
                         "wolf", "bear", "spider", "rat", "bat", "guard", "bandit"}
        if target_lower in creature_words or any(w in target_lower for w in creature_words):
            return "creature"

        object_words = {"door", "chest", "box", "lever", "switch", "altar", "statue",
                       "table", "chair", "bed", "throne", "fountain", "well"}
        if target_lower in object_words or any(w in target_lower for w in object_words):
            return "object"

        direction_words = {"north", "south", "east", "west", "up", "down"}
        if target_lower in direction_words:
            return "direction"

        # Default to unknown
        return "unknown"


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_input_parser() -> InputParser:
    """Create a configured InputParser instance."""
    return InputParser()
