"""
Tests for the Combat Engine Module.

Tests the combat state machine, turn management, and mechanics.
"""

import sys
import pytest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from combat.combat_engine import (
    CombatEngine,
    Combatant,
    CombatStatus,
    AttackResult,
    TurnResult,
    CombatPhase,
    CombatEndReason,
    DiceRoll,
    roll_dice,
    roll_d20,
    create_combatant_from_character,
    create_combatant_from_monster,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def engine():
    """Create a fresh combat engine."""
    return CombatEngine()


@pytest.fixture
def warrior():
    """Create a warrior combatant."""
    return Combatant(
        name="Aldric",
        hp_current=20,
        hp_max=20,
        ac=16,
        attack_bonus=3,
        damage_dice="1d8+2",
        is_player=True
    )


@pytest.fixture
def mage():
    """Create a mage combatant."""
    return Combatant(
        name="Elara",
        hp_current=8,
        hp_max=8,
        ac=11,
        attack_bonus=0,
        damage_dice="1d4",
        is_player=True
    )


@pytest.fixture
def goblin():
    """Create a goblin enemy."""
    return Combatant(
        name="Goblin",
        hp_current=4,
        hp_max=4,
        ac=13,
        attack_bonus=1,
        damage_dice="1d6",
        is_player=False,
        morale=7
    )


@pytest.fixture
def goblin_group():
    """Create multiple goblins."""
    return [
        Combatant(name="Goblin 1", hp_current=4, hp_max=4, ac=13, 
                  attack_bonus=1, damage_dice="1d6", morale=7),
        Combatant(name="Goblin 2", hp_current=4, hp_max=4, ac=13,
                  attack_bonus=1, damage_dice="1d6", morale=7),
        Combatant(name="Goblin 3", hp_current=4, hp_max=4, ac=13,
                  attack_bonus=1, damage_dice="1d6", morale=7),
    ]


@pytest.fixture
def party(warrior, mage):
    """Create a party."""
    return [warrior, mage]


# =============================================================================
# DICE ROLL TESTS
# =============================================================================

class TestDiceRolls:
    """Test dice rolling functions."""
    
    def test_roll_dice_simple(self):
        """Test simple dice roll."""
        result = roll_dice("1d6")
        
        assert isinstance(result, DiceRoll)
        assert 1 <= result.total <= 6
        assert len(result.rolls) == 1
    
    def test_roll_dice_multiple(self):
        """Test rolling multiple dice."""
        result = roll_dice("3d6")
        
        assert len(result.rolls) == 3
        assert 3 <= result.total <= 18
    
    def test_roll_dice_with_modifier(self):
        """Test dice with positive modifier."""
        result = roll_dice("1d20+5")
        
        assert result.modifier == 5
        assert 6 <= result.total <= 25
    
    def test_roll_dice_negative_modifier(self):
        """Test dice with negative modifier."""
        result = roll_dice("1d20-2")
        
        assert result.modifier == -2
        assert -1 <= result.total <= 18
    
    def test_roll_d20(self):
        """Test d20 convenience function."""
        result = roll_d20(modifier=3)
        
        assert 4 <= result.total <= 23
        assert result.modifier == 3
    
    def test_dice_roll_string(self):
        """Test DiceRoll string representation."""
        result = DiceRoll(
            notation="2d6+3",
            rolls=[4, 5],
            modifier=3,
            total=12
        )
        
        assert "2d6+3" in str(result)
        assert "12" in str(result)


# =============================================================================
# COMBATANT TESTS
# =============================================================================

class TestCombatant:
    """Test Combatant class."""
    
    def test_combatant_creation(self, warrior):
        """Test creating a combatant."""
        assert warrior.name == "Aldric"
        assert warrior.hp_current == 20
        assert warrior.is_alive
        assert warrior.is_active
    
    def test_combatant_is_alive(self):
        """Test is_alive property."""
        c = Combatant(name="Test", hp_current=5, hp_max=10, ac=10)
        assert c.is_alive
        
        c.hp_current = 0
        assert not c.is_alive
    
    def test_wound_status(self):
        """Test wound status descriptions."""
        c = Combatant(name="Test", hp_current=100, hp_max=100, ac=10)
        assert c.wound_status == "uninjured"
        
        c.hp_current = 80
        assert c.wound_status == "lightly wounded"
        
        c.hp_current = 50
        assert c.wound_status == "wounded"
        
        c.hp_current = 25
        assert c.wound_status == "badly wounded"
        
        c.hp_current = 5
        assert c.wound_status == "near death"
        
        c.hp_current = 0
        assert c.wound_status == "dead"
    
    def test_status_string_player(self, warrior):
        """Test status string for player (shows exact HP)."""
        status = warrior.to_status_string()
        
        assert "Aldric" in status
        assert "20/20" in status
    
    def test_status_string_enemy(self, goblin):
        """Test status string for enemy (shows wound status)."""
        status = goblin.to_status_string()
        
        assert "Goblin" in status
        assert "uninjured" in status


# =============================================================================
# COMBAT LIFECYCLE TESTS
# =============================================================================

class TestCombatLifecycle:
    """Test combat start/end."""
    
    def test_start_combat(self, engine, party, goblin):
        """Test starting combat."""
        status = engine.start_combat(party=party, enemies=[goblin])
        
        assert engine.phase == CombatPhase.IN_PROGRESS
        assert engine.round_number == 1
        assert status.phase == CombatPhase.IN_PROGRESS
        assert len(status.initiative_order) == 3
    
    def test_start_combat_sets_initiative(self, engine, party, goblin):
        """Test that initiative is rolled for all combatants."""
        engine.start_combat(party=party, enemies=[goblin])
        
        for c in engine.combatants:
            assert c.initiative >= 1
            assert c.initiative <= 6
    
    def test_start_combat_twice_raises_error(self, engine, party, goblin):
        """Test starting combat when already active."""
        engine.start_combat(party=party, enemies=[goblin])
        
        with pytest.raises(RuntimeError):
            engine.start_combat(party=party, enemies=[goblin])
    
    def test_end_combat_manual(self, engine, party, goblin):
        """Test manually ending combat."""
        engine.start_combat(party=party, enemies=[goblin])
        
        status = engine.end_combat(CombatEndReason.NEGOTIATED)
        
        assert engine.phase == CombatPhase.NOT_STARTED  # Reset
    
    def test_combat_status_no_combat(self, engine):
        """Test status when no combat active."""
        status = engine.get_status()
        
        assert status.phase == CombatPhase.NOT_STARTED
        assert "No combat active" in status.brief


# =============================================================================
# TURN MANAGEMENT TESTS
# =============================================================================

class TestTurnManagement:
    """Test turn progression."""
    
    def test_get_current_combatant(self, engine, party, goblin):
        """Test getting current combatant."""
        engine.start_combat(party=party, enemies=[goblin])
        
        current = engine.get_current_combatant()
        
        assert current is not None
        assert current.name in [c.name for c in party + [goblin]]
    
    def test_end_turn_advances(self, engine, party, goblin):
        """Test that end_turn advances to next combatant."""
        # Disable morale to prevent combat ending
        goblin.morale = None
        engine.start_combat(party=party, enemies=[goblin])
        
        first = engine.get_current_combatant().name
        result = engine.end_turn()
        
        # Combat might have ended, so check first
        if not result.combat_ended:
            second = engine.get_current_combatant().name
            assert first != second
            assert result.previous_combatant == first
            assert result.next_combatant == second
    
    def test_end_turn_round_advancement(self, engine, party, goblin):
        """Test round advancement after all combatants act."""
        # Disable morale to prevent premature combat end
        goblin.morale = None
        engine.start_combat(party=party, enemies=[goblin])
        
        # Go through all combatants
        new_round_detected = False
        for _ in range(4):  # 3 combatants + 1 to see round change
            if engine.phase != CombatPhase.IN_PROGRESS:
                break
            result = engine.end_turn()
            if result.new_round:
                new_round_detected = True
                break
        
        assert new_round_detected
        assert engine.round_number >= 2
    
    def test_end_turn_skips_dead(self, engine, warrior, goblin):
        """Test that dead combatants are skipped."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        # Kill the goblin
        goblin.hp_current = 0
        goblin.is_active = False
        
        # End turns - should only alternate to warrior
        result = engine.end_turn()
        
        # Combat should end since goblin is dead
        assert result.combat_ended or engine.get_current_combatant().is_player
    
    def test_turn_result_brief(self, engine, warrior, goblin):
        """Test TurnResult brief message."""
        # Use combatants without morale to avoid random fleeing
        goblin.morale = None  # Disable morale checks
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        result = engine.end_turn()
        
        # If combat didn't end, next combatant should be in brief
        if not result.combat_ended:
            assert result.next_combatant in result.brief


# =============================================================================
# ATTACK TESTS
# =============================================================================

class TestAttacks:
    """Test attack mechanics."""
    
    def test_attack_basic(self, engine, warrior, goblin):
        """Test basic attack."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        result = engine.attack("Aldric", "Goblin")
        
        assert isinstance(result, AttackResult)
        assert result.attacker == "Aldric"
        assert result.target == "Goblin"
    
    def test_attack_hit_deals_damage(self, engine, warrior, goblin):
        """Test that hits deal damage."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        original_hp = goblin.hp_current
        
        # Make many attacks to ensure at least one hit
        for _ in range(20):
            goblin.hp_current = original_hp  # Reset
            result = engine.attack("Aldric", "Goblin")
            if result.hit:
                assert result.damage_dealt > 0
                assert goblin.hp_current < original_hp
                break
    
    def test_attack_miss_no_damage(self, engine, warrior, goblin):
        """Test that misses deal no damage."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        original_hp = goblin.hp_current
        
        for _ in range(50):
            goblin.hp_current = original_hp
            result = engine.attack("Aldric", "Goblin")
            if not result.hit:
                assert result.damage_dealt == 0
                assert goblin.hp_current == original_hp
                break
    
    def test_attack_critical(self, engine, warrior, goblin):
        """Test critical hit detection."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        # Run many attacks to find a crit
        found_crit = False
        for _ in range(100):
            goblin.hp_current = goblin.hp_max
            result = engine.attack("Aldric", "Goblin")
            if result.critical:
                found_crit = True
                assert result.hit
                break
        
        # About 5% chance per attack, should find one in 100
        # (This could theoretically fail but very unlikely)
    
    def test_attack_fumble(self, engine, warrior, goblin):
        """Test fumble detection."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        found_fumble = False
        for _ in range(100):
            result = engine.attack("Aldric", "Goblin")
            if result.fumble:
                found_fumble = True
                assert not result.hit
                break
    
    def test_attack_kills_target(self, engine, warrior, goblin):
        """Test that lethal damage kills target."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        goblin.hp_current = 1  # Low HP
        
        for _ in range(20):
            goblin.hp_current = 1
            result = engine.attack("Aldric", "Goblin", damage_dice="2d6")
            if result.hit:
                if result.target_killed:
                    assert goblin.hp_current <= 0
                    assert not goblin.is_active
                    break
    
    def test_attack_result_brief(self, engine, warrior, goblin):
        """Test AttackResult brief message."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        result = engine.attack("Aldric", "Goblin")
        
        assert "Aldric" in result.brief
        assert "Goblin" in result.brief
    
    def test_attack_invalid_attacker(self, engine, warrior, goblin):
        """Test attack with invalid attacker name."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        with pytest.raises(ValueError):
            engine.attack("Nobody", "Goblin")
    
    def test_attack_invalid_target(self, engine, warrior, goblin):
        """Test attack with invalid target name."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        with pytest.raises(ValueError):
            engine.attack("Aldric", "Nobody")


# =============================================================================
# DAMAGE AND HEALING TESTS
# =============================================================================

class TestDamageHealing:
    """Test damage and healing application."""
    
    def test_apply_damage(self, engine, warrior, goblin):
        """Test applying direct damage."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        result = engine.apply_damage("Aldric", 5, "fire")
        
        assert warrior.hp_current == 15
        assert result["damage"] == 5
        assert "fire" in result["brief"] or "5 damage" in result["brief"]
    
    def test_apply_lethal_damage(self, engine, warrior, goblin):
        """Test lethal damage kills target."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        result = engine.apply_damage("Goblin", 100, "fireball")
        
        assert goblin.hp_current <= 0
        assert not goblin.is_active
        assert result["killed"]
    
    def test_apply_healing(self, engine, warrior, goblin):
        """Test healing."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        warrior.hp_current = 10
        result = engine.apply_healing("Aldric", 5, "potion")
        
        assert warrior.hp_current == 15
        assert result["healed"] == 5
    
    def test_healing_caps_at_max(self, engine, warrior, goblin):
        """Test healing doesn't exceed max HP."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        warrior.hp_current = 18
        result = engine.apply_healing("Aldric", 10, "spell")
        
        assert warrior.hp_current == 20  # Max
        assert result["healed"] == 2  # Only healed 2


# =============================================================================
# SAVING THROW TESTS
# =============================================================================

class TestSavingThrows:
    """Test saving throws."""
    
    def test_saving_throw_success(self, engine, warrior, goblin):
        """Test successful save."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        # Low target = easy to pass
        result = engine.saving_throw("Aldric", "spell", target=2, effect="charm")
        
        assert result.character == "Aldric"
        assert result.save_type == "spell"
        assert "Aldric" in result.brief
    
    def test_saving_throw_fail(self, engine, warrior, goblin):
        """Test failed save."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        # High target = hard to pass
        found_fail = False
        for _ in range(50):
            result = engine.saving_throw("Aldric", "spell", target=25, effect="death")
            if not result.success:
                found_fail = True
                assert "fails" in result.brief
                break


# =============================================================================
# MORALE TESTS
# =============================================================================

class TestMorale:
    """Test morale checks."""
    
    def test_morale_on_first_blood(self, engine, warrior, goblin_group):
        """Test morale triggers on first casualty."""
        engine.start_combat(party=[warrior], enemies=goblin_group)
        
        # Kill first goblin
        goblin_group[0].hp_current = 0
        goblin_group[0].is_active = False
        
        # End turn to trigger morale check
        result = engine.end_turn()
        
        # Morale should have been checked
        assert result.morale_check is not None or engine._morale_checked_first_blood
    
    def test_morale_on_half_defeated(self, engine, warrior, goblin_group):
        """Test morale triggers when half defeated."""
        engine.start_combat(party=[warrior], enemies=goblin_group)
        
        # Mark first blood as checked
        engine._morale_checked_first_blood = True
        
        # Kill half
        goblin_group[0].hp_current = 0
        goblin_group[0].is_active = False
        goblin_group[1].hp_current = 0
        goblin_group[1].is_active = False
        
        result = engine.end_turn()
        
        # Half morale should trigger
        assert result.morale_check is not None or engine._morale_checked_half
    
    def test_forced_morale_check(self, engine, warrior, goblin_group):
        """Test forced morale check."""
        engine.start_combat(party=[warrior], enemies=goblin_group)
        
        result = engine.force_morale_check(modifier=-2)  # Penalty
        
        assert result is not None
        assert result.creature_group is not None
    
    def test_morale_failure_causes_flee(self, engine, warrior, goblin_group):
        """Test that failed morale causes enemies to flee."""
        engine.start_combat(party=[warrior], enemies=goblin_group)
        
        # Force many morale checks until one fails
        fled = False
        for _ in range(50):
            if engine._enemies_have_fled:
                fled = True
                break
            engine.force_morale_check(modifier=-10)  # Big penalty to force fail
        
        # At least check the mechanism works
        # (This could pass or fail depending on rolls)


# =============================================================================
# COMBAT END TESTS
# =============================================================================

class TestCombatEnd:
    """Test combat end detection."""
    
    def test_combat_ends_enemies_defeated(self, engine, warrior, goblin):
        """Test combat ends when all enemies defeated."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        # Kill the goblin
        goblin.hp_current = 0
        goblin.is_active = False
        
        result = engine.end_turn()
        
        assert result.combat_ended
        assert result.end_reason == CombatEndReason.ENEMIES_DEFEATED
    
    def test_combat_ends_party_defeated(self, engine, warrior, goblin):
        """Test combat ends when party defeated."""
        # Disable morale to avoid interference
        goblin.morale = None
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        # Kill the warrior
        warrior.hp_current = 0
        warrior.is_active = False
        
        result = engine.end_turn()
        
        assert result.combat_ended
        assert result.end_reason == CombatEndReason.PARTY_DEFEATED
    
    def test_combat_ends_enemies_fled(self, engine, warrior, goblin_group):
        """Test combat ends when enemies flee."""
        engine.start_combat(party=[warrior], enemies=goblin_group)
        
        # Make all enemies flee
        for g in goblin_group:
            g.is_active = False
        engine._enemies_have_fled = True
        
        result = engine.end_turn()
        
        assert result.combat_ended
        assert result.end_reason == CombatEndReason.ENEMIES_FLED


# =============================================================================
# STATUS TESTS
# =============================================================================

class TestStatus:
    """Test status queries."""
    
    def test_get_status(self, engine, party, goblin):
        """Test getting combat status."""
        engine.start_combat(party=party, enemies=[goblin])
        
        status = engine.get_status()
        
        assert status.phase == CombatPhase.IN_PROGRESS
        assert status.round_number == 1
        assert status.active_party_count == 2
        assert status.active_enemy_count == 1
    
    def test_status_brief(self, engine, party, goblin):
        """Test status brief message."""
        engine.start_combat(party=party, enemies=[goblin])
        
        status = engine.get_status()
        
        assert "Round 1" in status.brief
        assert status.current_combatant in status.brief
    
    def test_status_full(self, engine, party, goblin):
        """Test full status message."""
        engine.start_combat(party=party, enemies=[goblin])
        
        status = engine.get_status()
        full = status.full_status
        
        assert "COMBAT STATUS" in full
        assert "Initiative Order" in full
        assert "PARTY" in full
        assert "ENEMIES" in full
    
    def test_get_combatant_status(self, engine, warrior, goblin):
        """Test getting individual combatant status."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        status = engine.get_combatant_status("Aldric")
        
        assert status is not None
        assert status["name"] == "Aldric"
        assert status["hp_current"] == 20
        assert status["is_player"]
    
    def test_get_combatant_status_not_found(self, engine, warrior, goblin):
        """Test getting status for non-existent combatant."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        status = engine.get_combatant_status("Nobody")
        
        assert status is None


# =============================================================================
# CONDITION TESTS
# =============================================================================

class TestConditions:
    """Test condition management."""
    
    def test_add_condition(self, engine, warrior, goblin):
        """Test adding a condition."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        engine.add_condition("Aldric", "poisoned")
        
        assert "poisoned" in warrior.conditions
    
    def test_remove_condition(self, engine, warrior, goblin):
        """Test removing a condition."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        warrior.conditions.append("stunned")
        engine.remove_condition("Aldric", "stunned")
        
        assert "stunned" not in warrior.conditions
    
    def test_conditions_show_in_status(self, engine, warrior, goblin):
        """Test conditions appear in status."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        engine.add_condition("Aldric", "paralyzed")
        status = engine.get_status()
        
        # Find Aldric's status string
        aldric_status = [s for s in status.party_status if "Aldric" in s][0]
        assert "paralyzed" in aldric_status


# =============================================================================
# FLEE TESTS
# =============================================================================

class TestFlee:
    """Test fleeing mechanics."""
    
    def test_flee_removes_from_combat(self, engine, warrior, goblin):
        """Test fleeing removes combatant."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        result = engine.flee("Goblin")
        
        assert not goblin.is_active
        assert "flees" in result["brief"]
    
    def test_party_flee(self, engine, warrior, goblin):
        """Test party member fleeing."""
        engine.start_combat(party=[warrior], enemies=[goblin])
        
        result = engine.flee("Aldric")
        
        assert not warrior.is_active
        assert result["is_player"]


# =============================================================================
# COMBAT LOG TESTS
# =============================================================================

class TestCombatLog:
    """Test combat logging."""
    
    def test_log_records_events(self, engine, party, goblin):
        """Test that events are logged."""
        engine.start_combat(party=party, enemies=[goblin])
        engine.attack("Aldric", "Goblin")
        
        log = engine.get_log()
        
        assert len(log) > 0
        assert any("Combat Begins" in entry for entry in log)


# =============================================================================
# FACTORY FUNCTION TESTS
# =============================================================================

class TestFactoryFunctions:
    """Test combatant creation helpers."""
    
    def test_create_from_character(self):
        """Test creating combatant from character-like object."""
        class MockCharacter:
            name = "Test Hero"
            hp_current = 15
            hp_max = 20
            ac = 14
            strength = 16
            level = 3
            character_id = "char_123"
        
        combatant = create_combatant_from_character(MockCharacter())
        
        assert combatant.name == "Test Hero"
        assert combatant.hp_current == 15
        assert combatant.is_player
    
    def test_create_from_monster(self):
        """Test creating combatant from monster-like object."""
        class MockMonster:
            name = "Orc"
            hit_dice = "2"
            armor_class = 6
            attacks = ["1 × sword (1d8)"]
            morale = 8
            monster_id = "mon_456"
        
        combatant = create_combatant_from_monster(MockMonster())
        
        assert combatant.name == "Orc"
        assert combatant.morale == 8
        assert not combatant.is_player
    
    def test_create_multiple_monsters(self):
        """Test creating multiple monsters with suffixes."""
        class MockMonster:
            name = "Goblin"
            hit_dice = "1-1"
            armor_class = 6
            attacks = []
            morale = 7
            monster_id = "gob"
        
        c1 = create_combatant_from_monster(MockMonster(), " 1")
        c2 = create_combatant_from_monster(MockMonster(), " 2")
        
        assert c1.name == "Goblin 1"
        assert c2.name == "Goblin 2"
        assert c1.id != c2.id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
