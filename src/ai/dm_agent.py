"""
Dolmenwood AI Dungeon Master - AI DM Agent

This module provides the AI Dungeon Master agent powered by Claude,
with comprehensive tool support for OSE/Dolmenwood game mechanics.

Features:
- Claude integration for narrative generation
- Comprehensive tool definitions for game mechanics
- Dice rolling with modifiers and advantage/disadvantage
- Combat management (initiative, attacks, damage, morale)
- Exploration mechanics (movement, encounters, foraging)
- Social interactions (reaction rolls, NPC dialogue)
- Magic and spellcasting support
- Context retrieval from vector database
- State persistence with GameStateManager

Author: AI Dungeon Master Project
Version: 1.1 - Combat Engine Integration
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional, Union

# Configure logging
logger = logging.getLogger(__name__)

# Combat engine integration
try:
    # Try relative import first (when running from src/)
    from combat.combat_tools import (
        COMBAT_TOOL_DEFINITIONS,
        CombatToolHandler,
        CombatToolResult,
        create_combat_handler,
    )
    from combat.combat_engine import CombatPhase
    COMBAT_ENGINE_AVAILABLE = True
except ImportError:
    try:
        # Try with src prefix (when running from project root)
        from src.combat.combat_tools import (
            COMBAT_TOOL_DEFINITIONS,
            CombatToolHandler,
            CombatToolResult,
            create_combat_handler,
        )
        from src.combat.combat_engine import CombatPhase
        COMBAT_ENGINE_AVAILABLE = True
    except ImportError:
        COMBAT_ENGINE_AVAILABLE = False
        logger.warning("Combat engine not available - using standalone tools")

# Hex crawl engine integration
try:
    from exploration.hex_crawl_tools import (
        HEX_CRAWL_TOOL_DEFINITIONS,
        HexCrawlToolHandler,
        HexCrawlToolResult,
        create_hex_crawl_handler,
    )
    HEX_CRAWL_ENGINE_AVAILABLE = True
except ImportError:
    try:
        from src.exploration.hex_crawl_tools import (
            HEX_CRAWL_TOOL_DEFINITIONS,
            HexCrawlToolHandler,
            HexCrawlToolResult,
            create_hex_crawl_handler,
        )
        HEX_CRAWL_ENGINE_AVAILABLE = True
    except ImportError:
        HEX_CRAWL_ENGINE_AVAILABLE = False
        logger.warning("Hex crawl engine not available")


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class DMConfig:
    """Configuration for the DM Agent."""
    
    # LLM Provider settings
    provider: str = "claude"  # "claude", "ollama", "openai"
    api_key: Optional[str] = None  # For Claude
    model: str = "claude-sonnet-4-20250514"  # Model name
    base_url: Optional[str] = None  # For Ollama/OpenAI-compatible
    max_tokens: int = 4096
    temperature: float = 0.8
    supports_tools: Optional[bool] = None  # Override tool detection
    
    # Game settings
    campaign_name: str = "Dolmenwood Campaign"
    dm_style: str = "evocative"  # evocative, terse, verbose
    rules_strictness: str = "balanced"  # strict, balanced, loose
    
    # Context settings
    max_context_tokens: int = 2000
    include_rules_context: bool = True
    include_monster_context: bool = True
    include_location_context: bool = True
    
    # Safety settings
    content_filter: bool = True
    max_violence_level: str = "moderate"  # mild, moderate, graphic
    
    def __post_init__(self):
        if self.api_key is None:
            self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        
        # Set default base URLs
        if self.base_url is None:
            if self.provider == "ollama":
                self.base_url = "http://localhost:11434"
            elif self.provider == "openai":
                self.base_url = "http://localhost:1234/v1"
        
        # Set default models per provider
        if self.provider == "ollama" and self.model == "claude-sonnet-4-20250514":
            self.model = "llama3.2"  # Default Ollama model
        elif self.provider == "openai" and self.model == "claude-sonnet-4-20250514":
            self.model = "local-model"  # Default local model


# =============================================================================
# DICE MECHANICS
# =============================================================================

class DiceRoller:
    """
    Comprehensive dice roller for OSE/Dolmenwood mechanics.
    
    Supports standard dice notation (XdY+Z), advantage/disadvantage,
    exploding dice, and drop lowest/highest.
    """
    
    # Dice notation pattern: 2d6+3, d20, 4d6kh3 (keep highest 3)
    DICE_PATTERN = re.compile(
        r"^(?P<count>\d+)?d(?P<sides>\d+)"
        r"(?:(?P<keep_type>k[hl])(?P<keep_count>\d+))?"
        r"(?P<modifier>[+-]\d+)?$",
        re.IGNORECASE
    )
    
    @classmethod
    def roll(cls, notation: str, advantage: bool = False, disadvantage: bool = False) -> "DiceResult":
        """
        Roll dice using standard notation.
        
        Args:
            notation: Dice notation (e.g., "2d6+3", "d20", "4d6kh3").
            advantage: Roll twice and take higher (for d20 rolls).
            disadvantage: Roll twice and take lower (for d20 rolls).
            
        Returns:
            DiceResult with total and individual rolls.
        """
        match = cls.DICE_PATTERN.match(notation.strip().lower())
        if not match:
            raise ValueError(f"Invalid dice notation: {notation}")
        
        count = int(match.group("count") or 1)
        sides = int(match.group("sides"))
        keep_type = match.group("keep_type")
        keep_count = int(match.group("keep_count")) if match.group("keep_count") else None
        modifier = int(match.group("modifier") or 0)
        
        # Handle advantage/disadvantage for d20 rolls
        if sides == 20 and count == 1 and (advantage or disadvantage):
            roll1 = random.randint(1, 20)
            roll2 = random.randint(1, 20)
            
            if advantage:
                chosen = max(roll1, roll2)
                rolls = [roll1, roll2]
                note = f"advantage: {roll1}, {roll2} → {chosen}"
            else:
                chosen = min(roll1, roll2)
                rolls = [roll1, roll2]
                note = f"disadvantage: {roll1}, {roll2} → {chosen}"
            
            return DiceResult(
                notation=notation,
                rolls=rolls,
                kept_rolls=[chosen],
                modifier=modifier,
                total=chosen + modifier,
                note=note
            )
        
        # Standard roll
        rolls = [random.randint(1, sides) for _ in range(count)]
        kept_rolls = rolls.copy()
        note = ""
        
        # Handle keep highest/lowest
        if keep_type and keep_count:
            if keep_type.lower() == "kh":
                kept_rolls = sorted(rolls, reverse=True)[:keep_count]
                note = f"kept highest {keep_count}"
            elif keep_type.lower() == "kl":
                kept_rolls = sorted(rolls)[:keep_count]
                note = f"kept lowest {keep_count}"
        
        total = sum(kept_rolls) + modifier
        
        return DiceResult(
            notation=notation,
            rolls=rolls,
            kept_rolls=kept_rolls,
            modifier=modifier,
            total=total,
            note=note
        )
    
    @classmethod
    def roll_d20(cls, modifier: int = 0, advantage: bool = False, disadvantage: bool = False) -> "DiceResult":
        """Convenience method for d20 rolls."""
        notation = f"d20{'+' if modifier >= 0 else ''}{modifier}" if modifier else "d20"
        return cls.roll(notation, advantage=advantage, disadvantage=disadvantage)
    
    @classmethod
    def roll_damage(cls, notation: str) -> "DiceResult":
        """Roll damage dice."""
        return cls.roll(notation)
    
    @classmethod
    def roll_ability_scores(cls) -> list["DiceResult"]:
        """Roll 6 ability scores using 4d6 drop lowest."""
        return [cls.roll("4d6kh3") for _ in range(6)]
    
    @classmethod
    def roll_hit_dice(cls, hit_dice: str, con_modifier: int = 0) -> "DiceResult":
        """
        Roll hit dice for HP.
        
        Args:
            hit_dice: Hit dice notation (e.g., "1d8", "2d6").
            con_modifier: Constitution modifier to add per die.
        """
        result = cls.roll(hit_dice)
        
        # Apply CON modifier per die (minimum 1 HP per die)
        count = len(result.kept_rolls)
        total_con_bonus = con_modifier * count
        
        # Minimum 1 HP per die
        min_total = count
        final_total = max(result.total + total_con_bonus, min_total)
        
        return DiceResult(
            notation=f"{hit_dice}+{con_modifier}/die",
            rolls=result.rolls,
            kept_rolls=result.kept_rolls,
            modifier=total_con_bonus,
            total=final_total,
            note=f"CON bonus: {total_con_bonus}"
        )
    
    @classmethod
    def roll_percentile(cls) -> "DiceResult":
        """Roll d100."""
        return cls.roll("d100")
    
    @classmethod
    def roll_reaction(cls, cha_modifier: int = 0) -> "DiceResult":
        """Roll 2d6 for reaction check."""
        result = cls.roll("2d6")
        total = result.total + cha_modifier
        return DiceResult(
            notation="2d6",
            rolls=result.rolls,
            kept_rolls=result.kept_rolls,
            modifier=cha_modifier,
            total=total,
            note=f"CHA mod: {cha_modifier}"
        )
    
    @classmethod
    def roll_morale(cls, morale_score: int) -> tuple["DiceResult", bool]:
        """
        Roll morale check.
        
        Returns:
            Tuple of (DiceResult, passed: bool)
        """
        result = cls.roll("2d6")
        passed = result.total <= morale_score
        result.note = f"vs ML {morale_score}: {'PASS' if passed else 'FAIL'}"
        return result, passed


@dataclass
class DiceResult:
    """Result of a dice roll."""
    notation: str
    rolls: list[int]
    kept_rolls: list[int]
    modifier: int
    total: int
    note: str = ""
    
    def __str__(self) -> str:
        rolls_str = ", ".join(str(r) for r in self.rolls)
        if self.note:
            return f"{self.notation} = [{rolls_str}] → {self.total} ({self.note})"
        elif self.modifier:
            return f"{self.notation} = [{rolls_str}] + {self.modifier} = {self.total}"
        else:
            return f"{self.notation} = [{rolls_str}] = {self.total}"
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "notation": self.notation,
            "rolls": self.rolls,
            "kept_rolls": self.kept_rolls,
            "modifier": self.modifier,
            "total": self.total,
            "note": self.note,
        }


# =============================================================================
# GAME MECHANICS
# =============================================================================

class CombatManager:
    """Handles combat mechanics for OSE/Dolmenwood."""
    
    @staticmethod
    def calculate_attack_roll(
        attack_bonus: int,
        target_ac: int,
        modifiers: int = 0,
        advantage: bool = False,
        disadvantage: bool = False
    ) -> tuple[DiceResult, bool, bool]:
        """
        Make an attack roll.
        
        Returns:
            Tuple of (DiceResult, hit: bool, critical: bool)
        """
        result = DiceRoller.roll_d20(
            modifier=attack_bonus + modifiers,
            advantage=advantage,
            disadvantage=disadvantage
        )
        
        # Natural 20 always hits (critical)
        # Natural 1 always misses
        natural_roll = result.kept_rolls[0]
        
        if natural_roll == 20:
            return result, True, True
        elif natural_roll == 1:
            return result, False, False
        else:
            # OSE uses descending AC: need to hit target AC or lower
            # With AAC (ascending): need to equal or exceed target AC
            # Using ascending AC convention
            hit = result.total >= target_ac
            return result, hit, False
    
    @staticmethod
    def roll_initiative(dex_modifier: int = 0) -> DiceResult:
        """Roll initiative (d6 in OSE, optionally with DEX mod)."""
        result = DiceRoller.roll("d6")
        total = result.total + dex_modifier
        return DiceResult(
            notation="d6",
            rolls=result.rolls,
            kept_rolls=result.kept_rolls,
            modifier=dex_modifier,
            total=total,
            note=f"DEX mod: {dex_modifier}" if dex_modifier else ""
        )
    
    @staticmethod
    def roll_damage(damage_dice: str, bonus: int = 0, critical: bool = False) -> DiceResult:
        """
        Roll damage.
        
        Args:
            damage_dice: Damage notation (e.g., "1d8").
            bonus: Damage bonus (e.g., from STR).
            critical: If True, roll damage twice.
        """
        result = DiceRoller.roll(damage_dice)
        
        if critical:
            # Roll damage twice for critical
            crit_roll = DiceRoller.roll(damage_dice)
            total_rolls = result.rolls + crit_roll.rolls
            total = sum(total_rolls) + bonus
            return DiceResult(
                notation=f"{damage_dice}×2",
                rolls=total_rolls,
                kept_rolls=total_rolls,
                modifier=bonus,
                total=max(total, 1),  # Minimum 1 damage
                note="CRITICAL!"
            )
        else:
            total = result.total + bonus
            return DiceResult(
                notation=damage_dice,
                rolls=result.rolls,
                kept_rolls=result.kept_rolls,
                modifier=bonus,
                total=max(total, 1),  # Minimum 1 damage
                note=""
            )
    
    @staticmethod
    def check_morale(morale_score: int) -> tuple[DiceResult, bool]:
        """Check if creature passes morale."""
        return DiceRoller.roll_morale(morale_score)
    
    @staticmethod
    def calculate_encounter_distance(terrain: str = "dungeon") -> int:
        """
        Calculate encounter distance based on terrain.
        
        Returns distance in feet.
        """
        if terrain == "dungeon":
            return DiceRoller.roll("2d6").total * 10
        elif terrain in ("forest", "swamp", "hills"):
            return DiceRoller.roll("4d6").total * 10
        elif terrain in ("plains", "desert"):
            return DiceRoller.roll("4d6").total * 40
        else:
            return DiceRoller.roll("2d6").total * 10


class ExplorationManager:
    """Handles exploration and travel mechanics."""
    
    # Terrain movement modifiers (multiplier)
    TERRAIN_MODIFIERS = {
        "road": 1.0,
        "clear": 1.0,
        "forest": 0.66,
        "hills": 0.66,
        "swamp": 0.5,
        "mountains": 0.5,
        "desert": 0.66,
    }
    
    @staticmethod
    def calculate_travel_time(
        distance_miles: float,
        base_movement: int,
        terrain: str = "clear",
        forced_march: bool = False
    ) -> dict[str, Any]:
        """
        Calculate travel time.
        
        Args:
            distance_miles: Distance to travel.
            base_movement: Base movement rate in feet.
            terrain: Terrain type.
            forced_march: If True, travel at increased rate with exhaustion risk.
            
        Returns:
            Dict with travel info.
        """
        # Convert base movement (dungeon) to overland miles/day
        # OSE: Divide dungeon movement by 5 for overland miles/day
        miles_per_day = base_movement / 5
        
        # Apply terrain modifier
        modifier = ExplorationManager.TERRAIN_MODIFIERS.get(terrain, 1.0)
        effective_miles = miles_per_day * modifier
        
        if forced_march:
            effective_miles *= 1.5
        
        days_needed = distance_miles / effective_miles
        
        return {
            "distance_miles": distance_miles,
            "base_movement": base_movement,
            "terrain": terrain,
            "effective_miles_per_day": round(effective_miles, 1),
            "days_needed": round(days_needed, 2),
            "forced_march": forced_march,
            "exhaustion_risk": forced_march,
        }
    
    @staticmethod
    def check_random_encounter(chance: int = 1, die: int = 6) -> tuple[DiceResult, bool]:
        """
        Check for random encounter.
        
        Args:
            chance: Number to roll at or under for encounter.
            die: Die size to roll.
            
        Returns:
            Tuple of (DiceResult, encounter: bool)
        """
        result = DiceRoller.roll(f"d{die}")
        encounter = result.total <= chance
        result.note = f"encounter on {chance} or less: {'ENCOUNTER!' if encounter else 'safe'}"
        return result, encounter
    
    @staticmethod
    def check_getting_lost(terrain: str = "forest", has_guide: bool = False) -> tuple[DiceResult, bool]:
        """
        Check if party gets lost.
        
        Returns:
            Tuple of (DiceResult, lost: bool)
        """
        # OSE lost chances vary by terrain
        lost_chances = {
            "clear": 1,
            "forest": 2,
            "swamp": 3,
            "mountains": 2,
            "desert": 3,
        }
        
        chance = lost_chances.get(terrain, 1)
        if has_guide:
            chance = max(1, chance - 1)
        
        result = DiceRoller.roll("d6")
        lost = result.total <= chance
        result.note = f"lost on {chance} or less ({terrain}): {'LOST!' if lost else 'on track'}"
        return result, lost
    
    @staticmethod
    def forage(survival_skill: int = 2, terrain: str = "forest") -> tuple[DiceResult, bool]:
        """
        Attempt to forage for food.
        
        Returns:
            Tuple of (DiceResult, success: bool)
        """
        result = DiceRoller.roll("d6")
        success = result.total <= survival_skill
        result.note = f"forage (skill {survival_skill}): {'SUCCESS' if success else 'FAILURE'}"
        return result, success
    
    @staticmethod
    def check_weather() -> str:
        """Generate weather conditions."""
        roll = DiceRoller.roll("d20").total
        
        if roll <= 5:
            return "clear"
        elif roll <= 10:
            return "overcast"
        elif roll <= 14:
            return "light rain"
        elif roll <= 17:
            return "heavy rain"
        elif roll <= 19:
            return "storm"
        else:
            return "unusual"


class SocialManager:
    """Handles social interactions and NPC reactions."""
    
    # Reaction table results (2d6)
    REACTION_TABLE = {
        2: ("hostile", "Attacks immediately"),
        3: ("hostile", "Aggressive, likely to attack"),
        4: ("hostile", "Threatening, demands tribute"),
        5: ("unfriendly", "Unfriendly, may attack if provoked"),
        6: ("unfriendly", "Wary, keeps distance"),
        7: ("neutral", "Neutral, uncertain"),
        8: ("neutral", "Neutral, open to interaction"),
        9: ("friendly", "Friendly, willing to talk"),
        10: ("friendly", "Helpful, offers assistance"),
        11: ("friendly", "Very friendly, eager to help"),
        12: ("friendly", "Enthusiastic ally, offers significant help"),
    }
    
    @classmethod
    def roll_reaction(cls, cha_modifier: int = 0, context_modifier: int = 0) -> dict[str, Any]:
        """
        Roll NPC reaction.
        
        Args:
            cha_modifier: Charisma modifier of speaking character.
            context_modifier: Situational modifier.
            
        Returns:
            Dict with reaction result.
        """
        result = DiceRoller.roll("2d6")
        total = max(2, min(12, result.total + cha_modifier + context_modifier))
        
        disposition, description = cls.REACTION_TABLE.get(total, ("neutral", "Neutral"))
        
        return {
            "roll": result.to_dict(),
            "modified_total": total,
            "cha_modifier": cha_modifier,
            "context_modifier": context_modifier,
            "disposition": disposition,
            "description": description,
        }
    
    @staticmethod
    def check_loyalty(loyalty_score: int, circumstance_modifier: int = 0) -> tuple[DiceResult, bool]:
        """
        Check retainer/hireling loyalty.
        
        Returns:
            Tuple of (DiceResult, loyal: bool)
        """
        result = DiceRoller.roll("2d6")
        target = loyalty_score + circumstance_modifier
        loyal = result.total <= target
        result.note = f"loyalty check vs {target}: {'LOYAL' if loyal else 'DISLOYAL'}"
        return result, loyal


class MagicManager:
    """Handles magic and spellcasting mechanics."""
    
    @staticmethod
    def check_spell_success(spell_level: int, caster_level: int) -> bool:
        """Check if spell succeeds (always True in OSE unless disrupted)."""
        return True
    
    @staticmethod
    def roll_spell_duration(duration_dice: str) -> DiceResult:
        """Roll spell duration."""
        return DiceRoller.roll(duration_dice)
    
    @staticmethod
    def check_magic_item_activation(
        item_type: str = "scroll",
        caster_level: int = 0,
        item_level: int = 0
    ) -> tuple[bool, str]:
        """
        Check if magic item can be activated.
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        if item_type == "scroll":
            if caster_level >= item_level:
                return True, "Scroll successfully read"
            else:
                # Chance of failure/backfire for scrolls above caster level
                roll = DiceRoller.roll("d100").total
                if roll <= 10 * (item_level - caster_level):
                    return False, "Scroll backfires!"
                return True, "Scroll read with difficulty"
        
        return True, "Item activated"
    
    @staticmethod
    def dispel_check(
        caster_level: int,
        target_level: int
    ) -> tuple[DiceResult, bool]:
        """
        Roll dispel magic check.
        
        Returns:
            Tuple of (DiceResult, success: bool)
        """
        result = DiceRoller.roll("d20")
        target = 11 + (target_level - caster_level)
        success = result.total >= target
        result.note = f"dispel vs level {target_level}: target {target}, {'SUCCESS' if success else 'FAILURE'}"
        return result, success


