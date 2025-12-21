"""
Dolmenwood AI DM - Hex Crawl Engine Module

This module provides automated hex crawl management including
movement, time tracking, encounters, resources, and exploration.
"""

from .hex_crawl_engine import (
    HexCrawlEngine,
    HexInfo,
    TravelResult,
    ExplorationResult,
    WatchActivity,
    Terrain,
    Weather,
    TimeOfDay,
    ResourceType,
)

from .hex_crawl_tools import (
    HEX_CRAWL_TOOL_DEFINITIONS,
    HexCrawlToolHandler,
    HexCrawlToolResult,
    create_hex_crawl_handler,
)

__all__ = [
    # Engine
    "HexCrawlEngine",
    "HexInfo",
    "TravelResult",
    "ExplorationResult",
    "WatchActivity",
    "Terrain",
    "Weather",
    "TimeOfDay",
    "ResourceType",
    # Tools
    "HEX_CRAWL_TOOL_DEFINITIONS",
    "HexCrawlToolHandler",
    "HexCrawlToolResult",
    "create_hex_crawl_handler",
]
