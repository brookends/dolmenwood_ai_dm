"""
Dolmenwood AI DM - Settlement Exploration Engine (v2.0)

This module implements the settlement exploration loop with proper
procedural controls.

The settlement loop:
1. Establish settlement mood
2. Update faction clocks
3. Resolve reactions to party
4. Offer rumors/services
5. Await player declaration
6. Request LLM description (social tone only)

Author: AI Dungeon Master Project
Version: 2.0
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from game_state.state_machine import StateMachine, TransitionTrigger
    from game_state.global_controller import GlobalController

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class SettlementSize(str, Enum):
    """Size categories for settlements."""
    HAMLET = "hamlet"       # 20-100 people
    VILLAGE = "village"     # 100-500 people
    TOWN = "town"           # 500-2000 people
    CITY = "city"           # 2000+ people


class SettlementMood(str, Enum):
    """Current mood of the settlement."""
    FESTIVE = "festive"         # Celebration, welcoming
    PEACEFUL = "peaceful"       # Normal, calm
    SUSPICIOUS = "suspicious"   # Wary of strangers
    FEARFUL = "fearful"         # Something is wrong
    HOSTILE = "hostile"         # Outsiders unwelcome
    MOURNING = "mourning"       # Recent tragedy


class ServiceType(str, Enum):
    """Types of services available."""
    INN = "inn"                 # Lodging and food
    TAVERN = "tavern"           # Drinks and rumors
    TEMPLE = "temple"           # Healing and blessing
    BLACKSMITH = "blacksmith"   # Weapons and armor
    GENERAL_STORE = "general_store"
    STABLES = "stables"
    HEALER = "healer"
    SAGE = "sage"               # Information
    GUILD = "guild"             # Specialized services


class RumorType(str, Enum):
    """Types of rumors."""
    GOSSIP = "gossip"           # Local news
    WARNING = "warning"         # Danger information
    QUEST_HOOK = "quest_hook"   # Adventure lead
    LORE = "lore"               # Historical/magical info
    FALSE = "false"             # Misleading info


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SettlementService:
    """
    A service available in the settlement.
    """
    service_id: str
    name: str
    service_type: ServiceType
    proprietor: str = ""
    quality: int = 1  # 1-5
    prices_modifier: float = 1.0  # 1.0 = normal
    available: bool = True
    notes: str = ""


@dataclass
class SettlementNPC:
    """
    An NPC in the settlement.
    """
    npc_id: str
    name: str
    occupation: str
    location: str = ""  # Where they can be found
    disposition: int = 0  # -5 to +5 toward party
    knows_rumors: list[str] = field(default_factory=list)
    quests_available: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Rumor:
    """
    A rumor that can be learned in the settlement.
    """
    rumor_id: str
    content: str
    rumor_type: RumorType
    is_true: bool = True
    source_npc: str = ""
    related_location: str = ""
    learned: bool = False


@dataclass
class SettlementStatus:
    """
    Current settlement exploration status.
    """
    settlement_id: str
    settlement_name: str
    size: SettlementSize
    mood: SettlementMood

    # Time
    time_of_day: str
    day_number: int

    # Services
    available_services: list[str]

    # Party status
    party_reputation: int
    known_npcs: list[str]
    learned_rumors: int

    # Warnings
    warnings: list[str]

    @property
    def brief(self) -> str:
        """Get concise status."""
        return (
            f"{self.settlement_name} ({self.size.value}) | "
            f"Mood: {self.mood.value} | "
            f"Reputation: {self.party_reputation:+d}"
        )

    @property
    def full_status(self) -> str:
        """Get detailed status."""
        lines = [
            f"=== SETTLEMENT: {self.settlement_name.upper()} ===",
            f"Size: {self.size.value.capitalize()}",
            f"Mood: {self.mood.value.capitalize()}",
            f"Time: {self.time_of_day}, Day {self.day_number}",
            f"",
            f"Party Reputation: {self.party_reputation:+d}",
            f"Known NPCs: {len(self.known_npcs)}",
            f"Rumors Learned: {self.learned_rumors}",
            f"",
            f"Available Services:",
        ]

        for service in self.available_services:
            lines.append(f"  • {service}")

        if self.warnings:
            lines.append("")
            lines.append("WARNINGS:")
            for w in self.warnings:
                lines.append(f"  ! {w}")

        return "\n".join(lines)


@dataclass
class SettlementActionResult:
    """
    Result of a settlement action.
    """
    action: str
    success: bool
    result: dict[str, Any] = field(default_factory=dict)
    time_spent: int = 0  # watches
    gold_spent: int = 0
    reputation_change: int = 0
    messages: list[str] = field(default_factory=list)

    @property
    def brief(self) -> str:
        """Get brief summary."""
        parts = [f"{self.action}: {'Success' if self.success else 'Failed'}"]
        if self.time_spent:
            parts.append(f"{self.time_spent} watch(es)")
        if self.gold_spent:
            parts.append(f"{self.gold_spent} gp spent")
        return " | ".join(parts)


# =============================================================================
# SETTLEMENT ENGINE
# =============================================================================

class SettlementEngine:
    """
    Settlement exploration state machine.

    Handles:
    - Settlement mood and atmosphere
    - Available services
    - NPC interactions
    - Rumor gathering
    - Reputation tracking
    - Time passage in settlements

    Example:
        >>> engine = SettlementEngine()
        >>> engine.enter_settlement("prigswort", "Prigwort", SettlementSize.VILLAGE)
        >>> result = engine.perform_action("gather_rumors")
        >>> print(result.brief)
    """

    def __init__(
        self,
        state_machine: Optional["StateMachine"] = None,
        controller: Optional["GlobalController"] = None
    ):
        """
        Initialize settlement engine.

        Args:
            state_machine: Optional state machine for transitions.
            controller: Optional global controller for state.
        """
        self.state_machine = state_machine
        self.controller = controller

        # Settlement state
        self.settlement_id: Optional[str] = None
        self.settlement_name: str = ""
        self.size: SettlementSize = SettlementSize.VILLAGE
        self.mood: SettlementMood = SettlementMood.PEACEFUL

        # Services
        self.services: dict[str, SettlementService] = {}

        # NPCs
        self.npcs: dict[str, SettlementNPC] = {}
        self.met_npcs: set[str] = set()

        # Rumors
        self.rumors: list[Rumor] = []
        self.learned_rumors: set[str] = set()

        # Party standing
        self.party_reputation: int = 0

        # Time
        self.watches_spent: int = 0

        logger.info("SettlementEngine initialized")

    # =========================================================================
    # SETTLEMENT LIFECYCLE
    # =========================================================================

    def enter_settlement(
        self,
        settlement_id: str,
        name: str,
        size: SettlementSize,
        mood: Optional[SettlementMood] = None
    ) -> SettlementStatus:
        """
        Enter a settlement.

        Args:
            settlement_id: Unique ID for this settlement.
            name: Display name.
            size: Settlement size category.
            mood: Optional mood (will be rolled if not provided).

        Returns:
            Initial settlement status.
        """
        self.settlement_id = settlement_id
        self.settlement_name = name
        self.size = size
        self.mood = mood or self._roll_mood()
        self.watches_spent = 0

        # Generate default services based on size
        self._generate_services()

        logger.info(f"Entered settlement {name} ({size.value})")

        return self.get_status()

    def exit_settlement(self) -> dict[str, Any]:
        """
        Exit the settlement.

        Returns:
            Summary of settlement visit.
        """
        summary = {
            "settlement_id": self.settlement_id,
            "settlement_name": self.settlement_name,
            "watches_spent": self.watches_spent,
            "npcs_met": len(self.met_npcs),
            "rumors_learned": len(self.learned_rumors),
            "reputation_change": self.party_reputation,
        }

        self.settlement_id = None
        self.settlement_name = ""
        self.services.clear()
        self.npcs.clear()
        self.met_npcs.clear()
        self.rumors.clear()
        self.learned_rumors.clear()

        return summary

    def _roll_mood(self) -> SettlementMood:
        """Roll for settlement mood."""
        # Could be influenced by world events, season, faction states
        roll = random.randint(1, 10)

        if roll <= 1:
            return SettlementMood.FESTIVE
        elif roll <= 5:
            return SettlementMood.PEACEFUL
        elif roll <= 7:
            return SettlementMood.SUSPICIOUS
        elif roll <= 8:
            return SettlementMood.FEARFUL
        elif roll <= 9:
            return SettlementMood.MOURNING
        else:
            return SettlementMood.HOSTILE

    def _generate_services(self) -> None:
        """Generate services based on settlement size."""
        self.services.clear()

        # All settlements have basic services
        self.services["tavern"] = SettlementService(
            service_id="tavern",
            name="Local Tavern",
            service_type=ServiceType.TAVERN
        )

        if self.size in (SettlementSize.VILLAGE, SettlementSize.TOWN, SettlementSize.CITY):
            self.services["inn"] = SettlementService(
                service_id="inn",
                name="Local Inn",
                service_type=ServiceType.INN
            )
            self.services["general_store"] = SettlementService(
                service_id="general_store",
                name="General Store",
                service_type=ServiceType.GENERAL_STORE
            )

        if self.size in (SettlementSize.TOWN, SettlementSize.CITY):
            self.services["blacksmith"] = SettlementService(
                service_id="blacksmith",
                name="Blacksmith",
                service_type=ServiceType.BLACKSMITH
            )
            self.services["temple"] = SettlementService(
                service_id="temple",
                name="Temple",
                service_type=ServiceType.TEMPLE
            )
            self.services["stables"] = SettlementService(
                service_id="stables",
                name="Stables",
                service_type=ServiceType.STABLES
            )

        if self.size == SettlementSize.CITY:
            self.services["healer"] = SettlementService(
                service_id="healer",
                name="Healer",
                service_type=ServiceType.HEALER
            )
            self.services["sage"] = SettlementService(
                service_id="sage",
                name="Sage",
                service_type=ServiceType.SAGE
            )

    # =========================================================================
    # ACTIONS
    # =========================================================================

    def perform_action(
        self,
        action: str,
        params: Optional[dict[str, Any]] = None
    ) -> SettlementActionResult:
        """
        Perform a settlement action.

        Args:
            action: Action to perform.
            params: Action parameters.

        Returns:
            SettlementActionResult with outcome.
        """
        params = params or {}

        if action == "gather_rumors":
            return self._action_gather_rumors()

        elif action == "visit_service":
            return self._action_visit_service(params.get("service_id", "tavern"))

        elif action == "rest":
            return self._action_rest(params.get("quality", "common"))

        elif action == "shop":
            return self._action_shop(params.get("items", []))

        elif action == "seek_healing":
            return self._action_seek_healing(params.get("character_id"))

        elif action == "hire":
            return self._action_hire(params.get("type", "porter"))

        elif action == "train":
            return self._action_train(params.get("skill"))

        elif action == "research":
            return self._action_research(params.get("topic"))

        else:
            return SettlementActionResult(
                action=action,
                success=False,
                messages=[f"Unknown action: {action}"]
            )

    def _action_gather_rumors(self) -> SettlementActionResult:
        """Spend time gathering rumors."""
        self.watches_spent += 1

        # CHA modifier affects rumor quality
        cha_mod = 0  # Would come from character

        # Mood affects willingness to share
        mood_mod = {
            SettlementMood.FESTIVE: 2,
            SettlementMood.PEACEFUL: 1,
            SettlementMood.SUSPICIOUS: -1,
            SettlementMood.FEARFUL: 0,
            SettlementMood.HOSTILE: -2,
            SettlementMood.MOURNING: -1,
        }

        roll = random.randint(1, 6) + cha_mod + mood_mod.get(self.mood, 0)

        rumors_found = []

        if roll >= 4:
            # Found a rumor
            rumor = self._generate_rumor()
            if rumor and rumor.rumor_id not in self.learned_rumors:
                rumors_found.append(rumor.content)
                self.learned_rumors.add(rumor.rumor_id)
                self.rumors.append(rumor)

        return SettlementActionResult(
            action="gather_rumors",
            success=len(rumors_found) > 0,
            result={"rumors": rumors_found, "roll": roll},
            time_spent=1,
            gold_spent=random.randint(1, 3),  # Buying drinks
            messages=rumors_found if rumors_found else ["No interesting rumors today."]
        )

    def _generate_rumor(self) -> Optional[Rumor]:
        """Generate a random rumor."""
        rumor_templates = [
            ("Strange lights seen in the woods near {location}", RumorType.WARNING, True),
            ("The old {location} is said to hold treasure", RumorType.QUEST_HOOK, True),
            ("Travelers went missing on the road to {location}", RumorType.WARNING, True),
            ("A merchant claims to have seen a {creature}", RumorType.GOSSIP, True),
            ("The lord's son has gone missing", RumorType.QUEST_HOOK, True),
            ("Drune cultists have been spotted nearby", RumorType.WARNING, True),
            ("Fairy rings have been appearing more often", RumorType.LORE, True),
            ("The well water has turned strange", RumorType.GOSSIP, True),
            ("There's gold hidden in the ruins", RumorType.QUEST_HOOK, False),  # False rumor
            ("The forest is completely safe", RumorType.FALSE, False),
        ]

        template, rumor_type, is_true = random.choice(rumor_templates)

        # Fill in location placeholder
        locations = ["Dolmenwood", "the Nagwood", "Lankshorn", "the old mill", "the barrow"]
        creatures = ["unicorn", "drune patrol", "giant spider", "ghost", "talking fox"]

        content = template.format(
            location=random.choice(locations),
            creature=random.choice(creatures)
        )

        return Rumor(
            rumor_id=f"rumor_{random.randint(1000, 9999)}",
            content=content,
            rumor_type=rumor_type,
            is_true=is_true
        )

    def _action_visit_service(self, service_id: str) -> SettlementActionResult:
        """Visit a service establishment."""
        service = self.services.get(service_id)

        if not service:
            return SettlementActionResult(
                action="visit_service",
                success=False,
                messages=[f"No such service: {service_id}"]
            )

        if not service.available:
            return SettlementActionResult(
                action="visit_service",
                success=False,
                messages=[f"{service.name} is not available right now."]
            )

        return SettlementActionResult(
            action="visit_service",
            success=True,
            result={
                "service": service_id,
                "name": service.name,
                "proprietor": service.proprietor,
                "quality": service.quality,
            },
            messages=[f"You visit {service.name}."]
        )

    def _action_rest(self, quality: str) -> SettlementActionResult:
        """Rest at an inn."""
        if "inn" not in self.services:
            return SettlementActionResult(
                action="rest",
                success=False,
                messages=["No inn available in this settlement."]
            )

        costs = {
            "poor": 1,
            "common": 5,
            "comfortable": 15,
            "luxurious": 50,
        }

        cost = costs.get(quality, 5)

        # Advance time
        self.watches_spent += 4  # Sleep through the night

        if self.controller:
            self.controller.advance_time("watch", 4)

        return SettlementActionResult(
            action="rest",
            success=True,
            result={"quality": quality, "healed": True},
            time_spent=4,
            gold_spent=cost,
            messages=[f"You rest at the inn ({quality} accommodations)."]
        )

    def _action_shop(self, items: list[str]) -> SettlementActionResult:
        """Purchase items."""
        if "general_store" not in self.services and "blacksmith" not in self.services:
            return SettlementActionResult(
                action="shop",
                success=False,
                messages=["No shops available in this settlement."]
            )

        # Simplified shopping - would check inventory
        total_cost = len(items) * 10  # Placeholder

        return SettlementActionResult(
            action="shop",
            success=True,
            result={"items_purchased": items},
            time_spent=1,
            gold_spent=total_cost,
            messages=[f"Purchased {len(items)} item(s)."]
        )

    def _action_seek_healing(self, character_id: Optional[str]) -> SettlementActionResult:
        """Seek healing services."""
        if "temple" not in self.services and "healer" not in self.services:
            return SettlementActionResult(
                action="seek_healing",
                success=False,
                messages=["No healing services available."]
            )

        # Healing costs
        cost = 50  # Base cost for healing

        return SettlementActionResult(
            action="seek_healing",
            success=True,
            result={"healed": True, "amount": "full"},
            time_spent=1,
            gold_spent=cost,
            messages=["Healing provided by the temple."]
        )

    def _action_hire(self, hire_type: str) -> SettlementActionResult:
        """Hire a retainer or hireling."""
        # Check if settlement large enough
        if self.size == SettlementSize.HAMLET:
            return SettlementActionResult(
                action="hire",
                success=False,
                messages=["Settlement too small for hiring."]
            )

        # Would roll for availability
        available = random.randint(1, 6) >= 3

        if not available:
            return SettlementActionResult(
                action="hire",
                success=False,
                time_spent=1,
                messages=[f"No {hire_type} available for hire."]
            )

        return SettlementActionResult(
            action="hire",
            success=True,
            result={"hired": hire_type},
            time_spent=1,
            gold_spent=10,  # Hiring fee
            messages=[f"Hired a {hire_type}."]
        )

    def _action_train(self, skill: Optional[str]) -> SettlementActionResult:
        """Train a skill."""
        if "guild" not in self.services and self.size not in (SettlementSize.TOWN, SettlementSize.CITY):
            return SettlementActionResult(
                action="train",
                success=False,
                messages=["No training available here."]
            )

        # Training takes significant time
        return SettlementActionResult(
            action="train",
            success=True,
            result={"skill": skill, "progress": 1},
            time_spent=6,  # 1 day
            gold_spent=100,
            messages=[f"Began training in {skill or 'general skills'}."]
        )

    def _action_research(self, topic: Optional[str]) -> SettlementActionResult:
        """Research a topic with a sage."""
        if "sage" not in self.services:
            return SettlementActionResult(
                action="research",
                success=False,
                messages=["No sage available for research."]
            )

        # Research success
        roll = random.randint(1, 6)
        success = roll >= 3

        return SettlementActionResult(
            action="research",
            success=success,
            result={"topic": topic, "information_found": success},
            time_spent=2,
            gold_spent=50,
            messages=[f"Research on '{topic or 'unknown topic'}': {'Found information!' if success else 'Nothing conclusive.'}"]
        )

    # =========================================================================
    # NPC MANAGEMENT
    # =========================================================================

    def add_npc(self, npc: SettlementNPC) -> None:
        """Add an NPC to the settlement."""
        self.npcs[npc.npc_id] = npc

    def meet_npc(self, npc_id: str) -> Optional[SettlementNPC]:
        """
        Meet an NPC for the first time.

        Returns:
            The NPC if found.
        """
        npc = self.npcs.get(npc_id)
        if npc:
            self.met_npcs.add(npc_id)
        return npc

    def modify_npc_disposition(self, npc_id: str, change: int) -> int:
        """
        Modify an NPC's disposition toward the party.

        Returns:
            New disposition value.
        """
        npc = self.npcs.get(npc_id)
        if npc:
            npc.disposition = max(-5, min(5, npc.disposition + change))
            return npc.disposition
        return 0

    # =========================================================================
    # REPUTATION
    # =========================================================================

    def modify_reputation(self, change: int) -> int:
        """
        Modify party reputation in this settlement.

        Returns:
            New reputation value.
        """
        self.party_reputation = max(-10, min(10, self.party_reputation + change))
        return self.party_reputation

    def get_reputation_effects(self) -> dict[str, Any]:
        """Get effects of current reputation."""
        effects = {
            "price_modifier": 1.0,
            "reaction_modifier": 0,
            "services_available": True,
        }

        if self.party_reputation >= 5:
            effects["price_modifier"] = 0.9
            effects["reaction_modifier"] = 2
        elif self.party_reputation >= 2:
            effects["price_modifier"] = 0.95
            effects["reaction_modifier"] = 1
        elif self.party_reputation <= -5:
            effects["price_modifier"] = 1.25
            effects["reaction_modifier"] = -2
            effects["services_available"] = False
        elif self.party_reputation <= -2:
            effects["price_modifier"] = 1.1
            effects["reaction_modifier"] = -1

        return effects

    # =========================================================================
    # STATUS
    # =========================================================================

    def get_status(self) -> SettlementStatus:
        """Get current settlement status."""
        warnings = []

        if self.mood == SettlementMood.HOSTILE:
            warnings.append("The locals are hostile to outsiders!")
        elif self.mood == SettlementMood.FEARFUL:
            warnings.append("The locals seem afraid of something.")

        if self.party_reputation <= -5:
            warnings.append("Your reputation here is very poor.")

        time_of_day = "morning"
        day_number = 1
        if self.controller:
            time_of_day = self.controller.get_time_of_day().value
            day_number = self.controller.get_current_time().day

        return SettlementStatus(
            settlement_id=self.settlement_id or "",
            settlement_name=self.settlement_name,
            size=self.size,
            mood=self.mood,
            time_of_day=time_of_day,
            day_number=day_number,
            available_services=[s.name for s in self.services.values() if s.available],
            party_reputation=self.party_reputation,
            known_npcs=list(self.met_npcs),
            learned_rumors=len(self.learned_rumors),
            warnings=warnings
        )


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_settlement_engine(
    state_machine: Optional["StateMachine"] = None,
    controller: Optional["GlobalController"] = None
) -> SettlementEngine:
    """
    Create a new settlement engine.

    Args:
        state_machine: Optional state machine.
        controller: Optional global controller.

    Returns:
        Configured SettlementEngine.
    """
    return SettlementEngine(
        state_machine=state_machine,
        controller=controller
    )
