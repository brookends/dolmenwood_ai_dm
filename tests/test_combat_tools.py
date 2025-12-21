"""
Tests for Combat Tools Module.

Tests the tool handler integration with the combat engine.
"""

import sys
import pytest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from combat.combat_tools import (
    CombatToolHandler,
    CombatToolResult,
    COMBAT_TOOL_DEFINITIONS,
    create_combat_handler,
)
from combat.combat_engine import CombatPhase


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def handler():
    """Create a fresh tool handler."""
    return CombatToolHandler()


@pytest.fixture
def party_data():
    """Party member data for tool calls."""
    return [
        {
            "name": "Aldric",
            "hp_current": 20,
            "hp_max": 20,
            "ac": 16,
            "attack_bonus": 3,
            "damage_dice": "1d8+2"
        },
        {
            "name": "Elara",
            "hp_current": 8,
            "hp_max": 8,
            "ac": 11,
            "attack_bonus": 0,
            "damage_dice": "1d4"
        }
    ]


@pytest.fixture
def enemy_data():
    """Enemy data for tool calls."""
    return [
        {
            "name": "Goblin 1",
            "hp_current": 4,
            "hp_max": 4,
            "ac": 13,
            "attack_bonus": 1,
            "damage_dice": "1d6",
            "morale": 7
        },
        {
            "name": "Goblin 2",
            "hp_current": 4,
            "hp_max": 4,
            "ac": 13,
            "attack_bonus": 1,
            "damage_dice": "1d6",
            "morale": 7
        }
    ]


@pytest.fixture
def active_combat(handler, party_data, enemy_data):
    """Start combat and return handler."""
    # Disable morale for predictable tests
    for e in enemy_data:
        e["morale"] = 12  # Very high = won't flee
    
    handler.handle_tool("start_combat", {
        "party": party_data,
        "enemies": enemy_data
    })
    return handler


# =============================================================================
# TOOL DEFINITIONS TESTS
# =============================================================================

class TestToolDefinitions:
    """Test tool definitions structure."""
    
    def test_all_required_tools_defined(self):
        """Test that all combat tools are defined."""
        tool_names = [t["name"] for t in COMBAT_TOOL_DEFINITIONS]
        
        required = [
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
            "force_morale"
        ]
        
        for name in required:
            assert name in tool_names, f"Missing tool: {name}"
    
    def test_tool_definitions_format(self):
        """Test tool definitions have correct format."""
        for tool in COMBAT_TOOL_DEFINITIONS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"
            assert "properties" in tool["input_schema"]


# =============================================================================
# START COMBAT TESTS
# =============================================================================

class TestStartCombat:
    """Test start_combat tool."""
    
    def test_start_combat_success(self, handler, party_data, enemy_data):
        """Test starting combat successfully."""
        result = handler.handle_tool("start_combat", {
            "party": party_data,
            "enemies": enemy_data
        })
        
        assert result.success
        assert "Combat begins" in result.brief
        assert handler.is_combat_active
    
    def test_start_combat_with_surprise(self, handler, party_data, enemy_data):
        """Test starting combat with surprise."""
        result = handler.handle_tool("start_combat", {
            "party": party_data,
            "enemies": enemy_data,
            "surprise": "party"
        })
        
        assert result.success
        assert "surprise" in result.brief.lower()
    
    def test_start_combat_returns_initiative(self, handler, party_data, enemy_data):
        """Test that start_combat returns initiative order."""
        result = handler.handle_tool("start_combat", {
            "party": party_data,
            "enemies": enemy_data
        })
        
        assert "initiative_order" in result.data
        assert len(result.data["initiative_order"]) == 4
    
    def test_start_combat_returns_first_turn(self, handler, party_data, enemy_data):
        """Test that start_combat indicates first turn."""
        result = handler.handle_tool("start_combat", {
            "party": party_data,
            "enemies": enemy_data
        })
        
        assert "current_combatant" in result.data
        assert result.data["round"] == 1


# =============================================================================
# ATTACK TESTS
# =============================================================================

