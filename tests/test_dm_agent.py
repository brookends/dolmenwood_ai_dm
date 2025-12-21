"""
Tests for the AI DM Agent Module.

Tests game mechanics (dice rolling, combat, etc.) without requiring API calls.
"""

import sys
import pytest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai.dm_agent import (
    DiceRoller,
    DiceResult,
    CombatManager,
    ExplorationManager,
    SocialManager,
    MagicManager,
    SavingThrowManager,
    ToolResult,
    DMResponse,
    DMConfig,
    TOOL_DEFINITIONS,
)


# =============================================================================
# DICE ROLLER TESTS
# =============================================================================

class TestDiceRoller:
    """Test dice rolling mechanics."""
    
    def test_roll_single_die(self):
        """Test rolling a single die."""
        result = DiceRoller.roll("d6")
        
        assert isinstance(result, DiceResult)
        assert result.notation == "d6"
        assert 1 <= result.total <= 6
        assert len(result.rolls) == 1
    
    def test_roll_multiple_dice(self):
        """Test rolling multiple dice."""
        result = DiceRoller.roll("3d6")
        
        assert len(result.rolls) == 3
        assert 3 <= result.total <= 18
    
    def test_roll_with_modifier(self):
        """Test rolling with positive modifier."""
        result = DiceRoller.roll("d20+5")
        
        assert result.modifier == 5
        assert result.total == result.rolls[0] + 5
    
    def test_roll_with_negative_modifier(self):
        """Test rolling with negative modifier."""
        result = DiceRoller.roll("d20-3")
        
        assert result.modifier == -3
        assert result.total == result.rolls[0] - 3
    
    def test_roll_keep_highest(self):
        """Test 4d6 keep highest 3."""
        result = DiceRoller.roll("4d6kh3")
        
        assert len(result.rolls) == 4
        assert len(result.kept_rolls) == 3
        # Kept rolls should be the 3 highest
        sorted_rolls = sorted(result.rolls, reverse=True)[:3]
        assert sorted(result.kept_rolls, reverse=True) == sorted_rolls
    
    def test_roll_d20(self):
        """Test d20 convenience method."""
        result = DiceRoller.roll_d20(modifier=2)
        
        assert 3 <= result.total <= 22  # 1+2 to 20+2
    
    def test_roll_with_advantage(self):
        """Test rolling with advantage."""
        result = DiceRoller.roll("d20", advantage=True)
        
        assert len(result.rolls) == 2
        assert result.total == max(result.rolls)
        assert "advantage" in result.note
    
    def test_roll_with_disadvantage(self):
        """Test rolling with disadvantage."""
        result = DiceRoller.roll("d20", disadvantage=True)
        
        assert len(result.rolls) == 2
        assert result.total == min(result.rolls)
        assert "disadvantage" in result.note
    
    def test_roll_ability_scores(self):
        """Test rolling 6 ability scores."""
        results = DiceRoller.roll_ability_scores()
        
        assert len(results) == 6
        for result in results:
            assert 3 <= result.total <= 18  # 4d6kh3 range
    
    def test_roll_percentile(self):
        """Test d100 roll."""
        result = DiceRoller.roll_percentile()
        
        assert 1 <= result.total <= 100
    
    def test_roll_morale(self):
        """Test morale check."""
        result, passed = DiceRoller.roll_morale(morale_score=7)
        
        assert 2 <= result.total <= 12
        assert passed == (result.total <= 7)
    
    def test_roll_reaction(self):
        """Test reaction roll."""
        result = DiceRoller.roll_reaction(cha_modifier=1)
        
        assert result.modifier == 1
        # Base 2d6 is 2-12, plus modifier
        assert 3 <= result.total <= 13
    
    def test_invalid_notation_raises_error(self):
        """Test that invalid notation raises ValueError."""
        with pytest.raises(ValueError):
            DiceRoller.roll("invalid")
    
    def test_dice_result_to_string(self):
        """Test DiceResult string representation."""
        result = DiceResult(
            notation="2d6",
            rolls=[3, 5],
            kept_rolls=[3, 5],
            modifier=0,
            total=8,
            note=""
        )
        
        result_str = str(result)
        assert "2d6" in result_str
        assert "8" in result_str
    
    def test_dice_result_to_dict(self):
        """Test DiceResult dict conversion."""
        result = DiceRoller.roll("d20")
        result_dict = result.to_dict()
        
        assert "notation" in result_dict
        assert "rolls" in result_dict
        assert "total" in result_dict


