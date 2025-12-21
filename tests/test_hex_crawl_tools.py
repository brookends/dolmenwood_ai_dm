"""
Tests for Hex Crawl Tools Module.

Tests the tool handler integration with the hex crawl engine.
"""

import sys
import pytest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from exploration.hex_crawl_tools import (
    HexCrawlToolHandler,
    HexCrawlToolResult,
    HEX_CRAWL_TOOL_DEFINITIONS,
    create_hex_crawl_handler,
)
from exploration.hex_crawl_engine import (
    Terrain,
    Season,
    get_adjacent_hexes,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def handler():
    """Create a fresh tool handler."""
    h = HexCrawlToolHandler()
    h.engine.set_resources(rations=20, torches=10, water=20)
    return h


@pytest.fixture
def setup_handler():
    """Create a handler with full setup."""
    h = HexCrawlToolHandler()
    h.setup(
        starting_hex="0808",
        terrain=Terrain.SETTLEMENT,
        party_size=4,
        season=Season.AUTUMN,
        starting_rations=20,
        starting_torches=10
    )
    return h


# =============================================================================
# TOOL DEFINITIONS TESTS
# =============================================================================

class TestToolDefinitions:
    """Test tool definitions structure."""
    
    def test_all_required_tools_defined(self):
        """Test that all hex crawl tools are defined."""
        tool_names = [t["name"] for t in HEX_CRAWL_TOOL_DEFINITIONS]
        
        required = [
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
        ]
        
        for name in required:
            assert name in tool_names, f"Missing tool: {name}"
    
    def test_tool_definitions_format(self):
        """Test tool definitions have correct format."""
        for tool in HEX_CRAWL_TOOL_DEFINITIONS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"


# =============================================================================
# TRAVEL TESTS
# =============================================================================

class TestTravel:
    """Test travel_to_hex tool."""
    
    def test_travel_success(self, handler):
        """Test successful travel."""
        adjacent = get_adjacent_hexes(handler.engine.current_hex)
        
        result = handler.handle_tool("travel_to_hex", {
            "destination": adjacent[0],
            "terrain": "forest"
        })
        
        assert result.success
        assert "destination" in result.data
    
    def test_travel_with_guide(self, handler):
        """Test travel with guide."""
        adjacent = get_adjacent_hexes(handler.engine.current_hex)
        
        result = handler.handle_tool("travel_to_hex", {
            "destination": adjacent[0],
            "terrain": "dense_forest",
            "has_guide": True
        })
        
        assert result.success
    
    def test_travel_on_road(self, handler):
        """Test travel on road."""
        adjacent = get_adjacent_hexes(handler.engine.current_hex)
        
        result = handler.handle_tool("travel_to_hex", {
            "destination": adjacent[0],
            "on_road": True
        })
        
        assert result.success
    
    def test_travel_forced_march(self, handler):
        """Test forced march."""
        adjacent = get_adjacent_hexes(handler.engine.current_hex)
        
        result = handler.handle_tool("travel_to_hex", {
            "destination": adjacent[0],
            "forced_march": True
        })
        
        assert result.success
    
    def test_travel_returns_encounter_flag(self, handler):
        """Test travel returns encounter flag."""
        adjacent = get_adjacent_hexes(handler.engine.current_hex)
        
        result = handler.handle_tool("travel_to_hex", {
            "destination": adjacent[0]
        })
        
        assert hasattr(result, "encounter_occurred")


# =============================================================================
# EXPLORATION TESTS
# =============================================================================

class TestExploration:
    """Test exploration tools."""
    
    def test_explore_current_hex(self, handler):
        """Test exploring current hex."""
        result = handler.handle_tool("explore_current_hex", {})
        
        assert result.success
        assert "hex_id" in result.data
    
    def test_detailed_exploration(self, handler):
        """Test detailed exploration."""
        result = handler.handle_tool("explore_current_hex", {
            "detailed": True
        })
        
        assert result.success
        assert result.data["watches_spent"] == 2
    
    def test_forage(self, handler):
        """Test foraging."""
        result = handler.handle_tool("forage", {})
        
        assert result.success
        assert "success" in result.data
        assert "amount" in result.data


# =============================================================================
# CAMP AND REST TESTS
# =============================================================================

class TestCamp:
    """Test camping and resting."""
    
    def test_short_rest(self, handler):
        """Test short rest."""
        result = handler.handle_tool("make_camp", {
            "full_rest": False
        })
        
        assert result.success
        assert result.data["activity"] == "rest"
    
    def test_full_camp(self, handler):
        """Test full camp."""
        result = handler.handle_tool("make_camp", {
            "full_rest": True
        })
        
        assert result.success
        assert result.data["activity"] == "camp"


# =============================================================================
# ENCOUNTER TESTS
# =============================================================================

class TestEncounters:
    """Test encounter checking."""
    
    def test_check_encounter(self, handler):
        """Test encounter check."""
        result = handler.handle_tool("check_random_encounter", {})
        
        assert result.success
        assert "roll" in result.data
        assert "chance" in result.data
    
    def test_check_encounter_with_modifier(self, handler):
        """Test encounter check with modifier."""
        result = handler.handle_tool("check_random_encounter", {
            "modifier": 2
        })
        
        assert result.success


# =============================================================================
# STATUS TESTS
# =============================================================================

class TestStatus:
    """Test status queries."""
    
    def test_get_status(self, handler):
        """Test getting status."""
        result = handler.handle_tool("get_hex_crawl_status", {})
        
        assert result.success
        assert "current_hex" in result.data
        assert "day" in result.data
        assert "resources" in result.data
    
    def test_get_detailed_status(self, handler):
        """Test detailed status."""
        result = handler.handle_tool("get_hex_crawl_status", {
            "detailed": True
        })
        
        assert result.success
        assert "HEX CRAWL STATUS" in result.brief
    
    def test_get_status_with_adjacent(self, handler):
        """Test status includes adjacent hexes."""
        result = handler.handle_tool("get_hex_crawl_status", {
            "include_adjacent": True
        })
        
        assert "adjacent_hexes" in result.data
        assert len(result.data["adjacent_hexes"]) > 0


# =============================================================================
# TIME TESTS
# =============================================================================

class TestTime:
    """Test time management."""
    
    def test_advance_time(self, handler):
        """Test advancing time."""
        result = handler.handle_tool("advance_time", {
            "watches": 2
        })
        
        assert result.success
        assert "day" in result.data
        assert "watch" in result.data


# =============================================================================
# RESOURCE TESTS
# =============================================================================

class TestResources:
    """Test resource management."""
    
    def test_add_resources(self, handler):
        """Test adding resources."""
        result = handler.handle_tool("manage_resources", {
            "resource": "rations",
            "amount": 5
        })
        
        assert result.success
        assert "current" in result.data
    
    def test_consume_resources(self, handler):
        """Test consuming resources."""
        initial = handler.engine.resources.rations
        
        result = handler.handle_tool("manage_resources", {
            "resource": "rations",
            "amount": -3
        })
        
        assert result.success
        assert handler.engine.resources.rations == initial - 3
    
    def test_invalid_resource(self, handler):
        """Test invalid resource type."""
        result = handler.handle_tool("manage_resources", {
            "resource": "invalid",
            "amount": 5
        })
        
        assert not result.success


# =============================================================================
# HEX INFO TESTS
# =============================================================================

class TestHexInfo:
    """Test hex info management."""
    
    def test_set_hex_info(self, handler):
        """Test setting hex info."""
        result = handler.handle_tool("set_hex_info", {
            "hex_id": "0910",
            "terrain": "ruins",
            "name": "Old Tower",
            "description": "A crumbling watchtower"
        })
        
        assert result.success
        assert "0910" in result.brief
    
    def test_set_hex_with_settlement(self, handler):
        """Test setting hex with settlement."""
        result = handler.handle_tool("set_hex_info", {
            "hex_id": "0707",
            "terrain": "settlement",
            "name": "Prigwort",
            "settlement": "Prigwort"
        })
        
        assert result.success


# =============================================================================
# WEATHER TESTS
# =============================================================================

class TestWeather:
    """Test weather management."""
    
    def test_set_weather(self, handler):
        """Test setting weather."""
        result = handler.handle_tool("set_weather", {
            "weather": "heavy_rain"
        })
        
        assert result.success
        assert handler.engine.current_weather.value == "heavy_rain"
    
    def test_invalid_weather(self, handler):
        """Test invalid weather."""
        result = handler.handle_tool("set_weather", {
            "weather": "invalid"
        })
        
        assert not result.success


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Test full workflows."""
    
    def test_travel_and_explore(self, setup_handler):
        """Test travel then explore workflow."""
        adjacent = get_adjacent_hexes(setup_handler.engine.current_hex)
        
        # Travel
        travel_result = setup_handler.handle_tool("travel_to_hex", {
            "destination": adjacent[0],
            "terrain": "forest"
        })
        assert travel_result.success
        
        # Explore
        explore_result = setup_handler.handle_tool("explore_current_hex", {
            "detailed": True
        })
        assert explore_result.success
    
    def test_forage_and_camp(self, setup_handler):
        """Test foraging then camping."""
        # Forage
        forage_result = setup_handler.handle_tool("forage", {})
        assert forage_result.success
        
        # Camp
        camp_result = setup_handler.handle_tool("make_camp", {
            "full_rest": True
        })
        assert camp_result.success
    
    def test_full_day_travel(self, setup_handler):
        """Test traveling multiple hexes in a day."""
        hexes_traveled = 0
        
        for _ in range(5):  # Try to travel 5 hexes
            adjacent = get_adjacent_hexes(setup_handler.engine.current_hex)
            
            result = setup_handler.handle_tool("travel_to_hex", {
                "destination": adjacent[0],
                "terrain": "clear"
            })
            
            if result.success:
                hexes_traveled += 1
            
            # Check if new day
            if result.data.get("day", 1) > 1:
                break
        
        assert hexes_traveled > 0


# =============================================================================
# UTILITY TESTS
# =============================================================================

class TestUtilities:
    """Test utility functions."""
    
    def test_create_handler(self):
        """Test handler creation."""
        handler = create_hex_crawl_handler()
        
        assert isinstance(handler, HexCrawlToolHandler)
    
    def test_setup_method(self):
        """Test quick setup method."""
        handler = HexCrawlToolHandler()
        handler.setup(
            starting_hex="1010",
            terrain=Terrain.FOREST,
            party_size=6,
            season=Season.WINTER,
            starting_rations=30
        )
        
        assert handler.engine.current_hex == "1010"
        assert handler.engine.party_size == 6
        assert handler.engine.season == Season.WINTER
        assert handler.engine.resources.rations == 30
    
    def test_unknown_tool(self, handler):
        """Test handling unknown tool."""
        result = handler.handle_tool("unknown_tool", {})
        
        assert not result.success
        assert "Unknown" in result.brief


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