class TestCombatAttack:
    """Test combat_attack tool."""
    
    def test_attack_requires_active_combat(self, handler):
        """Test attack fails without active combat."""
        result = handler.handle_tool("combat_attack", {
            "attacker": "Aldric",
            "target": "Goblin 1"
        })
        
        assert not result.success
        assert "No combat active" in result.brief
    
    def test_attack_success(self, active_combat):
        """Test attack during combat."""
        result = active_combat.handle_tool("combat_attack", {
            "attacker": "Aldric",
            "target": "Goblin 1"
        })
        
        assert result.success
        assert "Aldric" in result.brief
        assert "Goblin 1" in result.brief
    
    def test_attack_returns_hit_status(self, active_combat):
        """Test attack returns hit/miss info."""
        result = active_combat.handle_tool("combat_attack", {
            "attacker": "Aldric",
            "target": "Goblin 1"
        })
        
        assert "hit" in result.data
        assert "damage" in result.data
        assert "attack_roll" in result.data
    
    def test_attack_with_custom_damage(self, active_combat):
        """Test attack with custom damage dice."""
        result = active_combat.handle_tool("combat_attack", {
            "attacker": "Aldric",
            "target": "Goblin 1",
            "damage_dice": "2d6+5"
        })
        
        assert result.success


# =============================================================================
# DAMAGE AND HEALING TESTS
# =============================================================================

class TestDamageHealing:
    """Test damage and healing tools."""
    
    def test_damage_applies(self, active_combat):
        """Test applying damage."""
        result = active_combat.handle_tool("combat_damage", {
            "target": "Aldric",
            "damage": 5,
            "source": "trap"
        })
        
        assert result.success
        assert "5 damage" in result.brief
    
    def test_healing_applies(self, active_combat):
        """Test applying healing."""
        # First damage
        active_combat.handle_tool("combat_damage", {
            "target": "Aldric",
            "damage": 10
        })
        
        # Then heal
        result = active_combat.handle_tool("combat_heal", {
            "target": "Aldric",
            "amount": 5,
            "source": "potion"
        })
        
        assert result.success
        assert "heals" in result.brief.lower()


# =============================================================================
# SAVING THROW TESTS
# =============================================================================

class TestSavingThrows:
    """Test combat_save tool."""
    
    def test_save_success(self, active_combat):
        """Test making a save."""
        result = active_combat.handle_tool("combat_save", {
            "character": "Aldric",
            "save_type": "blast",
            "target": 12,
            "effect": "dragon breath"
        })
        
        assert result.success
        assert "Aldric" in result.brief
        assert "dragon breath" in result.brief
    
    def test_save_returns_result(self, active_combat):
        """Test save returns success/fail info."""
        result = active_combat.handle_tool("combat_save", {
            "character": "Aldric",
            "save_type": "spell",
            "target": 15,
            "effect": "charm"
        })
        
        assert "saved" in result.data
        assert "roll" in result.data


# =============================================================================
# TURN MANAGEMENT TESTS
# =============================================================================

class TestTurnManagement:
    """Test end_turn and status tools."""
    
    def test_end_turn_advances(self, active_combat):
        """Test end_turn advances to next combatant."""
        # Get current
        status1 = active_combat.handle_tool("get_combat_status", {})
        current1 = status1.data["current_combatant"]
        
        # End turn
        result = active_combat.handle_tool("end_turn", {})
        
        assert result.success
        
        # Check advanced
        if not result.combat_ended:
            status2 = active_combat.handle_tool("get_combat_status", {})
            # Could be same if combat ended
            assert status2.success
    
    def test_get_status(self, active_combat):
        """Test getting combat status."""
        result = active_combat.handle_tool("get_combat_status", {})
        
        assert result.success
        assert "round" in result.data
        assert "party_count" in result.data
        assert "enemy_count" in result.data
    
    def test_get_detailed_status(self, active_combat):
        """Test getting detailed status."""
        result = active_combat.handle_tool("get_combat_status", {
            "detailed": True
        })
        
        assert result.success
        assert "COMBAT STATUS" in result.brief or "Round" in result.brief


# =============================================================================
# FLEE TESTS
# =============================================================================

class TestFlee:
    """Test combat_flee tool."""
    
    def test_flee_removes_combatant(self, active_combat):
        """Test fleeing removes from combat."""
        result = active_combat.handle_tool("combat_flee", {
            "combatant": "Goblin 1"
        })
        
        assert result.success
        assert "flees" in result.brief.lower()


# =============================================================================
# CONDITION TESTS
# =============================================================================

