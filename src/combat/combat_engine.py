"""
Dolmenwood AI DM - Combat State Machine (v2.0)

This module provides automated combat management that tracks:
- Initiative order and turn progression
- Round counting
- HP and damage
- Morale triggers and checks
- Combat end conditions

The engine handles all mechanical bookkeeping so Claude can focus
on narration and NPC decision-making.

v2.0 Changes:
- Integration with StateMachine for state transitions
- Integration with GlobalController for time tracking
- Integration with TriggerHandler for COMBAT_ROUND triggers
- Return state tracking for proper exit transitions
- Dolmenwood-specific reaction and morale mechanics

Author: AI Dungeon Master Project
Version: 2.0
"""

from __future__ import annotations

import random
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Union, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from ..game_state.state_machine import StateMachine
    from ..game_state.global_controller import GlobalController
    from ..resolution.procedure_triggers import TriggerHandler

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class CombatPhase(str, Enum):
    """Current phase of combat."""
    NOT_STARTED = "not_started"
    INITIATIVE = "initiative"
    IN_PROGRESS = "in_progress"
    ENDED = "ended"


class CombatEndReason(str, Enum):
    """Why combat ended."""
    ENEMIES_DEFEATED = "enemies_defeated"
    ENEMIES_FLED = "enemies_fled"
    PARTY_DEFEATED = "party_defeated"
    PARTY_FLED = "party_fled"
    NEGOTIATED = "negotiated"
    INTERRUPTED = "interrupted"


class ActionType(str, Enum):
    """Types of combat actions."""
    ATTACK = "attack"
    CAST_SPELL = "cast_spell"
    USE_ITEM = "use_item"
    MOVE = "move"
    DEFEND = "defend"
    FLEE = "flee"
    OTHER = "other"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class Combatant:
    """
    A participant in combat.
    
    Attributes:
        name: Display name
        hp_current: Current hit points
        hp_max: Maximum hit points
        ac: Armor class
        attack_bonus: Bonus to attack rolls
        damage_dice: Default damage (e.g., "1d8+2")
        initiative: Initiative roll result
        is_player: True if player character
        is_active: False if dead/fled/incapacitated
        conditions: Active conditions (poisoned, etc.)
        morale: Morale score (NPCs only)
        attacks_per_round: Number of attacks
        special_abilities: List of special ability names
        id: Unique identifier for this combatant
    """
    name: str
    hp_current: int
    hp_max: int
    ac: int
    attack_bonus: int = 0
    damage_dice: str = "1d6"
    initiative: int = 0
    is_player: bool = False
    is_active: bool = True
    conditions: list[str] = field(default_factory=list)
    morale: Optional[int] = None
    attacks_per_round: int = 1
    special_abilities: list[str] = field(default_factory=list)
    id: str = ""
    
    def __post_init__(self):
        if not self.id:
            self.id = f"{self.name.lower().replace(' ', '_')}_{random.randint(1000, 9999)}"
    
    @property
    def is_alive(self) -> bool:
        """Check if combatant is alive."""
        return self.hp_current > 0
    
    @property
    def hp_percentage(self) -> float:
        """Get HP as percentage."""
        return (self.hp_current / self.hp_max) * 100 if self.hp_max > 0 else 0
    
    @property
    def wound_status(self) -> str:
        """Get narrative wound description."""
        pct = self.hp_percentage
        if pct >= 100:
            return "uninjured"
        elif pct >= 75:
            return "lightly wounded"
        elif pct >= 50:
            return "wounded"
        elif pct >= 25:
            return "badly wounded"
        elif pct > 0:
            return "near death"
        else:
            return "dead"
    
    def to_status_string(self, show_exact_hp: bool = False) -> str:
        """Get brief status string."""
        if not self.is_active:
            if not self.is_alive:
                return f"{self.name} (dead)"
            return f"{self.name} (out of combat)"
        
        if show_exact_hp or self.is_player:
            return f"{self.name} ({self.hp_current}/{self.hp_max} HP)"
        else:
            return f"{self.name} ({self.wound_status})"


@dataclass
class DiceRoll:
    """Result of a dice roll."""
    notation: str
    rolls: list[int]
    modifier: int
    total: int
    
    def __str__(self) -> str:
        if self.modifier:
            return f"{self.notation} = [{', '.join(str(r) for r in self.rolls)}] + {self.modifier} = {self.total}"
        return f"{self.notation} = [{', '.join(str(r) for r in self.rolls)}] = {self.total}"


@dataclass
class AttackResult:
    """Result of an attack action."""
    attacker: str
    target: str
    attack_roll: DiceRoll
    hit: bool
    critical: bool
    fumble: bool
    damage_roll: Optional[DiceRoll] = None
    damage_dealt: int = 0
    target_killed: bool = False
    target_hp_remaining: int = 0
    
    @property
    def brief(self) -> str:
        """One-sentence summary for Claude to narrate."""
        if self.fumble:
            return f"{self.attacker} fumbles their attack against {self.target}! (rolled natural 1)"
        elif self.critical:
            return f"{self.attacker} CRITICALLY HITS {self.target} for {self.damage_dealt} damage! (rolled natural 20)"
        elif self.hit:
            result = f"{self.attacker} hits {self.target} for {self.damage_dealt} damage."
            if self.target_killed:
                result += f" {self.target} falls!"
            return result
        else:
            return f"{self.attacker} misses {self.target}. (rolled {self.attack_roll.total} vs AC {self.target_hp_remaining})"