class SavingThrowManager:
    """Handles saving throw mechanics."""
    
    @staticmethod
    def make_save(
        save_target: int,
        modifier: int = 0,
        advantage: bool = False,
        disadvantage: bool = False
    ) -> tuple[DiceResult, bool]:
        """
        Make a saving throw.
        
        Args:
            save_target: Target number to roll at or above.
            modifier: Modifier to the roll.
            advantage: Roll with advantage.
            disadvantage: Roll with disadvantage.
            
        Returns:
            Tuple of (DiceResult, success: bool)
        """
        result = DiceRoller.roll_d20(
            modifier=modifier,
            advantage=advantage,
            disadvantage=disadvantage
        )
        
        success = result.total >= save_target
        result.note = f"save vs {save_target}: {'SUCCESS' if success else 'FAILURE'}"
        return result, success
    
    @staticmethod
    def get_save_type(effect: str) -> str:
        """Determine appropriate save type for an effect."""
        effect_lower = effect.lower()
        
        if any(word in effect_lower for word in ["death", "poison", "disease"]):
            return "doom"
        elif any(word in effect_lower for word in ["wand", "ray", "gaze"]):
            return "ray"
        elif any(word in effect_lower for word in ["paralysis", "petrify", "hold"]):
            return "hold"
        elif any(word in effect_lower for word in ["breath", "dragon", "blast", "area"]):
            return "blast"
        elif any(word in effect_lower for word in ["spell", "magic", "enchant"]):
            return "spell"
        else:
            return "spell"  # Default to spell save


