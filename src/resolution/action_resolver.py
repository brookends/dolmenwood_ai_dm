"""
Dolmenwood AI DM - Failure-First Action Resolver (v2.0)

This module implements the failure-first resolution layer for all actions.

The resolution order is:
1. Is the action possible?
2. What goes wrong by default?
3. What warning signs are visible?
4. Is a roll required?
5. Does failure change the situation?
6. Does success still incur cost?

Author: AI Dungeon Master Project
Version: 2.0
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from game_state.state_machine import StateMachine, GameState
    from game_state.global_controller import GlobalController

logger = logging.getLogger(__name__)


# =============================================================================
# ACTION TYPES
# =============================================================================

class ActionType(str, Enum):
    """Types of resolvable actions."""
    # Combat actions
    ATTACK_MELEE = "attack_melee"
    ATTACK_RANGED = "attack_ranged"
    CAST_SPELL = "cast_spell"
    USE_ITEM = "use_item"
    FLEE = "flee"
    DEFEND = "defend"

    # Exploration actions
    MOVE = "move"
    TRAVEL = "travel"
    SEARCH = "search"
    OPEN_DOOR = "open_door"
    DISARM_TRAP = "disarm_trap"
    PICK_LOCK = "pick_lock"
    CLIMB = "climb"
    SWIM = "swim"
    JUMP = "jump"
    FORAGE = "forage"

    # Social actions
    PERSUADE = "persuade"
    INTIMIDATE = "intimidate"
    DECEIVE = "deceive"
    BARTER = "barter"

    # Skill actions
    LISTEN = "listen"
    HIDE = "hide"
    SNEAK = "sneak"
    TRACK = "track"

    # Special actions
    SAVING_THROW = "saving_throw"
    ABILITY_CHECK = "ability_check"


class FailureType(str, Enum):
    """Types of failure consequences."""
    HARMLESS = "harmless"           # Nothing bad happens
    MINOR_SETBACK = "minor_setback" # Wasted time/resources
    REVEALED = "revealed"           # Position/intent known
    DANGER = "danger"               # Direct threat
    CATASTROPHIC = "catastrophic"   # Major consequence


class SuccessCostType(str, Enum):
    """Types of costs even on success."""
    FREE = "free"           # No cost
    TIME = "time"           # Takes time
    RESOURCE = "resource"   # Uses resources
    NOISE = "noise"         # Makes noise
    ATTENTION = "attention" # Draws attention


# =============================================================================
# ACTION DEFINITION
# =============================================================================

@dataclass
class Action:
    """
    Definition of an action to be resolved.
    """
    action_type: ActionType
    actor_id: str
    target_id: Optional[str] = None

    # Action parameters
    parameters: dict[str, Any] = field(default_factory=dict)

    # Modifiers
    modifiers: dict[str, int] = field(default_factory=dict)

    # Context
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionResult:
    """
    Complete result of action resolution.
    """
    action: Action
    success: bool
    possible: bool = True

    # Failure information
    failure_reason: str = ""
    failure_type: FailureType = FailureType.HARMLESS

    # Warning signs (visible before action)
    visible_warnings: list[str] = field(default_factory=list)

    # Roll information
    roll_required: bool = False
    roll_result: Optional[dict[str, Any]] = None

    # Success costs
    success_cost: SuccessCostType = SuccessCostType.FREE
    cost_details: dict[str, Any] = field(default_factory=dict)

    # Consequences
    consequences: list[str] = field(default_factory=list)
    state_changes: dict[str, Any] = field(default_factory=dict)

    # Narrative elements
    description: str = ""

    @property
    def brief(self) -> str:
        """Get brief summary."""
        if not self.possible:
            return f"Impossible: {self.failure_reason}"
        if not self.success:
            return f"Failed: {self.failure_reason}"
        if self.success_cost != SuccessCostType.FREE:
            return f"Success (at cost: {self.success_cost.value})"
        return "Success"

    def to_dict(self) -> dict[str, Any]:
        """Serialize result."""
        return {
            "action_type": self.action.action_type.value,
            "actor_id": self.action.actor_id,
            "success": self.success,
            "possible": self.possible,
            "failure_reason": self.failure_reason,
            "failure_type": self.failure_type.value,
            "visible_warnings": self.visible_warnings,
            "roll_required": self.roll_required,
            "roll_result": self.roll_result,
            "success_cost": self.success_cost.value,
            "cost_details": self.cost_details,
            "consequences": self.consequences,
            "state_changes": self.state_changes,
            "description": self.description,
        }


# =============================================================================
# DEFAULT FAILURES
# =============================================================================

# Define what goes wrong by default for each action type
DEFAULT_FAILURES: dict[ActionType, dict[str, Any]] = {
    ActionType.ATTACK_MELEE: {
        "type": FailureType.MINOR_SETBACK,
        "description": "The attack misses, wasting the opportunity",
        "consequences": ["target alerted", "position revealed"],
    },
    ActionType.ATTACK_RANGED: {
        "type": FailureType.MINOR_SETBACK,
        "description": "The shot goes wide, ammunition expended",
        "consequences": ["ammunition lost", "position revealed"],
    },
    ActionType.CAST_SPELL: {
        "type": FailureType.DANGER,
        "description": "The spell fizzles, slot expended with no effect",
        "consequences": ["spell slot lost", "magical discharge possible"],
    },
    ActionType.FLEE: {
        "type": FailureType.DANGER,
        "description": "Escape blocked or pursued",
        "consequences": ["attack of opportunity", "cornered"],
    },
    ActionType.TRAVEL: {
        "type": FailureType.MINOR_SETBACK,
        "description": "The party becomes lost or delayed",
        "consequences": ["time lost", "resources consumed", "possible danger"],
    },
    ActionType.SEARCH: {
        "type": FailureType.HARMLESS,
        "description": "Nothing found despite the effort",
        "consequences": ["time spent", "noise made"],
    },
    ActionType.OPEN_DOOR: {
        "type": FailureType.REVEALED,
        "description": "The door remains closed, noise made",
        "consequences": ["noise made", "stuck or locked"],
    },
    ActionType.DISARM_TRAP: {
        "type": FailureType.CATASTROPHIC,
        "description": "The trap is triggered!",
        "consequences": ["trap activates", "damage taken"],
    },
    ActionType.PICK_LOCK: {
        "type": FailureType.MINOR_SETBACK,
        "description": "The lock resists, tools may be damaged",
        "consequences": ["time spent", "possible tool breakage", "noise"],
    },
    ActionType.CLIMB: {
        "type": FailureType.DANGER,
        "description": "The climber slips and falls",
        "consequences": ["fall damage", "noise", "items dropped"],
    },
    ActionType.SWIM: {
        "type": FailureType.CATASTROPHIC,
        "description": "The swimmer struggles and begins to drown",
        "consequences": ["drowning risk", "equipment at risk"],
    },
    ActionType.FORAGE: {
        "type": FailureType.HARMLESS,
        "description": "No suitable food or resources found",
        "consequences": ["time spent"],
    },
    ActionType.PERSUADE: {
        "type": FailureType.REVEALED,
        "description": "The attempt fails, intentions revealed",
        "consequences": ["reduced trust", "reaction penalty"],
    },
    ActionType.INTIMIDATE: {
        "type": FailureType.DANGER,
        "description": "The target is angered rather than cowed",
        "consequences": ["hostility increased", "combat possible"],
    },
    ActionType.DECEIVE: {
        "type": FailureType.DANGER,
        "description": "The lie is detected",
        "consequences": ["trust lost", "hostility possible"],
    },
    ActionType.HIDE: {
        "type": FailureType.REVEALED,
        "description": "The character is spotted",
        "consequences": ["position known", "surprise lost"],
    },
    ActionType.SNEAK: {
        "type": FailureType.REVEALED,
        "description": "Noise alerts the target",
        "consequences": ["position known", "stealth broken"],
    },
    ActionType.LISTEN: {
        "type": FailureType.HARMLESS,
        "description": "Nothing heard, or sounds misinterpreted",
        "consequences": ["no information gained"],
    },
    ActionType.SAVING_THROW: {
        "type": FailureType.CATASTROPHIC,
        "description": "Full effect of the hazard is suffered",
        "consequences": ["full damage/effect applied"],
    },
}


# =============================================================================
# VISIBLE WARNINGS
# =============================================================================

def get_visible_warnings(
    action: Action,
    context: dict[str, Any]
) -> list[str]:
    """
    Get warning signs visible before attempting an action.

    These are clues that something might go wrong.
    """
    warnings = []

    # Trap warnings
    if action.action_type == ActionType.DISARM_TRAP:
        if context.get("trap_visible", False):
            warnings.append("The trap mechanism is visible but complex")
        if context.get("trap_magical", False):
            warnings.append("Faint magical runes glow on the mechanism")

    # Combat warnings
    if action.action_type in (ActionType.ATTACK_MELEE, ActionType.ATTACK_RANGED):
        target_hp_pct = context.get("target_hp_percentage", 100)
        if target_hp_pct >= 100:
            warnings.append("The target appears fresh and ready")
        if context.get("target_armored", False):
            warnings.append("Heavy armor protects the target")

    # Climb warnings
    if action.action_type == ActionType.CLIMB:
        if context.get("surface_wet", False):
            warnings.append("The surface is slick with moisture")
        if context.get("height", 0) > 20:
            warnings.append("A fall from this height would be dangerous")

    # Social warnings
    if action.action_type in (ActionType.PERSUADE, ActionType.INTIMIDATE, ActionType.DECEIVE):
        if context.get("target_hostile", False):
            warnings.append("The target regards you with open hostility")
        if context.get("target_suspicious", False):
            warnings.append("The target seems wary of your intentions")

    # Stealth warnings
    if action.action_type in (ActionType.HIDE, ActionType.SNEAK):
        if context.get("well_lit", False):
            warnings.append("Bright light makes concealment difficult")
        if context.get("open_ground", False):
            warnings.append("Little cover is available")

    # Spell warnings
    if action.action_type == ActionType.CAST_SPELL:
        if context.get("in_armor", False):
            warnings.append("Armor interferes with arcane gestures")

    return warnings


# =============================================================================
# ROLL DETERMINATION
# =============================================================================

def requires_roll(action: Action, context: dict[str, Any]) -> bool:
    """
    Determine if an action requires a roll.

    Some actions auto-succeed or auto-fail based on circumstances.
    """
    # Attacks always require rolls (unless auto-hit)
    if action.action_type in (ActionType.ATTACK_MELEE, ActionType.ATTACK_RANGED):
        if context.get("auto_hit", False):
            return False
        return True

    # Saving throws always require rolls
    if action.action_type == ActionType.SAVING_THROW:
        return True

    # Trivial tasks don't require rolls
    if context.get("trivial", False):
        return False

    # Impossible tasks don't require rolls (auto-fail)
    if context.get("impossible", False):
        return False

    # Default: most actions require rolls
    return action.action_type not in (
        ActionType.MOVE,  # Simple movement is auto-success
        ActionType.DEFEND,  # Defensive stance is auto-success
    )


def make_roll(
    action: Action,
    target: int,
    modifier: int = 0
) -> dict[str, Any]:
    """
    Make the appropriate roll for an action.

    Returns:
        Dict with roll details and success determination.
    """
    # Determine roll type based on action
    if action.action_type in (ActionType.ATTACK_MELEE, ActionType.ATTACK_RANGED):
        # Attack roll: d20 + modifiers vs AC
        roll = random.randint(1, 20)
        total = roll + modifier

        natural_20 = roll == 20
        natural_1 = roll == 1

        if natural_1:
            success = False
            critical = False
            fumble = True
        elif natural_20:
            success = True
            critical = True
            fumble = False
        else:
            success = total >= target
            critical = False
            fumble = False

        return {
            "type": "attack",
            "roll": roll,
            "modifier": modifier,
            "total": total,
            "target": target,
            "success": success,
            "critical": critical,
            "fumble": fumble,
        }

    elif action.action_type == ActionType.SAVING_THROW:
        # Saving throw: d20 vs target (roll high)
        roll = random.randint(1, 20)
        total = roll + modifier
        success = total >= target

        return {
            "type": "save",
            "roll": roll,
            "modifier": modifier,
            "total": total,
            "target": target,
            "success": success,
        }

    else:
        # Skill check: d6 vs skill rating (roll low)
        # OSE uses X-in-6 for most skills
        roll = random.randint(1, 6)
        success = roll <= target

        return {
            "type": "skill",
            "roll": roll,
            "target": target,
            "success": success,
        }


# =============================================================================
# SUCCESS COSTS
# =============================================================================

def calculate_success_cost(
    action: Action,
    context: dict[str, Any]
) -> tuple[SuccessCostType, dict[str, Any]]:
    """
    Calculate the cost of success.

    Even successful actions may have costs.
    """
    cost_type = SuccessCostType.FREE
    cost_details = {}

    # Time costs
    time_actions = {
        ActionType.SEARCH: 1,  # 1 turn
        ActionType.PICK_LOCK: 1,
        ActionType.DISARM_TRAP: 1,
        ActionType.FORAGE: 6,  # 6 turns (1 watch)
    }

    if action.action_type in time_actions:
        cost_type = SuccessCostType.TIME
        cost_details["turns"] = time_actions[action.action_type]

    # Resource costs
    if action.action_type == ActionType.ATTACK_RANGED:
        cost_type = SuccessCostType.RESOURCE
        cost_details["ammunition"] = 1

    if action.action_type == ActionType.CAST_SPELL:
        cost_type = SuccessCostType.RESOURCE
        cost_details["spell_slot"] = action.parameters.get("spell_level", 1)

    # Noise costs
    noise_actions = [
        ActionType.OPEN_DOOR,
        ActionType.ATTACK_MELEE,
        ActionType.ATTACK_RANGED,
    ]

    if action.action_type in noise_actions:
        if cost_type == SuccessCostType.FREE:
            cost_type = SuccessCostType.NOISE
        cost_details["noise_level"] = 1

    return cost_type, cost_details


# =============================================================================
# ACTION RESOLVER
# =============================================================================

class ActionResolver:
    """
    Failure-first action resolution system.

    All actions go through this resolver which ensures:
    1. Possibility is checked first
    2. Default failure is determined
    3. Warning signs are visible
    4. Rolls are made if required
    5. Failure consequences are applied
    6. Success costs are calculated

    Example:
        >>> resolver = ActionResolver()
        >>> action = Action(
        ...     action_type=ActionType.ATTACK_MELEE,
        ...     actor_id="fighter_1",
        ...     target_id="goblin_1",
        ...     parameters={"weapon": "sword"},
        ...     modifiers={"attack_bonus": 3}
        ... )
        >>> result = resolver.resolve(action, {"target_ac": 14})
        >>> print(result.success)
        True
    """

    def __init__(
        self,
        state_machine: Optional["StateMachine"] = None,
        controller: Optional["GlobalController"] = None
    ):
        self.state_machine = state_machine
        self.controller = controller

    def resolve(
        self,
        action: Action,
        context: Optional[dict[str, Any]] = None
    ) -> ActionResult:
        """
        Resolve an action using failure-first methodology.

        Args:
            action: The action to resolve.
            context: Additional context for resolution.

        Returns:
            ActionResult with complete resolution details.
        """
        context = context or {}
        context.update(action.context)

        # 1. Is the action possible?
        possible, impossibility_reason = self._is_possible(action, context)
        if not possible:
            return ActionResult(
                action=action,
                success=False,
                possible=False,
                failure_reason=impossibility_reason,
                failure_type=FailureType.HARMLESS,
                description=f"Cannot {action.action_type.value}: {impossibility_reason}"
            )

        # 2. What goes wrong by default?
        default_failure = self._get_default_failure(action)

        # 3. What warning signs are visible?
        warnings = get_visible_warnings(action, context)

        # 4. Is a roll required?
        roll_required = requires_roll(action, context)
        roll_result = None
        success = True

        if roll_required:
            target = self._get_target_number(action, context)
            modifier = sum(action.modifiers.values())
            roll_result = make_roll(action, target, modifier)
            success = roll_result["success"]

        # 5. Does failure change the situation?
        if not success:
            consequences = self._apply_failure_consequences(action, default_failure, context)
            return ActionResult(
                action=action,
                success=False,
                possible=True,
                failure_reason=default_failure["description"],
                failure_type=default_failure["type"],
                visible_warnings=warnings,
                roll_required=roll_required,
                roll_result=roll_result,
                consequences=consequences,
                description=self._generate_failure_description(action, roll_result, default_failure)
            )

        # 6. Does success still incur cost?
        success_cost, cost_details = calculate_success_cost(action, context)

        return ActionResult(
            action=action,
            success=True,
            possible=True,
            visible_warnings=warnings,
            roll_required=roll_required,
            roll_result=roll_result,
            success_cost=success_cost,
            cost_details=cost_details,
            description=self._generate_success_description(action, roll_result, cost_details)
        )

    def _is_possible(
        self,
        action: Action,
        context: dict[str, Any]
    ) -> tuple[bool, str]:
        """
        Check if an action is possible.

        Returns:
            Tuple of (is_possible, reason_if_not)
        """
        # Check state-based restrictions
        if self.state_machine:
            current_state = self.state_machine.current_state

            # Combat-only actions
            if action.action_type in (
                ActionType.ATTACK_MELEE,
                ActionType.ATTACK_RANGED,
                ActionType.FLEE,
                ActionType.DEFEND
            ):
                if current_state.value != "combat":
                    return False, "This action is only valid in combat"

            # Non-combat actions blocked in combat
            if action.action_type in (
                ActionType.TRAVEL,
                ActionType.FORAGE,
                ActionType.SEARCH
            ):
                if current_state.value == "combat":
                    return False, "Cannot perform this action during combat"

        # Check target exists
        if action.target_id is not None and context.get("target_missing", False):
            return False, "Target not found"

        # Check resource requirements
        if action.action_type == ActionType.ATTACK_RANGED:
            ammo = context.get("ammunition", 0)
            if ammo <= 0:
                return False, "No ammunition available"

        if action.action_type == ActionType.CAST_SPELL:
            spell_slots = context.get("spell_slots", {})
            spell_level = action.parameters.get("spell_level", 1)
            if spell_slots.get(spell_level, 0) <= 0:
                return False, f"No level {spell_level} spell slots remaining"

        # Check environmental requirements
        if action.action_type == ActionType.SWIM:
            if not context.get("water_present", False):
                return False, "No water to swim in"

        if action.action_type == ActionType.CLIMB:
            if not context.get("climbable_surface", True):
                return False, "No climbable surface"

        return True, ""

    def _get_default_failure(self, action: Action) -> dict[str, Any]:
        """Get the default failure for an action type."""
        return DEFAULT_FAILURES.get(
            action.action_type,
            {
                "type": FailureType.HARMLESS,
                "description": "The action fails",
                "consequences": [],
            }
        )

    def _get_target_number(
        self,
        action: Action,
        context: dict[str, Any]
    ) -> int:
        """Get the target number for a roll."""
        # Attack: target is AC
        if action.action_type in (ActionType.ATTACK_MELEE, ActionType.ATTACK_RANGED):
            return context.get("target_ac", 10)

        # Saving throw: target is save value
        if action.action_type == ActionType.SAVING_THROW:
            return context.get("save_target", 15)

        # Skill checks: target is skill rating (X-in-6)
        skill_defaults = {
            ActionType.SEARCH: 2,
            ActionType.LISTEN: 2,
            ActionType.HIDE: 2,
            ActionType.SNEAK: 2,
            ActionType.PICK_LOCK: 2,
            ActionType.DISARM_TRAP: 2,
            ActionType.CLIMB: 4,
            ActionType.SWIM: 4,
            ActionType.FORAGE: 2,
        }

        # Check for character skill override
        skill_value = context.get("skill_value")
        if skill_value is not None:
            return skill_value

        return skill_defaults.get(action.action_type, 2)

    def _apply_failure_consequences(
        self,
        action: Action,
        failure: dict[str, Any],
        context: dict[str, Any]
    ) -> list[str]:
        """
        Apply consequences of failure.

        Returns:
            List of consequence descriptions.
        """
        consequences = []

        failure_type = failure["type"]
        base_consequences = failure.get("consequences", [])

        # Apply base consequences
        consequences.extend(base_consequences)

        # Additional consequences based on failure type
        if failure_type == FailureType.CATASTROPHIC:
            # Catastrophic failures have additional effects
            if action.action_type == ActionType.DISARM_TRAP:
                consequences.append("trap_triggered")

            if action.action_type == ActionType.SWIM:
                consequences.append("drowning_check_required")

        if failure_type == FailureType.DANGER:
            # Dangerous failures may attract attention
            if context.get("in_dungeon", False):
                consequences.append("noise_increases")

        if failure_type == FailureType.REVEALED:
            # Revealed failures break stealth
            if context.get("hidden", False):
                consequences.append("stealth_broken")

        return consequences

    def _generate_failure_description(
        self,
        action: Action,
        roll_result: Optional[dict[str, Any]],
        failure: dict[str, Any]
    ) -> str:
        """Generate narrative description of failure."""
        parts = []

        # Roll info
        if roll_result:
            if roll_result["type"] == "attack":
                if roll_result.get("fumble"):
                    parts.append(f"Natural 1! A fumble!")
                else:
                    parts.append(
                        f"Rolled {roll_result['roll']} + {roll_result['modifier']} = "
                        f"{roll_result['total']} vs {roll_result['target']}"
                    )
            elif roll_result["type"] == "skill":
                parts.append(
                    f"Rolled {roll_result['roll']} (needed {roll_result['target']} or less)"
                )

        # Failure description
        parts.append(failure["description"])

        return ". ".join(parts)

    def _generate_success_description(
        self,
        action: Action,
        roll_result: Optional[dict[str, Any]],
        cost_details: dict[str, Any]
    ) -> str:
        """Generate narrative description of success."""
        parts = []

        # Roll info
        if roll_result:
            if roll_result["type"] == "attack":
                if roll_result.get("critical"):
                    parts.append("Critical hit!")
                else:
                    parts.append(
                        f"Rolled {roll_result['roll']} + {roll_result['modifier']} = "
                        f"{roll_result['total']} vs {roll_result['target']}"
                    )
            elif roll_result["type"] == "skill":
                parts.append(f"Rolled {roll_result['roll']} - success!")

        # Success statement
        parts.append(f"The {action.action_type.value.replace('_', ' ')} succeeds")

        # Cost info
        if cost_details:
            cost_parts = []
            if "turns" in cost_details:
                cost_parts.append(f"{cost_details['turns']} turn(s)")
            if "ammunition" in cost_details:
                cost_parts.append(f"{cost_details['ammunition']} ammunition")
            if "spell_slot" in cost_details:
                cost_parts.append(f"level {cost_details['spell_slot']} slot")
            if cost_parts:
                parts.append(f"(costs: {', '.join(cost_parts)})")

        return ". ".join(parts)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def resolve_attack(
    attacker_id: str,
    target_id: str,
    attack_bonus: int,
    target_ac: int,
    is_ranged: bool = False,
    resolver: Optional[ActionResolver] = None
) -> ActionResult:
    """
    Convenience function for resolving attacks.

    Args:
        attacker_id: ID of the attacker.
        target_id: ID of the target.
        attack_bonus: Attack bonus.
        target_ac: Target's AC.
        is_ranged: True for ranged attack.
        resolver: Optional resolver to use.

    Returns:
        ActionResult for the attack.
    """
    resolver = resolver or ActionResolver()

    action = Action(
        action_type=ActionType.ATTACK_RANGED if is_ranged else ActionType.ATTACK_MELEE,
        actor_id=attacker_id,
        target_id=target_id,
        modifiers={"attack_bonus": attack_bonus}
    )

    return resolver.resolve(action, {"target_ac": target_ac})


def resolve_save(
    character_id: str,
    save_type: str,
    save_target: int,
    modifier: int = 0,
    resolver: Optional[ActionResolver] = None
) -> ActionResult:
    """
    Convenience function for resolving saving throws.

    Args:
        character_id: ID of the character.
        save_type: Type of save (doom, ray, hold, blast, spell).
        save_target: Target number to meet or exceed.
        modifier: Modifier to the roll.
        resolver: Optional resolver to use.

    Returns:
        ActionResult for the save.
    """
    resolver = resolver or ActionResolver()

    action = Action(
        action_type=ActionType.SAVING_THROW,
        actor_id=character_id,
        parameters={"save_type": save_type},
        modifiers={"save_mod": modifier}
    )

    return resolver.resolve(action, {"save_target": save_target})


def resolve_skill_check(
    character_id: str,
    skill_type: ActionType,
    skill_value: int,
    resolver: Optional[ActionResolver] = None
) -> ActionResult:
    """
    Convenience function for resolving skill checks.

    Args:
        character_id: ID of the character.
        skill_type: Type of skill check.
        skill_value: Skill rating (X-in-6).
        resolver: Optional resolver to use.

    Returns:
        ActionResult for the skill check.
    """
    resolver = resolver or ActionResolver()

    action = Action(
        action_type=skill_type,
        actor_id=character_id,
    )

    return resolver.resolve(action, {"skill_value": skill_value})


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_action_resolver(
    state_machine: Optional["StateMachine"] = None,
    controller: Optional["GlobalController"] = None
) -> ActionResolver:
    """
    Create a new action resolver.

    Args:
        state_machine: Optional state machine for state checks.
        controller: Optional global controller for state access.

    Returns:
        Configured ActionResolver.
    """
    return ActionResolver(state_machine=state_machine, controller=controller)