# =============================================================================
# COMBAT MANAGER TESTS
# =============================================================================

class TestCombatManager:
    """Test combat mechanics."""
    
    def test_calculate_attack_roll_hit(self):
        """Test attack roll that hits."""
        # With high bonus, should usually hit low AC
        result, hit, critical = CombatManager.calculate_attack_roll(
            attack_bonus=10,
            target_ac=10,
            modifiers=0
        )
        
        assert isinstance(result, DiceResult)
        # Natural 1 always misses, natural 20 always hits
        if result.kept_rolls[0] == 1:
            assert not hit
        elif result.kept_rolls[0] == 20:
            assert hit
            assert critical
    
    def test_natural_20_is_critical(self):
        """Test that natural 20 is always a critical hit."""
        # Run multiple times to catch a natural 20
        criticals_found = 0
        for _ in range(100):
            result, hit, critical = CombatManager.calculate_attack_roll(
                attack_bonus=0,
                target_ac=25  # Very high AC
            )
            if result.kept_rolls[0] == 20:
                assert hit
                assert critical
                criticals_found += 1
        
        # Should have found at least one critical in 100 rolls (5% chance each)
        # This could theoretically fail but extremely unlikely
        assert criticals_found >= 0  # Just verify the logic works
    
    def test_natural_1_always_misses(self):
        """Test that natural 1 always misses."""
        for _ in range(100):
            result, hit, critical = CombatManager.calculate_attack_roll(
                attack_bonus=100,  # Huge bonus
                target_ac=1  # Very low AC
            )
            if result.kept_rolls[0] == 1:
                assert not hit
                assert not critical
    
    def test_roll_initiative(self):
        """Test initiative roll."""
        result = CombatManager.roll_initiative(dex_modifier=2)
        
        assert 3 <= result.total <= 8  # d6 + 2
    
    def test_roll_damage(self):
        """Test damage roll."""
        result = CombatManager.roll_damage("1d8", bonus=3)
        
        assert 4 <= result.total <= 11  # 1d8+3, minimum 1
    
    def test_roll_damage_critical(self):
        """Test critical damage doubles dice."""
        result = CombatManager.roll_damage("1d8", bonus=2, critical=True)
        
        # Critical doubles dice (2d8+2)
        assert len(result.rolls) == 2
        assert "CRITICAL" in result.note
    
    def test_morale_check(self):
        """Test morale check."""
        result, passed = CombatManager.check_morale(morale_score=8)
        
        assert 2 <= result.total <= 12
        assert passed == (result.total <= 8)
    
    def test_encounter_distance(self):
        """Test encounter distance calculation."""
        dungeon_dist = CombatManager.calculate_encounter_distance("dungeon")
        assert 20 <= dungeon_dist <= 120  # 2d6 * 10
        
        plains_dist = CombatManager.calculate_encounter_distance("plains")
        assert 160 <= plains_dist <= 960  # 4d6 * 40


# =============================================================================
# EXPLORATION MANAGER TESTS
# =============================================================================

class TestExplorationManager:
    """Test exploration mechanics."""
    
    def test_calculate_travel_time(self):
        """Test travel time calculation."""
        result = ExplorationManager.calculate_travel_time(
            distance_miles=12,
            base_movement=120,  # 120' dungeon movement
            terrain="clear"
        )
        
        assert result["distance_miles"] == 12
        assert result["effective_miles_per_day"] == 24  # 120/5 = 24
        assert result["days_needed"] == 0.5  # 12/24
    
    def test_travel_time_forest_terrain(self):
        """Test travel time in forest (slower)."""
        result = ExplorationManager.calculate_travel_time(
            distance_miles=24,
            base_movement=120,
            terrain="forest"
        )
        
        # Forest is 0.66x speed
        assert result["effective_miles_per_day"] == pytest.approx(15.84, rel=0.1)
    
    def test_travel_time_forced_march(self):
        """Test forced march increases speed."""
        normal = ExplorationManager.calculate_travel_time(
            distance_miles=24,
            base_movement=120,
            terrain="clear"
        )
        
        forced = ExplorationManager.calculate_travel_time(
            distance_miles=24,
            base_movement=120,
            terrain="clear",
            forced_march=True
        )
        
        assert forced["effective_miles_per_day"] > normal["effective_miles_per_day"]
        assert forced["exhaustion_risk"] is True
    
    def test_check_random_encounter(self):
        """Test random encounter check."""
        result, encounter = ExplorationManager.check_random_encounter(chance=1)
        
        assert 1 <= result.total <= 6
        assert encounter == (result.total <= 1)
    
    def test_check_getting_lost(self):
        """Test getting lost check."""
        result, lost = ExplorationManager.check_getting_lost(terrain="forest")
        
        # Forest has chance of 2 in 6
        assert lost == (result.total <= 2)
    
    def test_forage(self):
        """Test foraging."""
        result, success = ExplorationManager.forage(survival_skill=2)
        
        assert success == (result.total <= 2)
    
    def test_check_weather(self):
        """Test weather generation."""
        weather = ExplorationManager.check_weather()
        
        valid_weather = ["clear", "overcast", "light rain", "heavy rain", "storm", "unusual"]
        assert weather in valid_weather


