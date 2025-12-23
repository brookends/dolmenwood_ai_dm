"""
Game Orchestrator for Dolmenwood AI DM v2.0

The orchestrator is the central coordinator that:
1. Receives parsed player actions
2. Routes them to the appropriate game engine based on current state
3. Ensures all procedural triggers execute (mandatory procedures)
4. Collects structured results for the narrator

This is where ALL game decisions are made. The LLM narrator receives
only the final results to describe - it cannot change outcomes.

Author: AI Dungeon Master Project
Version: 2.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from input.input_parser import ParsedAction, ActionType, ActionCategory
    from game_state.state_machine import StateMachine, GameState
    from game_state.global_controller import GlobalController
    from resolution.procedure_triggers import TriggerHandler
    from resolution.action_resolver import ActionResolver

logger = logging.getLogger(__name__)


# =============================================================================
# RESULT DATA STRUCTURES
# =============================================================================

class ResultType(str, Enum):
    """Type of result from game action."""
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILURE = "failure"
    BLOCKED = "blocked"  # Action not allowed
    DEFERRED = "deferred"  # Waiting for more info
    INFO_ONLY = "info_only"  # No mechanical effect


@dataclass
class DiceRollResult:
    """Result of a single dice roll."""
    notation: str  # "d20", "2d6+3"
    rolls: list[int]
    modifier: int
    total: int
    purpose: str  # "attack", "damage", "saving throw"
    success: Optional[bool] = None  # If this was a check
    target_number: Optional[int] = None  # DC or AC


@dataclass
class MechanicalResult:
    """
    Complete mechanical result of an action.

    This contains ALL the information the narrator needs to describe
    what happened, without any ability to change the outcome.
    """
    result_type: ResultType
    action_taken: str  # Description of what was attempted
    action_category: str

    # Dice rolls made
    dice_rolls: list[DiceRollResult] = field(default_factory=list)

    # Outcomes
    primary_outcome: str = ""  # "hit", "miss", "success", "failure"
    outcome_details: dict[str, Any] = field(default_factory=dict)
    # Examples:
    # - {"damage": 7, "damage_type": "slashing"}
    # - {"distance_traveled": 1, "terrain": "forest"}
    # - {"trap_triggered": True, "damage_taken": 6}

    # State changes that occurred
    state_changes: dict[str, Any] = field(default_factory=dict)
    # Examples:
    # - {"goblin_hp": {"before": 8, "after": 1}}
    # - {"party_location": {"before": "0805", "after": "0806"}}

    # What the party can perceive
    visible_information: dict[str, Any] = field(default_factory=dict)
    # - What they see, hear, smell as a result
    # - Does NOT include hidden information

    # Procedure triggers that fired
    procedures_executed: list[str] = field(default_factory=list)
    # - "encounter_check", "resource_consumption", "time_advance"

    # Available follow-up actions
    available_actions: list[str] = field(default_factory=list)

    # Narrative hints (suggestions, not requirements)
    narrative_hints: list[str] = field(default_factory=list)

    # Error/blocked information
    error_message: Optional[str] = None
    blocked_reason: Optional[str] = None


@dataclass
class OrchestratorResult:
    """
    Complete result package from the orchestrator.

    This is what gets sent to the narrator LLM.
    """
    # The original action
    player_input: str
    parsed_action_type: str
    parsed_target: Optional[str]

    # The mechanical result
    mechanical_result: MechanicalResult

    # Current game state after action
    current_state: str
    state_changed: bool
    new_state: Optional[str] = None

    # Time tracking
    time_elapsed: dict[str, int] = field(default_factory=dict)
    # {"rounds": 1} or {"turns": 1} or {"watches": 1}

    # Resource changes
    resources_consumed: dict[str, Any] = field(default_factory=dict)

    # Any events triggered
    triggered_events: list[dict[str, Any]] = field(default_factory=list)
    # - Random encounters
    # - Environmental effects
    # - NPC reactions

    def to_narrator_prompt(self) -> dict[str, Any]:
        """Convert to a structured prompt for the narrator LLM."""
        return {
            "player_action": {
                "raw_input": self.player_input,
                "interpreted_as": self.parsed_action_type,
                "target": self.parsed_target,
            },
            "result": {
                "outcome": self.mechanical_result.result_type.value,
                "primary_result": self.mechanical_result.primary_outcome,
                "details": self.mechanical_result.outcome_details,
            },
            "dice_rolls": [
                {
                    "purpose": r.purpose,
                    "roll": r.notation,
                    "result": r.total,
                    "success": r.success,
                }
                for r in self.mechanical_result.dice_rolls
            ],
            "state_changes": self.mechanical_result.state_changes,
            "visible_to_party": self.mechanical_result.visible_information,
            "current_situation": {
                "game_state": self.current_state,
                "time_passed": self.time_elapsed,
                "resources_used": self.resources_consumed,
            },
            "events_triggered": self.triggered_events,
            "available_actions": self.mechanical_result.available_actions,
            "narrative_hints": self.mechanical_result.narrative_hints,
        }


# =============================================================================
# GAME ORCHESTRATOR
# =============================================================================

class GameOrchestrator:
    """
    Central coordinator for all game actions.

    The orchestrator:
    1. Receives parsed player actions
    2. Validates actions against current state
    3. Routes to appropriate engine
    4. Executes mandatory procedures
    5. Returns structured results

    The orchestrator MAKES decisions. The narrator DESCRIBES them.

    Example:
        >>> orchestrator = GameOrchestrator(state_machine, controller)
        >>> action = parser.parse("I attack the goblin")
        >>> result = orchestrator.process_action(action, context)
        >>> narrative = narrator.describe(result.to_narrator_prompt())
    """

    def __init__(
        self,
        state_machine: "StateMachine",
        global_controller: "GlobalController",
        trigger_handler: Optional["TriggerHandler"] = None,
        action_resolver: Optional["ActionResolver"] = None,
    ):
        """
        Initialize the orchestrator.

        Args:
            state_machine: Game state machine for state validation.
            global_controller: Global controller for time/resources.
            trigger_handler: Handler for procedural triggers.
            action_resolver: Resolver for action mechanics.
        """
        self.state_machine = state_machine
        self.global_controller = global_controller
        self.trigger_handler = trigger_handler
        self.action_resolver = action_resolver

        # Engine references (set via set_engine methods)
        self._combat_engine = None
        self._hex_crawl_engine = None
        self._dungeon_engine = None
        self._settlement_engine = None
        self._downtime_engine = None

        # Action handlers by category
        self._handlers: dict[str, Callable] = {}
        self._register_default_handlers()

        logger.info("GameOrchestrator initialized")

    def _register_default_handlers(self) -> None:
        """Register default action handlers."""
        from input.input_parser import ActionCategory

        self._handlers = {
            ActionCategory.COMBAT.value: self._handle_combat_action,
            ActionCategory.MOVEMENT.value: self._handle_movement_action,
            ActionCategory.EXPLORATION.value: self._handle_exploration_action,
            ActionCategory.SOCIAL.value: self._handle_social_action,
            ActionCategory.MAGIC.value: self._handle_magic_action,
            ActionCategory.REST.value: self._handle_rest_action,
            ActionCategory.INVENTORY.value: self._handle_inventory_action,
            ActionCategory.INFORMATION.value: self._handle_info_request,
        }

    # =========================================================================
    # ENGINE SETTERS
    # =========================================================================

    def set_combat_engine(self, engine: Any) -> None:
        """Set the combat engine reference."""
        self._combat_engine = engine

    def set_hex_crawl_engine(self, engine: Any) -> None:
        """Set the hex crawl engine reference."""
        self._hex_crawl_engine = engine

    def set_dungeon_engine(self, engine: Any) -> None:
        """Set the dungeon engine reference."""
        self._dungeon_engine = engine

    def set_settlement_engine(self, engine: Any) -> None:
        """Set the settlement engine reference."""
        self._settlement_engine = engine

    def set_downtime_engine(self, engine: Any) -> None:
        """Set the downtime engine reference."""
        self._downtime_engine = engine

    # =========================================================================
    # MAIN PROCESSING
    # =========================================================================

    def process_action(
        self,
        action: "ParsedAction",
        context: Optional[dict[str, Any]] = None,
    ) -> OrchestratorResult:
        """
        Process a parsed player action through the game engines.

        This is the main entry point. It:
        1. Validates the action is legal
        2. Routes to the appropriate handler
        3. Executes mandatory procedures
        4. Returns complete results

        Args:
            action: Parsed player action.
            context: Additional context (party state, location, etc.).

        Returns:
            OrchestratorResult with all mechanical outcomes.
        """
        context = context or {}

        # Check if action requires clarification
        if action.requires_clarification:
            return self._create_clarification_result(action)

        # Validate action is legal in current state
        validation = self._validate_action(action)
        if not validation["valid"]:
            return self._create_blocked_result(action, validation["reason"])

        # Get handler for action category
        handler = self._handlers.get(action.category.value)
        if not handler:
            return self._create_error_result(
                action, f"No handler for category: {action.category}"
            )

        # Execute the action
        try:
            mechanical_result = handler(action, context)
        except Exception as e:
            logger.error(f"Error processing action: {e}", exc_info=True)
            return self._create_error_result(action, str(e))

        # Execute mandatory post-action procedures
        procedures = self._execute_post_action_procedures(action, mechanical_result)
        mechanical_result.procedures_executed.extend(procedures)

        # Check for state transitions
        state_changed, new_state = self._check_state_transition(action, mechanical_result)

        # Build final result
        return OrchestratorResult(
            player_input=action.raw_input,
            parsed_action_type=action.action_type.value,
            parsed_target=action.target,
            mechanical_result=mechanical_result,
            current_state=self.state_machine.current_state.value,
            state_changed=state_changed,
            new_state=new_state.value if new_state else None,
            time_elapsed=self._get_time_elapsed(action),
            resources_consumed=self._get_resources_consumed(action),
        )

    def _validate_action(self, action: "ParsedAction") -> dict[str, Any]:
        """Validate that an action is legal in the current state."""
        from input.input_parser import ActionCategory, ActionType
        from game_state.state_machine import GameState

        current_state = self.state_machine.current_state

        # Combat actions require COMBAT state
        if action.category == ActionCategory.COMBAT:
            # Exception: attacks can trigger combat from exploration
            if action.action_type in (ActionType.ATTACK_MELEE, ActionType.ATTACK_RANGED):
                # Allow attacks from exploration states (they trigger combat)
                if current_state in (
                    GameState.WILDERNESS_TRAVEL,
                    GameState.WILDERNESS_ENCOUNTER,
                    GameState.DUNGEON_EXPLORATION,
                    GameState.DUNGEON_ENCOUNTER,
                    GameState.SETTLEMENT_EXPLORATION,
                    GameState.COMBAT,
                ):
                    return {"valid": True}
            elif current_state != GameState.COMBAT:
                return {
                    "valid": False,
                    "reason": "Combat actions require being in combat.",
                }

        # Movement actions
        if action.category == ActionCategory.MOVEMENT:
            if current_state == GameState.COMBAT:
                # Only flee/disengage allowed in combat
                if action.action_type not in (ActionType.FLEE,):
                    return {
                        "valid": False,
                        "reason": "Cannot travel while in combat. Use flee to escape.",
                    }

        # Social actions require appropriate context
        if action.category == ActionCategory.SOCIAL:
            if current_state == GameState.COMBAT:
                return {
                    "valid": False,
                    "reason": "Cannot engage in lengthy conversation during combat.",
                }

        # Rest actions
        if action.category == ActionCategory.REST:
            if current_state == GameState.COMBAT:
                return {
                    "valid": False,
                    "reason": "Cannot rest during combat.",
                }

        return {"valid": True}

    def _execute_post_action_procedures(
        self,
        action: "ParsedAction",
        result: MechanicalResult,
    ) -> list[str]:
        """Execute mandatory procedures after an action."""
        from game_state.global_controller import TimeUnit

        procedures_executed = []

        # These procedures MUST run - they are not optional

        # 1. Time advancement (based on action type)
        time_cost = self._get_action_time_cost(action)
        if time_cost > 0:
            # Convert minutes to appropriate time unit
            if time_cost >= 240:  # 4+ hours = watches
                watches = time_cost // 240
                self.global_controller.advance_time(TimeUnit.WATCH, watches)
                procedures_executed.append(f"time_advance:{watches}_watches")
            elif time_cost >= 10:  # 10+ min = dungeon turns
                turns = time_cost // 10
                self.global_controller.advance_time(TimeUnit.TURN, turns)
                procedures_executed.append(f"time_advance:{turns}_turns")
            else:  # minutes = combat rounds
                self.global_controller.advance_time(TimeUnit.ROUND, time_cost)
                procedures_executed.append(f"time_advance:{time_cost}_rounds")

        # 2. Resource consumption (light, rations, etc.)
        # TODO: Implement based on action and location

        # 3. Trigger checks based on state
        if self.trigger_handler:
            # In dungeons: wandering monster check every 2 turns
            # In wilderness: encounter check on travel
            # etc.
            pass

        return procedures_executed

    def _check_state_transition(
        self,
        action: "ParsedAction",
        result: MechanicalResult,
    ) -> tuple[bool, Optional["GameState"]]:
        """Check if the action should trigger a state transition."""
        from input.input_parser import ActionType
        from game_state.state_machine import TransitionTrigger

        # Combat initiation from attack
        if action.action_type in (ActionType.ATTACK_MELEE, ActionType.ATTACK_RANGED):
            if self.state_machine.can_transition(TransitionTrigger.REACTION_HOSTILE):
                transition = self.state_machine.transition(
                    trigger=TransitionTrigger.REACTION_HOSTILE,
                    context={"action": action.action_type.value},
                    reason="Player initiated combat",
                )
                return True, transition.to_state

        # Location transitions
        if action.action_type == ActionType.ENTER_LOCATION:
            location = action.parameters.get("location", "").lower()
            if any(w in location for w in ["dungeon", "cave", "ruins", "crypt", "tomb"]):
                if self.state_machine.can_transition(TransitionTrigger.ENTER_DUNGEON):
                    transition = self.state_machine.transition(
                        trigger=TransitionTrigger.ENTER_DUNGEON,
                        context={"location": location},
                        reason=f"Entered {location}",
                    )
                    return True, transition.to_state
            elif any(w in location for w in ["town", "village", "settlement", "inn"]):
                if self.state_machine.can_transition(TransitionTrigger.ENTER_SETTLEMENT):
                    transition = self.state_machine.transition(
                        trigger=TransitionTrigger.ENTER_SETTLEMENT,
                        context={"location": location},
                        reason=f"Entered {location}",
                    )
                    return True, transition.to_state

        # Rest triggers downtime
        if action.action_type in (ActionType.LONG_REST, ActionType.MAKE_CAMP):
            if self.state_machine.can_transition(TransitionTrigger.REST_INITIATED):
                transition = self.state_machine.transition(
                    trigger=TransitionTrigger.REST_INITIATED,
                    context={},
                    reason="Party resting",
                )
                return True, transition.to_state

        return False, None

    def _get_action_time_cost(self, action: "ParsedAction") -> int:
        """Get time cost in minutes for an action."""
        from input.input_parser import ActionType

        # Combat actions: ~1 minute per round
        if action.category.value == "combat":
            return 1  # Combat round

        # Exploration actions
        time_costs = {
            ActionType.SEARCH_AREA: 10,  # 1 dungeon turn
            ActionType.SEARCH_OBJECT: 5,
            ActionType.EXAMINE: 1,
            ActionType.LISTEN: 1,
            ActionType.OPEN_DOOR: 1,
            ActionType.OPEN_CONTAINER: 1,
            ActionType.PICK_LOCK: 10,
            ActionType.DISARM_TRAP: 10,
            ActionType.FORAGE: 240,  # 4 hours
            ActionType.HUNT: 240,
            ActionType.MAKE_CAMP: 30,
            ActionType.TRAVEL_DIRECTION: 240,  # 1 watch
            ActionType.TRAVEL_TO_HEX: 240,
            ActionType.SHORT_REST: 60,
            ActionType.LONG_REST: 480,  # 8 hours
        }

        return time_costs.get(action.action_type, 0)

    def _get_time_elapsed(self, action: "ParsedAction") -> dict[str, int]:
        """Get time elapsed from action."""
        minutes = self._get_action_time_cost(action)
        if minutes >= 240:
            return {"watches": minutes // 240}
        elif minutes >= 10:
            return {"turns": minutes // 10}
        elif minutes >= 1:
            return {"rounds": minutes}
        return {}

    def _get_resources_consumed(self, action: "ParsedAction") -> dict[str, Any]:
        """Get resources consumed by action."""
        # TODO: Implement based on action type
        return {}

    # =========================================================================
    # ACTION HANDLERS
    # =========================================================================

    def _handle_combat_action(
        self,
        action: "ParsedAction",
        context: dict[str, Any],
    ) -> MechanicalResult:
        """Handle combat actions through the combat engine."""
        from input.input_parser import ActionType

        if not self._combat_engine:
            return self._create_engine_missing_result("combat")

        if action.action_type == ActionType.ATTACK_MELEE:
            return self._resolve_melee_attack(action, context)
        elif action.action_type == ActionType.ATTACK_RANGED:
            return self._resolve_ranged_attack(action, context)
        elif action.action_type == ActionType.FLEE:
            return self._resolve_flee(action, context)
        elif action.action_type == ActionType.DEFEND:
            return self._resolve_defend(action, context)
        else:
            return self._create_unhandled_result(action)

    def _handle_movement_action(
        self,
        action: "ParsedAction",
        context: dict[str, Any],
    ) -> MechanicalResult:
        """Handle movement actions through hex crawl or dungeon engine."""
        from input.input_parser import ActionType
        from game_state.state_machine import GameState

        current_state = self.state_machine.current_state

        # In dungeon, use dungeon engine
        if current_state in (GameState.DUNGEON_EXPLORATION, GameState.DUNGEON_ENCOUNTER):
            if not self._dungeon_engine:
                return self._create_engine_missing_result("dungeon")
            return self._resolve_dungeon_movement(action, context)

        # In wilderness, use hex crawl engine
        if current_state in (GameState.WILDERNESS_TRAVEL, GameState.WILDERNESS_ENCOUNTER):
            if not self._hex_crawl_engine:
                return self._create_engine_missing_result("hex_crawl")
            return self._resolve_wilderness_movement(action, context)

        # In settlement
        if current_state == GameState.SETTLEMENT_EXPLORATION:
            return self._resolve_settlement_movement(action, context)

        return self._create_unhandled_result(action)

    def _handle_exploration_action(
        self,
        action: "ParsedAction",
        context: dict[str, Any],
    ) -> MechanicalResult:
        """Handle exploration actions."""
        from input.input_parser import ActionType

        if action.action_type == ActionType.SEARCH_AREA:
            return self._resolve_search(action, context)
        elif action.action_type == ActionType.EXAMINE:
            return self._resolve_examine(action, context)
        elif action.action_type == ActionType.LISTEN:
            return self._resolve_listen(action, context)
        elif action.action_type == ActionType.OPEN_DOOR:
            return self._resolve_open_door(action, context)
        elif action.action_type == ActionType.FORAGE:
            return self._resolve_forage(action, context)
        elif action.action_type == ActionType.MAKE_CAMP:
            return self._resolve_make_camp(action, context)
        else:
            return self._create_unhandled_result(action)

    def _handle_social_action(
        self,
        action: "ParsedAction",
        context: dict[str, Any],
    ) -> MechanicalResult:
        """Handle social actions."""
        from input.input_parser import ActionType

        if action.action_type == ActionType.TALK_TO_NPC:
            return self._resolve_talk_to_npc(action, context)
        elif action.action_type in (ActionType.PERSUADE, ActionType.INTIMIDATE, ActionType.DECEIVE):
            return self._resolve_social_check(action, context)
        elif action.action_type == ActionType.BARTER:
            return self._resolve_barter(action, context)
        else:
            return self._create_unhandled_result(action)

    def _handle_magic_action(
        self,
        action: "ParsedAction",
        context: dict[str, Any],
    ) -> MechanicalResult:
        """Handle magic/spell actions."""
        # TODO: Implement spell resolution
        return self._create_unhandled_result(action)

    def _handle_rest_action(
        self,
        action: "ParsedAction",
        context: dict[str, Any],
    ) -> MechanicalResult:
        """Handle rest actions."""
        from input.input_parser import ActionType

        if action.action_type == ActionType.LONG_REST:
            return self._resolve_long_rest(action, context)
        elif action.action_type == ActionType.SHORT_REST:
            return self._resolve_short_rest(action, context)
        else:
            return self._create_unhandled_result(action)

    def _handle_inventory_action(
        self,
        action: "ParsedAction",
        context: dict[str, Any],
    ) -> MechanicalResult:
        """Handle inventory actions."""
        # TODO: Implement inventory management
        return self._create_unhandled_result(action)

    def _handle_info_request(
        self,
        action: "ParsedAction",
        context: dict[str, Any],
    ) -> MechanicalResult:
        """Handle information requests (no mechanical effect)."""
        from input.input_parser import ActionType

        info = {}

        if action.action_type == ActionType.ASK_STATUS:
            info = self._get_party_status(context)
        elif action.action_type == ActionType.ASK_LOCATION:
            info = self._get_location_info(context)
        elif action.action_type == ActionType.ASK_TIME:
            time = self.global_controller.get_current_time()
            info = {
                "day": time.day,
                "watch": time.watch,
                "time_of_day": time.time_of_day.value,
            }
        elif action.action_type == ActionType.ASK_OPTIONS:
            info = {"available_actions": self._get_available_actions(context)}

        return MechanicalResult(
            result_type=ResultType.INFO_ONLY,
            action_taken="information request",
            action_category="information",
            primary_outcome="info_provided",
            visible_information=info,
        )

    # =========================================================================
    # RESOLUTION METHODS (Stubs - to be implemented with engines)
    # =========================================================================

    def _resolve_melee_attack(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve a melee attack using combat engine."""
        # TODO: Integrate with CombatEngine
        import random

        # Placeholder implementation
        attack_roll = random.randint(1, 20)
        attack_bonus = context.get("attack_bonus", 2)
        target_ac = context.get("target_ac", 12)
        total = attack_roll + attack_bonus
        hit = total >= target_ac

        dice_rolls = [
            DiceRollResult(
                notation="d20",
                rolls=[attack_roll],
                modifier=attack_bonus,
                total=total,
                purpose="attack roll",
                success=hit,
                target_number=target_ac,
            )
        ]

        if hit:
            damage_roll = random.randint(1, 8)
            damage_bonus = context.get("damage_bonus", 1)
            total_damage = damage_roll + damage_bonus
            dice_rolls.append(
                DiceRollResult(
                    notation="d8",
                    rolls=[damage_roll],
                    modifier=damage_bonus,
                    total=total_damage,
                    purpose="damage roll",
                )
            )
            return MechanicalResult(
                result_type=ResultType.SUCCESS,
                action_taken=f"melee attack against {action.target or 'target'}",
                action_category="combat",
                dice_rolls=dice_rolls,
                primary_outcome="hit",
                outcome_details={
                    "damage": total_damage,
                    "damage_type": "slashing",
                    "target": action.target,
                },
                narrative_hints=[
                    "Describe the successful strike",
                    "Show the target's reaction to being hit",
                ],
            )
        else:
            return MechanicalResult(
                result_type=ResultType.FAILURE,
                action_taken=f"melee attack against {action.target or 'target'}",
                action_category="combat",
                dice_rolls=dice_rolls,
                primary_outcome="miss",
                outcome_details={"target": action.target},
                narrative_hints=[
                    "Describe the near-miss",
                    "Show why the attack failed (dodge, parry, armor)",
                ],
            )

    def _resolve_ranged_attack(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve a ranged attack."""
        # Similar to melee, with range considerations
        return self._resolve_melee_attack(action, context)  # Placeholder

    def _resolve_flee(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve a flee attempt."""
        import random

        # Simple flee check
        flee_roll = random.randint(1, 6)
        success = flee_roll >= 3  # 4-in-6 chance

        return MechanicalResult(
            result_type=ResultType.SUCCESS if success else ResultType.FAILURE,
            action_taken="attempt to flee combat",
            action_category="combat",
            dice_rolls=[
                DiceRollResult(
                    notation="d6",
                    rolls=[flee_roll],
                    modifier=0,
                    total=flee_roll,
                    purpose="flee check",
                    success=success,
                    target_number=3,
                )
            ],
            primary_outcome="escaped" if success else "blocked",
            narrative_hints=[
                "Describe the frantic escape attempt" if success
                else "Describe being cut off from escape",
            ],
        )

    def _resolve_defend(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve a defensive stance."""
        return MechanicalResult(
            result_type=ResultType.SUCCESS,
            action_taken="take defensive stance",
            action_category="combat",
            primary_outcome="defending",
            outcome_details={"ac_bonus": 2},
            state_changes={"defending": True},
            narrative_hints=["Describe bracing for incoming attacks"],
        )

    def _resolve_wilderness_movement(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve wilderness travel."""
        # TODO: Integrate with HexCrawlEngine
        direction = action.parameters.get("direction", "north")
        return MechanicalResult(
            result_type=ResultType.SUCCESS,
            action_taken=f"travel {direction}",
            action_category="movement",
            primary_outcome="moved",
            outcome_details={"direction": direction, "distance": "1 hex"},
            narrative_hints=["Describe the journey through the terrain"],
        )

    def _resolve_dungeon_movement(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve dungeon movement."""
        # TODO: Integrate with DungeonEngine
        return MechanicalResult(
            result_type=ResultType.SUCCESS,
            action_taken="move through dungeon",
            action_category="movement",
            primary_outcome="moved",
            narrative_hints=["Describe the passage"],
        )

    def _resolve_settlement_movement(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve movement within a settlement."""
        location = action.parameters.get("location", "somewhere")
        return MechanicalResult(
            result_type=ResultType.SUCCESS,
            action_taken=f"go to {location}",
            action_category="movement",
            primary_outcome="arrived",
            outcome_details={"destination": location},
        )

    def _resolve_search(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve a search action."""
        import random

        # 2-in-6 chance to find something
        search_roll = random.randint(1, 6)
        found = search_roll <= 2

        # TODO: Look up what's actually hidden in the area

        return MechanicalResult(
            result_type=ResultType.SUCCESS if found else ResultType.FAILURE,
            action_taken=f"search {action.target or 'the area'}",
            action_category="exploration",
            dice_rolls=[
                DiceRollResult(
                    notation="d6",
                    rolls=[search_roll],
                    modifier=0,
                    total=search_roll,
                    purpose="search check",
                    success=found,
                    target_number=2,
                )
            ],
            primary_outcome="found_something" if found else "found_nothing",
            outcome_details={"searched": action.target or "area"},
            narrative_hints=[
                "Describe what was discovered" if found
                else "Describe thorough but fruitless search",
            ],
        )

    def _resolve_examine(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve examining something."""
        # TODO: Look up object details from game data
        return MechanicalResult(
            result_type=ResultType.INFO_ONLY,
            action_taken=f"examine {action.target}",
            action_category="exploration",
            primary_outcome="examined",
            visible_information={"target": action.target, "details": "placeholder"},
        )

    def _resolve_listen(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve a listen check."""
        import random

        listen_roll = random.randint(1, 6)
        heard = listen_roll <= 2  # 2-in-6 for non-thieves

        return MechanicalResult(
            result_type=ResultType.SUCCESS if heard else ResultType.FAILURE,
            action_taken="listen carefully",
            action_category="exploration",
            dice_rolls=[
                DiceRollResult(
                    notation="d6",
                    rolls=[listen_roll],
                    modifier=0,
                    total=listen_roll,
                    purpose="listen check",
                    success=heard,
                    target_number=2,
                )
            ],
            primary_outcome="heard_something" if heard else "heard_nothing",
        )

    def _resolve_open_door(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve opening a door."""
        import random

        # Check if stuck (2-in-6 chance door is stuck)
        stuck_roll = random.randint(1, 6)
        is_stuck = stuck_roll <= 2

        if is_stuck:
            # Strength check to force (2-in-6 base)
            force_roll = random.randint(1, 6)
            forced = force_roll <= 2

            return MechanicalResult(
                result_type=ResultType.SUCCESS if forced else ResultType.FAILURE,
                action_taken=f"open {action.target or 'the door'}",
                action_category="exploration",
                dice_rolls=[
                    DiceRollResult(
                        notation="d6",
                        rolls=[force_roll],
                        modifier=0,
                        total=force_roll,
                        purpose="force door",
                        success=forced,
                        target_number=2,
                    )
                ],
                primary_outcome="door_opened" if forced else "door_stuck",
                outcome_details={"door_was_stuck": True},
                narrative_hints=[
                    "Describe forcing the stuck door open" if forced
                    else "Describe the door refusing to budge",
                ],
            )
        else:
            return MechanicalResult(
                result_type=ResultType.SUCCESS,
                action_taken=f"open {action.target or 'the door'}",
                action_category="exploration",
                primary_outcome="door_opened",
                narrative_hints=["Describe what's revealed beyond the door"],
            )

    def _resolve_forage(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve foraging for food."""
        import random

        forage_roll = random.randint(1, 6)
        found_food = forage_roll <= 2

        rations_found = random.randint(1, 3) if found_food else 0

        return MechanicalResult(
            result_type=ResultType.SUCCESS if found_food else ResultType.FAILURE,
            action_taken="forage for food",
            action_category="exploration",
            dice_rolls=[
                DiceRollResult(
                    notation="d6",
                    rolls=[forage_roll],
                    modifier=0,
                    total=forage_roll,
                    purpose="foraging",
                    success=found_food,
                    target_number=2,
                )
            ],
            primary_outcome="found_food" if found_food else "no_food_found",
            outcome_details={"rations_found": rations_found} if found_food else {},
            state_changes={"rations": f"+{rations_found}"} if found_food else {},
        )

    def _resolve_make_camp(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve making camp."""
        return MechanicalResult(
            result_type=ResultType.SUCCESS,
            action_taken="make camp",
            action_category="exploration",
            primary_outcome="camp_established",
            narrative_hints=["Describe setting up camp for the night"],
        )

    def _resolve_talk_to_npc(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve initiating conversation with an NPC."""
        import random

        # Roll reaction if first meeting
        reaction_roll = random.randint(1, 6) + random.randint(1, 6)
        cha_mod = context.get("charisma_modifier", 0)
        total = reaction_roll + cha_mod

        if total <= 2:
            disposition = "hostile"
        elif total <= 5:
            disposition = "unfriendly"
        elif total <= 8:
            disposition = "neutral"
        elif total <= 11:
            disposition = "friendly"
        else:
            disposition = "helpful"

        return MechanicalResult(
            result_type=ResultType.SUCCESS,
            action_taken=f"speak with {action.target}",
            action_category="social",
            dice_rolls=[
                DiceRollResult(
                    notation="2d6",
                    rolls=[reaction_roll - cha_mod],  # Approximate
                    modifier=cha_mod,
                    total=total,
                    purpose="reaction roll",
                )
            ],
            primary_outcome="conversation_started",
            outcome_details={
                "npc": action.target,
                "disposition": disposition,
            },
            narrative_hints=[
                f"NPC is {disposition}",
                "LLM can voice the NPC based on this disposition",
            ],
        )

    def _resolve_social_check(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve a social skill check."""
        # TODO: Implement with appropriate modifiers
        return self._create_unhandled_result(action)

    def _resolve_barter(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve bartering/trading."""
        # TODO: Implement with price modifiers
        return self._create_unhandled_result(action)

    def _resolve_long_rest(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve a long rest."""
        # TODO: Implement healing, spell recovery, etc.
        return MechanicalResult(
            result_type=ResultType.SUCCESS,
            action_taken="rest for the night",
            action_category="rest",
            primary_outcome="rested",
            state_changes={"hp_restored": True, "spells_recovered": True},
            narrative_hints=["Describe the night's rest"],
        )

    def _resolve_short_rest(
        self, action: "ParsedAction", context: dict[str, Any]
    ) -> MechanicalResult:
        """Resolve a short rest."""
        return MechanicalResult(
            result_type=ResultType.SUCCESS,
            action_taken="take a short rest",
            action_category="rest",
            primary_outcome="rested",
            narrative_hints=["Describe the brief respite"],
        )

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _get_party_status(self, context: dict[str, Any]) -> dict[str, Any]:
        """Get current party status information."""
        # TODO: Get from actual party state
        return {"placeholder": "party status"}

    def _get_location_info(self, context: dict[str, Any]) -> dict[str, Any]:
        """Get current location information."""
        # TODO: Get from actual location state
        return {"placeholder": "location info"}

    def _get_available_actions(self, context: dict[str, Any]) -> list[str]:
        """Get list of available actions in current context."""
        # TODO: Generate based on state
        return ["explore", "travel", "rest", "search"]

    def _create_clarification_result(
        self, action: "ParsedAction"
    ) -> OrchestratorResult:
        """Create a result requesting clarification."""
        return OrchestratorResult(
            player_input=action.raw_input,
            parsed_action_type=action.action_type.value,
            parsed_target=action.target,
            mechanical_result=MechanicalResult(
                result_type=ResultType.DEFERRED,
                action_taken="awaiting clarification",
                action_category=action.category.value,
                error_message=action.clarification_prompt,
            ),
            current_state=self.state_machine.current_state.value,
            state_changed=False,
        )

    def _create_blocked_result(
        self, action: "ParsedAction", reason: str
    ) -> OrchestratorResult:
        """Create a result for blocked action."""
        return OrchestratorResult(
            player_input=action.raw_input,
            parsed_action_type=action.action_type.value,
            parsed_target=action.target,
            mechanical_result=MechanicalResult(
                result_type=ResultType.BLOCKED,
                action_taken=action.action_type.value,
                action_category=action.category.value,
                blocked_reason=reason,
            ),
            current_state=self.state_machine.current_state.value,
            state_changed=False,
        )

    def _create_error_result(
        self, action: "ParsedAction", error: str
    ) -> OrchestratorResult:
        """Create a result for an error."""
        return OrchestratorResult(
            player_input=action.raw_input,
            parsed_action_type=action.action_type.value,
            parsed_target=action.target,
            mechanical_result=MechanicalResult(
                result_type=ResultType.FAILURE,
                action_taken=action.action_type.value,
                action_category=action.category.value,
                error_message=error,
            ),
            current_state=self.state_machine.current_state.value,
            state_changed=False,
        )

    def _create_engine_missing_result(self, engine_name: str) -> MechanicalResult:
        """Create result when required engine is not available."""
        return MechanicalResult(
            result_type=ResultType.BLOCKED,
            action_taken="action requires engine",
            action_category="system",
            blocked_reason=f"{engine_name} engine not available",
        )

    def _create_unhandled_result(self, action: "ParsedAction") -> MechanicalResult:
        """Create result for unhandled action type."""
        return MechanicalResult(
            result_type=ResultType.BLOCKED,
            action_taken=action.action_type.value,
            action_category=action.category.value,
            blocked_reason=f"Action type {action.action_type.value} not yet implemented",
        )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_game_orchestrator(
    state_machine: "StateMachine",
    global_controller: "GlobalController",
    trigger_handler: Optional["TriggerHandler"] = None,
    action_resolver: Optional["ActionResolver"] = None,
) -> GameOrchestrator:
    """Create a configured GameOrchestrator instance."""
    return GameOrchestrator(
        state_machine=state_machine,
        global_controller=global_controller,
        trigger_handler=trigger_handler,
        action_resolver=action_resolver,
    )
