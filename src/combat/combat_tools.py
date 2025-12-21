"""
Dolmenwood AI DM - Combat Tools for Claude Integration

This module provides tool definitions and handlers that allow Claude
to interact with the Combat Engine through structured tool calls.

The tools are designed to:
1. Minimize what Claude needs to remember
2. Provide clear, brief summaries for narration
3. Handle all mechanical bookkeeping automatically

Author: AI Dungeon Master Project
Version: 1.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from .combat_engine import (
    CombatEngine,
    Combatant,
    CombatStatus,
    AttackResult,
    TurnResult,
    SaveResult,
    CombatPhase,
    CombatEndReason,
    create_combatant_from_character,
    create_combatant_from_monster,
)

logger = logging.getLogger(__name__)


# =============================================================================
# TOOL DEFINITIONS FOR CLAUDE
# =============================================================================

COMBAT_TOOL_DEFINITIONS = [
    {
        "name": "start_combat",
        "description": """Start a new combat encounter. Call this when combat begins.
        
Provide the party members and enemies involved. The system will:
- Roll initiative for all combatants
- Sort into initiative order
- Return whose turn it is first

Example: When 3 goblins ambush the party, call this with the party and goblin stats.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "party": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Character name"},
                            "hp_current": {"type": "integer", "description": "Current HP"},
                            "hp_max": {"type": "integer", "description": "Maximum HP"},
                            "ac": {"type": "integer", "description": "Armor Class"},
                            "attack_bonus": {"type": "integer", "description": "Attack bonus", "default": 0},
                            "damage_dice": {"type": "string", "description": "Damage dice (e.g., '1d8+2')", "default": "1d6"}
                        },
                        "required": ["name", "hp_current", "hp_max", "ac"]
                    },
                    "description": "List of party members in combat"
                },
                "enemies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Enemy name (add numbers for multiples: 'Goblin 1')"},
                            "hp_current": {"type": "integer", "description": "Current HP"},
                            "hp_max": {"type": "integer", "description": "Maximum HP"},
                            "ac": {"type": "integer", "description": "Armor Class"},
                            "attack_bonus": {"type": "integer", "description": "Attack bonus", "default": 0},
                            "damage_dice": {"type": "string", "description": "Damage dice", "default": "1d6"},
                            "morale": {"type": "integer", "description": "Morale score (2-12)", "default": 7}
                        },
                        "required": ["name", "hp_current", "hp_max", "ac"]
                    },
                    "description": "List of enemies in combat"
                },
                "surprise": {
                    "type": "string",
                    "enum": ["party", "enemies", "none"],
                    "description": "Which side has surprise (gets free round)",
                    "default": "none"
                }
            },
            "required": ["party", "enemies"]
        }
    },
    {
        "name": "combat_attack",
        "description": """Make an attack roll in combat. Use when a combatant attacks.
        
The system will:
- Roll the attack (d20 + attack bonus)
- Check for hit/miss/critical/fumble
- Roll and apply damage if hit
- Check for target death
- Return a brief summary to narrate

Call end_turn after each combatant finishes their action(s).""",
        "input_schema": {
            "type": "object",
            "properties": {
                "attacker": {
                    "type": "string",
                    "description": "Name of the attacking combatant"
                },
                "target": {
                    "type": "string",
                    "description": "Name of the target"
                },
                "attack_bonus": {
                    "type": "integer",
                    "description": "Override attack bonus (optional)"
                },
                "damage_dice": {
                    "type": "string",
                    "description": "Override damage dice (optional, e.g., '2d6+3')"
                },
                "damage_bonus": {
                    "type": "integer",
                    "description": "Extra damage bonus",
                    "default": 0
                }
            },
            "required": ["attacker", "target"]
        }
    },
    {
        "name": "combat_damage",
        "description": """Apply damage to a combatant from non-attack sources (spells, traps, effects).
        
Use this for:
- Spell damage (fireball, magic missile)
- Trap damage
- Environmental damage
- Any damage not from a standard attack roll""",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Name of the target taking damage"
                },
                "damage": {
                    "type": "integer",
                    "description": "Amount of damage"
                },
                "source": {
                    "type": "string",
                    "description": "Source of the damage (e.g., 'fireball', 'pit trap')"
                }
            },
            "required": ["target", "damage"]
        }
    },
    {
        "name": "combat_heal",
        "description": """Heal a combatant during combat.
        
Use for healing spells, potions, or abilities used during combat.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Name of the character being healed"
                },
                "amount": {
                    "type": "integer",
                    "description": "Amount of HP to restore"
                },
                "source": {
                    "type": "string",
                    "description": "Source of healing (e.g., 'Cure Light Wounds', 'healing potion')",
                    "default": "healing"
                }
            },
            "required": ["target", "amount"]
        }
    },
    {
        "name": "combat_save",
        "description": """Make a saving throw for a combatant.
        
Use when a combatant needs to save against an effect (spell, breath weapon, etc.).
Returns whether they saved or failed.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "character": {
                    "type": "string",
                    "description": "Name of the character making the save"
                },
                "save_type": {
                    "type": "string",
                    "enum": ["doom", "ray", "hold", "blast", "spell"],
                    "description": "Type of saving throw"
                },
                "target": {
                    "type": "integer",
                    "description": "Target number to meet or beat"
                },
                "modifier": {
                    "type": "integer",
                    "description": "Modifier to the roll",
                    "default": 0
                },
                "effect": {
                    "type": "string",
                    "description": "What they're saving against (e.g., 'dragon breath', 'hold person')"
                }
            },
            "required": ["character", "save_type", "target", "effect"]
        }
    },
    {
        "name": "end_turn",
        "description": """End the current combatant's turn and advance to the next.
        
ALWAYS call this after a combatant finishes their action(s). The system will:
- Advance to the next active combatant (skipping dead/fled)
- Track round changes
- Check morale automatically when triggered
- Detect if combat has ended
- Tell you whose turn is next""",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_combat_status",
        "description": """Get the current state of combat.
        
Call this when you need to know:
- Whose turn it is
- What round it is
- HP status of all combatants
- Initiative order

Returns a formatted status summary.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "detailed": {
                    "type": "boolean",
                    "description": "Get detailed status with full info",
                    "default": False
                }
            },
            "required": []
        }
    },
    {
        "name": "combat_flee",
        "description": """Have a combatant flee from combat.
        
Use when:
- An enemy decides to run
- A party member retreats
- Morale breaks (though this is usually automatic)""",
        "input_schema": {
            "type": "object",
            "properties": {
                "combatant": {
                    "type": "string",
                    "description": "Name of the combatant fleeing"
                }
            },
            "required": ["combatant"]
        }
    },
    {
        "name": "combat_condition",
        "description": """Add or remove a condition from a combatant.
        
Use for conditions like: poisoned, paralyzed, blinded, stunned, prone, etc.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "combatant": {
                    "type": "string",
                    "description": "Name of the combatant"
                },
                "condition": {
                    "type": "string",
                    "description": "The condition (e.g., 'poisoned', 'paralyzed')"
                },
                "action": {
                    "type": "string",
                    "enum": ["add", "remove"],
                    "description": "Whether to add or remove the condition"
                }
            },
            "required": ["combatant", "condition", "action"]
        }
    },
    {
        "name": "end_combat",
        "description": """Manually end combat.
        
Use when combat ends through negotiation, interruption, or other non-standard means.
(Combat ends automatically when all enemies or party are defeated/fled.)""",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "enum": ["negotiated", "interrupted", "enemies_fled", "party_fled"],
                    "description": "Why combat is ending"
                }
            },
            "required": ["reason"]
        }
    },
    {
        "name": "force_morale",
        "description": """Force a morale check for enemies (e.g., from intimidation or spell effect).
        
Morale is normally checked automatically on first casualty and when half enemies fall.
Use this for forced checks from player actions.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "modifier": {
                    "type": "integer",
                    "description": "Modifier to the morale check (negative = harder for enemies)",
                    "default": 0
                }
            },
            "required": []
        }
    }
]


# =============================================================================
# COMBAT TOOL HANDLER
# =============================================================================

@dataclass
class CombatToolResult:
    """Result from a combat tool call."""
    success: bool
    brief: str  # Short description for Claude to narrate
    data: dict[str, Any] = field(default_factory=dict)
    combat_ended: bool = False
    end_reason: Optional[str] = None


class CombatToolHandler:
    """
    Handles combat tool calls from Claude.
    
    Wraps the CombatEngine and provides Claude-friendly tool interfaces.
    
    Example:
        >>> handler = CombatToolHandler()
        >>> result = handler.handle_tool("start_combat", {...})
        >>> print(result.brief)  # Claude uses this to narrate
    """
    
    def __init__(self):
        """Initialize with a fresh combat engine."""
        self.engine = CombatEngine()
    
    @property
    def is_combat_active(self) -> bool:
        """Check if combat is currently active."""
        return self.engine.phase == CombatPhase.IN_PROGRESS
    
    def handle_tool(self, tool_name: str, tool_input: dict[str, Any]) -> CombatToolResult:
        """
        Handle a combat tool call.
        
        Args:
            tool_name: Name of the tool being called.
            tool_input: Input parameters for the tool.
        
        Returns:
            CombatToolResult with brief description and data.
        """
        handlers = {
            "start_combat": self._handle_start_combat,
            "combat_attack": self._handle_attack,
            "combat_damage": self._handle_damage,
            "combat_heal": self._handle_heal,
            "combat_save": self._handle_save,
            "end_turn": self._handle_end_turn,
            "get_combat_status": self._handle_get_status,
            "combat_flee": self._handle_flee,
            "combat_condition": self._handle_condition,
            "end_combat": self._handle_end_combat,
            "force_morale": self._handle_force_morale,
        }
        
        handler = handlers.get(tool_name)
        if not handler:
            return CombatToolResult(
                success=False,
                brief=f"Unknown combat tool: {tool_name}"
            )
        
        try:
            return handler(tool_input)
        except Exception as e:
            logger.error(f"Combat tool error ({tool_name}): {e}")
            return CombatToolResult(
                success=False,
                brief=f"Error: {str(e)}"
            )
    
    def _handle_start_combat(self, input: dict) -> CombatToolResult:
        """Handle start_combat tool."""
        # Convert party dicts to Combatants
        party = []
        for p in input.get("party", []):
            party.append(Combatant(
                name=p["name"],
                hp_current=p["hp_current"],
                hp_max=p["hp_max"],
                ac=p["ac"],
                attack_bonus=p.get("attack_bonus", 0),
                damage_dice=p.get("damage_dice", "1d6"),
                is_player=True
            ))
        
        # Convert enemy dicts to Combatants
        enemies = []
        for e in input.get("enemies", []):
            enemies.append(Combatant(
                name=e["name"],
                hp_current=e["hp_current"],
                hp_max=e["hp_max"],
                ac=e["ac"],
                attack_bonus=e.get("attack_bonus", 0),
                damage_dice=e.get("damage_dice", "1d6"),
                morale=e.get("morale", 7),
                is_player=False
            ))
        
        # Handle surprise
        surprise = input.get("surprise", "none")
        surprise_param = None if surprise == "none" else surprise
        
        # Start combat
        status = self.engine.start_combat(
            party=party,
            enemies=enemies,
            surprise=surprise_param
        )
        
        # Build initiative announcement
        init_order = " → ".join(status.initiative_order)
        current = status.current_combatant
        
        brief_parts = [
            f"Combat begins! Initiative order: {init_order}.",
        ]
        
        if surprise_param:
            brief_parts.insert(0, f"The {surprise_param} have surprise!")
        
        brief_parts.append(f"Round 1: It's {current}'s turn." + 
                          (" What do they do?" if status.current_is_player else ""))
        
        return CombatToolResult(
            success=True,
            brief=" ".join(brief_parts),
            data={
                "round": 1,
                "current_combatant": current,
                "current_is_player": status.current_is_player,
                "initiative_order": status.initiative_order,
                "party_status": status.party_status,
                "enemy_status": status.enemy_status
            }
        )
    
    def _handle_attack(self, input: dict) -> CombatToolResult:
        """Handle combat_attack tool."""
        if not self.is_combat_active:
            return CombatToolResult(
                success=False,
                brief="No combat active. Use start_combat first."
            )
        
        result = self.engine.attack(
            attacker_name=input["attacker"],
            target_name=input["target"],
            attack_bonus=input.get("attack_bonus"),
            damage_dice=input.get("damage_dice"),
            damage_bonus=input.get("damage_bonus", 0)
        )
        
        return CombatToolResult(
            success=True,
            brief=result.brief,
            data={
                "hit": result.hit,
                "critical": result.critical,
                "fumble": result.fumble,
                "damage": result.damage_dealt,
                "target_killed": result.target_killed,
                "attack_roll": result.attack_roll.total
            }
        )
    
    def _handle_damage(self, input: dict) -> CombatToolResult:
        """Handle combat_damage tool."""
        if not self.is_combat_active:
            return CombatToolResult(
                success=False,
                brief="No combat active."
            )
        
        result = self.engine.apply_damage(
            target_name=input["target"],
            damage=input["damage"],
            source=input.get("source", "unknown")
        )
        
        return CombatToolResult(
            success=True,
            brief=result["brief"],
            data=result
        )
    
    def _handle_heal(self, input: dict) -> CombatToolResult:
        """Handle combat_heal tool."""
        if not self.is_combat_active:
            return CombatToolResult(
                success=False,
                brief="No combat active."
            )
        
        result = self.engine.apply_healing(
            target_name=input["target"],
            amount=input["amount"],
            source=input.get("source", "healing")
        )
        
        return CombatToolResult(
            success=True,
            brief=result["brief"],
            data=result
        )
    
    def _handle_save(self, input: dict) -> CombatToolResult:
        """Handle combat_save tool."""
        if not self.is_combat_active:
            return CombatToolResult(
                success=False,
                brief="No combat active."
            )
        
        result = self.engine.saving_throw(
            character_name=input["character"],
            save_type=input["save_type"],
            target=input["target"],
            modifier=input.get("modifier", 0),
            effect=input["effect"]
        )
        
        return CombatToolResult(
            success=True,
            brief=result.brief,
            data={
                "saved": result.success,
                "roll": result.roll.total,
                "target": result.target
            }
        )
    
    def _handle_end_turn(self, input: dict) -> CombatToolResult:
        """Handle end_turn tool."""
        if not self.is_combat_active:
            return CombatToolResult(
                success=False,
                brief="No combat active."
            )
        
        result = self.engine.end_turn()
        
        return CombatToolResult(
            success=True,
            brief=result.brief,
            data={
                "round": result.round_number,
                "new_round": result.new_round,
                "next_combatant": result.next_combatant,
                "next_is_player": result.next_is_player,
                "morale_checked": result.morale_check is not None,
                "morale_passed": result.morale_check.passed if result.morale_check else None
            },
            combat_ended=result.combat_ended,
            end_reason=result.end_reason.value if result.end_reason else None
        )
    
    def _handle_get_status(self, input: dict) -> CombatToolResult:
        """Handle get_combat_status tool."""
        status = self.engine.get_status()
        
        detailed = input.get("detailed", False)
        brief = status.full_status if detailed else status.brief
        
        return CombatToolResult(
            success=True,
            brief=brief,
            data={
                "phase": status.phase.value,
                "round": status.round_number,
                "current_combatant": status.current_combatant,
                "current_is_player": status.current_is_player,
                "party_count": status.active_party_count,
                "enemy_count": status.active_enemy_count
            }
        )
    
    def _handle_flee(self, input: dict) -> CombatToolResult:
        """Handle combat_flee tool."""
        if not self.is_combat_active:
            return CombatToolResult(
                success=False,
                brief="No combat active."
            )
        
        result = self.engine.flee(input["combatant"])
        
        # Check if this ended combat
        ended, reason = self.engine._check_combat_end()
        if ended:
            self.engine.phase = CombatPhase.ENDED
        
        return CombatToolResult(
            success=True,
            brief=result["brief"],
            data=result,
            combat_ended=ended,
            end_reason=reason.value if reason else None
        )
    
    def _handle_condition(self, input: dict) -> CombatToolResult:
        """Handle combat_condition tool."""
        if not self.is_combat_active:
            return CombatToolResult(
                success=False,
                brief="No combat active."
            )
        
        combatant = input["combatant"]
        condition = input["condition"]
        action = input["action"]
        
        if action == "add":
            self.engine.add_condition(combatant, condition)
            brief = f"{combatant} is now {condition}."
        else:
            self.engine.remove_condition(combatant, condition)
            brief = f"{combatant} is no longer {condition}."
        
        return CombatToolResult(
            success=True,
            brief=brief,
            data={"combatant": combatant, "condition": condition, "action": action}
        )
    
    def _handle_end_combat(self, input: dict) -> CombatToolResult:
        """Handle end_combat tool."""
        reason_str = input["reason"]
        reason_map = {
            "negotiated": CombatEndReason.NEGOTIATED,
            "interrupted": CombatEndReason.INTERRUPTED,
            "enemies_fled": CombatEndReason.ENEMIES_FLED,
            "party_fled": CombatEndReason.PARTY_FLED,
        }
        
        reason = reason_map.get(reason_str, CombatEndReason.INTERRUPTED)
        self.engine.end_combat(reason)
        
        return CombatToolResult(
            success=True,
            brief=f"Combat ended ({reason_str}).",
            combat_ended=True,
            end_reason=reason_str
        )
    
    def _handle_force_morale(self, input: dict) -> CombatToolResult:
        """Handle force_morale tool."""
        if not self.is_combat_active:
            return CombatToolResult(
                success=False,
                brief="No combat active."
            )
        
        result = self.engine.force_morale_check(
            modifier=input.get("modifier", 0)
        )
        
        if result is None:
            return CombatToolResult(
                success=True,
                brief="No enemies with morale scores to check.",
                data={}
            )
        
        # Check if this ended combat
        ended, reason = self.engine._check_combat_end()
        if ended:
            self.engine.phase = CombatPhase.ENDED
        
        return CombatToolResult(
            success=True,
            brief=result.brief,
            data={
                "passed": result.passed,
                "roll": result.roll.total,
                "morale_score": result.morale_score
            },
            combat_ended=ended,
            end_reason=reason.value if reason else None
        )
    
    def reset(self) -> None:
        """Reset for a new combat (after combat ends)."""
        self.engine = CombatEngine()


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def create_combat_handler() -> CombatToolHandler:
    """Create a new combat tool handler."""
    return CombatToolHandler()