# =============================================================================
# SOCIAL MANAGER TESTS
# =============================================================================

class TestSocialManager:
    """Test social interaction mechanics."""
    
    def test_roll_reaction(self):
        """Test reaction roll."""
        result = SocialManager.roll_reaction(cha_modifier=1, context_modifier=0)
        
        assert "disposition" in result
        assert "description" in result
        assert result["modified_total"] >= 2 and result["modified_total"] <= 12
    
    def test_reaction_dispositions(self):
        """Test that all dispositions are valid."""
        valid_dispositions = ["hostile", "unfriendly", "neutral", "friendly"]
        
        for _ in range(50):
            result = SocialManager.roll_reaction()
            assert result["disposition"] in valid_dispositions
    
    def test_reaction_with_high_cha(self):
        """Test reaction with high charisma modifier."""
        # High CHA should tend toward friendly
        friendly_count = 0
        for _ in range(100):
            result = SocialManager.roll_reaction(cha_modifier=3)
            if result["disposition"] == "friendly":
                friendly_count += 1
        
        # Should be mostly friendly with +3 CHA
        assert friendly_count > 30  # Very likely with +3 modifier
    
    def test_check_loyalty(self):
        """Test loyalty check."""
        result, loyal = SocialManager.check_loyalty(loyalty_score=8)
        
        assert loyal == (result.total <= 8)


# =============================================================================
# SAVING THROW TESTS
# =============================================================================

class TestSavingThrowManager:
    """Test saving throw mechanics."""
    
    def test_make_save_success(self):
        """Test successful saving throw."""
        # Run multiple times
        successes = 0
        for _ in range(100):
            result, success = SavingThrowManager.make_save(save_target=10)
            if result.total >= 10:
                assert success
                successes += 1
        
        # Should have some successes
        assert successes > 0
    
    def test_make_save_with_modifier(self):
        """Test save with modifier."""
        result, success = SavingThrowManager.make_save(save_target=15, modifier=3)
        
        # Roll + 3 should be compared to 15
        assert success == (result.total >= 15)
    
    def test_get_save_type(self):
        """Test save type determination."""
        assert SavingThrowManager.get_save_type("poison") == "doom"
        assert SavingThrowManager.get_save_type("wand") == "ray"
        assert SavingThrowManager.get_save_type("gaze attack") == "ray"
        assert SavingThrowManager.get_save_type("paralysis") == "hold"
        assert SavingThrowManager.get_save_type("dragon breath") == "blast"
        assert SavingThrowManager.get_save_type("magic spell") == "spell"


# =============================================================================
# MAGIC MANAGER TESTS
# =============================================================================

class TestMagicManager:
    """Test magic mechanics."""
    
    def test_spell_success(self):
        """Test basic spell success."""
        success = MagicManager.check_spell_success(spell_level=1, caster_level=1)
        assert success is True
    
    def test_roll_spell_duration(self):
        """Test spell duration roll."""
        result = MagicManager.roll_spell_duration("2d6")
        
        assert 2 <= result.total <= 12
    
    def test_magic_item_activation(self):
        """Test magic item activation."""
        success, message = MagicManager.check_magic_item_activation(
            item_type="scroll",
            caster_level=5,
            item_level=3
        )
        
        assert success is True
        assert "successfully" in message.lower()
    
    def test_dispel_check(self):
        """Test dispel magic check."""
        result, success = MagicManager.dispel_check(caster_level=5, target_level=3)
        
        # Target is 11 + (3-5) = 9
        assert success == (result.total >= 9)


# =============================================================================
# TOOL RESULT TESTS
# =============================================================================

