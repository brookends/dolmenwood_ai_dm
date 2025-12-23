"""
Dolmenwood AI Dungeon Master - Main Game Loop (v2.0)

This module provides the main game orchestrator that integrates all
components: PDF processing, vector database, game state management,
and the AI DM agent.

v2.0 Features:
- Formal state machine with 8 mutually exclusive game states
- Hierarchical action architecture with always-active GlobalController
- Mode-specific deterministic execution loops
- Non-negotiable procedure triggers
- Failure-first action resolution
- LLM integration with strict authority boundaries
- Complete game session management
- CLI interface for gameplay
- PDF content ingestion
- Save/load functionality
- Character management
- Campaign configuration

Author: AI Dungeon Master Project
Version: 2.0
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from data_models import (
    WorldState,
    DolmenwoodCharacter,
    HistoryEntry,
    LocationType,
    Season,
    Weather,
    Kindred,
    CharacterClass,
)
from game_state.state_manager import GameStateManager
from vector_db.rules_retriever import RulesRetriever, create_retriever
from ai.dm_agent import DolmenwoodDM, DMConfig, DMResponse, DiceRoller

# v2.0 Core Architecture
from game_state.state_machine import GameState, StateMachine, StateTransition, TransitionTrigger
from game_state.global_controller import (
    GlobalController,
    GameTime,
    PartyResources,
    WorldFlags,
)
from game_state.transition_detector import (
    StateTransitionDetector,
    create_transition_detector,
)
from resolution.procedure_triggers import (
    ProcedureTrigger,
    TriggerHandler,
    TriggerResult,
)
from resolution.action_resolver import (
    ActionResolver,
    ActionResult,
)

# v2.0 Data Models
from data_models_v2 import (
    TimeTrackerV2,
    LocationState,
    EncounterState,
    FactionState,
    PartyStateV2,
    WorldStateV2,
)

# v2.0 Tables
from tables.dolmenwood_tables import (
    DolmenwoodTables,
    DolmenwoodRegion,
)

# v2.0 Mode Engines
try:
    from dungeon.dungeon_engine import DungeonEngine, TurnResult as DungeonTurnResult
    DUNGEON_ENGINE_AVAILABLE = True
except ImportError:
    DUNGEON_ENGINE_AVAILABLE = False
    DungeonEngine = None
    DungeonTurnResult = None
    logger.warning("Dungeon engine not available")

try:
    from settlement.settlement_engine import SettlementEngine
    SETTLEMENT_ENGINE_AVAILABLE = True
except ImportError:
    SETTLEMENT_ENGINE_AVAILABLE = False
    SettlementEngine = None
    logger.warning("Settlement engine not available")

try:
    from downtime.downtime_engine import DowntimeEngine
    DOWNTIME_ENGINE_AVAILABLE = True
except ImportError:
    DOWNTIME_ENGINE_AVAILABLE = False
    DowntimeEngine = None
    logger.warning("Downtime engine not available")

# v2.0 AI Integration
from ai.prompt_schemas import (
    LLMAuthority,
    PromptCategory,
    PromptBuilder,
    ResponseParser,
    create_prompt_builder,
    create_response_parser,
    AUTHORITY_RULES,
)

# Combat engine
try:
    from combat.combat_tools import CombatToolHandler, create_combat_handler
    COMBAT_ENGINE_AVAILABLE = True
except ImportError:
    COMBAT_ENGINE_AVAILABLE = False
    logger.warning("Combat engine not available")

# Hex crawl engine
try:
    from exploration.hex_crawl_tools import HexCrawlToolHandler, create_hex_crawl_handler
    HEX_CRAWL_ENGINE_AVAILABLE = True
except ImportError:
    HEX_CRAWL_ENGINE_AVAILABLE = False
    logger.warning("Hex crawl engine not available")

# Content loader
try:
    from content_loader import ContentLoader, LoadResult
    CONTENT_LOADER_AVAILABLE = True
except ImportError:
    CONTENT_LOADER_AVAILABLE = False
    logger.warning("Content loader not available")


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class GameConfig:
    """Configuration for the game session."""
    
    # Paths
    data_dir: str = "./data"
    database_path: str = "./data/game_state.db"
    vector_db_path: str = "./data/vectordb"
    pdf_dir: str = "./data/pdfs"
    
    # API Keys (from environment)
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    
    # LLM Provider settings
    llm_provider: str = "claude"  # "claude", "ollama", "openai"
    llm_model: Optional[str] = None  # Model name (provider-specific)
    llm_base_url: Optional[str] = None  # For Ollama/OpenAI-compatible
    
    # Game settings
    campaign_name: str = "Dolmenwood Campaign"
    dm_style: str = "evocative"
    rules_strictness: str = "balanced"
    
    # Feature flags
    use_vector_db: bool = True
    use_mock_embeddings: bool = False  # For testing without API (poor quality)
    use_local_embeddings: bool = False  # Use sentence-transformers (free, good quality)
    auto_save: bool = True
    
    def __post_init__(self):
        """Load API keys from environment if not provided."""
        if self.anthropic_api_key is None:
            self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
        if self.openai_api_key is None:
            self.openai_api_key = os.environ.get("OPENAI_API_KEY")
        
        # Set default model per provider
        if self.llm_model is None:
            if self.llm_provider == "claude":
                self.llm_model = "claude-sonnet-4-20250514"
            elif self.llm_provider == "ollama":
                self.llm_model = "llama3.2"
            elif self.llm_provider == "openai":
                self.llm_model = "local-model"
        
        # Set default base URLs
        if self.llm_base_url is None:
            if self.llm_provider == "ollama":
                self.llm_base_url = "http://localhost:11434"
            elif self.llm_provider == "openai":
                self.llm_base_url = "http://localhost:1234/v1"
        
        # Create directories
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.pdf_dir).mkdir(parents=True, exist_ok=True)


# =============================================================================
# GAME SESSION
# =============================================================================

class DolmenwoodGame:
    """
    Main game orchestrator for Dolmenwood AI DM.
    
    Integrates all components and manages the game session lifecycle.
    
    Example:
        >>> game = DolmenwoodGame()
        >>> game.start_new_campaign("My Campaign")
        >>> response = game.process_input("I look around the tavern")
        >>> print(response.narrative)
    """
    
    def __init__(self, config: Optional[GameConfig] = None):
        """
        Initialize the game.

        Args:
            config: Game configuration. Uses defaults if not provided.
        """
        self.config = config or GameConfig()

        # Initialize components
        self._state_manager: Optional[GameStateManager] = None
        self._rules_retriever: Optional[RulesRetriever] = None
        self._dm: Optional[DolmenwoodDM] = None
        self._combat_handler: Optional[CombatToolHandler] = None
        self._hex_crawl_handler: Optional[HexCrawlToolHandler] = None

        # v2.0 Core Architecture Components
        self._state_machine: Optional[StateMachine] = None
        self._global_controller: Optional[GlobalController] = None
        self._trigger_handler: Optional[TriggerHandler] = None
        self._action_resolver: Optional[ActionResolver] = None
        self._prompt_builder: Optional[PromptBuilder] = None
        self._response_parser: Optional[ResponseParser] = None
        self._transition_detector: Optional[StateTransitionDetector] = None

        # v2.0 Mode Engines
        self._dungeon_engine: Optional[DungeonEngine] = None
        self._settlement_engine: Optional[SettlementEngine] = None
        self._downtime_engine: Optional[DowntimeEngine] = None

        # v2.0 Tables
        self._dolmenwood_tables: Optional[DolmenwoodTables] = None

        # Current session state
        self._campaign_id: Optional[str] = None
        self._world_state: Optional[WorldState] = None
        self._world_state_v2: Optional[WorldStateV2] = None  # v2.0 extended state
        self._turn_number: int = 0
        self._session_start: Optional[datetime] = None

        logger.info("DolmenwoodGame v2.0 initialized")
    
    # =========================================================================
    # INITIALIZATION
    # =========================================================================
    
    def _init_state_manager(self) -> GameStateManager:
        """Initialize the game state manager."""
        if self._state_manager is None:
            self._state_manager = GameStateManager(self.config.database_path)
            logger.info(f"State manager initialized: {self.config.database_path}")
        return self._state_manager
    
    def _init_rules_retriever(self) -> Optional[RulesRetriever]:
        """Initialize the rules retriever (vector database)."""
        if not self.config.use_vector_db:
            logger.info("Vector database disabled")
            return None
        
        if self._rules_retriever is None:
            try:
                self._rules_retriever = create_retriever(
                    persist_directory=self.config.vector_db_path,
                    use_mock_embeddings=self.config.use_mock_embeddings,
                    use_local_embeddings=self.config.use_local_embeddings,
                    api_key=self.config.openai_api_key
                )
                logger.info(f"Rules retriever initialized: {self.config.vector_db_path}")
            except Exception as e:
                logger.warning(f"Failed to initialize rules retriever: {e}")
                return None
        
        return self._rules_retriever
    
    def _init_dm(self) -> DolmenwoodDM:
        """Initialize the AI DM agent."""
        if self._dm is None:
            # Create combat handler if available
            if COMBAT_ENGINE_AVAILABLE and self._combat_handler is None:
                self._combat_handler = create_combat_handler()
                logger.info("Combat handler initialized")

            # Create hex crawl handler if available
            if HEX_CRAWL_ENGINE_AVAILABLE and self._hex_crawl_handler is None:
                self._hex_crawl_handler = create_hex_crawl_handler()
                logger.info("Hex crawl handler initialized")

            # v2.0: Initialize state machine and transition detector before DM
            # This ensures they're available for the DM's state-aware processing
            self._init_state_machine()
            self._init_transition_detector()

            dm_config = DMConfig(
                provider=self.config.llm_provider,
                api_key=self.config.anthropic_api_key,
                model=self.config.llm_model,
                base_url=self.config.llm_base_url,
                dm_style=self.config.dm_style,
                rules_strictness=self.config.rules_strictness,
                campaign_name=self.config.campaign_name,
            )
            
            self._dm = DolmenwoodDM(
                config=dm_config,
                rules_retriever=self._rules_retriever,
                state_manager=self._state_manager,
                campaign_id=self._campaign_id,
                combat_handler=self._combat_handler,
                hex_crawl_handler=self._hex_crawl_handler,
                # v2.0: State machine integration
                state_machine=self._state_machine,
                transition_detector=self._transition_detector,
            )
            logger.info("DM agent initialized (v2.0 state-aware)")

        return self._dm

    # =========================================================================
    # v2.0 INITIALIZATION
    # =========================================================================

    def _init_state_machine(self) -> StateMachine:
        """Initialize the v2.0 state machine."""
        if self._state_machine is None:
            self._state_machine = StateMachine()
            logger.info("v2.0 State machine initialized")
        return self._state_machine

    def _init_global_controller(self) -> GlobalController:
        """Initialize the v2.0 global controller."""
        if self._global_controller is None:
            self._global_controller = GlobalController()
            logger.info("v2.0 Global controller initialized")
        return self._global_controller

    def _init_trigger_handler(self) -> TriggerHandler:
        """Initialize the v2.0 procedure trigger handler."""
        if self._trigger_handler is None:
            self._trigger_handler = TriggerHandler()
            logger.info("v2.0 Trigger handler initialized")
        return self._trigger_handler

    def _init_action_resolver(self) -> ActionResolver:
        """Initialize the v2.0 action resolver."""
        if self._action_resolver is None:
            self._action_resolver = ActionResolver()
            logger.info("v2.0 Action resolver initialized")
        return self._action_resolver

    def _init_prompt_builder(self) -> PromptBuilder:
        """Initialize the v2.0 prompt builder for LLM integration."""
        if self._prompt_builder is None:
            self._prompt_builder = create_prompt_builder()
            logger.info("v2.0 Prompt builder initialized")
        return self._prompt_builder

    def _init_response_parser(self) -> ResponseParser:
        """Initialize the v2.0 response parser for LLM integration."""
        if self._response_parser is None:
            self._response_parser = create_response_parser()
            logger.info("v2.0 Response parser initialized")
        return self._response_parser

    def _init_dolmenwood_tables(self) -> DolmenwoodTables:
        """Initialize Dolmenwood-specific random tables."""
        if self._dolmenwood_tables is None:
            self._dolmenwood_tables = DolmenwoodTables()
            logger.info("Dolmenwood tables initialized")
        return self._dolmenwood_tables

    def _init_dungeon_engine(self) -> Optional[DungeonEngine]:
        """Initialize the v2.0 dungeon exploration engine."""
        if DUNGEON_ENGINE_AVAILABLE and self._dungeon_engine is None:
            state_machine = self._init_state_machine()
            controller = self._init_global_controller()
            trigger_handler = self._init_trigger_handler()
            self._dungeon_engine = DungeonEngine(
                state_machine=state_machine,
                controller=controller,
                trigger_handler=trigger_handler
            )
            logger.info("v2.0 Dungeon engine initialized")
        return self._dungeon_engine

    def _init_settlement_engine(self) -> Optional[SettlementEngine]:
        """Initialize the v2.0 settlement exploration engine."""
        if SETTLEMENT_ENGINE_AVAILABLE and self._settlement_engine is None:
            state_machine = self._init_state_machine()
            controller = self._init_global_controller()
            self._settlement_engine = SettlementEngine(
                state_machine=state_machine,
                controller=controller
            )
            logger.info("v2.0 Settlement engine initialized")
        return self._settlement_engine

    def _init_downtime_engine(self) -> Optional[DowntimeEngine]:
        """Initialize the v2.0 downtime activities engine."""
        if DOWNTIME_ENGINE_AVAILABLE and self._downtime_engine is None:
            state_machine = self._init_state_machine()
            global_controller = self._init_global_controller()
            trigger_handler = self._init_trigger_handler()
            self._downtime_engine = DowntimeEngine(
                state_machine=state_machine,
                global_controller=global_controller,
                trigger_handler=trigger_handler
            )
            logger.info("v2.0 Downtime engine initialized")
        return self._downtime_engine

    def _init_transition_detector(self) -> StateTransitionDetector:
        """Initialize the v2.0 state transition detector."""
        if self._transition_detector is None:
            state_machine = self._init_state_machine()
            self._transition_detector = create_transition_detector(
                state_machine=state_machine,
                auto_execute=False  # We handle execution manually
            )
            logger.info("v2.0 Transition detector initialized")
        return self._transition_detector

    def _init_v2_components(self) -> None:
        """Initialize all v2.0 architecture components."""
        self._init_state_machine()
        self._init_global_controller()
        self._init_trigger_handler()
        self._init_action_resolver()
        self._init_prompt_builder()
        self._init_response_parser()
        self._init_dolmenwood_tables()
        self._init_transition_detector()

        # Initialize mode engines
        self._init_dungeon_engine()
        self._init_settlement_engine()
        self._init_downtime_engine()

        logger.info("All v2.0 components initialized")

    @property
    def is_combat_active(self) -> bool:
        """Check if combat is currently active."""
        if self._dm and self._dm.combat_handler:
            return self._dm.is_combat_active
        return False
    
    @property
    def hex_crawl_handler(self) -> Optional[HexCrawlToolHandler]:
        """Get the hex crawl handler."""
        return self._hex_crawl_handler

    # v2.0 Property Accessors
    @property
    def state_machine(self) -> Optional[StateMachine]:
        """Get the v2.0 state machine."""
        return self._state_machine

    @property
    def current_game_state(self) -> Optional[GameState]:
        """Get the current game state from the state machine."""
        if self._state_machine:
            return self._state_machine.current_state
        return None

    @property
    def global_controller(self) -> Optional[GlobalController]:
        """Get the v2.0 global controller."""
        return self._global_controller

    @property
    def trigger_handler(self) -> Optional[TriggerHandler]:
        """Get the v2.0 trigger handler."""
        return self._trigger_handler

    @property
    def action_resolver(self) -> Optional[ActionResolver]:
        """Get the v2.0 action resolver."""
        return self._action_resolver

    @property
    def dolmenwood_tables(self) -> Optional[DolmenwoodTables]:
        """Get the Dolmenwood random tables."""
        return self._dolmenwood_tables

    @property
    def dungeon_engine(self) -> Optional[DungeonEngine]:
        """Get the v2.0 dungeon engine."""
        return self._dungeon_engine

    @property
    def settlement_engine(self) -> Optional[SettlementEngine]:
        """Get the v2.0 settlement engine."""
        return self._settlement_engine

    @property
    def downtime_engine(self) -> Optional[DowntimeEngine]:
        """Get the v2.0 downtime engine."""
        return self._downtime_engine

    @property
    def transition_detector(self) -> Optional[StateTransitionDetector]:
        """Get the v2.0 state transition detector."""
        return self._transition_detector

    def initialize(self) -> None:
        """Initialize all components including v2.0 architecture."""
        self._init_state_manager()
        self._init_rules_retriever()
        self._init_dm()
        self._init_v2_components()
        logger.info("All game components initialized (v2.0)")
    
    # =========================================================================
    # CAMPAIGN MANAGEMENT
    # =========================================================================
    
    def start_new_campaign(
        self,
        campaign_name: str,
        starting_location: str = "Prigwort",
        starting_hex: str = "0808",
        season: Season = Season.AUTUMN
    ) -> str:
        """
        Start a new campaign.
        
        Args:
            campaign_name: Name of the campaign.
            starting_location: Starting location name.
            starting_hex: Starting hex ID.
            season: Starting season.
            
        Returns:
            Campaign ID.
        """
        self.initialize()
        
        # Create world state
        self._world_state = WorldState(
            campaign_name=campaign_name,
            current_date="1st of Woldsmoon, 1412",
            current_hex=starting_hex,
            current_location_name=starting_location,
            current_location_type=LocationType.SETTLEMENT,
            season=season,
            weather=Weather.CLEAR,
        )
        
        # Save to database
        state_manager = self._init_state_manager()
        self._campaign_id = state_manager.create_campaign(self._world_state)
        
        # Update DM with campaign context
        self._update_dm_context()
        
        self._session_start = datetime.now()
        self._turn_number = 0
        
        logger.info(f"New campaign started: {campaign_name} (ID: {self._campaign_id})")
        return self._campaign_id
    
    def load_campaign(self, campaign_id: str) -> bool:
        """
        Load an existing campaign.
        
        Args:
            campaign_id: ID of the campaign to load.
            
        Returns:
            True if successful, False otherwise.
        """
        self.initialize()
        
        state_manager = self._init_state_manager()
        world_state = state_manager.get_campaign(campaign_id)
        
        if world_state is None:
            logger.error(f"Campaign not found: {campaign_id}")
            return False
        
        self._campaign_id = campaign_id
        self._world_state = world_state
        self._session_start = datetime.now()
        
        # Get last turn number from history
        history = state_manager.get_history(campaign_id, limit=1)
        if history:
            self._turn_number = history[0].turn_number
        else:
            self._turn_number = 0
        
        self._update_dm_context()
        
        logger.info(f"Campaign loaded: {world_state.campaign_name}")
        return True
    
    def list_campaigns(self) -> list[dict[str, Any]]:
        """List all available campaigns."""
        state_manager = self._init_state_manager()
        campaigns = state_manager.list_campaigns()
        return [
            {
                "campaign_id": c.campaign_id,
                "name": c.campaign_name,
                "location": c.current_location_name,
                "date": c.current_date,
            }
            for c in campaigns
        ]
    
    def save_session(self, save_name: Optional[str] = None) -> str:
        """
        Save the current session.
        
        Args:
            save_name: Optional name for the save.
            
        Returns:
            Save ID.
        """
        if not self._campaign_id:
            raise RuntimeError("No active campaign to save")
        
        state_manager = self._init_state_manager()
        
        save_id = state_manager.create_save(
            campaign_id=self._campaign_id,
            save_name=save_name or f"Session Save - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        )
        
        logger.info(f"Session saved: {save_id}")
        return save_id
    
    def _update_dm_context(self) -> None:
        """Update the DM's game context."""
        if self._dm and self._world_state:
            state_manager = self._init_state_manager()
            characters = state_manager.list_characters(self._campaign_id) if self._campaign_id else []
            
            context = {
                "party": [c.name for c in characters],
                "location": self._world_state.current_location_name,
                "hex": self._world_state.current_hex,
                "time": self._world_state.current_date,
                "season": self._world_state.season.value if self._world_state.season else "autumn",
                "weather": self._world_state.weather.value if self._world_state.weather else "clear",
                "active_quests": [q.title if hasattr(q, 'title') else str(q) for q in self._world_state.active_quests],
                "combat_active": False,  # Combat state tracked separately
            }
            
            self._dm.set_game_context(context)
    
    # =========================================================================
    # CHARACTER MANAGEMENT
    # =========================================================================
    
    def create_character(
        self,
        name: str,
        player_name: str,
        kindred: Kindred,
        character_class: CharacterClass,
        level: int = 1,
        strength: int = 10,
        intelligence: int = 10,
        wisdom: int = 10,
        dexterity: int = 10,
        constitution: int = 10,
        charisma: int = 10,
    ) -> str:
        """
        Create a new character.
        
        Returns:
            Character ID.
        """
        if not self._campaign_id:
            raise RuntimeError("No active campaign")
        
        character = DolmenwoodCharacter(
            name=name,
            player_name=player_name,
            kindred=kindred,
            character_class=character_class,
            level=level,
            strength=strength,
            intelligence=intelligence,
            wisdom=wisdom,
            dexterity=dexterity,
            constitution=constitution,
            charisma=charisma,
            hp_max=DiceRoller.roll("1d8").total + (constitution - 10) // 2,
            hp_current=0,  # Will be set to max
            ac=10,
            xp_current=0,
            xp_next_level=2000,
        )
        character.hp_current = character.hp_max
        
        state_manager = self._init_state_manager()
        char_id = state_manager.create_character(character, self._campaign_id)
        
        # Add to party
        if char_id not in self._world_state.party_characters:
            self._world_state.party_characters.append(char_id)
            state_manager.update_campaign(self._world_state)
        
        self._update_dm_context()
        
        logger.info(f"Character created: {name} ({char_id})")
        return char_id
    
    def get_party(self) -> list[DolmenwoodCharacter]:
        """Get all characters in the current party."""
        if not self._campaign_id:
            return []
        
        state_manager = self._init_state_manager()
        return state_manager.list_characters(self._campaign_id)
    
    def roll_new_character_stats(self) -> dict[str, int]:
        """Roll ability scores for a new character (4d6 drop lowest)."""
        abilities = ["strength", "intelligence", "wisdom", "dexterity", "constitution", "charisma"]
        results = DiceRoller.roll_ability_scores()
        
        return {
            ability: result.total
            for ability, result in zip(abilities, results)
        }
    
    # =========================================================================
    # GAMEPLAY
    # =========================================================================
    
    def process_input(self, player_input: str) -> DMResponse:
        """
        Process player input and get DM response.
        
        Args:
            player_input: The player's action or statement.
            
        Returns:
            DMResponse with narrative and mechanical results.
        """
        if not self._campaign_id:
            raise RuntimeError("No active campaign")
        
        self._turn_number += 1
        
        # Get DM response
        dm = self._init_dm()
        response = dm.process_player_input(player_input)
        
        # Log to history
        state_manager = self._init_state_manager()
        history_entry = HistoryEntry(
            campaign_id=self._campaign_id,
            turn_number=self._turn_number,
            event_type="player_action",
            player_input=player_input,
            dm_response=response.narrative,
            state_changes=response.state_changes,
            dice_rolls=[str(r) for r in response.dice_rolls],
        )
        state_manager.log_history(history_entry, self._campaign_id)
        
        # Auto-save if enabled
        if self.config.auto_save and self._turn_number % 10 == 0:
            self.save_session(f"Auto-save Turn {self._turn_number}")
        
        return response
    
    def get_session_summary(self) -> str:
        """Get a summary of the current session."""
        if not self._campaign_id:
            return "No active campaign."
        
        state_manager = self._init_state_manager()
        party = state_manager.list_characters(self._campaign_id)
        
        summary = [
            f"Campaign: {self._world_state.campaign_name}",
            f"Location: {self._world_state.current_location_name} (Hex {self._world_state.current_hex})",
            f"Date: {self._world_state.current_date}",
            f"Season: {self._world_state.season.value if self._world_state.season else 'Unknown'}",
            f"Weather: {self._world_state.weather.value if self._world_state.weather else 'Unknown'}",
            f"Turn: {self._turn_number}",
            "",
            "Party:",
        ]
        
        for char in party:
            summary.append(f"  - {char.name} ({char.kindred.value} {char.character_class.value} {char.level}) HP: {char.hp_current}/{char.hp_max}")
        
        if self._world_state.active_quests:
            summary.append("")
            summary.append("Active Quests:")
            for quest in self._world_state.active_quests:
                summary.append(f"  - {quest}")
        
        return "\n".join(summary)
    
    # =========================================================================
    # PDF INGESTION
    # =========================================================================
    
    def ingest_pdf(
        self, 
        pdf_path: str, 
        source_id: str = "players_book",
        skip_indexing: bool = False
    ) -> dict[str, int]:
        """
        Ingest a PDF and index its contents.
        
        Args:
            pdf_path: Path to the PDF file.
            source_id: Identifier for the source (e.g., "players_book", "monster_book", 
                      "campaign_book", or a custom adventure ID).
            skip_indexing: Skip vector DB indexing (faster, SQLite only).
            
        Returns:
            Dict with counts of indexed items.
        """
        from pdf_processor.dolmenwood_parser import DolmenwoodPDFProcessor, BookType
        
        # Determine if this is a core book or adventure
        core_book_types = {bt.value for bt in BookType}
        
        # Create processor with the PDF path
        processor = DolmenwoodPDFProcessor(
            pdf_paths={source_id: pdf_path}
        )
        
        # Extract all content
        result = processor.extract_all()
        
        counts = {"parsed": {}}
        
        # Count parsed items
        if result.rules:
            counts["parsed"]["rules"] = len(result.rules)
        if result.monsters:
            counts["parsed"]["monsters"] = len(result.monsters)
        if result.hexes:
            counts["parsed"]["hexes"] = len(result.hexes)
        if result.spells:
            counts["parsed"]["spells"] = len(result.spells)
        if result.items:
            counts["parsed"]["items"] = len(result.items)
        if result.npcs:
            counts["parsed"]["npcs"] = len(result.npcs)
        if result.adventure_locations:
            counts["parsed"]["adventure_locations"] = len(result.adventure_locations)
        if result.adventure_modules:
            counts["parsed"]["adventure_modules"] = len(result.adventure_modules)
        
        # Report any errors
        if result.errors:
            counts["errors"] = result.errors
            for error in result.errors:
                logger.warning(f"Extraction error: {error}")
        
        # Index in vector database (unless skipped)
        if skip_indexing:
            logger.info("Skipping vector indexing (--skip-indexing flag)")
            counts["indexed"] = "skipped"
        else:
            rules_retriever = self._init_rules_retriever()
            if rules_retriever:
                try:
                    index_counts = rules_retriever.index_extraction_result(result)
                    counts["indexed"] = index_counts
                    logger.info(f"Vector DB indexed: {index_counts}")
                except Exception as e:
                    logger.error(f"Failed to index in vector database: {e}")
                    counts["index_error"] = str(e)
            else:
                logger.warning("Vector database not available - skipping indexing")
                counts["indexed"] = None
        
        # Import to state manager
        state_manager = self._init_state_manager()
        import_counts = state_manager.import_extraction_result(result)
        counts["imported"] = import_counts
        
        logger.info(f"PDF ingested: {pdf_path}, counts: {counts}")
        return counts
    
    def get_vector_db_stats(self) -> dict[str, int]:
        """Get statistics from the vector database."""
        if self._rules_retriever:
            return self._rules_retriever.get_collection_stats()
        return {}
    
    # =========================================================================
    # CONTENT LOADING (JSON Files)
    # =========================================================================
    
    def load_content(
        self,
        content_dir: str = "data/content",
        skip_indexing: bool = False
    ) -> dict[str, Any]:
        """
        Load game content from JSON files.
        
        This is the preferred method for loading curated content,
        as it avoids the unreliability of PDF extraction.
        
        Args:
            content_dir: Path to the content directory.
            skip_indexing: Skip vector DB indexing (faster).
            
        Returns:
            Dict with counts of loaded items.
        """
        if not CONTENT_LOADER_AVAILABLE:
            logger.error("Content loader not available")
            return {"error": "Content loader not available"}
        
        loader = ContentLoader(content_dir)
        
        # Initialize state manager
        state_manager = self._init_state_manager()
        
        # Initialize rules retriever (unless skipping indexing)
        rules_retriever = None
        if not skip_indexing:
            rules_retriever = self._init_rules_retriever()
        
        # Load and import
        result = loader.load_and_import(
            state_manager=state_manager,
            rules_retriever=rules_retriever,
            skip_indexing=skip_indexing
        )
        
        return {
            "monsters": result.monsters,
            "spells": result.spells,
            "items": result.items,
            "hexes": result.hexes,
            "npcs": result.npcs,
            "rules": result.rules,
            "total": result.total,
            "errors": result.errors
        }
    
    # =========================================================================
    # CLEANUP
    # =========================================================================
    
    def close(self) -> None:
        """Clean up resources."""
        if self._state_manager:
            self._state_manager.close()
            self._state_manager = None
        
        logger.info("Game resources cleaned up")