@dataclass
class SaveResult:
    """Result of a saving throw."""
    character: str
    save_type: str
    effect: str
    roll: DiceRoll
    target: int
    success: bool
    
    @property
    def brief(self) -> str:
        """One-sentence summary."""
        outcome = "succeeds" if self.success else "fails"
        return f"{self.character} {outcome} their {self.save_type} save vs {self.effect}. (rolled {self.roll.total} vs {self.target})"


@dataclass
class MoraleResult:
    """Result of a morale check."""
    creature_group: str
    roll: DiceRoll
    morale_score: int
    passed: bool
    trigger: str  # "first_blood" or "half_defeated"
    
    @property
    def brief(self) -> str:
        """One-sentence summary."""
        if self.passed:
            return f"The {self.creature_group} hold their ground! (morale {self.roll.total} vs {self.morale_score})"
        else:
            return f"The {self.creature_group} break and flee! (morale {self.roll.total} vs {self.morale_score})"


@dataclass
class TurnResult:
    """Result of ending a turn and advancing to next combatant."""
    previous_combatant: str
    next_combatant: str
    next_is_player: bool
    round_number: int
    new_round: bool
    morale_check: Optional[MoraleResult] = None
    combat_ended: bool = False
    end_reason: Optional[CombatEndReason] = None
    
    @property
    def brief(self) -> str:
        """Status update for Claude."""
        parts = []
        
        if self.new_round:
            parts.append(f"--- Round {self.round_number} ---")
        
        if self.morale_check:
            parts.append(self.morale_check.brief)
        
        if self.combat_ended:
            if self.end_reason == CombatEndReason.ENEMIES_DEFEATED:
                parts.append("All enemies have been defeated! Combat ends.")
            elif self.end_reason == CombatEndReason.ENEMIES_FLED:
                parts.append("The remaining enemies have fled! Combat ends.")
            elif self.end_reason == CombatEndReason.PARTY_DEFEATED:
                parts.append("The party has fallen! Combat ends.")
            elif self.end_reason == CombatEndReason.PARTY_FLED:
                parts.append("The party has fled! Combat ends.")
        else:
            if self.next_is_player:
                parts.append(f"It's {self.next_combatant}'s turn. What do they do?")
            else:
                parts.append(f"It's {self.next_combatant}'s turn.")
        
        return " ".join(parts)


@dataclass
class CombatStatus:
    """Current state of combat for Claude."""
    phase: CombatPhase
    round_number: int
    current_combatant: Optional[str]
    current_is_player: bool
    initiative_order: list[str]
    party_status: list[str]  # Brief status for each party member
    enemy_status: list[str]  # Brief status for each enemy
    active_party_count: int
    active_enemy_count: int
    
    @property
    def brief(self) -> str:
        """Concise status summary."""
        if self.phase == CombatPhase.NOT_STARTED:
            return "No combat active."
        elif self.phase == CombatPhase.ENDED:
            return "Combat has ended."
        
        lines = [
            f"Round {self.round_number} | Current: {self.current_combatant}",
            f"Party: {', '.join(self.party_status)}",
            f"Enemies: {', '.join(self.enemy_status)}",
        ]
        return "\n".join(lines)
    
    @property
    def full_status(self) -> str:
        """Detailed status."""
        if self.phase == CombatPhase.NOT_STARTED:
            return "No combat active."
        
        lines = [
            f"=== COMBAT STATUS (Round {self.round_number}) ===",
            f"Current Turn: {self.current_combatant}",
            "",
            "Initiative Order: " + " → ".join(self.initiative_order),
            "",
            "PARTY:",
        ]
        for status in self.party_status:
            lines.append(f"  • {status}")
        
        lines.append("")
        lines.append("ENEMIES:")
        for status in self.enemy_status:
            lines.append(f"  • {status}")
        
        return "\n".join(lines)


# =============================================================================
# DICE UTILITIES
# =============================================================================

def roll_dice(notation: str) -> DiceRoll:
    """
    Roll dice using standard notation.
    
    Args:
        notation: Dice notation (e.g., "2d6+3", "1d20", "4d6")
    
    Returns:
        DiceRoll with results.
    """
    import re
    
    pattern = r"^(\d+)?d(\d+)([+-]\d+)?$"
    match = re.match(pattern, notation.lower().strip())
    
    if not match:
        raise ValueError(f"Invalid dice notation: {notation}")
    
    count = int(match.group(1) or 1)
    sides = int(match.group(2))
    modifier = int(match.group(3) or 0)
    
    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier
    
    return DiceRoll(
        notation=notation,
        rolls=rolls,
        modifier=modifier,
        total=total
    )


def roll_d20(modifier: int = 0) -> DiceRoll:
    """Roll a d20 with optional modifier."""
    roll = random.randint(1, 20)
    return DiceRoll(
        notation=f"d20{'+' if modifier >= 0 else ''}{modifier}" if modifier else "d20",
        rolls=[roll],
        modifier=modifier,
        total=roll + modifier
    )