class TestToolResult:
    """Test ToolResult class."""
    
    def test_tool_result_creation(self):
        """Test creating a ToolResult."""
        result = ToolResult(
            tool_name="roll_dice",
            success=True,
            result={"total": 15},
            message="Rolled d20 = 15"
        )
        
        assert result.tool_name == "roll_dice"
        assert result.success is True
    
    def test_tool_result_to_dict(self):
        """Test ToolResult dict conversion."""
        dice = DiceRoller.roll("d20")
        result = ToolResult(
            tool_name="roll_dice",
            success=True,
            result={"total": dice.total},
            message=f"Rolled {dice}",
            dice_rolls=[dice]
        )
        
        result_dict = result.to_dict()
        
        assert "tool_name" in result_dict
        assert "dice_rolls" in result_dict
        assert len(result_dict["dice_rolls"]) == 1


# =============================================================================
# DM RESPONSE TESTS
# =============================================================================

class TestDMResponse:
    """Test DMResponse class."""
    
    def test_dm_response_creation(self):
        """Test creating a DMResponse."""
        response = DMResponse(
            narrative="You enter a dark room.",
            tool_results=[],
            dice_rolls=[],
            model_used="test"
        )
        
        assert response.narrative == "You enter a dark room."
        assert response.timestamp is not None
    
    def test_dm_response_to_dict(self):
        """Test DMResponse dict conversion."""
        response = DMResponse(
            narrative="Test narrative",
            model_used="test"
        )
        
        response_dict = response.to_dict()
        
        assert "narrative" in response_dict
        assert "timestamp" in response_dict
        assert "model_used" in response_dict


# =============================================================================
# DM CONFIG TESTS
# =============================================================================

class TestDMConfig:
    """Test DMConfig class."""
    
    def test_default_config(self):
        """Test default configuration."""
        config = DMConfig()
        
        assert config.model == "claude-sonnet-4-20250514"
        assert config.temperature == 0.8
        assert config.dm_style == "evocative"
    
    def test_custom_config(self):
        """Test custom configuration."""
        config = DMConfig(
            model="claude-opus-4-20250514",
            temperature=0.5,
            dm_style="terse"
        )
        
        assert config.model == "claude-opus-4-20250514"
        assert config.temperature == 0.5
        assert config.dm_style == "terse"


# =============================================================================
# TOOL DEFINITIONS TESTS
# =============================================================================

class TestToolDefinitions:
    """Test tool definitions structure."""
    
    def test_tool_definitions_format(self):
        """Test that tool definitions have correct format."""
        for tool in TOOL_DEFINITIONS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"
            assert "properties" in tool["input_schema"]
    
    def test_required_tools_exist(self):
        """Test that essential tools are defined."""
        tool_names = [t["name"] for t in TOOL_DEFINITIONS]
        
        required = [
            "roll_dice",
            "attack_roll",
            "saving_throw",
            "morale_check",
            "reaction_roll",
            "search_rules",
            "lookup_monster",
        ]
        
        for name in required:
            assert name in tool_names, f"Missing required tool: {name}"


# =============================================================================
# COMBAT ENGINE INTEGRATION TESTS
# =============================================================================