class TestConditions:
    """Test combat_condition tool."""
    
    def test_add_condition(self, active_combat):
        """Test adding a condition."""
        result = active_combat.handle_tool("combat_condition", {
            "combatant": "Aldric",
            "condition": "poisoned",
            "action": "add"
        })
        
        assert result.success
        assert "poisoned" in result.brief
    
    def test_remove_condition(self, active_combat):
        """Test removing a condition."""
        # Add first
        active_combat.handle_tool("combat_condition", {
            "combatant": "Aldric",
            "condition": "stunned",
            "action": "add"
        })
        
        # Remove
        result = active_combat.handle_tool("combat_condition", {
            "combatant": "Aldric",
            "condition": "stunned",
            "action": "remove"
        })
        
        assert result.success
        assert "no longer" in result.brief.lower()


# =============================================================================
# END COMBAT TESTS
# =============================================================================

class TestEndCombat:
    """Test end_combat tool."""
    
    def test_end_combat_manual(self, active_combat):
        """Test manually ending combat."""
        result = active_combat.handle_tool("end_combat", {
            "reason": "negotiated"
        })
        
        assert result.success
        assert result.combat_ended
        assert not active_combat.is_combat_active


# =============================================================================
# MORALE TESTS
# =============================================================================

class TestMorale:
    """Test force_morale tool."""
    
    def test_force_morale(self, handler, party_data, enemy_data):
        """Test forcing a morale check."""
        handler.handle_tool("start_combat", {
            "party": party_data,
            "enemies": enemy_data
        })
        
        result = handler.handle_tool("force_morale", {
            "modifier": -2
        })
        
        assert result.success
        # Should have morale result or no enemies with morale
        assert "passed" in result.data or "No enemies" in result.brief


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestCombatFlow:
    """Test complete combat flow."""
    
    def test_full_combat_round(self, handler, party_data, enemy_data):
        """Test a full round of combat."""
        # Start combat
        result = handler.handle_tool("start_combat", {
            "party": party_data,
            "enemies": [{
                "name": "Goblin",
                "hp_current": 20,  # High HP so combat continues
                "hp_max": 20,
                "ac": 13,
                "morale": 12  # High morale
            }]
        })
        assert result.success
        
        # Get first combatant
        status = handler.handle_tool("get_combat_status", {})
        
        # Each combatant takes a turn
        turn_count = 0
        while handler.is_combat_active and turn_count < 5:
            # Make an attack
            current = status.data["current_combatant"]
            if status.data["current_is_player"]:
                handler.handle_tool("combat_attack", {
                    "attacker": current,
                    "target": "Goblin"
                })
            else:
                handler.handle_tool("combat_attack", {
                    "attacker": current,
                    "target": "Aldric"
                })
            
            # End turn
            result = handler.handle_tool("end_turn", {})
            if result.combat_ended:
                break
            
            status = handler.handle_tool("get_combat_status", {})
            turn_count += 1
        
        # Should have progressed
        assert turn_count > 0 or not handler.is_combat_active
    
    def test_combat_ends_on_defeat(self, handler, party_data):
        """Test combat ends when enemies defeated."""
        # Start with weak enemy
        handler.handle_tool("start_combat", {
            "party": party_data,
            "enemies": [{
                "name": "Weak Goblin",
                "hp_current": 1,
                "hp_max": 1,
                "ac": 10,
                "morale": 12
            }]
        })
        
        # Attack until dead
        for _ in range(20):
            result = handler.handle_tool("combat_attack", {
                "attacker": "Aldric",
                "target": "Weak Goblin",
                "damage_dice": "2d6"
            })
            
            if result.data.get("target_killed"):
                # End turn should end combat
                turn_result = handler.handle_tool("end_turn", {})
                assert turn_result.combat_ended
                break


# =============================================================================
# UTILITY TESTS
# =============================================================================

class TestUtilities:
    """Test utility functions."""
    
    def test_create_handler(self):
        """Test handler creation function."""
        handler = create_combat_handler()
        
        assert isinstance(handler, CombatToolHandler)
        assert not handler.is_combat_active
    
    def test_handler_reset(self, active_combat):
        """Test handler reset."""
        assert active_combat.is_combat_active
        
        active_combat.reset()
        
        assert not active_combat.is_combat_active
    
    def test_unknown_tool(self, handler):
        """Test handling unknown tool."""
        result = handler.handle_tool("unknown_tool", {})
        
        assert not result.success
        assert "Unknown" in result.brief


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