# =============================================================================
# TOOL RESULT
# =============================================================================

@dataclass
class ToolResult:
    """Result of executing a tool."""
    tool_name: str
    success: bool
    result: Any
    message: str
    dice_rolls: list[DiceResult] = field(default_factory=list)
    state_changes: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "result": self.result,
            "message": self.message,
            "dice_rolls": [r.to_dict() for r in self.dice_rolls],
            "state_changes": self.state_changes,
        }


# =============================================================================
# DM RESPONSE
# =============================================================================

@dataclass
class DMResponse:
    """Response from the DM agent."""
    narrative: str
    tool_results: list[ToolResult] = field(default_factory=list)
    dice_rolls: list[DiceResult] = field(default_factory=list)
    state_changes: dict[str, Any] = field(default_factory=dict)
    context_used: list[str] = field(default_factory=list)
    raw_response: Optional[str] = None
    model_used: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "narrative": self.narrative,
            "tool_results": [t.to_dict() for t in self.tool_results],
            "dice_rolls": [d.to_dict() for d in self.dice_rolls],
            "state_changes": self.state_changes,
            "context_used": self.context_used,
            "model_used": self.model_used,
            "timestamp": self.timestamp.isoformat(),
        }


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

TOOL_DEFINITIONS = [
    {
        "name": "roll_dice",
        "description": "Roll dice using standard notation (e.g., '2d6+3', 'd20', '4d6kh3'). Use for any dice rolls during gameplay.",
        "input_schema": {
            "type": "object",
            "properties": {
                "notation": {
                    "type": "string",
                    "description": "Dice notation (e.g., '2d6', 'd20+5', '4d6kh3')"
                },
                "advantage": {
                    "type": "boolean",
                    "description": "Roll with advantage (d20 only)",
                    "default": False
                },
                "disadvantage": {
                    "type": "boolean",
                    "description": "Roll with disadvantage (d20 only)",
                    "default": False
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for the roll"
                }
            },
            "required": ["notation"]
        }
    },
    {
        "name": "attack_roll",
        "description": "Make an attack roll against a target. Handles hit/miss determination and damage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "attacker_name": {
                    "type": "string",
                    "description": "Name of the attacker"
                },
                "target_name": {
                    "type": "string",
                    "description": "Name of the target"
                },
                "attack_bonus": {
                    "type": "integer",
                    "description": "Attack bonus (THAC0 or BAB)",
                    "default": 0
                },
                "target_ac": {
                    "type": "integer",
                    "description": "Target's AC"
                },
                "damage_dice": {
                    "type": "string",
                    "description": "Damage dice (e.g., '1d8+2')"
                },
                "damage_bonus": {
                    "type": "integer",
                    "description": "Bonus damage",
                    "default": 0
                },
                "advantage": {
                    "type": "boolean",
                    "default": False
                },
                "disadvantage": {
                    "type": "boolean",
                    "default": False
                }
            },
            "required": ["attacker_name", "target_name", "target_ac", "damage_dice"]
        }
    },
    {
        "name": "saving_throw",
        "description": "Make a saving throw against an effect.",
        "input_schema": {
            "type": "object",
            "properties": {
                "character_name": {
                    "type": "string",
                    "description": "Character making the save"
                },
                "save_type": {
                    "type": "string",
                    "enum": ["doom", "ray", "hold", "blast", "spell"],
                    "description": "Type of saving throw"
                },
                "save_target": {
                    "type": "integer",
                    "description": "Target number to meet or exceed"
                },
                "modifier": {
                    "type": "integer",
                    "description": "Modifier to the roll",
                    "default": 0
                },
                "effect": {
                    "type": "string",
                    "description": "Effect being saved against"
                }
            },
            "required": ["character_name", "save_type", "save_target"]
        }
    },
    {
        "name": "morale_check",
        "description": "Check if creatures pass morale and continue fighting.",
        "input_schema": {
            "type": "object",
            "properties": {
                "creature_name": {
                    "type": "string",
                    "description": "Name of creature/group"
                },
                "morale_score": {
                    "type": "integer",
                    "description": "Morale score (2-12)"
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for morale check"
                }
            },
            "required": ["creature_name", "morale_score"]
        }
    },
    {
        "name": "reaction_roll",
        "description": "Roll for NPC/monster reaction when first encountered.",
        "input_schema": {
            "type": "object",
            "properties": {
                "npc_name": {
                    "type": "string",
                    "description": "Name of NPC/creature"
                },
                "cha_modifier": {
                    "type": "integer",
                    "description": "CHA modifier of speaking character",
                    "default": 0
                },
                "context_modifier": {
                    "type": "integer",
                    "description": "Situational modifier",
                    "default": 0
                },
                "context": {
                    "type": "string",
                    "description": "Description of the encounter context"
                }
            },
            "required": ["npc_name"]
        }
    },
    {
        "name": "roll_initiative",
        "description": "Roll initiative for combat.",
        "input_schema": {
            "type": "object",
            "properties": {
                "combatants": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "dex_modifier": {"type": "integer", "default": 0}
                        },
                        "required": ["name"]
                    },
                    "description": "List of combatants with optional DEX modifiers"
                }
            },
            "required": ["combatants"]
        }
    },
    {
        "name": "check_random_encounter",
        "description": "Check if a random encounter occurs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "location_type": {
                    "type": "string",
                    "enum": ["dungeon", "wilderness", "settlement"],
                    "description": "Type of location"
                },
                "chance": {
                    "type": "integer",
                    "description": "Chance on d6 (e.g., 1 = 1-in-6)",
                    "default": 1
                }
            },
            "required": ["location_type"]
        }
    },
    {
        "name": "search_rules",
        "description": "Search the rulebook for relevant rules on a topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What rules to search for"
                },
                "category": {
                    "type": "string",
                    "description": "Optional category filter (combat, magic, exploration)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "lookup_monster",
        "description": "Look up monster statistics and abilities.",
        "input_schema": {
            "type": "object",
            "properties": {
                "monster_name": {
                    "type": "string",
                    "description": "Name of the monster to look up"
                }
            },
            "required": ["monster_name"]
        }
    },
    {
        "name": "lookup_spell",
        "description": "Look up spell details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "spell_name": {
                    "type": "string",
                    "description": "Name of the spell"
                },
                "level": {
                    "type": "integer",
                    "description": "Optional spell level filter"
                }
            },
            "required": ["spell_name"]
        }
    },
    {
        "name": "lookup_location",
        "description": "Look up information about a hex location or area.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Location name, hex ID, or description"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "apply_damage",
        "description": "Apply damage to a character or creature.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {
                    "type": "string",
                    "description": "Name of the target"
                },
                "damage": {
                    "type": "integer",
                    "description": "Amount of damage"
                },
                "damage_type": {
                    "type": "string",
                    "description": "Type of damage (optional)"
                }
            },
            "required": ["target_name", "damage"]
        }
    },
    {
        "name": "heal_character",
        "description": "Heal a character.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {
                    "type": "string",
                    "description": "Name of the character"
                },
                "amount": {
                    "type": "integer",
                    "description": "Amount to heal"
                },
                "source": {
                    "type": "string",
                    "description": "Source of healing (spell, potion, rest)"
                }
            },
            "required": ["target_name", "amount"]
        }
    },
    {
        "name": "update_condition",
        "description": "Add or remove a condition from a character.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {
                    "type": "string",
                    "description": "Name of the character"
                },
                "condition": {
                    "type": "string",
                    "description": "Condition name (poisoned, paralyzed, etc.)"
                },
                "action": {
                    "type": "string",
                    "enum": ["add", "remove"],
                    "description": "Whether to add or remove the condition"
                },
                "duration": {
                    "type": "string",
                    "description": "Duration of the condition"
                }
            },
            "required": ["target_name", "condition", "action"]
        }
    },
    {
        "name": "generate_treasure",
        "description": "Generate treasure based on treasure type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "treasure_type": {
                    "type": "string",
                    "description": "Treasure type (A-O, or 'individual')"
                },
                "context": {
                    "type": "string",
                    "description": "Context for the treasure"
                }
            },
            "required": ["treasure_type"]
        }
    }
]

