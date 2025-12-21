"""
Dolmenwood AI DM - Hex Crawl Tools for Claude Integration

This module provides tool definitions and handlers that allow Claude
to interact with the Hex Crawl Engine through structured tool calls.

Author: AI Dungeon Master Project
Version: 1.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from .hex_crawl_engine import (
    HexCrawlEngine,
    HexInfo,
    TravelResult,
    ExplorationResult,
    WatchActivity,
    Terrain,
    Weather,
    TimeOfDay,
    Season,
    ResourceType,
    get_adjacent_hexes,
)

logger = logging.getLogger(__name__)


# =============================================================================
# TOOL DEFINITIONS FOR CLAUDE
# =============================================================================

HEX_CRAWL_TOOL_DEFINITIONS = [
    {
        "name": "travel_to_hex",
        "description": """Move the party to an adjacent hex. Call this when the party wants to travel.
        
The system will:
- Calculate travel time based on terrain
- Check for getting lost
- Check for random encounters
- Consume resources (rations, light)
- Track discovered hexes

Returns travel outcome including any encounters.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "destination": {
                    "type": "string",
                    "description": "Target hex ID (e.g., '0809')"
                },
                "terrain": {
                    "type": "string",
                    "enum": ["clear", "forest", "dense_forest", "hills", "mountains", 
                             "swamp", "river", "lake", "settlement", "ruins", "road"],
                    "description": "Terrain type of destination (if known)"
                },
                "has_guide": {
                    "type": "boolean",
                    "description": "Party has a guide (reduces lost chance)",
                    "default": False
                },
                "forced_march": {
                    "type": "boolean",
                    "description": "Push through exhaustion for faster travel",
                    "default": False
                },
                "on_road": {
                    "type": "boolean",
                    "description": "Traveling on a road (faster)",
                    "default": False
                }
            },
            "required": ["destination"]
        }
    },
    {
        "name": "explore_current_hex",
        "description": """Explore the current hex to discover points of interest.
        
Use when the party wants to search the area. Takes 1-2 watches.
May trigger random encounters.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "detailed": {
                    "type": "boolean",
                    "description": "Thorough exploration (2 watches, better discoveries)",
                    "default": False
                }
            },
            "required": []
        }
    },
    {
        "name": "forage",
        "description": """Spend a watch foraging for food.
        
Success depends on terrain. Forest and water are good; mountains and settlements are poor.
May trigger random encounters.""",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "make_camp",
        "description": """Set up camp and rest.
        
Use for:
- Short rest (1 watch)
- Full camp (rest until dawn)

Reduced encounter chance while camping with watches set.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "full_rest": {
                    "type": "boolean",
                    "description": "Camp until dawn (vs just 1 watch rest)",
                    "default": False
                }
            },
            "required": []
        }
    },
    {
        "name": "check_random_encounter",
        "description": """Manually check for a random encounter.
        
Normally encounters are checked automatically during travel/exploration.
Use this for additional checks or special situations.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "modifier": {
                    "type": "integer",
                    "description": "Modifier to encounter chance (+/- to X-in-6)",
                    "default": 0
                }
            },
            "required": []
        }
    },
    {
        "name": "get_hex_crawl_status",
        "description": """Get current hex crawl status.
        
Returns:
- Current position and terrain
- Time (day, watch, time of day)
- Weather
- Resources
- Adjacent hexes""",
        "input_schema": {
            "type": "object",
            "properties": {
                "detailed": {
                    "type": "boolean",
                    "description": "Get full detailed status",
                    "default": False
                },
                "include_adjacent": {
                    "type": "boolean",
                    "description": "Include adjacent hex info",
                    "default": True
                }
            },
            "required": []
        }
    },
    {
        "name": "advance_time",
        "description": """Advance time by a number of watches.
        
Use when time passes without travel (waiting, talking, shopping).
Each watch is 4 hours. 6 watches per day.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "watches": {
                    "type": "integer",
                    "description": "Number of watches to advance (1-6)",
                    "default": 1
                }
            },
            "required": []
        }
    },
    {
        "name": "manage_resources",
        "description": """Add or consume party resources.
        
Track rations, water, torches, lantern oil, ammunition.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "resource": {
                    "type": "string",
                    "enum": ["rations", "water", "torches", "lantern_oil", "arrows", "bolts"],
                    "description": "Resource type"
                },
                "amount": {
                    "type": "integer",
                    "description": "Amount (positive to add, negative to consume)"
                }
            },
            "required": ["resource", "amount"]
        }
    },
    {
        "name": "set_hex_info",
        "description": """Add information about a hex (from rulebook or discovery).
        
Use when revealing hex contents from the adventure module.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "hex_id": {
                    "type": "string",
                    "description": "Hex ID (e.g., '0808')"
                },
                "terrain": {
                    "type": "string",
                    "enum": ["clear", "forest", "dense_forest", "hills", "mountains",
                             "swamp", "river", "lake", "settlement", "ruins", "road"],
                    "description": "Terrain type"
                },
                "name": {
                    "type": "string",
                    "description": "Location name"
                },
                "description": {
                    "type": "string",
                    "description": "Brief description"
                },
                "settlement": {
                    "type": "string",
                    "description": "Settlement name if present"
                },
                "points_of_interest": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Notable locations/features"
                }
            },
            "required": ["hex_id"]
        }
    },
    {
        "name": "set_weather",
        "description": """Manually set the weather.
        
Weather is normally rolled automatically each day.
Use this to override for story reasons.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "weather": {
                    "type": "string",
                    "enum": ["clear", "cloudy", "overcast", "light_rain", "heavy_rain",
                             "fog", "storm", "snow", "blizzard"],
                    "description": "Weather condition"
                }
            },
            "required": ["weather"]
        }
    }
]


# =============================================================================
# TOOL RESULT
# =============================================================================

@dataclass
class HexCrawlToolResult:
    """Result from a hex crawl tool call."""
    success: bool
    brief: str
    data: dict[str, Any] = field(default_factory=dict)
    encounter_occurred: bool = False
    warnings: list[str] = field(default_factory=list)


# =============================================================================
# TOOL HANDLER
# =============================================================================

class HexCrawlToolHandler:
    """
    Handles hex crawl tool calls from Claude.
    
    Wraps the HexCrawlEngine and provides Claude-friendly tool interfaces.
    
    Example:
        >>> handler = HexCrawlToolHandler()
        >>> handler.engine.set_party_size(4)
        >>> result = handler.handle_tool("travel_to_hex", {"destination": "0809"})
        >>> print(result.brief)
    """
    
    def __init__(self):
        """Initialize with a fresh hex crawl engine."""
        self.engine = HexCrawlEngine()
    
    def handle_tool(self, tool_name: str, tool_input: dict[str, Any]) -> HexCrawlToolResult:
        """
        Handle a hex crawl tool call.
        
        Args:
            tool_name: Name of the tool being called.
            tool_input: Input parameters for the tool.
        
        Returns:
            HexCrawlToolResult with brief description and data.
        """
        handlers = {
            "travel_to_hex": self._handle_travel,
            "explore_current_hex": self._handle_explore,
            "forage": self._handle_forage,
            "make_camp": self._handle_camp,
            "check_random_encounter": self._handle_encounter_check,
            "get_hex_crawl_status": self._handle_get_status,
            "advance_time": self._handle_advance_time,
            "manage_resources": self._handle_resources,
            "set_hex_info": self._handle_set_hex_info,
            "set_weather": self._handle_set_weather,
        }
        
        handler = handlers.get(tool_name)
        if not handler:
            return HexCrawlToolResult(
                success=False,
                brief=f"Unknown hex crawl tool: {tool_name}"
            )
        
        try:
            return handler(tool_input)
        except Exception as e:
            logger.error(f"Hex crawl tool error ({tool_name}): {e}")
            return HexCrawlToolResult(
                success=False,
                brief=f"Error: {str(e)}"
            )
    
    def _handle_travel(self, input: dict) -> HexCrawlToolResult:
        """Handle travel_to_hex tool."""
        destination = input["destination"]
        
        # Parse terrain if provided
        terrain = None
        if "terrain" in input and input["terrain"]:
            try:
                terrain = Terrain(input["terrain"])
            except ValueError:
                pass
        
        result = self.engine.travel_to_hex(
            destination=destination,
            terrain=terrain,
            has_guide=input.get("has_guide", False),
            forced_march=input.get("forced_march", False),
            on_road=input.get("on_road", False)
        )
        
        if not result.success:
            return HexCrawlToolResult(
                success=False,
                brief=f"Cannot travel to {destination} - too far or invalid hex."
            )
        
        # Get warnings
        warnings = self.engine.get_resource_warnings()
        
        return HexCrawlToolResult(
            success=True,
            brief=result.brief,
            data={
                "origin": result.origin_hex,
                "destination": result.destination_hex,
                "actual_destination": result.actual_destination,
                "got_lost": result.got_lost,
                "watches_spent": result.watches_spent,
                "day": result.day_number,
                "watch": result.current_watch,
                "time_of_day": result.time_of_day.value,
                "weather": result.weather.value,
                "terrain": result.terrain_crossed.value,
                "new_hex_discovered": result.new_hex_discovered,
                "exhaustion_failed": result.exhaustion_failed,
                "resources_consumed": result.resources_consumed,
            },
            encounter_occurred=result.encounter_occurred,
            warnings=warnings
        )
    
    def _handle_explore(self, input: dict) -> HexCrawlToolResult:
        """Handle explore_current_hex tool."""
        detailed = input.get("detailed", False)
        
        result = self.engine.explore_hex(detailed=detailed)
        
        return HexCrawlToolResult(
            success=True,
            brief=result.brief,
            data={
                "hex_id": result.hex_id,
                "discoveries": result.discoveries,
                "watches_spent": result.watches_spent,
            },
            encounter_occurred=result.encounter_occurred,
            warnings=self.engine.get_resource_warnings()
        )
    
    def _handle_forage(self, input: dict) -> HexCrawlToolResult:
        """Handle forage tool."""
        result = self.engine.forage()
        
        return HexCrawlToolResult(
            success=True,
            brief=result.brief,
            data={
                "success": result.foraging_success,
                "amount": result.foraging_amount,
                "total_rations": self.engine.resources.rations,
            },
            encounter_occurred=result.encounter_occurred,
            warnings=self.engine.get_resource_warnings()
        )
    
    def _handle_camp(self, input: dict) -> HexCrawlToolResult:
        """Handle make_camp tool."""
        full_rest = input.get("full_rest", False)
        
        result = self.engine.rest(full_rest=full_rest)
        
        return HexCrawlToolResult(
            success=True,
            brief=result.brief,
            data={
                "activity": result.activity.value,
                "watches_spent": result.watches_spent,
                "day": self.engine.day_number,
                "watch": self.engine.watch_number,
                "weather": result.weather.value,
            },
            encounter_occurred=result.encounter_occurred,
            warnings=self.engine.get_resource_warnings()
        )
    
    def _handle_encounter_check(self, input: dict) -> HexCrawlToolResult:
        """Handle check_random_encounter tool."""
        modifier = input.get("modifier", 0)
        
        result = self.engine.check_encounter(modifier=modifier)
        
        return HexCrawlToolResult(
            success=True,
            brief=result["brief"],
            data=result,
            encounter_occurred=result["encounter"]
        )
    
    def _handle_get_status(self, input: dict) -> HexCrawlToolResult:
        """Handle get_hex_crawl_status tool."""
        detailed = input.get("detailed", False)
        include_adjacent = input.get("include_adjacent", True)
        
        status = self.engine.get_status()
        
        if detailed:
            brief = status.full_status
        else:
            brief = status.brief
        
        data = {
            "current_hex": status.current_hex,
            "terrain": status.current_terrain.value,
            "day": status.day_number,
            "watch": status.watch_number,
            "time_of_day": status.time_of_day.value,
            "weather": status.weather.value,
            "season": status.season.value,
            "resources": status.resources,
            "party_size": status.party_size,
            "hexes_discovered": status.discovered_hexes,
        }
        
        if include_adjacent:
            data["adjacent_hexes"] = self.engine.get_adjacent_info()
        
        return HexCrawlToolResult(
            success=True,
            brief=brief,
            data=data,
            warnings=self.engine.get_resource_warnings()
        )
    
    def _handle_advance_time(self, input: dict) -> HexCrawlToolResult:
        """Handle advance_time tool."""
        watches = max(1, min(6, input.get("watches", 1)))
        
        result = self.engine.advance_watch(watches)
        
        return HexCrawlToolResult(
            success=True,
            brief=result["brief"],
            data=result,
            warnings=self.engine.get_resource_warnings()
        )
    
    def _handle_resources(self, input: dict) -> HexCrawlToolResult:
        """Handle manage_resources tool."""
        resource_str = input["resource"]
        amount = input["amount"]
        
        try:
            resource = ResourceType(resource_str)
        except ValueError:
            return HexCrawlToolResult(
                success=False,
                brief=f"Unknown resource type: {resource_str}"
            )
        
        if amount >= 0:
            self.engine.add_resources(resource, amount)
            brief = f"Added {amount} {resource_str} (now have {self.engine.resources.get(resource)})"
        else:
            result = self.engine.consume_resource(resource, abs(amount))
            brief = result["brief"]
        
        return HexCrawlToolResult(
            success=True,
            brief=brief,
            data={
                "resource": resource_str,
                "amount": amount,
                "current": self.engine.resources.get(resource),
            },
            warnings=self.engine.get_resource_warnings()
        )
    
    def _handle_set_hex_info(self, input: dict) -> HexCrawlToolResult:
        """Handle set_hex_info tool."""
        hex_id = input["hex_id"]
        
        terrain = None
        if "terrain" in input and input["terrain"]:
            try:
                terrain = Terrain(input["terrain"])
            except ValueError:
                pass
        
        self.engine.add_hex_info(
            hex_id=hex_id,
            terrain=terrain,
            name=input.get("name"),
            description=input.get("description"),
            settlement=input.get("settlement"),
            points_of_interest=input.get("points_of_interest"),
        )
        
        hex_info = self.engine.get_hex_info(hex_id)
        name = hex_info.name if hex_info else hex_id
        
        return HexCrawlToolResult(
            success=True,
            brief=f"Updated hex {hex_id}: {name}",
            data=hex_info.to_dict() if hex_info else {}
        )
    
    def _handle_set_weather(self, input: dict) -> HexCrawlToolResult:
        """Handle set_weather tool."""
        weather_str = input["weather"]
        
        try:
            weather = Weather(weather_str)
        except ValueError:
            return HexCrawlToolResult(
                success=False,
                brief=f"Unknown weather: {weather_str}"
            )
        
        self.engine.current_weather = weather
        
        return HexCrawlToolResult(
            success=True,
            brief=f"Weather is now {weather.value.replace('_', ' ')}",
            data={"weather": weather.value}
        )
    
    # =========================================================================
    # CONVENIENCE METHODS
    # =========================================================================
    
    def setup(
        self,
        starting_hex: str = "0808",
        terrain: Terrain = Terrain.SETTLEMENT,
        party_size: int = 4,
        season: Season = Season.AUTUMN,
        starting_rations: int = 20,
        starting_torches: int = 10
    ) -> None:
        """
        Quick setup for hex crawl.
        
        Args:
            starting_hex: Starting hex ID.
            terrain: Starting terrain.
            party_size: Number of party members.
            season: Current season.
            starting_rations: Starting rations.
            starting_torches: Starting torches.
        """
        self.engine.set_starting_position(starting_hex, terrain)
        self.engine.set_party_size(party_size)
        self.engine.set_season(season)
        self.engine.set_resources(
            rations=starting_rations,
            torches=starting_torches,
            water=party_size * 3
        )


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def create_hex_crawl_handler() -> HexCrawlToolHandler:
    """Create a new hex crawl tool handler."""
    return HexCrawlToolHandler()
