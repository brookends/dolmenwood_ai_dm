"""
Dolmenwood AI DM - Downtime Module (v2.0)

This package contains the downtime activities engine.
"""

from .downtime_engine import (
    DowntimeEngine,
    DowntimeActivity,
    TrainingType,
    FactionAction,
    ResearchType,
    CraftingType,
    CarousingResult,
    TrainingProgress,
    ResearchProject,
    CraftingProject,
    FactionProgress,
    DowntimeDay,
    DowntimeSession,
)

__all__ = [
    "DowntimeEngine",
    "DowntimeActivity",
    "TrainingType",
    "FactionAction",
    "ResearchType",
    "CraftingType",
    "CarousingResult",
    "TrainingProgress",
    "ResearchProject",
    "CraftingProject",
    "FactionProgress",
    "DowntimeDay",
    "DowntimeSession",
]
