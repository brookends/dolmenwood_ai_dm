"""
Tests for the Hex Crawl Engine Module.

Tests hex navigation, time tracking, resources, and exploration.
"""

import sys
import pytest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from exploration.hex_crawl_engine import (
    HexCrawlEngine,
    HexInfo,
    TravelResult,
    ExplorationResult,
    Terrain,
    Weather,
    TimeOfDay,
    Season,
    ResourceType,
    ResourceStatus,
    parse_hex_id,
    make_hex_id,
    get_adjacent_hexes,
    hex_distance,
    roll_weather,
)


# =============================================================================
# HEX UTILITIES TESTS
# =============================================================================

class TestHexUtilities:
    """Test hex coordinate utilities."""
    
    def test_parse_hex_id(self):
        """Test parsing hex ID."""
        col, row = parse_hex_id("0808")
        assert col == 8
        assert row == 8
    
    def test_parse_hex_id_leading_zeros(self):
        """Test parsing hex with leading zeros."""
        col, row = parse_hex_id("0102")
        assert col == 1
        assert row == 2
    
    def test_parse_hex_id_invalid(self):
        """Test parsing invalid hex ID."""
        with pytest.raises(ValueError):
            parse_hex_id("08")
        
        with pytest.raises(ValueError):
            parse_hex_id("08080")
    
    def test_make_hex_id(self):
        """Test creating hex ID."""
        assert make_hex_id(8, 8) == "0808"
        assert make_hex_id(1, 2) == "0102"
        assert make_hex_id(12, 15) == "1215"
    
    def test_get_adjacent_hexes(self):
        """Test getting adjacent hexes."""
        adjacent = get_adjacent_hexes("0808")
        
        assert len(adjacent) == 6
        # All should be valid hex IDs
        for hex_id in adjacent:
            assert len(hex_id) == 4
    
    def test_get_adjacent_hexes_edge(self):
        """Test adjacent hexes at edge of map."""
        adjacent = get_adjacent_hexes("0000")
        
        # Should have fewer than 6 adjacent (some out of bounds)
        assert len(adjacent) < 6
        # All should be valid
        for hex_id in adjacent:
            col, row = parse_hex_id(hex_id)
            assert col >= 0
            assert row >= 0
    
    def test_hex_distance_adjacent(self):
        """Test distance between adjacent hexes."""
        adjacent = get_adjacent_hexes("0808")
        
        for adj in adjacent:
            distance = hex_distance("0808", adj)
            assert distance == 1
    
    def test_hex_distance_same(self):
        """Test distance to same hex."""
        assert hex_distance("0808", "0808") == 0
    
    def test_hex_distance_far(self):
        """Test distance to far hex."""
        distance = hex_distance("0808", "1515")
        assert distance > 5


# =============================================================================
# RESOURCE STATUS TESTS
# =============================================================================

class TestResourceStatus:
    """Test resource tracking."""
    
    def test_resource_creation(self):
        """Test creating resource status."""
        resources = ResourceStatus(rations=10, torches=5)
        
        assert resources.rations == 10
        assert resources.torches == 5
        assert resources.water == 0
    
    def test_consume_resource(self):
        """Test consuming resources."""
        resources = ResourceStatus(rations=10)
        
        consumed = resources.consume(ResourceType.RATIONS, 3)
        
        assert consumed == 3
        assert resources.rations == 7
    
    def test_consume_more_than_available(self):
        """Test consuming more than available."""
        resources = ResourceStatus(rations=2)
        
        consumed = resources.consume(ResourceType.RATIONS, 5)
        
        assert consumed == 2
        assert resources.rations == 0
    
    def test_add_resource(self):
        """Test adding resources."""
        resources = ResourceStatus(rations=5)
        
        resources.add(ResourceType.RATIONS, 10)
        
        assert resources.rations == 15
    
    def test_to_dict(self):
        """Test converting to dictionary."""
        resources = ResourceStatus(rations=5, torches=3)
        
        d = resources.to_dict()
        
        assert d["rations"] == 5
        assert d["torches"] == 3


# =============================================================================
# HEX CRAWL ENGINE TESTS
# =============================================================================