# Old combat tools to replace when combat engine is available
OLD_COMBAT_TOOL_NAMES = {"attack_roll", "morale_check", "roll_initiative"}

# Old exploration tools to replace when hex crawl engine is available
OLD_EXPLORATION_TOOL_NAMES = {"check_random_encounter"}


def get_tool_definitions(
    use_combat_engine: bool = True,
    use_hex_crawl_engine: bool = True
) -> list[dict]:
    """
    Get the complete list of tool definitions.
    
    When engines are available, replaces old standalone tools
    with the new stateful tools.
    
    Args:
        use_combat_engine: Whether to use the combat engine tools.
        use_hex_crawl_engine: Whether to use the hex crawl engine tools.
        
    Returns:
        List of tool definitions for Claude API.
    """
    tools = TOOL_DEFINITIONS.copy()
    tools_to_remove = set()
    tools_to_add = []
    
    # Combat engine
    if use_combat_engine and COMBAT_ENGINE_AVAILABLE:
        tools_to_remove.update(OLD_COMBAT_TOOL_NAMES)
        tools_to_add.extend(COMBAT_TOOL_DEFINITIONS)
    
    # Hex crawl engine
    if use_hex_crawl_engine and HEX_CRAWL_ENGINE_AVAILABLE:
        tools_to_remove.update(OLD_EXPLORATION_TOOL_NAMES)
        tools_to_add.extend(HEX_CRAWL_TOOL_DEFINITIONS)
    
    # Filter and combine
    filtered_tools = [t for t in tools if t["name"] not in tools_to_remove]
    return filtered_tools + tools_to_add


# Combat tool names for routing
COMBAT_TOOL_NAMES = {
    "start_combat",
    "combat_attack",
    "combat_damage", 
    "combat_heal",
    "combat_save",
    "end_turn",
    "get_combat_status",
    "combat_flee",
    "combat_condition",
    "end_combat",
    "force_morale",
}

# Hex crawl tool names for routing
HEX_CRAWL_TOOL_NAMES = {
    "travel_to_hex",
    "explore_current_hex",
    "forage",
    "make_camp",
    "check_random_encounter",
    "get_hex_crawl_status",
    "advance_time",
    "manage_resources",
    "set_hex_info",
    "set_weather",
}


# =============================================================================
# SYSTEM PROMPT
# =============================================================================

