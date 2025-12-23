"""
Dolmenwood AI DM - Procedure Triggers (v2.0)

This module implements non-negotiable procedural checkpoints that fire
automatically based on game state, time, or events.

Procedure triggers ensure:
- Mandatory checks happen at the right times
- The game follows OSE/Dolmenwood procedures
- No procedural steps are skipped
- All randomness goes through defined procedures

Author: AI Dungeon Master Project
Version: 2.0
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from game_state.state_machine import StateMachine, GameState
    from game_state.global_controller import GlobalController

logger = logging.getLogger(__name__)


# =============================================================================
# TRIGGER TYPES
# =============================================================================

class ProcedureTrigger(str, Enum):
    """
    Events that trigger mandatory procedures.

    These triggers fire automatically and cannot be skipped.
    """
    # Time-Based (automatic)
    TRAVEL_SEGMENT = "travel_segment"      # End of each hex traversal
    DUNGEON_TURN = "dungeon_turn"          # Every 10-minute turn
    COMBAT_ROUND = "combat_round"          # End of each combat round
    REST_WATCH = "rest_watch"              # Each watch during rest
    DAY_END = "day_end"                    # End of each day

    # Risk-Based (conditional)
    LOUD_ACTION = "loud_action"            # Noisy activity in dungeon
    FAILED_NAVIGATION = "failed_navigation"  # Party got lost
    LOW_RESOURCES = "low_resources"        # Resources critically low
    LIGHT_DEPLETED = "light_depleted"      # Light source exhausted
    THRESHOLD_CROSSED = "threshold_crossed"  # Entering new area

    # Interaction (event-driven)
    UNKNOWN_NPC = "unknown_npc"            # Meeting new NPC
    DAMAGE_THRESHOLD = "damage_threshold"  # First blood, half HP
    NEW_AREA = "new_area"                  # Entering new hex/room
    SEARCH_ACTION = "search_action"        # Searching for secrets
    FORCED_MARCH = "forced_march"          # Exhaustion check

    # Combat-Specific
    FIRST_BLOOD = "first_blood"            # First enemy killed
    HALF_DEFEATED = "half_defeated"        # Half enemies down
    LEADER_KILLED = "leader_killed"        # Enemy leader falls
    SPELL_CAST = "spell_cast"              # Spell with consequences


class TriggerPriority(int, Enum):
    """
    Priority for trigger execution order.

    Lower numbers execute first.
    """
    CRITICAL = 0    # Must execute immediately (combat end, death)
    HIGH = 10       # Important checks (morale, encounters)
    NORMAL = 20     # Standard procedures (resource consumption)
    LOW = 30        # Deferred checks (atmosphere, descriptions)


# =============================================================================
# TRIGGER RESULT
# =============================================================================

@dataclass
class TriggerResult:
    """
    Result of executing a procedure trigger.
    """
    trigger: ProcedureTrigger
    executed: bool
    results: dict[str, Any] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)
    state_changes: dict[str, Any] = field(default_factory=dict)
    follow_up_triggers: list[ProcedureTrigger] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def brief(self) -> str:
        """Get brief summary of trigger execution."""
        if not self.executed:
            return f"{self.trigger.value}: skipped"
        if self.messages:
            return f"{self.trigger.value}: {self.messages[0]}"
        return f"{self.trigger.value}: executed"

    def to_dict(self) -> dict[str, Any]:
        """Serialize result."""
        return {
            "trigger": self.trigger.value,
            "executed": self.executed,
            "results": self.results,
            "messages": self.messages,
            "state_changes": self.state_changes,
            "follow_up_triggers": [t.value for t in self.follow_up_triggers],
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class TriggerCondition:
    """
    Condition that must be met for a trigger to fire.
    """
    check: Callable[..., bool]
    description: str

    def evaluate(self, context: dict[str, Any]) -> bool:
        """Evaluate the condition."""
        try:
            return self.check(context)
        except Exception as e:
            logger.warning(f"Trigger condition failed: {e}")
            return False


# =============================================================================
# PROCEDURE HANDLERS
# =============================================================================

class ProcedureHandler:
    """
    Base class for procedure handlers.

    Each procedure type has a handler that executes the mandatory
    steps for that procedure.
    """

    def __init__(self, name: str):
        self.name = name

    def can_execute(self, context: dict[str, Any]) -> bool:
        """Check if this handler can execute with given context."""
        return True

    def execute(self, context: dict[str, Any]) -> TriggerResult:
        """Execute the procedure."""
        raise NotImplementedError


class TravelSegmentHandler(ProcedureHandler):
    """
    Handler for end of travel segment.

    Executes:
    1. Advance time by terrain cost
    2. Check for random encounter
    3. Check for getting lost
    4. Consume resources
    5. Update party location
    """

    def __init__(self):
        super().__init__("travel_segment")

    def execute(self, context: dict[str, Any]) -> TriggerResult:
        messages = []
        results = {}
        state_changes = {}
        follow_up = []

        terrain = context.get("terrain", "forest")
        destination = context.get("destination")
        controller = context.get("controller")

        # 1. Calculate time cost
        terrain_costs = {
            "road": 1, "clear": 1, "forest": 2, "dense_forest": 3,
            "hills": 2, "mountains": 3, "swamp": 3
        }
        watches_cost = terrain_costs.get(terrain, 2)
        results["watches_spent"] = watches_cost
        messages.append(f"Travel through {terrain} takes {watches_cost} watch(es)")

        # 2. Check for random encounter
        encounter_chances = {
            "road": 1, "clear": 1, "forest": 2, "dense_forest": 3,
            "hills": 2, "mountains": 2, "swamp": 3, "ruins": 3
        }
        encounter_chance = encounter_chances.get(terrain, 2)
        encounter_roll = random.randint(1, 6)
        encounter_occurred = encounter_roll <= encounter_chance

        results["encounter_roll"] = encounter_roll
        results["encounter_chance"] = encounter_chance
        results["encounter_occurred"] = encounter_occurred

        if encounter_occurred:
            messages.append(f"ENCOUNTER! (rolled {encounter_roll} vs {encounter_chance}-in-6)")
            follow_up.append(ProcedureTrigger.UNKNOWN_NPC)  # Will trigger reaction

        # 3. Check for getting lost
        lost_chances = {
            "road": 0, "clear": 1, "forest": 2, "dense_forest": 3,
            "hills": 2, "mountains": 2, "swamp": 3
        }
        lost_chance = lost_chances.get(terrain, 1)

        if context.get("has_guide"):
            lost_chance = max(0, lost_chance - 1)

        lost_roll = random.randint(1, 6)
        got_lost = lost_chance > 0 and lost_roll <= lost_chance

        results["lost_roll"] = lost_roll
        results["lost_chance"] = lost_chance
        results["got_lost"] = got_lost

        if got_lost:
            messages.append(f"LOST! (rolled {lost_roll} vs {lost_chance}-in-6)")
            follow_up.append(ProcedureTrigger.FAILED_NAVIGATION)
            state_changes["got_lost"] = True

        # 4. Resource consumption would happen here via controller
        if controller:
            # Advance time
            time_result = controller.advance_time("watch", watches_cost)
            state_changes["time_advanced"] = watches_cost

            if time_result.get("new_day"):
                follow_up.append(ProcedureTrigger.DAY_END)

        # 5. Mark new location
        if destination and not got_lost:
            state_changes["new_hex"] = destination
            messages.append(f"Arrived at hex {destination}")

        return TriggerResult(
            trigger=ProcedureTrigger.TRAVEL_SEGMENT,
            executed=True,
            results=results,
            messages=messages,
            state_changes=state_changes,
            follow_up_triggers=follow_up
        )


class DungeonTurnHandler(ProcedureHandler):
    """
    Handler for dungeon exploration turn (10 minutes).

    Executes:
    1. Advance time by 1 turn
    2. Deplete light sources
    3. Check for wandering monsters
    4. Apply noise consequences
    """

    def __init__(self):
        super().__init__("dungeon_turn")

    def execute(self, context: dict[str, Any]) -> TriggerResult:
        messages = []
        results = {}
        state_changes = {}
        follow_up = []

        controller = context.get("controller")
        noise_level = context.get("noise_level", 0)

        # 1. Advance time
        results["turns_passed"] = 1
        messages.append("10 minutes pass...")

        # 2. Light source depletion
        if controller:
            party = controller.get_party_state()
            if party.light_source == "torch":
                party.light_remaining -= 1
                results["light_remaining"] = party.light_remaining
                if party.light_remaining <= 0:
                    messages.append("Torch sputters and dies!")
                    follow_up.append(ProcedureTrigger.LIGHT_DEPLETED)

        # 3. Wandering monster check (1-in-6, modified by noise)
        base_chance = 1
        total_chance = min(5, base_chance + noise_level)

        wander_roll = random.randint(1, 6)
        monster_appears = wander_roll <= total_chance

        results["wandering_monster_roll"] = wander_roll
        results["wandering_monster_chance"] = total_chance
        results["wandering_monster_appears"] = monster_appears

        if monster_appears:
            messages.append(f"WANDERING MONSTER! (rolled {wander_roll} vs {total_chance}-in-6)")
            follow_up.append(ProcedureTrigger.UNKNOWN_NPC)

        # 4. Apply noise consequences
        if noise_level > 0:
            results["noise_level"] = noise_level
            state_changes["noise_level"] = max(0, noise_level - 1)  # Decay noise

        return TriggerResult(
            trigger=ProcedureTrigger.DUNGEON_TURN,
            executed=True,
            results=results,
            messages=messages,
            state_changes=state_changes,
            follow_up_triggers=follow_up
        )


class CombatRoundHandler(ProcedureHandler):
    """
    Handler for end of combat round.

    Executes:
    1. Check for morale triggers
    2. Expire duration effects
    3. Advance round counter
    """

    def __init__(self):
        super().__init__("combat_round")

    def execute(self, context: dict[str, Any]) -> TriggerResult:
        messages = []
        results = {}
        state_changes = {}
        follow_up = []

        round_number = context.get("round_number", 1)
        enemies_killed = context.get("enemies_killed", 0)
        total_enemies = context.get("total_enemies", 1)

        results["round_completed"] = round_number
        messages.append(f"End of round {round_number}")

        # Check for morale trigger conditions
        # First blood
        if enemies_killed == 1 and context.get("first_blood_checked") is False:
            follow_up.append(ProcedureTrigger.FIRST_BLOOD)
            state_changes["first_blood_checked"] = True

        # Half defeated
        if enemies_killed >= total_enemies // 2 and context.get("half_defeated_checked") is False:
            follow_up.append(ProcedureTrigger.HALF_DEFEATED)
            state_changes["half_defeated_checked"] = True

        return TriggerResult(
            trigger=ProcedureTrigger.COMBAT_ROUND,
            executed=True,
            results=results,
            messages=messages,
            state_changes=state_changes,
            follow_up_triggers=follow_up
        )


class RestWatchHandler(ProcedureHandler):
    """
    Handler for rest watch.

    Executes:
    1. Advance time by 1 watch
    2. Check for night encounter
    3. Process healing/recovery
    """

    def __init__(self):
        super().__init__("rest_watch")

    def execute(self, context: dict[str, Any]) -> TriggerResult:
        messages = []
        results = {}
        state_changes = {}
        follow_up = []

        watch_number = context.get("watch_number", 1)
        is_wilderness = context.get("is_wilderness", True)

        messages.append(f"Watch {watch_number} passes")

        # Night encounter check (reduced chance while resting with watch)
        if context.get("has_watch", True):
            encounter_chance = 1  # 1-in-6
        else:
            encounter_chance = 2  # Higher without watch

        encounter_roll = random.randint(1, 6)
        encounter = encounter_roll <= encounter_chance

        results["encounter_roll"] = encounter_roll
        results["encounter_occurred"] = encounter

        if encounter:
            messages.append("The watch spots movement in the darkness!")
            follow_up.append(ProcedureTrigger.UNKNOWN_NPC)

        return TriggerResult(
            trigger=ProcedureTrigger.REST_WATCH,
            executed=True,
            results=results,
            messages=messages,
            state_changes=state_changes,
            follow_up_triggers=follow_up
        )


class DayEndHandler(ProcedureHandler):
    """
    Handler for end of day.

    Executes:
    1. Consume daily rations
    2. Apply starvation if no food
    3. Roll new weather
    4. Advance faction clocks
    """

    def __init__(self):
        super().__init__("day_end")

    def execute(self, context: dict[str, Any]) -> TriggerResult:
        messages = []
        results = {}
        state_changes = {}
        follow_up = []

        controller = context.get("controller")
        party_size = context.get("party_size", 4)

        messages.append("A new day dawns...")

        # Consume rations
        rations_needed = party_size
        results["rations_needed"] = rations_needed

        if controller:
            rations_consumed = controller.consume_resource("rations", rations_needed)
            results["rations_consumed"] = rations_consumed

            if rations_consumed < rations_needed:
                messages.append("Not enough rations! The party goes hungry.")
                follow_up.append(ProcedureTrigger.LOW_RESOURCES)
                state_changes["hunger"] = True

        # Natural healing (1 HP per day of rest - but this requires full rest)
        if context.get("full_rest", False):
            results["healing_available"] = True
            messages.append("Full rest allows natural healing")

        return TriggerResult(
            trigger=ProcedureTrigger.DAY_END,
            executed=True,
            results=results,
            messages=messages,
            state_changes=state_changes,
            follow_up_triggers=follow_up
        )


class LoudActionHandler(ProcedureHandler):
    """
    Handler for loud actions in dungeon.

    Executes:
    1. Increase noise level
    2. Immediate wandering monster check (if very loud)
    """

    def __init__(self):
        super().__init__("loud_action")

    def execute(self, context: dict[str, Any]) -> TriggerResult:
        messages = []
        results = {}
        state_changes = {}
        follow_up = []

        noise_level = context.get("noise_level", 1)
        action_description = context.get("action", "loud action")

        messages.append(f"The {action_description} echoes through the dungeon...")

        # Increase noise level
        new_noise = min(4, noise_level + 1)
        state_changes["noise_level"] = new_noise
        results["noise_level"] = new_noise

        # Very loud actions trigger immediate check
        if noise_level >= 3:
            check_roll = random.randint(1, 6)
            immediate_monster = check_roll <= 2

            results["immediate_check_roll"] = check_roll
            results["immediate_monster"] = immediate_monster

            if immediate_monster:
                messages.append("The noise attracts attention!")
                follow_up.append(ProcedureTrigger.UNKNOWN_NPC)

        return TriggerResult(
            trigger=ProcedureTrigger.LOUD_ACTION,
            executed=True,
            results=results,
            messages=messages,
            state_changes=state_changes,
            follow_up_triggers=follow_up
        )


class UnknownNPCHandler(ProcedureHandler):
    """
    Handler for encountering unknown NPC/monster.

    Executes:
    1. Determine distance
    2. Check for surprise
    3. Roll reaction (if applicable)
    """

    def __init__(self):
        super().__init__("unknown_npc")

    def execute(self, context: dict[str, Any]) -> TriggerResult:
        messages = []
        results = {}
        state_changes = {}
        follow_up = []

        terrain = context.get("terrain", "dungeon")
        party_cha_mod = context.get("cha_mod", 0)

        # 1. Determine encounter distance
        if terrain == "dungeon":
            distance = random.randint(1, 6) * 10 + random.randint(1, 6) * 10
        else:
            distance = random.randint(1, 6) * 10 * 4  # Wilderness - much farther

        results["distance_feet"] = distance
        messages.append(f"Encounter at {distance} feet")

        # 2. Surprise check (each side rolls d6, 1-2 = surprised)
        party_surprise_roll = random.randint(1, 6)
        enemy_surprise_roll = random.randint(1, 6)

        party_surprised = party_surprise_roll <= 2
        enemy_surprised = enemy_surprise_roll <= 2

        results["party_surprise_roll"] = party_surprise_roll
        results["enemy_surprise_roll"] = enemy_surprise_roll
        results["party_surprised"] = party_surprised
        results["enemy_surprised"] = enemy_surprised

        if party_surprised and not enemy_surprised:
            messages.append("The party is surprised!")
            state_changes["surprise"] = "party"
        elif enemy_surprised and not party_surprised:
            messages.append("The party surprises the encounter!")
            state_changes["surprise"] = "enemy"

        # 3. Reaction roll (2d6 + CHA mod)
        reaction_roll = random.randint(1, 6) + random.randint(1, 6) + party_cha_mod
        results["reaction_roll"] = reaction_roll

        # Reaction table
        if reaction_roll <= 2:
            reaction = "hostile"
            messages.append("Immediate attack!")
        elif reaction_roll <= 5:
            reaction = "unfriendly"
            messages.append("Hostile but not attacking yet")
        elif reaction_roll <= 8:
            reaction = "neutral"
            messages.append("Uncertain, waiting to see what happens")
        elif reaction_roll <= 11:
            reaction = "indifferent"
            messages.append("Not interested in the party")
        else:
            reaction = "friendly"
            messages.append("Friendly and willing to talk")

        results["reaction"] = reaction
        state_changes["encounter_reaction"] = reaction

        return TriggerResult(
            trigger=ProcedureTrigger.UNKNOWN_NPC,
            executed=True,
            results=results,
            messages=messages,
            state_changes=state_changes,
            follow_up_triggers=follow_up
        )


class DamageThresholdHandler(ProcedureHandler):
    """
    Handler for damage threshold events.

    Executes:
    1. Check morale for first blood
    2. Check morale for half defeated
    """

    def __init__(self):
        super().__init__("damage_threshold")

    def execute(self, context: dict[str, Any]) -> TriggerResult:
        messages = []
        results = {}
        state_changes = {}
        follow_up = []

        threshold_type = context.get("threshold_type", "first_blood")
        morale_score = context.get("morale_score", 7)

        # Roll morale
        morale_roll = random.randint(1, 6) + random.randint(1, 6)
        passed = morale_roll <= morale_score

        results["morale_roll"] = morale_roll
        results["morale_score"] = morale_score
        results["morale_passed"] = passed

        if passed:
            messages.append(f"Morale check passed ({morale_roll} vs {morale_score})")
        else:
            messages.append(f"MORALE BROKEN! ({morale_roll} vs {morale_score})")
            state_changes["enemies_flee"] = True

        return TriggerResult(
            trigger=ProcedureTrigger.DAMAGE_THRESHOLD,
            executed=True,
            results=results,
            messages=messages,
            state_changes=state_changes,
            follow_up_triggers=follow_up
        )


class SearchActionHandler(ProcedureHandler):
    """
    Handler for search actions.

    Executes:
    1. Roll for secret door/trap discovery
    2. Advance time (1 turn)
    3. Check for wandering monster
    """

    def __init__(self):
        super().__init__("search_action")

    def execute(self, context: dict[str, Any]) -> TriggerResult:
        messages = []
        results = {}
        state_changes = {}
        follow_up = []

        search_skill = context.get("search_skill", 2)  # Default 2-in-6
        area = context.get("area", "10x10 area")

        messages.append(f"Searching the {area}...")

        # Search roll
        search_roll = random.randint(1, 6)
        found_something = search_roll <= search_skill

        results["search_roll"] = search_roll
        results["search_skill"] = search_skill
        results["found"] = found_something

        if found_something:
            messages.append("Something is discovered!")
            results["discovery"] = True
        else:
            messages.append("Nothing found")
            results["discovery"] = False

        # This takes 1 turn - trigger dungeon turn
        follow_up.append(ProcedureTrigger.DUNGEON_TURN)

        return TriggerResult(
            trigger=ProcedureTrigger.SEARCH_ACTION,
            executed=True,
            results=results,
            messages=messages,
            state_changes=state_changes,
            follow_up_triggers=follow_up
        )


# =============================================================================
# TRIGGER HANDLER REGISTRY
# =============================================================================

class TriggerHandler:
    """
    Central handler for all procedure triggers.

    Routes triggers to appropriate handlers and manages execution order.
    """

    def __init__(
        self,
        state_machine: Optional["StateMachine"] = None,
        controller: Optional["GlobalController"] = None
    ):
        self.state_machine = state_machine
        self.controller = controller

        # Register handlers
        self._handlers: dict[ProcedureTrigger, ProcedureHandler] = {
            ProcedureTrigger.TRAVEL_SEGMENT: TravelSegmentHandler(),
            ProcedureTrigger.DUNGEON_TURN: DungeonTurnHandler(),
            ProcedureTrigger.COMBAT_ROUND: CombatRoundHandler(),
            ProcedureTrigger.REST_WATCH: RestWatchHandler(),
            ProcedureTrigger.DAY_END: DayEndHandler(),
            ProcedureTrigger.LOUD_ACTION: LoudActionHandler(),
            ProcedureTrigger.UNKNOWN_NPC: UnknownNPCHandler(),
            ProcedureTrigger.DAMAGE_THRESHOLD: DamageThresholdHandler(),
            ProcedureTrigger.FIRST_BLOOD: DamageThresholdHandler(),
            ProcedureTrigger.HALF_DEFEATED: DamageThresholdHandler(),
            ProcedureTrigger.SEARCH_ACTION: SearchActionHandler(),
        }

        # Execution log
        self._execution_log: list[TriggerResult] = []

    def handle_trigger(
        self,
        trigger: ProcedureTrigger,
        context: Optional[dict[str, Any]] = None
    ) -> TriggerResult:
        """
        Handle a procedure trigger.

        Args:
            trigger: The trigger to handle.
            context: Context for the trigger.

        Returns:
            TriggerResult with execution results.
        """
        context = context or {}

        # Add controller to context if available
        if self.controller and "controller" not in context:
            context["controller"] = self.controller

        # Get handler
        handler = self._handlers.get(trigger)
        if not handler:
            logger.warning(f"No handler for trigger: {trigger.value}")
            return TriggerResult(
                trigger=trigger,
                executed=False,
                messages=[f"No handler for {trigger.value}"]
            )

        # Check if handler can execute
        if not handler.can_execute(context):
            return TriggerResult(
                trigger=trigger,
                executed=False,
                messages=["Conditions not met for execution"]
            )

        # Execute handler
        try:
            result = handler.execute(context)
            self._execution_log.append(result)

            # Handle follow-up triggers
            for follow_up in result.follow_up_triggers:
                follow_up_result = self.handle_trigger(follow_up, context)
                result.results[f"follow_up_{follow_up.value}"] = follow_up_result.to_dict()

            logger.info(f"Trigger executed: {trigger.value}")
            return result

        except Exception as e:
            logger.error(f"Trigger execution failed: {e}")
            return TriggerResult(
                trigger=trigger,
                executed=False,
                messages=[f"Execution failed: {str(e)}"]
            )

    def register_handler(
        self,
        trigger: ProcedureTrigger,
        handler: ProcedureHandler
    ) -> None:
        """Register a custom handler for a trigger."""
        self._handlers[trigger] = handler

    def get_execution_log(self) -> list[TriggerResult]:
        """Get the execution log."""
        return self._execution_log.copy()

    def clear_execution_log(self) -> None:
        """Clear the execution log."""
        self._execution_log.clear()


# =============================================================================
# AUTOMATIC TRIGGER CHECKER
# =============================================================================

class AutomaticTriggerChecker:
    """
    Checks for triggers that should fire automatically based on state.

    This runs periodically to catch any missed automatic triggers.
    """

    def __init__(
        self,
        trigger_handler: TriggerHandler,
        controller: Optional["GlobalController"] = None
    ):
        self.trigger_handler = trigger_handler
        self.controller = controller

        # Track what we've checked
        self._last_day_checked: int = 0
        self._last_watch_checked: int = 0

    def check_time_triggers(self) -> list[TriggerResult]:
        """
        Check for time-based triggers.

        Returns:
            List of trigger results for any fired triggers.
        """
        results = []

        if not self.controller:
            return results

        time = self.controller.get_current_time()

        # Day end trigger
        if time.day > self._last_day_checked:
            result = self.trigger_handler.handle_trigger(
                ProcedureTrigger.DAY_END,
                {"party_size": self.controller.get_party_state().party_size}
            )
            results.append(result)
            self._last_day_checked = time.day

        return results

    def check_resource_triggers(self) -> list[TriggerResult]:
        """
        Check for resource-based triggers.

        Returns:
            List of trigger results for any fired triggers.
        """
        results = []

        if not self.controller:
            return results

        party = self.controller.get_party_state()

        # Low resources
        if party.resources.rations <= 0:
            result = self.trigger_handler.handle_trigger(
                ProcedureTrigger.LOW_RESOURCES,
                {"resource": "rations", "amount": 0}
            )
            results.append(result)

        # Light depleted
        if party.light_source and party.light_remaining <= 0:
            result = self.trigger_handler.handle_trigger(
                ProcedureTrigger.LIGHT_DEPLETED,
                {}
            )
            results.append(result)

        return results


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_trigger_handler(
    state_machine: Optional["StateMachine"] = None,
    controller: Optional["GlobalController"] = None
) -> TriggerHandler:
    """
    Create a new trigger handler.

    Args:
        state_machine: Optional state machine for state checks.
        controller: Optional global controller for state access.

    Returns:
        Configured TriggerHandler.
    """
    return TriggerHandler(state_machine=state_machine, controller=controller)