class TestHexCrawlEngine:
    """Test hex crawl engine."""
    
    @pytest.fixture
    def engine(self):
        """Create a fresh engine."""
        return HexCrawlEngine()
    
    def test_engine_creation(self, engine):
        """Test engine initializes correctly."""
        assert engine.current_hex == "0808"
        assert engine.day_number == 1
        assert engine.watch_number == 2
        assert engine.party_size == 4
    
    def test_set_starting_position(self, engine):
        """Test setting starting position."""
        engine.set_starting_position("0505", Terrain.FOREST, "Dark Woods")
        
        assert engine.current_hex == "0505"
        assert engine.current_terrain == Terrain.FOREST
        assert "0505" in engine.discovered_hexes
    
    def test_set_party_size(self, engine):
        """Test setting party size."""
        engine.set_party_size(6)
        
        assert engine.party_size == 6
    
    def test_set_resources(self, engine):
        """Test setting resources."""
        engine.set_resources(rations=20, torches=10)
        
        assert engine.resources.rations == 20
        assert engine.resources.torches == 10


# =============================================================================
# TRAVEL TESTS
# =============================================================================

class TestTravel:
    """Test travel mechanics."""
    
    @pytest.fixture
    def engine(self):
        """Create engine with resources."""
        e = HexCrawlEngine()
        e.set_resources(rations=20, torches=10)
        return e
    
    def test_travel_to_adjacent(self, engine):
        """Test traveling to adjacent hex."""
        adjacent = get_adjacent_hexes(engine.current_hex)
        destination = adjacent[0]
        
        result = engine.travel_to_hex(destination, terrain=Terrain.FOREST)
        
        assert result.success
        assert engine.current_hex == destination or result.got_lost
    
    def test_travel_advances_time(self, engine):
        """Test that travel advances time."""
        start_watch = engine.watch_number
        adjacent = get_adjacent_hexes(engine.current_hex)
        
        result = engine.travel_to_hex(adjacent[0], terrain=Terrain.CLEAR)
        
        assert result.watches_spent >= 1
    
    def test_travel_discovers_hex(self, engine):
        """Test that travel discovers new hexes."""
        adjacent = get_adjacent_hexes(engine.current_hex)
        destination = adjacent[0]
        
        result = engine.travel_to_hex(destination, terrain=Terrain.FOREST)
        
        # If not lost, should have discovered destination
        if not result.got_lost:
            assert destination in engine.discovered_hexes
    
    def test_travel_on_road_faster(self, engine):
        """Test that roads reduce travel time."""
        adjacent = get_adjacent_hexes(engine.current_hex)
        
        # Travel without road
        result1 = engine.travel_to_hex(adjacent[0], terrain=Terrain.FOREST, on_road=False)
        
        # Reset
        engine.current_hex = "0808"
        engine.watch_number = 2
        
        # Travel on road
        result2 = engine.travel_to_hex(adjacent[0], terrain=Terrain.FOREST, on_road=True)
        
        assert result2.watches_spent <= result1.watches_spent
    
    def test_travel_result_brief(self, engine):
        """Test travel result brief message."""
        adjacent = get_adjacent_hexes(engine.current_hex)
        
        result = engine.travel_to_hex(adjacent[0], terrain=Terrain.FOREST)
        
        assert result.brief is not None
        assert len(result.brief) > 10


# =============================================================================
# EXPLORATION TESTS
# =============================================================================

class TestExploration:
    """Test exploration mechanics."""
    
    @pytest.fixture
    def engine(self):
        """Create engine."""
        e = HexCrawlEngine()
        e.set_resources(rations=20)
        return e
    
    def test_explore_hex(self, engine):
        """Test exploring current hex."""
        result = engine.explore_hex(detailed=False)
        
        assert result.hex_id == engine.current_hex
        assert result.watches_spent == 1
    
    def test_detailed_exploration(self, engine):
        """Test detailed exploration takes longer."""
        result = engine.explore_hex(detailed=True)
        
        assert result.watches_spent == 2
    
    def test_forage(self, engine):
        """Test foraging."""
        initial_rations = engine.resources.rations
        
        result = engine.forage()
        
        assert result.activity == "forage"
        # May or may not find food
        if result.foraging_success:
            assert engine.resources.rations > initial_rations


# =============================================================================
# REST AND CAMP TESTS
# =============================================================================

class TestRestAndCamp:
    """Test resting and camping."""
    
    @pytest.fixture
    def engine(self):
        """Create engine."""
        return HexCrawlEngine()
    
    def test_short_rest(self, engine):
        """Test short rest."""
        result = engine.rest(full_rest=False)
        
        assert result.activity == "rest"
        assert result.watches_spent == 1
    
    def test_camp(self, engine):
        """Test making camp."""
        result = engine.rest(full_rest=True)
        
        assert result.activity == "camp"
        assert result.watches_spent >= 2