def generate_system_prompt(
    config: DMConfig, 
    game_context: Optional[dict] = None,
    combat_status: Optional[str] = None,
    hex_crawl_status: Optional[str] = None
) -> str:
    """
    Generate the system prompt for the DM agent.
    
    Args:
        config: DM configuration.
        game_context: Current game state context.
        combat_status: Detailed combat status if in combat.
        hex_crawl_status: Detailed hex crawl status for exploration.
    """
    
    base_prompt = f"""You are an expert AI Dungeon Master running a Dolmenwood campaign using Old-School Essentials (OSE) rules. Your name is the Dolmenwood DM.

## Your Role
You are the narrator, referee, and world simulator for this tabletop RPG session. You control all NPCs, monsters, and the environment. You adjudicate rules fairly, create immersive descriptions, and respond to player actions with appropriate consequences.

## Campaign Setting: Dolmenwood
Dolmenwood is a fairy-tale forest setting with:
- Dense, ancient woodlands full of mystery and danger
- The Cold Prince and other fairy lords who hold sway over parts of the forest
- Moss Dwarfs, Woodgrues, and other unique kindreds
- The Drune - sinister sorcerers who worship dark powers
- Settlements like Prigwort, Lankshorn, and Castle Brackenwold
- A blend of whimsy and horror, folk tales and dark fantasy

## Rules System: Old-School Essentials (OSE)
You follow OSE/B/X D&D rules:
- Roll d20 for attacks, saves; compare to target numbers
- Descending AC (optional ascending) 
- 2d6 for reaction rolls and morale checks
- Six ability scores: STR, INT, WIS, DEX, CON, CHA
- Five saving throw categories: Doom, Ray, Hold, Blast, Spell
- Class-based level progression with XP from treasure

## DM Style: {config.dm_style.title()}
{"- Use evocative, atmospheric descriptions that bring Dolmenwood to life" if config.dm_style == "evocative" else ""}
{"- Keep descriptions brief and focused on actionable information" if config.dm_style == "terse" else ""}
{"- Provide rich, detailed descriptions with extensive world-building" if config.dm_style == "verbose" else ""}

## Rules Strictness: {config.rules_strictness.title()}
{"- Apply rules exactly as written; rulings follow RAW" if config.rules_strictness == "strict" else ""}
{"- Balance rules-as-written with reasonable rulings for fun" if config.rules_strictness == "balanced" else ""}
{"- Prioritize narrative and player fun over strict rule adherence" if config.rules_strictness == "loose" else ""}

## Tool Usage
You have access to tools for game mechanics. ALWAYS use the appropriate tool when:
- Making any dice rolls (use roll_dice or specific roll tools)
- Looking up rules, monsters, spells, or locations

### Combat Tools (Use these when combat occurs!)
When combat begins:
1. Call `start_combat` with party members and enemies to initialize combat
2. The system will roll initiative and tell you whose turn it is
3. For each combatant's turn:
   - If it's a player's turn, ask what they do
   - If it's an NPC/monster's turn, decide their action (1-2 sentences of narration)
   - Use `combat_attack` for attacks, `combat_damage` for spells/effects, `combat_save` for saves
   - Call `end_turn` when the combatant finishes their action
4. The system handles initiative order, HP tracking, morale, and combat end detection automatically
5. Use the `brief` from tool results as the basis for your narration

Combat tool quick reference:
- `start_combat` - Begin combat with party and enemies
- `combat_attack` - Make an attack roll (handles hit/miss/damage)
- `combat_damage` - Apply non-attack damage (spells, traps)
- `combat_heal` - Heal a combatant
- `combat_save` - Make a saving throw
- `end_turn` - Advance to next combatant (ALWAYS call this after each turn!)
- `get_combat_status` - Check current combat state
- `combat_flee` - Combatant flees
- `combat_condition` - Add/remove conditions

### Hex Crawl Tools (Use these for wilderness travel!)
When traveling through Dolmenwood:
1. Use `travel_to_hex` when the party wants to move to a new hex
2. The system handles: travel time, getting lost, encounters, resource consumption
3. Use `explore_current_hex` to search for points of interest
4. Use `forage` when the party hunts for food
5. Use `make_camp` for resting and overnight stays
6. Use `get_hex_crawl_status` to check current position, time, weather, resources

Hex crawl tool quick reference:
- `travel_to_hex` - Move to adjacent hex (checks lost, encounters, time)
- `explore_current_hex` - Search for discoveries
- `forage` - Hunt/gather for food
- `make_camp` - Rest or camp overnight
- `get_hex_crawl_status` - Current position, time, resources
- `advance_time` - Pass time without travel
- `manage_resources` - Add/consume rations, torches, etc.
- `set_hex_info` - Record hex details from adventure

When tool results include `encounter_occurred: true`, narrate an appropriate random encounter!
Pay attention to resource warnings - low rations and light sources affect the party.

## Response Format
1. Use tools first to resolve any mechanical actions
2. Take the `brief` result from tools and expand it into evocative narration (1-2 sentences)
3. End with a clear prompt for the next action

## Important Guidelines
- Never reveal monster HP totals directly; describe wounds narratively
- Ask for clarification if player intent is unclear
- Maintain consistent world state and NPC behaviors
- Telegraph dangers fairly - players should have chances to avoid traps
- Reward creative problem-solving
- Keep the tone appropriate to Dolmenwood's fairy-tale horror atmosphere
- During combat, keep narration brief and action-focused
"""
    
    # Add game context if available
    if game_context:
        context_section = "\n## Current Game State\n"
        
        if game_context.get("party"):
            context_section += f"Party: {', '.join(game_context['party'])}\n"
        
        if game_context.get("location"):
            context_section += f"Location: {game_context['location']}\n"
        
        if game_context.get("time"):
            context_section += f"Time: {game_context['time']}\n"
        
        if game_context.get("active_quests"):
            context_section += f"Active Quests: {', '.join(str(q) for q in game_context['active_quests'])}\n"
        
        base_prompt += context_section
    
    # Add hex crawl status
    if hex_crawl_status:
        base_prompt += f"""
## 🗺️ EXPLORATION STATUS 🗺️
{hex_crawl_status}

Remember to use hex crawl tools for travel, exploration, and resource management.
"""
    
    # Add detailed combat status if in combat
    if combat_status:
        base_prompt += f"""
## ⚔️ COMBAT IS ACTIVE ⚔️
{combat_status}

Remember: 
- Call the appropriate combat tool for the current combatant's action
- ALWAYS call `end_turn` after each combatant finishes
- Describe NPC actions in 1-2 evocative sentences
- For player turns, describe the situation and ask what they do
"""
    
    return base_prompt


# =============================================================================
# DOLMENWOOD DM CLASS
# =============================================================================