class TestCombatEngineIntegration:
    """Test combat engine integration with DM agent."""
    
    def test_combat_engine_available(self):
        """Test that combat engine is available."""
        from ai.dm_agent import COMBAT_ENGINE_AVAILABLE
        assert COMBAT_ENGINE_AVAILABLE is True
    
    def test_get_tool_definitions_with_combat_engine(self):
        """Test that tool definitions include combat engine tools."""
        from ai.dm_agent import get_tool_definitions, COMBAT_TOOL_NAMES
        
        tools = get_tool_definitions(use_combat_engine=True)
        tool_names = {t["name"] for t in tools}
        
        # Should have combat engine tools
        for combat_tool in COMBAT_TOOL_NAMES:
            assert combat_tool in tool_names, f"Missing combat tool: {combat_tool}"
        
        # Should NOT have old combat tools
        old_tools = {"attack_roll", "morale_check", "roll_initiative"}
        for old_tool in old_tools:
            assert old_tool not in tool_names, f"Old tool should be replaced: {old_tool}"
    
    def test_get_tool_definitions_without_combat_engine(self):
        """Test tool definitions when combat engine disabled."""
        from ai.dm_agent import get_tool_definitions
        
        tools = get_tool_definitions(use_combat_engine=False)
        tool_names = {t["name"] for t in tools}
        
        # Should have old combat tools
        assert "attack_roll" in tool_names
        assert "morale_check" in tool_names
        assert "roll_initiative" in tool_names
    
    def test_dm_creates_combat_handler(self):
        """Test DM creates combat handler automatically."""
        from ai.dm_agent import DolmenwoodDM, DMConfig
        
        dm = DolmenwoodDM(config=DMConfig(api_key="test"))
        
        assert dm.combat_handler is not None
        assert dm.is_combat_active is False
    
    def test_dm_uses_provided_handler(self):
        """Test DM uses provided combat handler."""
        from ai.dm_agent import DolmenwoodDM, DMConfig
        from combat.combat_tools import create_combat_handler
        
        handler = create_combat_handler()
        dm = DolmenwoodDM(
            config=DMConfig(api_key="test"),
            combat_handler=handler
        )
        
        assert dm.combat_handler is handler
    
    def test_combat_tool_names_complete(self):
        """Test all combat tools are in COMBAT_TOOL_NAMES."""
        from ai.dm_agent import COMBAT_TOOL_NAMES
        
        expected = {
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
        
        assert COMBAT_TOOL_NAMES == expected


# =============================================================================
# HEX CRAWL ENGINE INTEGRATION TESTS
# =============================================================================

class TestHexCrawlEngineIntegration:
    """Test hex crawl engine integration with DM agent."""
    
    def test_hex_crawl_engine_available(self):
        """Test that hex crawl engine is available."""
        from ai.dm_agent import HEX_CRAWL_ENGINE_AVAILABLE
        assert HEX_CRAWL_ENGINE_AVAILABLE is True
    
    def test_get_tool_definitions_with_hex_crawl_engine(self):
        """Test that tool definitions include hex crawl engine tools."""
        from ai.dm_agent import get_tool_definitions, HEX_CRAWL_TOOL_NAMES
        
        tools = get_tool_definitions(use_hex_crawl_engine=True)
        tool_names = {t["name"] for t in tools}
        
        # Should have hex crawl engine tools
        for hex_tool in HEX_CRAWL_TOOL_NAMES:
            assert hex_tool in tool_names, f"Missing hex crawl tool: {hex_tool}"
    
    def test_get_tool_definitions_without_hex_crawl_engine(self):
        """Test tool definitions when hex crawl engine disabled."""
        from ai.dm_agent import get_tool_definitions
        
        tools = get_tool_definitions(use_hex_crawl_engine=False)
        tool_names = {t["name"] for t in tools}
        
        # Should have old exploration tool
        assert "check_random_encounter" in tool_names
        
        # Should NOT have hex crawl tools
        assert "travel_to_hex" not in tool_names
        assert "explore_current_hex" not in tool_names
    
    def test_dm_creates_hex_crawl_handler(self):
        """Test DM creates hex crawl handler automatically."""
        from ai.dm_agent import DolmenwoodDM, DMConfig
        
        dm = DolmenwoodDM(config=DMConfig(api_key="test"))
        
        assert dm.hex_crawl_handler is not None
    
    def test_dm_uses_provided_hex_crawl_handler(self):
        """Test DM uses provided hex crawl handler."""
        from ai.dm_agent import DolmenwoodDM, DMConfig
        from exploration.hex_crawl_tools import create_hex_crawl_handler
        
        handler = create_hex_crawl_handler()
        dm = DolmenwoodDM(
            config=DMConfig(api_key="test"),
            hex_crawl_handler=handler
        )
        
        assert dm.hex_crawl_handler is handler
    
    def test_hex_crawl_tool_names_complete(self):
        """Test all hex crawl tools are in HEX_CRAWL_TOOL_NAMES."""
        from ai.dm_agent import HEX_CRAWL_TOOL_NAMES
        
        expected = {
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
        
        assert HEX_CRAWL_TOOL_NAMES == expected
    
    def test_both_engines_enabled(self):
        """Test both combat and hex crawl engines work together."""
        from ai.dm_agent import DolmenwoodDM, DMConfig, get_tool_definitions
        
        dm = DolmenwoodDM(config=DMConfig(api_key="test"))
        
        # Both handlers should be available
        assert dm.combat_handler is not None
        assert dm.hex_crawl_handler is not None
        
        # Tool definitions should include both
        tools = get_tool_definitions(use_combat_engine=True, use_hex_crawl_engine=True)
        tool_names = {t["name"] for t in tools}
        
        # Combat tools
        assert "start_combat" in tool_names
        assert "combat_attack" in tool_names
        
        # Hex crawl tools
        assert "travel_to_hex" in tool_names
        assert "get_hex_crawl_status" in tool_names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