# =============================================================================
# CLI INTERFACE
# =============================================================================

class DolmenwoodCLI:
    """Command-line interface for the Dolmenwood AI DM."""
    
    COMMANDS = {
        "/help": "Show available commands",
        "/status": "Show current session status",
        "/combat": "Show combat status (if in combat)",
        "/party": "Show party members",
        "/roll": "Roll dice (e.g., /roll 2d6+3)",
        "/save": "Save the current session",
        "/quit": "Quit the game",
        "/new": "Start a new campaign",
        "/load": "Load an existing campaign",
        "/list": "List available campaigns",
        "/character": "Create a new character",
        # v2.0 Commands
        "/state": "Show current game state (v2.0)",
        "/time": "Show in-game time and date (v2.0)",
        "/tables": "Roll on Dolmenwood tables (v2.0)",
        "/reaction": "Roll reaction (e.g., /reaction +1)",
        "/morale": "Roll morale check (e.g., /morale -2)",
    }
    
    def __init__(self, game: Optional[DolmenwoodGame] = None):
        """Initialize the CLI."""
        self.game = game or DolmenwoodGame()
        self.running = False
    
    def print_banner(self) -> None:
        """Print the game banner."""
        banner = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║             🌲 DOLMENWOOD AI DUNGEON MASTER 🌲               ║