# =============================================================================
# TIME TESTS
# =============================================================================

class TestTime:
    """Test time management."""
    
    @pytest.fixture
    def engine(self):
        """Create engine."""
        return HexCrawlEngine()
    
    def test_advance_watch(self, engine):
        """Test advancing time."""
        start = engine.watch_number
        
        result = engine.advance_watch(2)
        
        assert engine.watch_number == start + 2 or engine.day_number > 1
    
    def test_day_rollover(self, engine):
        """Test day changes when watches exceed 6."""
        engine.watch_number = 5
        
        result = engine.advance_watch(3)
        
        assert engine.day_number == 2
        assert engine.watch_number <= 6


# =============================================================================
# ENCOUNTER TESTS
# =============================================================================

class TestEncounters:
    """Test random encounter checks."""
    
    @pytest.fixture
    def engine(self):
        """Create engine."""
        return HexCrawlEngine()
    
    def test_check_encounter(self, engine):
        """Test encounter check."""
        result = engine.check_encounter()
        
        assert "roll" in result
        assert "chance" in result
        assert "encounter" in result
        assert "brief" in result
    
    def test_encounter_modifier(self, engine):
        """Test encounter check with modifier."""
        # High modifier should increase chance
        result = engine.check_encounter(modifier=3)
        
        assert result["chance"] > 1


# =============================================================================
# WEATHER TESTS
# =============================================================================

class TestWeather:
    """Test weather system."""
    
    def test_roll_weather(self):
        """Test rolling weather."""
        weather = roll_weather(Season.AUTUMN)
        
        assert isinstance(weather, Weather)
    
    def test_weather_varies_by_season(self):
        """Test that different seasons give different weather distributions."""
        # This is probabilistic but we can check it doesn't crash
        for season in Season:
            weather = roll_weather(season)
            assert isinstance(weather, Weather)


# =============================================================================
# STATUS TESTS
# =============================================================================

class TestStatus:
    """Test status queries."""
    
    @pytest.fixture
    def engine(self):
        """Create engine."""
        e = HexCrawlEngine()
        e.set_resources(rations=15, torches=5)
        return e
    
    def test_get_status(self, engine):
        """Test getting status."""
        status = engine.get_status()
        
        assert status.current_hex == engine.current_hex
        assert status.day_number == engine.day_number
        assert status.resources["rations"] == 15
    
    def test_status_brief(self, engine):
        """Test status brief message."""
        status = engine.get_status()
        
        assert len(status.brief) > 10
        assert engine.current_hex in status.brief
    
    def test_status_full(self, engine):
        """Test full status."""
        status = engine.get_status()
        
        assert "HEX CRAWL STATUS" in status.full_status
    
    def test_resource_warnings(self, engine):
        """Test resource warnings."""
        engine.resources.rations = 4  # Low for party of 4
        
        warnings = engine.get_resource_warnings()
        
        assert len(warnings) > 0
        assert any("rations" in w.lower() for w in warnings)
    
    def test_get_adjacent_info(self, engine):
        """Test getting adjacent hex info."""
        info = engine.get_adjacent_info()
        
        assert len(info) == 6
        for hex_info in info:
            assert "hex_id" in hex_info
            assert "known" in hex_info


# =============================================================================
# HEX INFO TESTS
# =============================================================================

class TestHexInfo:
    """Test hex information tracking."""
    
    @pytest.fixture
    def engine(self):
        """Create engine."""
        return HexCrawlEngine()
    
    def test_add_hex_info(self, engine):
        """Test adding hex info."""
        engine.add_hex_info(
            hex_id="0910",
            terrain=Terrain.RUINS,
            name="Old Tower",
            description="A crumbling watchtower"
        )
        
        info = engine.get_hex_info("0910")
        
        assert info is not None
        assert info.name == "Old Tower"
        assert info.terrain == Terrain.RUINS
    
    def test_hex_info_to_dict(self, engine):
        """Test converting hex info to dict."""
        engine.add_hex_info(
            hex_id="0910",
            terrain=Terrain.FOREST,
            name="Test"
        )
        
        info = engine.get_hex_info("0910")
        d = info.to_dict()
        
        assert d["hex_id"] == "0910"
        assert d["terrain"] == "forest"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