class DolmenwoodDM:
    """
    AI Dungeon Master for Dolmenwood campaigns.
    
    Integrates Claude API with game mechanics tools, vector database
    for rules lookup, and state management for persistence.
    
    Example:
        >>> dm = DolmenwoodDM(config=DMConfig())
        >>> response = dm.process_player_input("I search the room for traps")
        >>> print(response.narrative)
    """
    
    def __init__(
        self,
        config: Optional[DMConfig] = None,
        rules_retriever: Optional[Any] = None,  # RulesRetriever
        state_manager: Optional[Any] = None,  # GameStateManager
        campaign_id: Optional[str] = None,
        combat_handler: Optional[Any] = None,  # CombatToolHandler
        hex_crawl_handler: Optional[Any] = None,  # HexCrawlToolHandler
        state_machine: Optional[Any] = None,  # v2.0: StateMachine
        transition_detector: Optional[Any] = None,  # v2.0: StateTransitionDetector
    ):
        """
        Initialize the DM agent.

        Args:
            config: DM configuration.
            rules_retriever: Vector database for rules lookup.
            state_manager: Game state persistence manager.
            campaign_id: Current campaign ID.
            combat_handler: Combat tool handler for stateful combat.
            hex_crawl_handler: Hex crawl handler for exploration.
            state_machine: v2.0 state machine for game state tracking.
            transition_detector: v2.0 transition detector for auto state changes.
        """
        self.config = config or DMConfig()
        self.rules_retriever = rules_retriever
        self.state_manager = state_manager
        self.campaign_id = campaign_id

        # v2.0: State machine integration
        self._state_machine = state_machine
        self._transition_detector = transition_detector

        # Initialize combat handler
        if combat_handler is not None:
            self._combat_handler = combat_handler
        elif COMBAT_ENGINE_AVAILABLE:
            self._combat_handler = create_combat_handler()
        else:
            self._combat_handler = None

        # Initialize hex crawl handler
        if hex_crawl_handler is not None:
            self._hex_crawl_handler = hex_crawl_handler
        elif HEX_CRAWL_ENGINE_AVAILABLE:
            self._hex_crawl_handler = create_hex_crawl_handler()
        else:
            self._hex_crawl_handler = None

        # Initialize LLM provider
        self._provider = self._create_provider()

        # Legacy client (for backward compatibility)
        self._client: Optional[Any] = None

        # Current game context
        self._game_context: dict[str, Any] = {}

        # Conversation history for context
        self._conversation_history: list[dict[str, Any]] = []
        self._max_history_length = 20

        # Tool handlers
        self._tool_handlers = self._init_tool_handlers()
        
        # Get tool definitions (with or without engines)
        self._tool_definitions = get_tool_definitions(
            use_combat_engine=self._combat_handler is not None,
            use_hex_crawl_engine=self._hex_crawl_handler is not None
        )
        
        logger.info(f"DolmenwoodDM initialized with provider: {self._provider.provider_name}")
        if not self._provider.supports_tool_calling:
            logger.warning("Provider does not support native tool calling - using prompt-based tools")
        if self._combat_handler:
            logger.info("Combat engine enabled")
        if self._hex_crawl_handler:
            logger.info("Hex crawl engine enabled")
    
    def _create_provider(self):
        """Create the LLM provider based on config."""
        from ai.llm_provider import (
            create_llm_provider,
            ClaudeProvider,
            OllamaProvider,
            OpenAICompatibleProvider,
        )
        
        provider_type = self.config.provider.lower()
        
        if provider_type == "claude":
            return ClaudeProvider(
                api_key=self.config.api_key,
                model=self.config.model,
            )
        elif provider_type == "ollama":
            return OllamaProvider(
                model=self.config.model,
                base_url=self.config.base_url or "http://localhost:11434",
                supports_tools=self.config.supports_tools,
            )
        elif provider_type == "openai":
            return OpenAICompatibleProvider(
                model=self.config.model,
                base_url=self.config.base_url or "http://localhost:1234/v1",
                supports_tools=self.config.supports_tools or False,
            )
        else:
            raise ValueError(f"Unknown provider: {provider_type}")
    
    @property
    def provider(self):
        """Get the LLM provider."""
        return self._provider
    
    @property
    def combat_handler(self) -> Optional[Any]:
        """Get the combat handler."""
        return self._combat_handler
    
    @property
    def hex_crawl_handler(self) -> Optional[Any]:
        """Get the hex crawl handler."""
        return self._hex_crawl_handler
    
    @property
    def is_combat_active(self) -> bool:
        """Check if combat is currently active."""
        if self._combat_handler:
            return self._combat_handler.is_combat_active
        return False

    # =========================================================================
    # v2.0 STATE MACHINE INTEGRATION
    # =========================================================================

    @property
    def state_machine(self):
        """Get the v2.0 state machine."""
        return self._state_machine

    @property
    def transition_detector(self):
        """Get the v2.0 transition detector."""
        return self._transition_detector

    @property
    def current_game_state(self) -> Optional[str]:
        """Get the current game state name."""
        if self._state_machine:
            return self._state_machine.current_state.value
        return None

    def _process_tool_transition(
        self,
        tool_name: str,
        tool_args: dict,
        tool_result: Optional[str] = None
    ) -> Optional[dict]:
        """
        Check if a tool call should trigger a state transition.

        Args:
            tool_name: Name of the tool that was executed.
            tool_args: Arguments passed to the tool.
            tool_result: Optional result string from the tool.

        Returns:
            Dict with transition info if one occurred, None otherwise.
        """
        if not self._transition_detector:
            return None

        transition = self._transition_detector.process_tool_call(
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result=tool_result
        )

        if transition:
            logger.info(
                f"Tool '{tool_name}' triggered state transition: "
                f"{transition.from_state.value} -> {transition.to_state.value}"
            )
            return {
                "from_state": transition.from_state.value,
                "to_state": transition.to_state.value,
                "trigger": transition.trigger.value,
            }

        return None

    def get_state_context_for_prompt(self) -> str:
        """
        Get state-aware context for the system prompt.

        Returns context about the current game state to help the LLM
        understand what mode the game is in and what actions are appropriate.
        """
        if not self._state_machine:
            return ""

        state = self._state_machine.current_state
        valid_triggers = self._state_machine.get_valid_triggers()

        state_descriptions = {
            "wilderness_travel": (
                "The party is traveling through the wilderness. "
                "Time passes in 4-hour watches. Check for encounters each watch. "
                "Party can: travel, forage, make camp, enter locations."
            ),
            "wilderness_encounter": (
                "The party has encountered something in the wilderness! "
                "Determine distance and surprise. Roll reaction if applicable. "
                "Party can: fight, flee, parley, hide."
            ),
            "dungeon_exploration": (
                "The party is exploring a dungeon. Time passes in 10-minute turns. "
                "Track light sources and noise. Check for wandering monsters. "
                "Party can: move, search, interact with objects, rest."
            ),
            "dungeon_encounter": (
                "The party has encountered something in the dungeon! "
                "Determine surprise and reaction. Combat may ensue. "
                "Party can: fight, flee, parley."
            ),
            "combat": (
                "Combat is active! Use combat rounds and initiative order. "
                "Track HP, apply damage, check morale. "
                "Combat ends when enemies defeated, flee, or party retreats."
            ),
            "settlement_exploration": (
                "The party is in a settlement. They can visit services, "
                "talk to NPCs, gather rumors, buy supplies, or rest. "
                "Time passes more freely here."
            ),
            "social_interaction": (
                "The party is engaged in social interaction with NPCs. "
                "Use reaction rolls and NPC motivations. "
                "Negotiate, gather info, or attempt persuasion."
            ),
            "downtime": (
                "The party is resting or engaged in downtime activities. "
                "Healing occurs, spells are recovered, activities can be pursued. "
                "Time passes in days or weeks."
            ),
        }

        context = f"\n[GAME STATE: {state.value.upper()}]\n"
        context += state_descriptions.get(state.value, "")
        context += f"\nValid actions that can change state: {[t.value for t in valid_triggers]}\n"

        return context
    
    @property
    def client(self):
        """
        Lazy-load Anthropic client (for backward compatibility).
        
        Prefer using self._provider for new code.
        """
        if self._client is None:
            if self.config.provider == "claude":
                from anthropic import Anthropic
                self._client = Anthropic(api_key=self.config.api_key)
            else:
                logger.warning("client property accessed but not using Claude provider")
        return self._client
    
    def _init_tool_handlers(self) -> dict[str, Callable]:
        """Initialize tool handler functions."""
        handlers = {
            "roll_dice": self._handle_roll_dice,
            "saving_throw": self._handle_saving_throw,
            "reaction_roll": self._handle_reaction_roll,
            "check_random_encounter": self._handle_random_encounter,
            "search_rules": self._handle_search_rules,
            "lookup_monster": self._handle_lookup_monster,
            "lookup_spell": self._handle_lookup_spell,
            "lookup_location": self._handle_lookup_location,
            "apply_damage": self._handle_apply_damage,
            "heal_character": self._handle_heal_character,
            "update_condition": self._handle_update_condition,
            "generate_treasure": self._handle_generate_treasure,
        }
        
        # Only include old combat handlers if combat engine not available
        if not self._combat_handler:
            handlers.update({
                "attack_roll": self._handle_attack_roll,
                "morale_check": self._handle_morale_check,
                "roll_initiative": self._handle_roll_initiative,
            })
        
        return handlers
    
    # =========================================================================
    # TOOL HANDLERS
    # =========================================================================
    
    def _handle_roll_dice(self, notation: str, advantage: bool = False, 
                          disadvantage: bool = False, reason: str = "") -> ToolResult:
        """Handle generic dice roll."""
        try:
            result = DiceRoller.roll(notation, advantage=advantage, disadvantage=disadvantage)
            return ToolResult(
                tool_name="roll_dice",
                success=True,
                result=result.to_dict(),
                message=f"Rolled {result}",
                dice_rolls=[result]
            )
        except ValueError as e:
            return ToolResult(
                tool_name="roll_dice",
                success=False,
                result=None,
                message=str(e)
            )
    
    def _handle_attack_roll(
        self, attacker_name: str, target_name: str, target_ac: int,
        damage_dice: str, attack_bonus: int = 0, damage_bonus: int = 0,
        advantage: bool = False, disadvantage: bool = False
    ) -> ToolResult:
        """Handle attack roll with damage."""
        attack_result, hit, critical = CombatManager.calculate_attack_roll(
            attack_bonus=attack_bonus,
            target_ac=target_ac,
            advantage=advantage,
            disadvantage=disadvantage
        )
        
        dice_rolls = [attack_result]
        damage_dealt = 0
        
        if hit:
            damage_result = CombatManager.roll_damage(
                damage_dice=damage_dice,
                bonus=damage_bonus,
                critical=critical
            )
            damage_dealt = damage_result.total
            dice_rolls.append(damage_result)
            
            if critical:
                message = f"{attacker_name} CRITICALLY HITS {target_name}! {attack_result} vs AC {target_ac}. Damage: {damage_result} ({damage_dealt} total)"
            else:
                message = f"{attacker_name} hits {target_name}! {attack_result} vs AC {target_ac}. Damage: {damage_result} ({damage_dealt} total)"
        else:
            message = f"{attacker_name} misses {target_name}. {attack_result} vs AC {target_ac}"
        
        return ToolResult(
            tool_name="attack_roll",
            success=True,
            result={
                "attacker": attacker_name,
                "target": target_name,
                "hit": hit,
                "critical": critical,
                "damage": damage_dealt,
                "attack_roll": attack_result.to_dict(),
            },
            message=message,
            dice_rolls=dice_rolls,
            state_changes={"damage_dealt": damage_dealt, "target": target_name} if hit else {}
        )
    
    def _handle_saving_throw(
        self, character_name: str, save_type: str, save_target: int,
        modifier: int = 0, effect: str = ""
    ) -> ToolResult:
        """Handle saving throw."""
        result, success = SavingThrowManager.make_save(save_target, modifier)
        
        message = f"{character_name} makes a {save_type} save vs {effect or 'effect'}. {result}"
        if success:
            message += " - SAVED!"
        else:
            message += " - FAILED!"
        
        return ToolResult(
            tool_name="saving_throw",
            success=True,
            result={
                "character": character_name,
                "save_type": save_type,
                "target": save_target,
                "saved": success,
                "roll": result.to_dict(),
            },
            message=message,
            dice_rolls=[result]
        )
    
    def _handle_morale_check(
        self, creature_name: str, morale_score: int, reason: str = ""
    ) -> ToolResult:
        """Handle morale check."""
        result, passed = CombatManager.check_morale(morale_score)
        
        if passed:
            message = f"{creature_name} passes morale check! {result} - Continues fighting."
        else:
            message = f"{creature_name} fails morale check! {result} - Flees or surrenders!"
        
        return ToolResult(
            tool_name="morale_check",
            success=True,
            result={
                "creature": creature_name,
                "morale_score": morale_score,
                "passed": passed,
                "roll": result.to_dict(),
            },
            message=message,
            dice_rolls=[result],
            state_changes={"morale_failed": not passed, "creature": creature_name}
        )
    
    def _handle_reaction_roll(
        self, npc_name: str, cha_modifier: int = 0,
        context_modifier: int = 0, context: str = ""
    ) -> ToolResult:
        """Handle reaction roll."""
        result = SocialManager.roll_reaction(cha_modifier, context_modifier)
        
        message = (f"{npc_name} reaction: {result['disposition']} "
                  f"(rolled {result['roll']['total']} + {cha_modifier} CHA = {result['modified_total']}). "
                  f"{result['description']}")
        
        return ToolResult(
            tool_name="reaction_roll",
            success=True,
            result=result,
            message=message,
            dice_rolls=[DiceResult(**result['roll'])]
        )
    
    def _handle_roll_initiative(self, combatants: list[dict]) -> ToolResult:
        """Handle initiative rolls for all combatants."""
        results = []
        
        for combatant in combatants:
            name = combatant["name"]
            dex_mod = combatant.get("dex_modifier", 0)
            init_roll = CombatManager.roll_initiative(dex_mod)
            results.append({
                "name": name,
                "initiative": init_roll.total,
                "roll": init_roll.to_dict()
            })
        
        # Sort by initiative (highest first)
        results.sort(key=lambda x: x["initiative"], reverse=True)
        
        order_str = ", ".join([f"{r['name']} ({r['initiative']})" for r in results])
        message = f"Initiative order: {order_str}"
        
        return ToolResult(
            tool_name="roll_initiative",
            success=True,
            result={"initiative_order": results},
            message=message,
            dice_rolls=[DiceResult(**r['roll']) for r in results]
        )
    
    def _handle_random_encounter(
        self, location_type: str, chance: int = 1
    ) -> ToolResult:
        """Handle random encounter check."""
        result, encounter = ExplorationManager.check_random_encounter(chance)
        
        if encounter:
            message = f"Random encounter in {location_type}! {result}"
        else:
            message = f"No encounter in {location_type}. {result}"
        
        return ToolResult(
            tool_name="check_random_encounter",
            success=True,
            result={"encounter": encounter, "location": location_type, "roll": result.to_dict()},
            message=message,
            dice_rolls=[result]
        )
    
    def _handle_search_rules(self, query: str, category: str = None) -> ToolResult:
        """Handle rules search."""
        if not self.rules_retriever:
            return ToolResult(
                tool_name="search_rules",
                success=False,
                result=None,
                message="Rules database not available"
            )
        
        results = self.rules_retriever.search_rules(query, n_results=3, category=category)
        
        if results:
            content = "\n\n".join([r.to_context_string() for r in results])
            message = f"Found {len(results)} relevant rules"
        else:
            content = "No relevant rules found"
            message = "No matching rules found"
        
        return ToolResult(
            tool_name="search_rules",
            success=True,
            result={"query": query, "results": content},
            message=message
        )
    
    def _handle_lookup_monster(self, monster_name: str) -> ToolResult:
        """Handle monster lookup."""
        if not self.rules_retriever:
            return ToolResult(
                tool_name="lookup_monster",
                success=False,
                result=None,
                message="Monster database not available"
            )
        
        results = self.rules_retriever.search_monsters(monster_name, n_results=1)
        
        if results:
            content = results[0].content
            message = f"Found: {monster_name}"
        else:
            content = f"No monster found matching '{monster_name}'"
            message = "Monster not found"
        
        return ToolResult(
            tool_name="lookup_monster",
            success=bool(results),
            result={"monster": monster_name, "data": content},
            message=message
        )
    
    def _handle_lookup_spell(self, spell_name: str, level: int = None) -> ToolResult:
        """Handle spell lookup."""
        if not self.rules_retriever:
            return ToolResult(
                tool_name="lookup_spell",
                success=False,
                result=None,
                message="Spell database not available"
            )
        
        results = self.rules_retriever.search_spells(spell_name, n_results=1, level=level)
        
        if results:
            content = results[0].content
            message = f"Found spell: {spell_name}"
        else:
            content = f"No spell found matching '{spell_name}'"
            message = "Spell not found"
        
        return ToolResult(
            tool_name="lookup_spell",
            success=bool(results),
            result={"spell": spell_name, "data": content},
            message=message
        )
    
    def _handle_lookup_location(self, query: str) -> ToolResult:
        """Handle location lookup."""
        if not self.rules_retriever:
            return ToolResult(
                tool_name="lookup_location",
                success=False,
                result=None,
                message="Location database not available"
            )
        
        results = self.rules_retriever.search_locations(query, n_results=1)
        
        if results:
            content = results[0].content
            message = f"Found location info"
        else:
            content = f"No location found matching '{query}'"
            message = "Location not found"
        
        return ToolResult(
            tool_name="lookup_location",
            success=bool(results),
            result={"query": query, "data": content},
            message=message
        )
    
    def _handle_apply_damage(
        self, target_name: str, damage: int, damage_type: str = ""
    ) -> ToolResult:
        """Handle applying damage to a target."""
        # In full implementation, this would update the game state
        message = f"{target_name} takes {damage} {damage_type + ' ' if damage_type else ''}damage!"
        
        return ToolResult(
            tool_name="apply_damage",
            success=True,
            result={"target": target_name, "damage": damage, "type": damage_type},
            message=message,
            state_changes={"damage": {"target": target_name, "amount": damage}}
        )
    
    def _handle_heal_character(
        self, target_name: str, amount: int, source: str = ""
    ) -> ToolResult:
        """Handle healing a character."""
        message = f"{target_name} is healed for {amount} HP"
        if source:
            message += f" ({source})"
        
        return ToolResult(
            tool_name="heal_character",
            success=True,
            result={"target": target_name, "healed": amount, "source": source},
            message=message,
            state_changes={"healing": {"target": target_name, "amount": amount}}
        )
    
    def _handle_update_condition(
        self, target_name: str, condition: str, action: str,
        duration: str = ""
    ) -> ToolResult:
        """Handle adding/removing conditions."""
        if action == "add":
            message = f"{target_name} is now {condition}"
            if duration:
                message += f" for {duration}"
        else:
            message = f"{target_name} is no longer {condition}"
        
        return ToolResult(
            tool_name="update_condition",
            success=True,
            result={"target": target_name, "condition": condition, "action": action},
            message=message,
            state_changes={"condition": {"target": target_name, "condition": condition, "action": action}}
        )
    
    def _handle_generate_treasure(
        self, treasure_type: str, context: str = ""
    ) -> ToolResult:
        """Handle treasure generation (simplified)."""
        # Simplified treasure generation
        treasure = []
        
        # Roll for coins
        if treasure_type.upper() in "ABCDEFGH":
            copper = DiceRoller.roll("3d6").total * 100
            silver = DiceRoller.roll("2d6").total * 100
            gold = DiceRoller.roll("1d6").total * 10
            treasure.append(f"{copper} cp, {silver} sp, {gold} gp")
        
        # Chance for gems/jewelry
        if DiceRoller.roll("d6").total >= 4:
            gems = DiceRoller.roll("1d6").total
            treasure.append(f"{gems} gems")
        
        # Chance for magic item
        if treasure_type.upper() in "ABC" and DiceRoller.roll("d20").total >= 18:
            treasure.append("1 magic item (roll on magic item table)")
        
        treasure_str = "; ".join(treasure) if treasure else "No treasure"
        
        return ToolResult(
            tool_name="generate_treasure",
            success=True,
            result={"treasure_type": treasure_type, "treasure": treasure_str},
            message=f"Treasure Type {treasure_type}: {treasure_str}"
        )
    
    # =========================================================================
    # TOOL EXECUTION
    # =========================================================================
    
    def _execute_tool(self, tool_name: str, tool_input: dict) -> ToolResult:
        """Execute a tool and return the result."""
        
        # Route combat tools to the combat handler
        if self._combat_handler and tool_name in COMBAT_TOOL_NAMES:
            try:
                combat_result = self._combat_handler.handle_tool(tool_name, tool_input)
                
                # Convert CombatToolResult to ToolResult
                return ToolResult(
                    tool_name=tool_name,
                    success=combat_result.success,
                    result=combat_result.data,
                    message=combat_result.brief,
                    state_changes={
                        "combat_ended": combat_result.combat_ended,
                        "end_reason": combat_result.end_reason
                    } if combat_result.combat_ended else {}
                )
            except Exception as e:
                logger.error(f"Combat tool error: {tool_name}: {e}")
                return ToolResult(
                    tool_name=tool_name,
                    success=False,
                    result=None,
                    message=f"Combat tool error: {str(e)}"
                )
        
        # Route hex crawl tools to the hex crawl handler
        if self._hex_crawl_handler and tool_name in HEX_CRAWL_TOOL_NAMES:
            try:
                hex_result = self._hex_crawl_handler.handle_tool(tool_name, tool_input)
                
                # Build state changes
                state_changes = {}
                if hex_result.encounter_occurred:
                    state_changes["encounter_occurred"] = True
                if hex_result.warnings:
                    state_changes["warnings"] = hex_result.warnings
                
                # Convert HexCrawlToolResult to ToolResult
                return ToolResult(
                    tool_name=tool_name,
                    success=hex_result.success,
                    result=hex_result.data,
                    message=hex_result.brief,
                    state_changes=state_changes
                )
            except Exception as e:
                logger.error(f"Hex crawl tool error: {tool_name}: {e}")
                return ToolResult(
                    tool_name=tool_name,
                    success=False,
                    result=None,
                    message=f"Hex crawl tool error: {str(e)}"
                )
        
        # Handle non-combat, non-hex-crawl tools
        handler = self._tool_handlers.get(tool_name)
        
        if not handler:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                result=None,
                message=f"Unknown tool: {tool_name}"
            )
        
        try:
            return handler(**tool_input)
        except Exception as e:
            logger.error(f"Tool execution error: {tool_name}: {e}")
            return ToolResult(
                tool_name=tool_name,
                success=False,
                result=None,
                message=f"Tool error: {str(e)}"
            )
    
    def _get_combat_status_for_prompt(self) -> Optional[str]:
        """Get formatted combat status for system prompt."""
        if not self._combat_handler or not self._combat_handler.is_combat_active:
            return None
        
        status = self._combat_handler.engine.get_status()
        return status.full_status
    
    def _get_hex_crawl_status_for_prompt(self) -> Optional[str]:
        """Get formatted hex crawl status for system prompt."""
        if not self._hex_crawl_handler:
            return None
        
        status = self._hex_crawl_handler.engine.get_status()
        return status.full_status
    
    # =========================================================================
    # MAIN PROCESSING
    # =========================================================================
    
    def set_game_context(self, context: dict[str, Any]) -> None:
        """Update the current game context."""
        self._game_context.update(context)
    
    def process_player_input(self, player_input: str) -> DMResponse:
        """
        Process player input and generate DM response.
        
        Args:
            player_input: The player's action or statement.
            
        Returns:
            DMResponse with narrative and any mechanical results.
        """
        # Build messages
        # Get combat status if in combat
        combat_status = self._get_combat_status_for_prompt()
        
        # Get hex crawl status for exploration context
        hex_crawl_status = self._get_hex_crawl_status_for_prompt()
        
        # Build system prompt
        system_prompt = generate_system_prompt(
            self.config,
            self._game_context,
            combat_status=combat_status,
            hex_crawl_status=hex_crawl_status
        )

        # v2.0: Add state machine context to prompt
        state_context = self.get_state_context_for_prompt()
        if state_context:
            system_prompt += state_context

        # Add context from rules database if available
        context_used = []
        if self.rules_retriever and self.config.include_rules_context:
            context = self.rules_retriever.get_context_for_query(
                player_input,
                max_tokens=self.config.max_context_tokens,
                include_rules=self.config.include_rules_context,
                include_monsters=self.config.include_monster_context,
                include_locations=self.config.include_location_context
            )
            if context:
                system_prompt += f"\n\n## Relevant Rules Context\n{context}"
                context_used.append("rules_context")
        
        # Build conversation messages
        from ai.llm_provider import LLMMessage
        
        llm_messages = []
        for msg in self._conversation_history:
            llm_messages.append(LLMMessage(
                role=msg["role"],
                content=msg["content"]
            ))
        llm_messages.append(LLMMessage(role="user", content=player_input))
        
        # Call LLM provider with tools
        all_tool_results = []
        all_dice_rolls = []
        all_state_changes = {}
        
        try:
            # Determine tools to use
            tools = self._tool_definitions if self._provider.supports_tool_calling else self._tool_definitions
            
            response = self._provider.generate(
                messages=llm_messages,
                system_prompt=system_prompt,
                tools=tools,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
            )
            
            # Process tool calls (with loop for native tool calling)
            max_tool_iterations = 10
            iterations = 0
            
            while response.tool_calls and iterations < max_tool_iterations:
                iterations += 1
                tool_results_text = []

                for tool_call in response.tool_calls:
                    tool_result = self._execute_tool(tool_call.name, tool_call.arguments)
                    all_tool_results.append(tool_result)
                    all_dice_rolls.extend(tool_result.dice_rolls)
                    all_state_changes.update(tool_result.state_changes)

                    # v2.0: Check for state transitions triggered by this tool
                    transition_info = self._process_tool_transition(
                        tool_name=tool_call.name,
                        tool_args=tool_call.arguments,
                        tool_result=tool_result.message
                    )
                    if transition_info:
                        all_state_changes["state_transition"] = transition_info

                    # Format result for next message
                    tool_results_text.append(
                        f"[Tool: {tool_call.name}] Result: {json.dumps(tool_result.to_dict())}"
                    )
                
                # For providers with native tool support, continue the conversation
                if self._provider.supports_tool_calling:
                    # Add assistant message with tool calls indication
                    assistant_content = response.content
                    if not assistant_content:
                        assistant_content = f"Using tools: {', '.join(tc.name for tc in response.tool_calls)}"
                    llm_messages.append(LLMMessage(role="assistant", content=assistant_content))
                    
                    # Add tool results
                    llm_messages.append(LLMMessage(
                        role="user",
                        content="\n".join(tool_results_text)
                    ))
                    
                    # Continue generation
                    response = self._provider.generate(
                        messages=llm_messages,
                        system_prompt=system_prompt,
                        tools=tools,
                        max_tokens=self.config.max_tokens,
                        temperature=self.config.temperature,
                    )
                else:
                    # For prompt-based tools, we already have content - just append tool results
                    # and do one more generation for the narrative
                    tool_results_summary = "\n".join(tool_results_text)
                    llm_messages.append(LLMMessage(
                        role="assistant", 
                        content=response.content or "Processing..."
                    ))
                    llm_messages.append(LLMMessage(
                        role="user",
                        content=f"Tool results:\n{tool_results_summary}\n\nNow provide your narrative response incorporating these results."
                    ))
                    
                    response = self._provider.generate(
                        messages=llm_messages,
                        system_prompt=system_prompt,
                        tools=None,  # No tools for narrative response
                        max_tokens=self.config.max_tokens,
                        temperature=self.config.temperature,
                    )
                    break  # Exit loop for non-native tool calling
            
            # Extract final narrative
            narrative = response.content
            
            # Update conversation history
            self._conversation_history.append({"role": "user", "content": player_input})
            self._conversation_history.append({"role": "assistant", "content": narrative})
            
            # Trim history if too long
            if len(self._conversation_history) > self._max_history_length * 2:
                self._conversation_history = self._conversation_history[-self._max_history_length * 2:]
            
            return DMResponse(
                narrative=narrative,
                tool_results=all_tool_results,
                dice_rolls=all_dice_rolls,
                state_changes=all_state_changes,
                context_used=context_used,
                raw_response=str(response.raw_response) if response.raw_response else "",
                model_used=self._provider.provider_name
            )
            
        except Exception as e:
            logger.error(f"Error processing input: {e}")
            return DMResponse(
                narrative=f"*The DM pauses, looking troubled.* I apologize, but I encountered an issue: {str(e)}",
                tool_results=[],
                dice_rolls=[],
                state_changes={},
                model_used=self._provider.provider_name
            )
    
    def clear_history(self) -> None:
        """Clear conversation history."""
        self._conversation_history = []
    
    def get_conversation_summary(self) -> str:
        """Get a summary of the conversation so far."""
        if not self._conversation_history:
            return "No conversation history yet."
        
        summary_parts = []
        for msg in self._conversation_history[-10:]:  # Last 10 messages
            role = "Player" if msg["role"] == "user" else "DM"
            content = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
            summary_parts.append(f"{role}: {content}")
        
        return "\n".join(summary_parts)


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def create_dm(
    config: Optional[DMConfig] = None,
    rules_retriever: Optional[Any] = None,
    state_manager: Optional[Any] = None,
    campaign_id: Optional[str] = None
) -> DolmenwoodDM:
    """Create a new DolmenwoodDM instance."""
    return DolmenwoodDM(
        config=config,
        rules_retriever=rules_retriever,
        state_manager=state_manager,
        campaign_id=campaign_id
    )