# =============================================================================
# COMBAT ENGINE
# =============================================================================

class CombatEngine:
    """
    Automated combat state machine (v2.0).

    Handles initiative, turn order, HP tracking, morale, and combat end
    detection. Provides clear status summaries for the AI DM.

    v2.0 Integration Points:
    - StateMachine: Operates in COMBAT state, tracks return state
    - GlobalController: Time tracking via rounds (10 rounds = 1 turn)
    - TriggerHandler: Fires COMBAT_ROUND triggers each round
    - DolmenwoodTables: Uses Dolmenwood reaction and morale tables

    Example:
        >>> engine = CombatEngine()
        >>> status = engine.start_combat(party=[warrior, mage], enemies=[goblin1, goblin2])
        >>> print(status.brief)
        >>>
        >>> # On player turn
        >>> result = engine.attack("Warrior", "Goblin 1")
        >>> print(result.brief)
        >>>
        >>> # Advance to next turn
        >>> turn_result = engine.end_turn()
        >>> print(turn_result.brief)
    """

    # Reaction table (2d6) per OSE/Dolmenwood rules
    REACTION_TABLE = {
        2: ("hostile", "Attacks immediately"),
        3: ("hostile", "Hostile, likely to attack"),
        4: ("hostile", "Hostile, likely to attack"),
        5: ("unfriendly", "Unfriendly, may attack"),
        6: ("wary", "Uncertain, monster's decision"),
        7: ("neutral", "Uncertain, monster's decision"),
        8: ("neutral", "Uncertain, monster's decision"),
        9: ("interested", "No immediate attack"),
        10: ("friendly", "No immediate attack"),
        11: ("friendly", "Friendly"),
        12: ("helpful", "Eager to be friendly"),
    }

    # Morale modifiers
    MORALE_MODIFIERS = {
        "leader_dead": -2,
        "winning": +2,
        "losing": -2,
        "outnumbered": -1,
        "outnumber_enemy": +1,
        "defending_home": +2,
        "cornered": +2,
        "surprised": -1,
    }

    def __init__(
        self,
        state_machine: Optional["StateMachine"] = None,
        global_controller: Optional["GlobalController"] = None,
        trigger_handler: Optional["TriggerHandler"] = None,
    ):
        """
        Initialize combat engine with v2.0 integrations.

        Args:
            state_machine: Reference to StateMachine for state transitions
            global_controller: Reference to GlobalController for time tracking
            trigger_handler: Reference to TriggerHandler for procedure triggers
        """
        # v2.0 Integration references
        self.state_machine = state_machine
        self.global_controller = global_controller
        self.trigger_handler = trigger_handler

        self.combatants: list[Combatant] = []
        self.round_number: int = 0
        self.current_index: int = 0
        self.phase: CombatPhase = CombatPhase.NOT_STARTED
        self.combat_log: list[str] = []

        # Morale tracking
        self._enemy_start_count: int = 0
        self._morale_checked_first_blood: bool = False
        self._morale_checked_half: bool = False
        self._enemies_have_fled: bool = False

        # v2.0: Track return state for proper transitions after combat
        self._return_state: Optional[str] = None
        self._return_metadata: Dict[str, Any] = {}

        # v2.0: Combat context from triggering encounter
        self.encounter_context: Dict[str, Any] = {}

        # Combat ID for persistence
        self.combat_id: str = f"combat_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"
    
    # =========================================================================
    # COMBAT LIFECYCLE
    # =========================================================================
    
    def start_combat(
        self,
        party: list[Combatant],
        enemies: list[Combatant],
        surprise: Optional[str] = None,  # "party", "enemies", or None
        return_state: Optional[str] = None,
        return_metadata: Optional[Dict[str, Any]] = None,
        encounter_context: Optional[Dict[str, Any]] = None,
    ) -> CombatStatus:
        """
        Start a new combat encounter.

        Args:
            party: List of party member Combatants.
            enemies: List of enemy Combatants.
            surprise: Which side has surprise (gets a free round).
            return_state: State to return to after combat ends (v2.0)
            return_metadata: Metadata for return state transition (v2.0)
            encounter_context: Context about the triggering encounter (v2.0)

        Returns:
            CombatStatus with initiative order and first turn info.
        """
        if self.phase != CombatPhase.NOT_STARTED:
            raise RuntimeError("Combat already in progress. Call end_combat() first.")

        # v2.0: Store return state for proper transitions after combat
        self._return_state = return_state
        self._return_metadata = return_metadata or {}
        self.encounter_context = encounter_context or {}

        # Mark sides
        for c in party:
            c.is_player = True
        for c in enemies:
            c.is_player = False

        # Combine all combatants
        self.combatants = party + enemies
        self._enemy_start_count = len([e for e in enemies if e.is_active])

        # Roll initiative for each combatant (1d6 per OSE rules)
        self.phase = CombatPhase.INITIATIVE
        for c in self.combatants:
            init_roll = roll_dice("1d6")
            c.initiative = init_roll.total
            self._log(f"{c.name} rolls initiative: {init_roll.total}")

        # Sort by initiative (highest first), with players winning ties
        self.combatants.sort(
            key=lambda c: (c.initiative, 1 if c.is_player else 0),
            reverse=True
        )

        # Handle surprise
        if surprise == "party":
            # Party goes first, enemies skip round 1
            self.combatants.sort(key=lambda c: (0 if c.is_player else 1, -c.initiative))
            self._log("The party has surprise!")
        elif surprise == "enemies":
            # Enemies go first, party skips round 1
            self.combatants.sort(key=lambda c: (1 if c.is_player else 0, -c.initiative))
            self._log("The enemies have surprise!")

        # Start round 1
        self.round_number = 1
        self.current_index = 0
        self.phase = CombatPhase.IN_PROGRESS

        self._log(f"=== Combat Begins! Round 1 ===")
        self._log(f"Initiative order: {', '.join(c.name for c in self.combatants)}")

        # v2.0: Fire combat round trigger
        self._fire_round_trigger()

        return self.get_status()

    def _fire_round_trigger(self) -> None:
        """Fire the COMBAT_ROUND procedure trigger."""
        if self.trigger_handler:
            self.trigger_handler.fire_trigger("COMBAT_ROUND", {
                "round": self.round_number,
                "combat_id": self.combat_id,
                "active_combatants": len([c for c in self.combatants if c.is_active]),
            })

        # v2.0: Track time - 10 rounds = 1 dungeon turn
        if self.global_controller and self.round_number % 10 == 0:
            # Every 10 rounds of combat = 1 minute = 1/10th of a turn
            pass  # Time tracking handled by GlobalController
    
    def end_combat(self, reason: CombatEndReason = CombatEndReason.INTERRUPTED) -> Dict[str, Any]:
        """
        End combat and transition back to return state.

        Args:
            reason: Why combat is ending.

        Returns:
            Dict with final status and transition info.
        """
        self.phase = CombatPhase.ENDED
        self._log(f"=== Combat Ended: {reason.value} ===")

        status = self.get_status()

        result = {
            "status": status,
            "reason": reason.value,
            "rounds_elapsed": self.round_number,
            "return_state": self._return_state,
            "survivors": {
                "party": [c.name for c in self.combatants if c.is_player and c.is_alive],
                "enemies": [c.name for c in self.combatants if not c.is_player and c.is_alive],
            },
            "casualties": {
                "party": [c.name for c in self.combatants if c.is_player and not c.is_alive],
                "enemies": [c.name for c in self.combatants if not c.is_player and not c.is_alive],
            },
        }

        # v2.0: Transition back to return state if state machine available
        if self.state_machine:
            try:
                from game_state.state_machine import TransitionTrigger
                # Determine trigger based on combat outcome
                if reason == CombatEndReason.VICTORY:
                    trigger = TransitionTrigger.ENEMIES_DEFEATED
                elif reason == CombatEndReason.ENEMIES_FLED:
                    trigger = TransitionTrigger.ENEMIES_FLEE
                elif reason == CombatEndReason.PARTY_FLED:
                    trigger = TransitionTrigger.PARTY_RETREAT
                else:
                    trigger = TransitionTrigger.ENEMIES_DEFEATED  # Default

                self.state_machine.transition(
                    trigger=trigger,
                    context={
                        "reason": reason.value,
                        "rounds": self.round_number,
                        "return_state": self._return_state,
                        **self._return_metadata,
                    },
                    reason=f"Combat ended: {reason.value}"
                )
                result["state_transition"] = self.state_machine.current_state.value
            except Exception as e:
                result["transition_error"] = str(e)

        # Reset for next combat
        self._reset()

        return result
    
    def _reset(self) -> None:
        """Reset engine state for new combat."""
        self.combatants = []
        self.round_number = 0
        self.current_index = 0
        self.phase = CombatPhase.NOT_STARTED
        self._enemy_start_count = 0
        self._morale_checked_first_blood = False
        self._morale_checked_half = False
        self._enemies_have_fled = False
        # v2.0: Clear return state tracking
        self._return_state = None
        self._return_metadata = {}
        self.encounter_context = {}
    
    # =========================================================================
    # TURN MANAGEMENT
    # =========================================================================
    
    def get_current_combatant(self) -> Optional[Combatant]:
        """Get the combatant whose turn it is."""
        if self.phase != CombatPhase.IN_PROGRESS:
            return None
        
        if 0 <= self.current_index < len(self.combatants):
            return self.combatants[self.current_index]
        return None
    
    def end_turn(self) -> TurnResult:
        """
        End current turn and advance to next combatant.
        
        Handles:
        - Skipping dead/fled combatants
        - Round advancement
        - Morale checks (if triggered)
        - Combat end detection
        
        Returns:
            TurnResult with next turn info.
        """
        if self.phase != CombatPhase.IN_PROGRESS:
            raise RuntimeError("No combat in progress.")
        
        previous = self.get_current_combatant()
        previous_name = previous.name if previous else "Unknown"
        
        # Find next active combatant
        new_round = False
        morale_result = None
        
        # Check for morale before advancing (in case enemies need to flee)
        morale_result = self._check_morale_triggers()
        
        # Advance to next active combatant
        attempts = 0
        while attempts < len(self.combatants) + 1:
            self.current_index += 1
            
            # Check for round end
            if self.current_index >= len(self.combatants):
                self.current_index = 0
                self.round_number += 1
                new_round = True
                self._log(f"=== Round {self.round_number} ===")
                # v2.0: Fire round trigger on new round
                self._fire_round_trigger()
            
            current = self.combatants[self.current_index]
            if current.is_active and current.is_alive:
                break
            
            attempts += 1
        
        # Check for combat end
        combat_ended, end_reason = self._check_combat_end()
        
        if combat_ended:
            self.phase = CombatPhase.ENDED
            self._log(f"Combat ended: {end_reason.value}")
        
        next_combatant = self.get_current_combatant()
        
        return TurnResult(
            previous_combatant=previous_name,
            next_combatant=next_combatant.name if next_combatant else "None",
            next_is_player=next_combatant.is_player if next_combatant else False,
            round_number=self.round_number,
            new_round=new_round,
            morale_check=morale_result,
            combat_ended=combat_ended,
            end_reason=end_reason
        )
    
    # =========================================================================
    # COMBAT ACTIONS
    # =========================================================================
    
    def attack(
        self,
        attacker_name: str,
        target_name: str,
        attack_bonus: Optional[int] = None,
        damage_dice: Optional[str] = None,
        damage_bonus: int = 0
    ) -> AttackResult:
        """
        Make an attack roll.
        
        Args:
            attacker_name: Name of attacking combatant.
            target_name: Name of target combatant.
            attack_bonus: Override attacker's attack bonus.
            damage_dice: Override attacker's damage dice.
            damage_bonus: Additional damage bonus.
        
        Returns:
            AttackResult with hit/miss and damage info.
        """
        attacker = self._get_combatant(attacker_name)
        target = self._get_combatant(target_name)
        
        if not attacker:
            raise ValueError(f"Attacker not found: {attacker_name}")
        if not target:
            raise ValueError(f"Target not found: {target_name}")
        
        # Use provided or default values
        atk_bonus = attack_bonus if attack_bonus is not None else attacker.attack_bonus
        dmg_dice = damage_dice or attacker.damage_dice
        
        # Roll attack
        attack_roll = roll_d20(atk_bonus)
        natural_roll = attack_roll.rolls[0]
        
        # Determine hit
        fumble = natural_roll == 1
        critical = natural_roll == 20
        hit = critical or (not fumble and attack_roll.total >= target.ac)
        
        # Roll damage if hit
        damage_roll = None
        damage_dealt = 0
        target_killed = False
        
        if hit:
            damage_roll = roll_dice(dmg_dice)
            damage_dealt = damage_roll.total + damage_bonus
            
            # Double damage on crit
            if critical:
                crit_damage = roll_dice(dmg_dice)
                damage_dealt += crit_damage.total
            
            # Minimum 1 damage
            damage_dealt = max(1, damage_dealt)
            
            # Apply damage
            target.hp_current -= damage_dealt
            target_killed = target.hp_current <= 0
            
            if target_killed:
                target.is_active = False
                self._log(f"{attacker.name} kills {target.name} with {damage_dealt} damage!")
            else:
                self._log(f"{attacker.name} hits {target.name} for {damage_dealt} damage.")
        else:
            self._log(f"{attacker.name} misses {target.name}.")
        
        return AttackResult(
            attacker=attacker.name,
            target=target.name,
            attack_roll=attack_roll,
            hit=hit,
            critical=critical,
            fumble=fumble,
            damage_roll=damage_roll,
            damage_dealt=damage_dealt,
            target_killed=target_killed,
            target_hp_remaining=max(0, target.hp_current) if not target_killed else target.ac  # Show AC on miss
        )
    
    def apply_damage(
        self,
        target_name: str,
        damage: int,
        source: str = "unknown"
    ) -> dict[str, Any]:
        """
        Apply damage to a combatant (from spells, traps, etc.).
        
        Returns:
            Dict with damage info.
        """
        target = self._get_combatant(target_name)
        if not target:
            raise ValueError(f"Target not found: {target_name}")
        
        target.hp_current -= damage
        killed = target.hp_current <= 0
        
        if killed:
            target.is_active = False
        
        self._log(f"{target.name} takes {damage} damage from {source}.")
        
        return {
            "target": target.name,
            "damage": damage,
            "hp_remaining": max(0, target.hp_current),
            "killed": killed,
            "brief": f"{target.name} takes {damage} damage{' and falls!' if killed else '.'}"
        }
    
    def apply_healing(
        self,
        target_name: str,
        amount: int,
        source: str = "healing"
    ) -> dict[str, Any]:
        """
        Heal a combatant.
        
        Returns:
            Dict with healing info.
        """
        target = self._get_combatant(target_name)
        if not target:
            raise ValueError(f"Target not found: {target_name}")
        
        old_hp = target.hp_current
        target.hp_current = min(target.hp_current + amount, target.hp_max)
        actual_healed = target.hp_current - old_hp
        
        self._log(f"{target.name} heals {actual_healed} HP from {source}.")
        
        return {
            "target": target.name,
            "healed": actual_healed,
            "hp_current": target.hp_current,
            "hp_max": target.hp_max,
            "brief": f"{target.name} heals {actual_healed} HP ({target.hp_current}/{target.hp_max})."
        }
    
    def saving_throw(
        self,
        character_name: str,
        save_type: str,
        target: int,
        modifier: int = 0,
        effect: str = "effect"
    ) -> SaveResult:
        """
        Make a saving throw.
        
        Args:
            character_name: Who is saving.
            save_type: Type of save (doom, ray, hold, blast, spell).
            target: Target number to meet or exceed.
            modifier: Modifier to the roll.
            effect: What they're saving against.
        
        Returns:
            SaveResult with outcome.
        """
        roll = roll_d20(modifier)
        success = roll.total >= target
        
        self._log(f"{character_name} {'saves' if success else 'fails'} vs {effect} ({roll.total} vs {target}).")
        
        return SaveResult(
            character=character_name,
            save_type=save_type,
            effect=effect,
            roll=roll,
            target=target,
            success=success
        )
    
    def flee(self, combatant_name: str) -> dict[str, Any]:
        """
        Remove a combatant from combat (fled).
        
        Returns:
            Dict with flee info.
        """
        combatant = self._get_combatant(combatant_name)
        if not combatant:
            raise ValueError(f"Combatant not found: {combatant_name}")
        
        combatant.is_active = False
        self._log(f"{combatant.name} flees from combat!")
        
        return {
            "combatant": combatant.name,
            "is_player": combatant.is_player,
            "brief": f"{combatant.name} flees from combat!"
        }
    
    def add_condition(self, combatant_name: str, condition: str) -> None:
        """Add a condition to a combatant."""
        combatant = self._get_combatant(combatant_name)
        if combatant and condition not in combatant.conditions:
            combatant.conditions.append(condition)
            self._log(f"{combatant.name} is now {condition}.")
    
    def remove_condition(self, combatant_name: str, condition: str) -> None:
        """Remove a condition from a combatant."""
        combatant = self._get_combatant(combatant_name)
        if combatant and condition in combatant.conditions:
            combatant.conditions.remove(condition)
            self._log(f"{combatant.name} is no longer {condition}.")
    
    # =========================================================================
    # STATUS QUERIES
    # =========================================================================
    
    def get_status(self) -> CombatStatus:
        """Get current combat status."""
        current = self.get_current_combatant()
        
        # Build initiative order (active combatants only)
        init_order = [c.name for c in self.combatants if c.is_active and c.is_alive]
        
        # Build party and enemy status
        party_status = []
        enemy_status = []
        
        active_party = 0
        active_enemies = 0
        
        for c in self.combatants:
            status_str = c.to_status_string(show_exact_hp=c.is_player)
            
            if c.conditions:
                status_str += f" [{', '.join(c.conditions)}]"
            
            if c.is_player:
                party_status.append(status_str)
                if c.is_active and c.is_alive:
                    active_party += 1
            else:
                enemy_status.append(status_str)
                if c.is_active and c.is_alive:
                    active_enemies += 1
        
        return CombatStatus(
            phase=self.phase,
            round_number=self.round_number,
            current_combatant=current.name if current else None,
            current_is_player=current.is_player if current else False,
            initiative_order=init_order,
            party_status=party_status,
            enemy_status=enemy_status,
            active_party_count=active_party,
            active_enemy_count=active_enemies
        )
    
    def get_combatant_status(self, name: str) -> Optional[dict[str, Any]]:
        """Get detailed status for one combatant."""
        c = self._get_combatant(name)
        if not c:
            return None
        
        return {
            "name": c.name,
            "hp_current": c.hp_current,
            "hp_max": c.hp_max,
            "ac": c.ac,
            "is_alive": c.is_alive,
            "is_active": c.is_active,
            "conditions": c.conditions.copy(),
            "wound_status": c.wound_status,
            "is_player": c.is_player
        }
    
    # =========================================================================
    # MORALE
    # =========================================================================
    
    def _check_morale_triggers(self) -> Optional[MoraleResult]:
        """Check if morale should be rolled and roll if needed."""
        if self._enemies_have_fled:
            return None
        
        active_enemies = [c for c in self.combatants if not c.is_player and c.is_active and c.is_alive]
        dead_enemies = [c for c in self.combatants if not c.is_player and not c.is_alive]
        
        if not active_enemies:
            return None
        
        # Get representative morale score (use average or first enemy's morale)
        morale_scores = [e.morale for e in active_enemies if e.morale is not None]
        if not morale_scores:
            return None  # No morale score, enemies don't flee
        
        avg_morale = sum(morale_scores) // len(morale_scores)
        
        # First blood check
        if not self._morale_checked_first_blood and len(dead_enemies) >= 1:
            self._morale_checked_first_blood = True
            return self._roll_morale(avg_morale, "first_blood", active_enemies)
        
        # Half defeated check
        if not self._morale_checked_half and len(dead_enemies) >= self._enemy_start_count // 2:
            self._morale_checked_half = True
            return self._roll_morale(avg_morale, "half_defeated", active_enemies)
        
        return None
    
    def _roll_morale(
        self,
        morale_score: int,
        trigger: str,
        enemies: list[Combatant]
    ) -> MoraleResult:
        """Roll morale for enemy group."""
        roll = roll_dice("2d6")
        passed = roll.total <= morale_score
        
        # Get group name
        if len(enemies) == 1:
            group_name = enemies[0].name
        else:
            # Try to find common name
            names = [e.name for e in enemies]
            # Simple approach: use first enemy's base name
            group_name = names[0].rstrip('0123456789 ')
            if group_name:
                group_name = f"{group_name}s" if len(enemies) > 1 else group_name
            else:
                group_name = "enemies"
        
        if not passed:
            # All remaining enemies flee
            for e in enemies:
                e.is_active = False
            self._enemies_have_fled = True
            self._log(f"Morale failed! The {group_name} flee!")
        else:
            self._log(f"Morale passed! The {group_name} continue fighting.")
        
        return MoraleResult(
            creature_group=group_name,
            roll=roll,
            morale_score=morale_score,
            passed=passed,
            trigger=trigger
        )
    
    def force_morale_check(self, modifier: int = 0) -> Optional[MoraleResult]:
        """Force a morale check (e.g., from spell or intimidation)."""
        active_enemies = [c for c in self.combatants if not c.is_player and c.is_active and c.is_alive]
        
        if not active_enemies:
            return None
        
        morale_scores = [e.morale for e in active_enemies if e.morale is not None]
        if not morale_scores:
            return None
        
        avg_morale = (sum(morale_scores) // len(morale_scores)) + modifier
        return self._roll_morale(avg_morale, "forced", active_enemies)
    
    # =========================================================================
    # COMBAT END DETECTION
    # =========================================================================
    
    def _check_combat_end(self) -> tuple[bool, Optional[CombatEndReason]]:
        """Check if combat should end."""
        active_party = [c for c in self.combatants if c.is_player and c.is_active and c.is_alive]
        active_enemies = [c for c in self.combatants if not c.is_player and c.is_active and c.is_alive]
        
        if not active_enemies:
            if self._enemies_have_fled:
                return True, CombatEndReason.ENEMIES_FLED
            return True, CombatEndReason.ENEMIES_DEFEATED
        
        if not active_party:
            fled_party = [c for c in self.combatants if c.is_player and c.is_active and not c.is_alive]
            if fled_party:
                return True, CombatEndReason.PARTY_FLED
            return True, CombatEndReason.PARTY_DEFEATED
        
        return False, None
    
    # =========================================================================
    # UTILITIES
    # =========================================================================
    
    def _get_combatant(self, name: str) -> Optional[Combatant]:
        """Find combatant by name (case-insensitive)."""
        name_lower = name.lower()
        for c in self.combatants:
            if c.name.lower() == name_lower:
                return c
        return None
    
    def _log(self, message: str) -> None:
        """Add to combat log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.combat_log.append(f"[{timestamp}] {message}")
        logger.debug(message)
    
    def get_log(self) -> list[str]:
        """Get combat log."""
        return self.combat_log.copy()

    # =========================================================================
    # v2.0 REACTION ROLLS
    # =========================================================================

    def roll_reaction(
        self,
        modifier: int = 0,
        creature_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Roll reaction for an encounter (2d6 per OSE rules).

        This determines the initial disposition of encountered creatures
        before combat is initiated.

        Args:
            modifier: CHA modifier or other situational modifiers
            creature_type: Type of creature for logging

        Returns:
            Dict with reaction result and description
        """
        roll = roll_dice("2d6")
        total = roll.total + modifier

        # Clamp to table range
        total = max(2, min(12, total))

        reaction, description = self.REACTION_TABLE.get(
            total, ("neutral", "Uncertain")
        )

        result = {
            "roll": roll.total,
            "modifier": modifier,
            "total": total,
            "reaction": reaction,
            "description": description,
            "creature_type": creature_type,
            "initiates_combat": reaction == "hostile",
            "brief": f"Reaction roll: {roll.total}+{modifier}={total} → {reaction.upper()}: {description}",
        }

        self._log(result["brief"])
        return result

    def calculate_morale_modifier(
        self,
        conditions: List[str],
    ) -> int:
        """
        Calculate total morale modifier from conditions.

        Args:
            conditions: List of condition strings matching MORALE_MODIFIERS keys

        Returns:
            Total modifier to apply to morale checks
        """
        total = 0
        for condition in conditions:
            if condition in self.MORALE_MODIFIERS:
                total += self.MORALE_MODIFIERS[condition]
        return total

    def get_combat_summary(self) -> Dict[str, Any]:
        """
        Get a comprehensive combat summary for logging/persistence.

        Returns:
            Dict with complete combat state
        """
        return {
            "combat_id": self.combat_id,
            "phase": self.phase.value,
            "round_number": self.round_number,
            "combatants": [
                {
                    "id": c.id,
                    "name": c.name,
                    "hp_current": c.hp_current,
                    "hp_max": c.hp_max,
                    "ac": c.ac,
                    "is_player": c.is_player,
                    "is_active": c.is_active,
                    "is_alive": c.is_alive,
                    "conditions": c.conditions,
                    "initiative": c.initiative,
                }
                for c in self.combatants
            ],
            "active_party": len([c for c in self.combatants if c.is_player and c.is_active and c.is_alive]),
            "active_enemies": len([c for c in self.combatants if not c.is_player and c.is_active and c.is_alive]),
            "return_state": self._return_state,
            "encounter_context": self.encounter_context,
            "log_entries": len(self.combat_log),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize combat state for persistence."""
        return self.get_combat_summary()

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        state_machine: Optional["StateMachine"] = None,
        global_controller: Optional["GlobalController"] = None,
        trigger_handler: Optional["TriggerHandler"] = None,
    ) -> "CombatEngine":
        """
        Restore combat engine from serialized state.

        Args:
            data: Serialized combat data
            state_machine: StateMachine reference
            global_controller: GlobalController reference
            trigger_handler: TriggerHandler reference

        Returns:
            Restored CombatEngine instance
        """
        engine = cls(
            state_machine=state_machine,
            global_controller=global_controller,
            trigger_handler=trigger_handler,
        )

        engine.combat_id = data.get("combat_id", engine.combat_id)
        engine.phase = CombatPhase(data.get("phase", "not_started"))
        engine.round_number = data.get("round_number", 0)
        engine._return_state = data.get("return_state")
        engine.encounter_context = data.get("encounter_context", {})

        # Restore combatants
        for c_data in data.get("combatants", []):
            combatant = Combatant(
                name=c_data["name"],
                hp_current=c_data["hp_current"],
                hp_max=c_data["hp_max"],
                ac=c_data["ac"],
                is_player=c_data.get("is_player", False),
                is_active=c_data.get("is_active", True),
                conditions=c_data.get("conditions", []),
                initiative=c_data.get("initiative", 0),
                id=c_data.get("id", ""),
            )
            engine.combatants.append(combatant)

        return engine


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_combatant_from_character(character: Any) -> Combatant:
    """
    Create a Combatant from a DolmenwoodCharacter.
    
    Args:
        character: DolmenwoodCharacter instance.
    
    Returns:
        Combatant ready for combat.
    """
    # Calculate attack bonus from level and STR
    str_mod = (getattr(character, 'strength', 10) - 10) // 2
    attack_bonus = (getattr(character, 'level', 1) - 1) // 3 + str_mod  # Rough THAC0 conversion
    
    # Default damage (assume melee weapon)
    damage_dice = "1d8"  # Longsword default
    
    return Combatant(
        name=character.name,
        hp_current=getattr(character, 'hp_current', 10),
        hp_max=getattr(character, 'hp_max', 10),
        ac=getattr(character, 'ac', 10),
        attack_bonus=attack_bonus,
        damage_dice=damage_dice,
        is_player=True,
        id=getattr(character, 'character_id', '')
    )


def create_combatant_from_monster(monster: Any, name_suffix: str = "") -> Combatant:
    """
    Create a Combatant from a MonsterStatBlock.
    
    Args:
        monster: MonsterStatBlock instance.
        name_suffix: Optional suffix for unique naming (e.g., " 1", " 2").
    
    Returns:
        Combatant ready for combat.
    """
    # Parse hit dice to get HP
    hd = getattr(monster, 'hit_dice', '1')
    hp = _parse_hit_dice_to_hp(hd)
    
    # Parse AC
    ac = getattr(monster, 'armor_class', 9)
    if isinstance(ac, str):
        try:
            ac = int(ac.split()[0])  # Handle "7 [12]" format
        except ValueError:
            ac = 9
    
    # Attack bonus based on HD
    try:
        hd_num = int(str(hd).split('+')[0].split('-')[0])
    except ValueError:
        hd_num = 1
    attack_bonus = hd_num
    
    # Get damage from attacks
    damage_dice = "1d6"  # Default
    attacks = getattr(monster, 'attacks', [])
    if attacks and isinstance(attacks, list) and len(attacks) > 0:
        # Try to parse damage from attack string
        first_attack = str(attacks[0])
        import re
        damage_match = re.search(r'\d+d\d+(?:[+-]\d+)?', first_attack)
        if damage_match:
            damage_dice = damage_match.group()
    
    name = monster.name + name_suffix
    
    return Combatant(
        name=name,
        hp_current=hp,
        hp_max=hp,
        ac=ac,
        attack_bonus=attack_bonus,
        damage_dice=damage_dice,
        is_player=False,
        morale=getattr(monster, 'morale', 7),
        id=getattr(monster, 'monster_id', '') + name_suffix.replace(' ', '_')
    )


def _parse_hit_dice_to_hp(hd: str) -> int:
    """Parse hit dice string and roll HP."""
    import re
    
    hd_str = str(hd).strip()
    
    # Handle formats: "2", "2+1", "1-1", "2d8", "1d8+2"
    
    # Simple number
    if hd_str.isdigit():
        count = int(hd_str)
        return sum(random.randint(1, 8) for _ in range(count))
    
    # XdY format
    dice_match = re.match(r'(\d+)d(\d+)([+-]\d+)?', hd_str)
    if dice_match:
        count = int(dice_match.group(1))
        sides = int(dice_match.group(2))
        mod = int(dice_match.group(3) or 0)
        return sum(random.randint(1, sides) for _ in range(count)) + mod
    
    # X+Y or X-Y format (OSE style)
    mod_match = re.match(r'(\d+)([+-])(\d+)', hd_str)
    if mod_match:
        count = int(mod_match.group(1))
        sign = 1 if mod_match.group(2) == '+' else -1
        mod = int(mod_match.group(3)) * sign
        return max(1, sum(random.randint(1, 8) for _ in range(count)) + mod)
    
    # Fallback
    return random.randint(1, 8)