║                                                              ║
║     A fairy-tale forest adventure powered by Claude AI      ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
        """
        print(banner)
    
    def print_help(self) -> None:
        """Print available commands."""
        print("\n📜 Available Commands:")
        print("-" * 40)
        for cmd, desc in self.COMMANDS.items():
            print(f"  {cmd:<12} - {desc}")
        print("-" * 40)
        print("  Or simply type your action to play!")
        print()
    
    def handle_command(self, command: str) -> bool:
        """
        Handle a slash command.
        
        Returns:
            False if should quit, True otherwise.
        """
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        if cmd == "/help":
            self.print_help()
        
        elif cmd == "/status":
            print("\n" + self.game.get_session_summary())
        
        elif cmd == "/combat":
            if self.game.is_combat_active:
                if self.game._dm and self.game._dm.combat_handler:
                    status = self.game._dm.combat_handler.engine.get_status()
                    print("\n⚔️  COMBAT STATUS")
                    print("=" * 40)
                    print(status.full_status)
            else:
                print("\n  No combat active.")
        
        elif cmd == "/party":
            party = self.game.get_party()
            if party:
                print("\n🎭 Party Members:")
                for char in party:
                    print(f"  • {char.name} - {char.kindred.value} {char.character_class.value} Level {char.level}")
                    print(f"    HP: {char.hp_current}/{char.hp_max} | AC: {char.ac}")
            else:
                print("\n  No characters in party yet.")
        
        elif cmd == "/roll":
            if args:
                try:
                    result = DiceRoller.roll(args)
                    print(f"\n🎲 {result}")
                except ValueError as e:
                    print(f"\n❌ Invalid dice notation: {e}")
            else:
                print("\n  Usage: /roll 2d6+3")
        
        elif cmd == "/save":
            try:
                save_id = self.game.save_session(args if args else None)
                print(f"\n💾 Session saved! (ID: {save_id})")
            except Exception as e:
                print(f"\n❌ Save failed: {e}")
        
        elif cmd == "/quit":
            print("\n👋 Thanks for playing! May the Nag-Lord watch over your travels.")
            return False
        
        elif cmd == "/new":
            name = args if args else input("  Campaign name: ").strip()
            if name:
                self.game.start_new_campaign(name)
                print(f"\n🌲 New campaign '{name}' started!")
                print("  You find yourself in Prigwort, a small market town at the edge of Dolmenwood.")
        
        elif cmd == "/load":
            campaigns = self.game.list_campaigns()
            if not campaigns:
                print("\n  No saved campaigns found.")
            else:
                print("\n📚 Available Campaigns:")
                for i, c in enumerate(campaigns, 1):
                    print(f"  {i}. {c['name']} - {c['location']}")
                
                choice = input("  Enter number to load: ").strip()
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(campaigns):
                        if self.game.load_campaign(campaigns[idx]["campaign_id"]):
                            print(f"\n✅ Campaign '{campaigns[idx]['name']}' loaded!")
                        else:
                            print("\n❌ Failed to load campaign.")
                    else:
                        print("\n❌ Invalid selection.")
                except ValueError:
                    print("\n❌ Invalid input.")
        
        elif cmd == "/list":
            campaigns = self.game.list_campaigns()
            if campaigns:
                print("\n📚 Saved Campaigns:")
                for c in campaigns:
                    print(f"  • {c['name']} ({c['location']}) - {c['date']}")
            else:
                print("\n  No saved campaigns.")
        
        elif cmd == "/character":
            self._create_character_wizard()

        # v2.0 Commands
        elif cmd == "/state":
            self._show_game_state()

        elif cmd == "/time":
            self._show_game_time()

        elif cmd == "/tables":
            self._roll_tables(args)

        elif cmd == "/reaction":
            self._roll_reaction(args)

        elif cmd == "/morale":
            self._roll_morale(args)

        else:
            print(f"\n❓ Unknown command: {cmd}")
            print("  Type /help for available commands.")

        return True
    
    def _create_character_wizard(self) -> None:
        """Interactive character creation."""
        if not self.game._campaign_id:
            print("\n❌ Start or load a campaign first!")
            return
        
        print("\n🧙 Character Creation")
        print("-" * 30)
        
        name = input("  Name: ").strip()
        if not name:
            print("  ❌ Cancelled.")
            return
        
        player_name = input("  Player name: ").strip() or "Player"
        
        # Kindred selection
        print("\n  Available Kindreds:")
        kindreds = list(Kindred)
        for i, k in enumerate(kindreds, 1):
            print(f"    {i}. {k.value}")
        
        try:
            kindred_idx = int(input("  Choose kindred (number): ").strip()) - 1
            kindred = kindreds[kindred_idx]
        except (ValueError, IndexError):
            print("  ❌ Invalid selection, defaulting to Human.")
            kindred = Kindred.HUMAN
        
        # Class selection
        print("\n  Available Classes:")
        classes = list(CharacterClass)
        for i, c in enumerate(classes, 1):
            print(f"    {i}. {c.value}")
        
        try:
            class_idx = int(input("  Choose class (number): ").strip()) - 1
            char_class = classes[class_idx]
        except (ValueError, IndexError):
            print("  ❌ Invalid selection, defaulting to Fighter.")
            char_class = CharacterClass.FIGHTER
        
        # Roll stats
        print("\n  Rolling ability scores (4d6 drop lowest)...")
        stats = self.game.roll_new_character_stats()
        for ability, value in stats.items():
            print(f"    {ability.capitalize()}: {value}")
        
        # Create character
        char_id = self.game.create_character(
            name=name,
            player_name=player_name,
            kindred=kindred,
            character_class=char_class,
            **stats
        )
        
        print(f"\n✅ Character '{name}' created and added to party!")

    # =========================================================================
    # v2.0 CLI HELPER METHODS
    # =========================================================================

    def _show_game_state(self) -> None:
        """Show the current v2.0 game state."""
        if not self.game._campaign_id:
            print("\n  No active campaign.")
            return

        state = self.game.current_game_state
        if state:
            print(f"\n🎮 Current Game State: {state.value.upper()}")

            # Show state-specific info
            if state == GameState.WILDERNESS_TRAVEL:
                print("  Mode: Wilderness exploration (4-hour watches)")
            elif state == GameState.DUNGEON_EXPLORATION:
                print("  Mode: Dungeon crawl (10-minute turns)")
            elif state == GameState.COMBAT:
                print("  Mode: Active combat (combat rounds)")
            elif state == GameState.SETTLEMENT_EXPLORATION:
                print("  Mode: Town/settlement exploration")
            elif state == GameState.DOWNTIME:
                print("  Mode: Downtime activities")
            elif state == GameState.SOCIAL_INTERACTION:
                print("  Mode: Social/NPC interaction")
        else:
            print("\n  Game state not initialized.")

    def _show_game_time(self) -> None:
        """Show the current in-game time."""
        if not self.game._campaign_id:
            print("\n  No active campaign.")
            return

        gc = self.game.global_controller
        if gc:
            time = gc.get_current_time()
            print(f"\n⏰ In-Game Time")
            print("-" * 30)
            print(f"  Day: {time.day}, Month: {time.month}, Year: {time.year}")
            print(f"  Watch: {time.watch}/6 ({time.time_of_day.value})")
            print(f"  Dungeon Turns: {time.total_turns}")
            print(f"  Combat Rounds: {time.total_rounds}")
            if time.is_daylight:
                print(f"  Lighting: Daylight")
            else:
                print(f"  Lighting: Darkness (light source needed)")
        else:
            print("\n  Time tracker not initialized.")

    def _roll_tables(self, args: str) -> None:
        """Roll on Dolmenwood random tables."""
        tables = self.game.dolmenwood_tables
        if not tables:
            print("\n  Dolmenwood tables not initialized.")
            return

        if not args:
            print("\n📊 Available Tables:")
            print("  - encounter <region>  : Roll wilderness encounter")
            print("  - fairy              : Roll fairy manifestation")
            print("  - regions            : List available regions")
            return

        parts = args.split()
        table_type = parts[0].lower()

        if table_type == "regions":
            print("\n🌲 Dolmenwood Regions:")
            for region in DolmenwoodRegion:
                print(f"  - {region.value}")

        elif table_type == "encounter":
            region_name = parts[1] if len(parts) > 1 else "the_fog_moors"
            try:
                region = DolmenwoodRegion(region_name)
                encounter = tables.roll_encounter(region)
                print(f"\n⚔️  Encounter ({region.value}):")
                print(f"  {encounter}")
            except ValueError:
                print(f"\n❌ Unknown region: {region_name}")
                print("  Use '/tables regions' to see available regions.")

        elif table_type == "fairy":
            manifestation = tables.roll_fairy_manifestation()
            print(f"\n✨ Fairy Manifestation:")
            print(f"  {manifestation}")

        else:
            print(f"\n❌ Unknown table: {table_type}")

    def _roll_reaction(self, args: str) -> None:
        """Roll a reaction check."""
        modifier = 0
        if args:
            try:
                modifier = int(args.replace("+", ""))
            except ValueError:
                print("\n❌ Invalid modifier. Use format: /reaction +2 or /reaction -1")
                return

        tables = self.game.dolmenwood_tables
        if tables:
            result = tables.roll_reaction(modifier)
            print(f"\n🎭 Reaction Roll (2d6{modifier:+d}):")
            print(f"  {result}")
        else:
            # Fallback using DiceRoller
            roll = DiceRoller.roll("2d6")
            total = roll.total + modifier
            if total <= 2:
                reaction = "Hostile, attacks"
            elif total <= 5:
                reaction = "Unfriendly, may attack"
            elif total <= 8:
                reaction = "Neutral, uncertain"
            elif total <= 11:
                reaction = "Indifferent, uninterested"
            else:
                reaction = "Friendly, helpful"
            print(f"\n🎭 Reaction Roll: {roll.total}{modifier:+d} = {total}")
            print(f"  Result: {reaction}")

    def _roll_morale(self, args: str) -> None:
        """Roll a morale check."""
        modifier = 0
        if args:
            try:
                modifier = int(args.replace("+", ""))
            except ValueError:
                print("\n❌ Invalid modifier. Use format: /morale +2 or /morale -1")
                return

        tables = self.game.dolmenwood_tables
        if tables:
            result = tables.roll_morale(modifier)
            print(f"\n💀 Morale Check (2d6{modifier:+d}):")
            print(f"  {result}")
        else:
            # Fallback using DiceRoller
            roll = DiceRoller.roll("2d6")
            total = roll.total + modifier
            if total <= 2:
                morale = "Flee in panic!"
            elif total <= 5:
                morale = "Fighting retreat"
            elif total <= 8:
                morale = "Hold, but shaken"
            else:
                morale = "Stand firm"
            print(f"\n💀 Morale Check: {roll.total}{modifier:+d} = {total}")
            print(f"  Result: {morale}")

    def run(self) -> None:
        """Run the main game loop."""
        self.print_banner()
        self.print_help()
        
        # Check for API key
        if not self.game.config.anthropic_api_key:
            print("⚠️  Warning: ANTHROPIC_API_KEY not set. AI responses will not work.")
            print("   Set the environment variable or responses will fail.\n")
        
        self.running = True
        
        while self.running:
            try:
                user_input = input("\n🎮 > ").strip()
                
                if not user_input:
                    continue
                
                if user_input.startswith("/"):
                    if not self.handle_command(user_input):
                        self.running = False
                else:
                    # Process as game input
                    if not self.game._campaign_id:
                        print("\n⚠️  No active campaign. Use /new or /load first.")
                        continue
                    
                    print("\n🎲 Processing...")
                    try:
                        response = self.game.process_input(user_input)
                        
                        # Show dice rolls if any
                        if response.dice_rolls:
                            print("\n📊 Dice Rolls:")
                            for roll in response.dice_rolls:
                                print(f"   {roll}")
                        
                        # Show narrative
                        print(f"\n📖 {response.narrative}")
                        
                    except Exception as e:
                        logger.error(f"Error processing input: {e}")
                        print(f"\n❌ Error: {e}")
                        print("   The DM seems confused. Try again or type /help.")
            
            except KeyboardInterrupt:
                print("\n\n👋 Interrupted. Use /quit to exit properly.")
            
            except EOFError:
                print("\n👋 Goodbye!")
                self.running = False
        
        self.game.close()


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(
        description="Dolmenwood AI Dungeon Master - A fairy-tale forest adventure"
    )
    
    parser.add_argument(
        "--data-dir",
        default="./data",
        help="Directory for game data (default: ./data)"
    )
    
    parser.add_argument(
        "--dm-style",
        choices=["evocative", "terse", "verbose"],
        default="evocative",
        help="DM narrative style (default: evocative)"
    )
    
    parser.add_argument(
        "--no-vector-db",
        action="store_true",
        help="Disable vector database for rules lookup"
    )
    
    parser.add_argument(
        "--mock-embeddings",
        action="store_true",
        help="Use mock embeddings (no API calls, poor quality)"
    )
    
    parser.add_argument(
        "--local-embeddings",
        action="store_true",
        help="Use local sentence-transformers embeddings (no API calls, good quality, ~1-2GB RAM)"
    )
    
    parser.add_argument(
        "--ingest-pdf",
        metavar="PATH",
        help="Ingest a PDF before starting the game"
    )
    
    parser.add_argument(
        "--load-content",
        action="store_true",
        help="Load content from data/content/ JSON files"
    )
    
    parser.add_argument(
        "--content-dir",
        metavar="PATH",
        default="data/content",
        help="Content directory for --load-content (default: data/content)"
    )
    
    parser.add_argument(
        "--skip-indexing",
        action="store_true",
        help="Skip vector DB indexing during content loading (saves to SQLite only, faster)"
    )
    
    parser.add_argument(
        "--campaign",
        metavar="ID",
        help="Load a specific campaign by ID"
    )
    
    # LLM Provider options
    parser.add_argument(
        "--llm-provider",
        choices=["claude", "ollama", "openai"],
        default="claude",
        help="LLM provider to use (default: claude)"
    )
    
    parser.add_argument(
        "--llm-model",
        metavar="MODEL",
        help="Model name (default: provider-specific)"
    )
    
    parser.add_argument(
        "--llm-url",
        metavar="URL",
        help="Base URL for Ollama or OpenAI-compatible server"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create configuration
    config = GameConfig(
        data_dir=args.data_dir,
        database_path=f"{args.data_dir}/game_state.db",
        vector_db_path=f"{args.data_dir}/vectordb",
        dm_style=args.dm_style,
        use_vector_db=not args.no_vector_db,
        use_mock_embeddings=args.mock_embeddings,
        use_local_embeddings=args.local_embeddings,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
        llm_base_url=args.llm_url,
    )
    
    # Show LLM provider info
    if args.llm_provider != "claude":
        print(f"🤖 Using LLM provider: {args.llm_provider}")
        if args.llm_model:
            print(f"   Model: {args.llm_model}")
        if args.llm_url:
            print(f"   URL: {args.llm_url}")
        print()
    
    # Warn about local embeddings resource usage
    if args.local_embeddings and args.ingest_pdf:
        print("⚠️  Local embeddings requires:")
        print("   - ~1-2GB RAM for the model")
        print("   - Several minutes for large PDFs (CPU-bound)")
        print("   - Consider --mock-embeddings for faster testing")
        print()
    
    # Create game
    game = DolmenwoodGame(config)
    
    # Ingest PDF if specified
    if args.ingest_pdf:
        print(f"📄 Ingesting PDF: {args.ingest_pdf}")
        if args.skip_indexing:
            print("   (Skipping vector indexing - SQLite only)")
        game.initialize()
        counts = game.ingest_pdf(args.ingest_pdf, skip_indexing=args.skip_indexing)
        print(f"   Results: {counts}")
    
    # Load content from JSON files if specified
    if args.load_content:
        print(f"📂 Loading content from: {args.content_dir}")
        if args.skip_indexing:
            print("   (Skipping vector indexing - SQLite only)")
        game.initialize()
        counts = game.load_content(
            content_dir=args.content_dir,
            skip_indexing=args.skip_indexing
        )
        if counts.get("error"):
            print(f"   ❌ Error: {counts['error']}")
        else:
            print(f"   ✅ Loaded {counts['total']} items:")
            for key in ["monsters", "spells", "items", "hexes", "npcs", "rules"]:
                if counts.get(key, 0) > 0:
                    print(f"      - {counts[key]} {key}")
            if counts.get("errors"):
                print(f"   ⚠️  {len(counts['errors'])} errors occurred")
    
    # Load campaign if specified
    if args.campaign:
        game.initialize()
        if not game.load_campaign(args.campaign):
            print(f"❌ Failed to load campaign: {args.campaign}")
            sys.exit(1)
    
    # Run CLI
    cli = DolmenwoodCLI(game)
    cli.run()


if __name__ == "__main__":
    main()
