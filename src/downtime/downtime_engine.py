"""
Dolmenwood AI DM - Downtime Engine (v2.0)

Implements the DOWNTIME game state with activities like:
- Natural healing over time
- Training (skills, weapons, languages, spells)
- Faction advancement and relationship building
- Research and rumor gathering
- Crafting and item creation
- Carousing and lifestyle expenses
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List, Any, Tuple
import random


class DowntimeActivity(str, Enum):
    """Types of downtime activities."""
    REST = "rest"
    TRAINING = "training"
    RESEARCH = "research"
    FACTION_WORK = "faction_work"
    CRAFTING = "crafting"
    CAROUSING = "carousing"
    WORKING = "working"
    RECRUITING = "recruiting"
    SPELL_RESEARCH = "spell_research"
    ITEM_CREATION = "item_creation"
    RECOVERY = "recovery"


class TrainingType(str, Enum):
    """Types of training available."""
    WEAPON_PROFICIENCY = "weapon_proficiency"
    SKILL = "skill"
    LANGUAGE = "language"
    TOOL_PROFICIENCY = "tool_proficiency"
    COMBAT_STYLE = "combat_style"
    LEVEL_UP = "level_up"


class FactionAction(str, Enum):
    """Actions that can advance faction standing."""
    COMPLETE_MISSION = "complete_mission"
    DONATION = "donation"
    ADVOCACY = "advocacy"
    INTELLIGENCE = "intelligence"
    SABOTAGE = "sabotage"
    RECRUITMENT = "recruitment"


class ResearchType(str, Enum):
    """Types of research activities."""
    LORE = "lore"
    LOCATION = "location"
    CREATURE = "creature"
    MAGIC_ITEM = "magic_item"
    SPELL = "spell"
    HISTORY = "history"
    FACTION_SECRETS = "faction_secrets"


class CraftingType(str, Enum):
    """Types of crafting projects."""
    MUNDANE_ITEM = "mundane_item"
    POTION = "potion"
    SCROLL = "scroll"
    MAGIC_ITEM = "magic_item"
    AMMUNITION = "ammunition"
    POISON = "poison"
    TOOL = "tool"


class CarousingResult(str, Enum):
    """Possible carousing outcomes."""
    NOTHING_SPECIAL = "nothing_special"
    MADE_FRIEND = "made_friend"
    MADE_ENEMY = "made_enemy"
    LEARNED_RUMOR = "learned_rumor"
    GAMBLING_WIN = "gambling_win"
    GAMBLING_LOSS = "gambling_loss"
    HANGOVER = "hangover"
    ROMANTIC_ENTANGLEMENT = "romantic_entanglement"
    JOINED_ORGANIZATION = "joined_organization"
    BLACKMAIL_MATERIAL = "blackmail_material"
    LOST_ITEM = "lost_item"
    GAINED_REPUTATION = "gained_reputation"
    LOST_REPUTATION = "lost_reputation"
    ARRESTED = "arrested"
    BRAWL = "brawl"


@dataclass
class TrainingProgress:
    """Tracks progress on a training project."""
    training_type: TrainingType
    target: str  # What is being trained (e.g., "sword", "elvish", "lockpicking")
    days_required: int
    days_completed: int = 0
    gold_cost: int = 0
    gold_paid: int = 0
    trainer_id: Optional[str] = None
    notes: str = ""

    @property
    def is_complete(self) -> bool:
        return self.days_completed >= self.days_required and self.gold_paid >= self.gold_cost

    @property
    def days_remaining(self) -> int:
        return max(0, self.days_required - self.days_completed)

    @property
    def gold_remaining(self) -> int:
        return max(0, self.gold_cost - self.gold_paid)


@dataclass
class ResearchProject:
    """Tracks progress on a research project."""
    research_type: ResearchType
    subject: str
    progress_points: int = 0
    points_required: int = 10
    sources_consulted: List[str] = field(default_factory=list)
    discoveries: List[str] = field(default_factory=list)
    gold_spent: int = 0

    @property
    def is_complete(self) -> bool:
        return self.progress_points >= self.points_required

    @property
    def progress_percentage(self) -> int:
        return min(100, int((self.progress_points / self.points_required) * 100))


@dataclass
class CraftingProject:
    """Tracks progress on a crafting project."""
    crafting_type: CraftingType
    item_name: str
    days_required: int
    days_worked: int = 0
    materials_cost: int = 0
    materials_acquired: bool = False
    special_components: List[str] = field(default_factory=list)
    components_acquired: List[str] = field(default_factory=list)
    quality_modifiers: int = 0

    @property
    def is_complete(self) -> bool:
        return (
            self.days_worked >= self.days_required
            and self.materials_acquired
            and set(self.special_components) <= set(self.components_acquired)
        )

    @property
    def days_remaining(self) -> int:
        return max(0, self.days_required - self.days_worked)


@dataclass
class FactionProgress:
    """Tracks faction relationship progress."""
    faction_id: str
    faction_name: str
    current_standing: int = 0  # -5 to +5 scale
    reputation_points: int = 0
    points_to_next_level: int = 10
    completed_missions: List[str] = field(default_factory=list)
    known_contacts: List[str] = field(default_factory=list)
    active_mission: Optional[str] = None

    @property
    def standing_description(self) -> str:
        if self.current_standing <= -4:
            return "Hostile"
        elif self.current_standing <= -2:
            return "Unfriendly"
        elif self.current_standing <= 0:
            return "Neutral"
        elif self.current_standing <= 2:
            return "Friendly"
        elif self.current_standing <= 4:
            return "Allied"
        else:
            return "Devoted"


@dataclass
class DowntimeDay:
    """Result of a single downtime day."""
    day_number: int
    activity: DowntimeActivity
    success: bool
    gold_spent: int = 0
    gold_earned: int = 0
    hp_recovered: int = 0
    xp_earned: int = 0
    events: List[str] = field(default_factory=list)
    items_gained: List[str] = field(default_factory=list)
    items_lost: List[str] = field(default_factory=list)
    relationships_changed: Dict[str, int] = field(default_factory=dict)
    notes: str = ""


@dataclass
class DowntimeSession:
    """Complete downtime session result."""
    character_id: str
    location: str
    start_day: int
    end_day: int
    days: List[DowntimeDay] = field(default_factory=list)
    training_progress: List[TrainingProgress] = field(default_factory=list)
    research_progress: List[ResearchProject] = field(default_factory=list)
    crafting_progress: List[CraftingProject] = field(default_factory=list)
    faction_progress: List[FactionProgress] = field(default_factory=list)
    total_gold_spent: int = 0
    total_gold_earned: int = 0
    total_hp_recovered: int = 0
    total_xp_earned: int = 0
    rumors_learned: List[str] = field(default_factory=list)
    contacts_made: List[str] = field(default_factory=list)
    complications: List[str] = field(default_factory=list)


class DowntimeEngine:
    """
    Engine for managing downtime activities in Dolmenwood.

    Handles the structured downtime loop where characters can:
    - Rest and recover HP naturally
    - Train new skills or improve existing ones
    - Research lore, locations, or magical secrets
    - Advance faction relationships
    - Craft items
    - Carouse and make contacts

    Integration Points:
    - StateMachine: Operates in DOWNTIME state
    - GlobalController: Advances time, tracks resources
    - TriggerHandler: Fires DOWNTIME_DAY triggers
    - ActionResolver: Resolves training/research checks
    """

    # Healing rates
    NATURAL_HEALING_PER_DAY = 1  # HP recovered per day of rest
    BED_REST_HEALING_PER_DAY = 2  # HP recovered with complete bed rest

    # Training costs (per week)
    TRAINING_COSTS = {
        TrainingType.WEAPON_PROFICIENCY: {"gold": 50, "weeks": 4},
        TrainingType.SKILL: {"gold": 25, "weeks": 2},
        TrainingType.LANGUAGE: {"gold": 50, "weeks": 8},
        TrainingType.TOOL_PROFICIENCY: {"gold": 25, "weeks": 2},
        TrainingType.COMBAT_STYLE: {"gold": 100, "weeks": 6},
        TrainingType.LEVEL_UP: {"gold": 0, "weeks": 1},  # Cost varies by level
    }

    # Lifestyle expenses per day
    LIFESTYLE_COSTS = {
        "wretched": 0,
        "squalid": 1,  # 1 sp
        "poor": 2,     # 2 sp
        "modest": 10,  # 1 gp
        "comfortable": 20,  # 2 gp
        "wealthy": 40,  # 4 gp
        "aristocratic": 100,  # 10 gp minimum
    }

    # Carousing costs and XP
    CAROUSING_LEVELS = {
        "cheap": {"cost": 10, "xp": 50, "mishap_chance": 1},
        "moderate": {"cost": 50, "xp": 150, "mishap_chance": 2},
        "expensive": {"cost": 200, "xp": 400, "mishap_chance": 3},
        "extravagant": {"cost": 1000, "xp": 1000, "mishap_chance": 4},
    }

    # Carousing mishap table (1d20)
    CAROUSING_MISHAPS = [
        (1, 1, CarousingResult.ARRESTED, "Arrested for disorderly conduct"),
        (2, 2, CarousingResult.BRAWL, "Got into a brawl, take 1d6 damage"),
        (3, 4, CarousingResult.GAMBLING_LOSS, "Lost heavily gambling, pay double"),
        (5, 6, CarousingResult.MADE_ENEMY, "Made an enemy of a local"),
        (7, 8, CarousingResult.LOST_ITEM, "Lost a minor item"),
        (9, 10, CarousingResult.HANGOVER, "Terrible hangover, -2 to all rolls tomorrow"),
        (11, 11, CarousingResult.ROMANTIC_ENTANGLEMENT, "Romantic entanglement with complications"),
        (12, 12, CarousingResult.JOINED_ORGANIZATION, "Somehow joined a secret society"),
        (13, 14, CarousingResult.LOST_REPUTATION, "Did something embarrassing, lost reputation"),
        (15, 16, CarousingResult.NOTHING_SPECIAL, "Nothing notable happened"),
        (17, 18, CarousingResult.LEARNED_RUMOR, "Learned an interesting rumor"),
        (19, 19, CarousingResult.MADE_FRIEND, "Made a useful friend"),
        (20, 20, CarousingResult.GAMBLING_WIN, "Won big gambling, earn extra gold"),
    ]

    def __init__(
        self,
        global_controller: Optional[Any] = None,
        state_machine: Optional[Any] = None,
        trigger_handler: Optional[Any] = None,
    ):
        """
        Initialize the downtime engine.

        Args:
            global_controller: Reference to GlobalController for resource/time tracking
            state_machine: Reference to StateMachine for state transitions
            trigger_handler: Reference to TriggerHandler for procedure triggers
        """
        self.global_controller = global_controller
        self.state_machine = state_machine
        self.trigger_handler = trigger_handler

        # Active projects by character
        self.active_training: Dict[str, List[TrainingProgress]] = {}
        self.active_research: Dict[str, List[ResearchProject]] = {}
        self.active_crafting: Dict[str, List[CraftingProject]] = {}
        self.faction_standings: Dict[str, Dict[str, FactionProgress]] = {}

        # Current session tracking
        self.current_session: Optional[DowntimeSession] = None

    def start_downtime(
        self,
        character_id: str,
        location: str,
        starting_day: int = 1,
    ) -> DowntimeSession:
        """
        Start a new downtime session for a character.

        Args:
            character_id: ID of the character taking downtime
            location: Where the downtime is being spent
            starting_day: The starting day number

        Returns:
            New DowntimeSession tracking the session
        """
        session = DowntimeSession(
            character_id=character_id,
            location=location,
            start_day=starting_day,
            end_day=starting_day,
        )
        self.current_session = session
        return session

    def spend_day(
        self,
        activity: DowntimeActivity,
        lifestyle: str = "modest",
        activity_params: Optional[Dict[str, Any]] = None,
    ) -> DowntimeDay:
        """
        Spend one day of downtime on an activity.

        Args:
            activity: The activity to perform
            lifestyle: Lifestyle level for the day
            activity_params: Additional parameters for the activity

        Returns:
            DowntimeDay with the results
        """
        if not self.current_session:
            raise ValueError("No active downtime session")

        params = activity_params or {}
        day_number = self.current_session.end_day

        # Calculate lifestyle cost
        lifestyle_cost = self.LIFESTYLE_COSTS.get(lifestyle, 10)

        # Dispatch to appropriate activity handler
        if activity == DowntimeActivity.REST:
            result = self._handle_rest(day_number, params)
        elif activity == DowntimeActivity.RECOVERY:
            result = self._handle_recovery(day_number, params)
        elif activity == DowntimeActivity.TRAINING:
            result = self._handle_training(day_number, params)
        elif activity == DowntimeActivity.RESEARCH:
            result = self._handle_research(day_number, params)
        elif activity == DowntimeActivity.FACTION_WORK:
            result = self._handle_faction_work(day_number, params)
        elif activity == DowntimeActivity.CRAFTING:
            result = self._handle_crafting(day_number, params)
        elif activity == DowntimeActivity.CAROUSING:
            result = self._handle_carousing(day_number, params)
        elif activity == DowntimeActivity.WORKING:
            result = self._handle_working(day_number, params)
        elif activity == DowntimeActivity.RECRUITING:
            result = self._handle_recruiting(day_number, params)
        elif activity == DowntimeActivity.SPELL_RESEARCH:
            result = self._handle_spell_research(day_number, params)
        elif activity == DowntimeActivity.ITEM_CREATION:
            result = self._handle_item_creation(day_number, params)
        else:
            result = DowntimeDay(
                day_number=day_number,
                activity=activity,
                success=True,
                notes="Day passed uneventfully",
            )

        # Add lifestyle cost
        result.gold_spent += lifestyle_cost

        # Update session
        self.current_session.days.append(result)
        self.current_session.end_day += 1
        self.current_session.total_gold_spent += result.gold_spent
        self.current_session.total_gold_earned += result.gold_earned
        self.current_session.total_hp_recovered += result.hp_recovered
        self.current_session.total_xp_earned += result.xp_earned

        # Fire downtime day trigger if handler available
        if self.trigger_handler:
            self.trigger_handler.fire_trigger("DOWNTIME_DAY", {
                "character_id": self.current_session.character_id,
                "day": day_number,
                "activity": activity.value,
                "result": result,
            })

        # Advance time in global controller
        if self.global_controller:
            self.global_controller.advance_day()

        return result

    def _handle_rest(self, day_number: int, params: Dict[str, Any]) -> DowntimeDay:
        """Handle a day of rest."""
        bed_rest = params.get("bed_rest", False)
        hp_recovery = self.BED_REST_HEALING_PER_DAY if bed_rest else self.NATURAL_HEALING_PER_DAY

        return DowntimeDay(
            day_number=day_number,
            activity=DowntimeActivity.REST,
            success=True,
            hp_recovered=hp_recovery,
            notes=f"Rested {'in bed' if bed_rest else 'lightly'}, recovered {hp_recovery} HP",
        )

    def _handle_recovery(self, day_number: int, params: Dict[str, Any]) -> DowntimeDay:
        """Handle recovery from conditions (disease, poison, level drain, etc.)."""
        condition = params.get("condition", "general")
        healer_available = params.get("healer", False)

        # Base recovery chance
        recovery_chance = 3  # 3-in-6
        if healer_available:
            recovery_chance = 5  # 5-in-6 with healer

        roll = random.randint(1, 6)
        success = roll <= recovery_chance

        return DowntimeDay(
            day_number=day_number,
            activity=DowntimeActivity.RECOVERY,
            success=success,
            hp_recovered=1 if success else 0,
            notes=f"{'Recovered from' if success else 'Still suffering from'} {condition}",
            events=[f"Recovery roll: {roll} vs {recovery_chance}-in-6"],
        )

    def _handle_training(self, day_number: int, params: Dict[str, Any]) -> DowntimeDay:
        """Handle a day of training."""
        training_type = TrainingType(params.get("type", "skill"))
        target = params.get("target", "general training")
        trainer_available = params.get("trainer", True)

        if not self.current_session:
            raise ValueError("No active session")

        char_id = self.current_session.character_id

        # Find or create training progress
        if char_id not in self.active_training:
            self.active_training[char_id] = []

        # Find existing training for this target
        training = None
        for t in self.active_training[char_id]:
            if t.target == target and t.training_type == training_type:
                training = t
                break

        # Create new training if not found
        if not training:
            costs = self.TRAINING_COSTS[training_type]
            training = TrainingProgress(
                training_type=training_type,
                target=target,
                days_required=costs["weeks"] * 7,
                gold_cost=costs["gold"],
            )
            self.active_training[char_id].append(training)

        # Progress training
        if trainer_available:
            training.days_completed += 1
            success = True
            notes = f"Training {target}: {training.days_completed}/{training.days_required} days"
        else:
            # Self-study is half as effective
            training.days_completed += 0.5
            success = True
            notes = f"Self-study {target}: {training.days_completed}/{training.days_required} days"

        events = []
        if training.is_complete:
            events.append(f"Completed training in {target}!")
            self.active_training[char_id].remove(training)
            self.current_session.training_progress.append(training)

        return DowntimeDay(
            day_number=day_number,
            activity=DowntimeActivity.TRAINING,
            success=success,
            notes=notes,
            events=events,
        )

    def _handle_research(self, day_number: int, params: Dict[str, Any]) -> DowntimeDay:
        """Handle a day of research."""
        research_type = ResearchType(params.get("type", "lore"))
        subject = params.get("subject", "general knowledge")
        library_access = params.get("library", False)
        gold_spent = params.get("gold_spent", 0)

        if not self.current_session:
            raise ValueError("No active session")

        char_id = self.current_session.character_id

        # Find or create research project
        if char_id not in self.active_research:
            self.active_research[char_id] = []

        project = None
        for r in self.active_research[char_id]:
            if r.subject == subject and r.research_type == research_type:
                project = r
                break

        if not project:
            project = ResearchProject(
                research_type=research_type,
                subject=subject,
            )
            self.active_research[char_id].append(project)

        # Calculate progress
        base_progress = 1
        if library_access:
            base_progress += 1
        if gold_spent >= 10:
            base_progress += 1  # Bribes, books, etc.

        # Roll for research success (1d6)
        roll = random.randint(1, 6)
        if roll >= 4:  # 4-6 succeeds
            project.progress_points += base_progress
            success = True
            notes = f"Research on {subject}: {project.progress_percentage}% complete"
        else:
            success = False
            notes = f"Research on {subject} yielded nothing today"

        project.gold_spent += gold_spent

        events = []
        discoveries = []
        if project.is_complete:
            events.append(f"Completed research on {subject}!")
            discoveries.append(f"Discovered information about {subject}")
            self.active_research[char_id].remove(project)
            self.current_session.research_progress.append(project)

        return DowntimeDay(
            day_number=day_number,
            activity=DowntimeActivity.RESEARCH,
            success=success,
            gold_spent=gold_spent,
            notes=notes,
            events=events,
            items_gained=discoveries,
        )

    def _handle_faction_work(self, day_number: int, params: Dict[str, Any]) -> DowntimeDay:
        """Handle a day of faction work."""
        faction_id = params.get("faction_id", "unknown")
        faction_name = params.get("faction_name", faction_id)
        action = FactionAction(params.get("action", "advocacy"))
        gold_spent = params.get("gold_spent", 0)

        if not self.current_session:
            raise ValueError("No active session")

        char_id = self.current_session.character_id

        # Find or create faction progress
        if char_id not in self.faction_standings:
            self.faction_standings[char_id] = {}

        if faction_id not in self.faction_standings[char_id]:
            self.faction_standings[char_id][faction_id] = FactionProgress(
                faction_id=faction_id,
                faction_name=faction_name,
            )

        progress = self.faction_standings[char_id][faction_id]

        # Calculate reputation gain based on action
        rep_gain = 0
        if action == FactionAction.COMPLETE_MISSION:
            rep_gain = 3
        elif action == FactionAction.DONATION:
            rep_gain = gold_spent // 100  # 1 rep per 100 gold
        elif action == FactionAction.ADVOCACY:
            rep_gain = 1
        elif action == FactionAction.INTELLIGENCE:
            rep_gain = 2
        elif action == FactionAction.SABOTAGE:
            rep_gain = 2  # But might anger other factions
        elif action == FactionAction.RECRUITMENT:
            rep_gain = 1

        # Roll for success
        roll = random.randint(1, 6)
        if roll >= 3:  # 3-6 succeeds
            progress.reputation_points += rep_gain
            success = True

            # Check for standing increase
            if progress.reputation_points >= progress.points_to_next_level:
                progress.current_standing += 1
                progress.reputation_points -= progress.points_to_next_level
                progress.points_to_next_level = 10 + (progress.current_standing * 5)
        else:
            success = False
            rep_gain = 0

        return DowntimeDay(
            day_number=day_number,
            activity=DowntimeActivity.FACTION_WORK,
            success=success,
            gold_spent=gold_spent,
            notes=f"Faction work for {faction_name}: {progress.standing_description} ({progress.reputation_points} rep)",
            relationships_changed={faction_id: rep_gain},
        )

    def _handle_crafting(self, day_number: int, params: Dict[str, Any]) -> DowntimeDay:
        """Handle a day of crafting."""
        crafting_type = CraftingType(params.get("type", "mundane_item"))
        item_name = params.get("item", "unknown item")
        gold_spent = params.get("gold_spent", 0)

        if not self.current_session:
            raise ValueError("No active session")

        char_id = self.current_session.character_id

        # Find or create crafting project
        if char_id not in self.active_crafting:
            self.active_crafting[char_id] = []

        project = None
        for c in self.active_crafting[char_id]:
            if c.item_name == item_name:
                project = c
                break

        if not project:
            # Determine crafting time based on type
            days_map = {
                CraftingType.MUNDANE_ITEM: 3,
                CraftingType.AMMUNITION: 1,
                CraftingType.POTION: 7,
                CraftingType.SCROLL: 7,
                CraftingType.POISON: 5,
                CraftingType.TOOL: 5,
                CraftingType.MAGIC_ITEM: 30,
            }
            project = CraftingProject(
                crafting_type=crafting_type,
                item_name=item_name,
                days_required=days_map.get(crafting_type, 7),
                materials_cost=gold_spent,
                materials_acquired=gold_spent > 0,
            )
            self.active_crafting[char_id].append(project)

        # Progress crafting
        if project.materials_acquired:
            project.days_worked += 1
            success = True
            notes = f"Crafting {item_name}: {project.days_worked}/{project.days_required} days"
        else:
            success = False
            notes = f"Need materials for {item_name}"

        events = []
        items_gained = []
        if project.is_complete:
            events.append(f"Completed crafting {item_name}!")
            items_gained.append(item_name)
            self.active_crafting[char_id].remove(project)
            self.current_session.crafting_progress.append(project)

        return DowntimeDay(
            day_number=day_number,
            activity=DowntimeActivity.CRAFTING,
            success=success,
            gold_spent=gold_spent,
            notes=notes,
            events=events,
            items_gained=items_gained,
        )

    def _handle_carousing(self, day_number: int, params: Dict[str, Any]) -> DowntimeDay:
        """Handle a night of carousing."""
        level = params.get("level", "moderate")

        carousing_info = self.CAROUSING_LEVELS.get(level, self.CAROUSING_LEVELS["moderate"])
        gold_cost = carousing_info["cost"]
        xp_earned = carousing_info["xp"]
        mishap_chance = carousing_info["mishap_chance"]

        events = []
        items_gained = []
        items_lost = []
        gold_earned = 0
        relationships = {}

        # Check for mishap
        mishap_roll = random.randint(1, 6)
        if mishap_roll <= mishap_chance:
            # Roll on mishap table
            mishap_d20 = random.randint(1, 20)
            for low, high, result_type, description in self.CAROUSING_MISHAPS:
                if low <= mishap_d20 <= high:
                    events.append(f"Carousing mishap: {description}")

                    if result_type == CarousingResult.GAMBLING_LOSS:
                        gold_cost *= 2
                    elif result_type == CarousingResult.GAMBLING_WIN:
                        gold_earned = gold_cost
                    elif result_type == CarousingResult.LEARNED_RUMOR:
                        items_gained.append("Rumor")
                        if self.current_session:
                            self.current_session.rumors_learned.append("A rumor learned while carousing")
                    elif result_type == CarousingResult.MADE_FRIEND:
                        if self.current_session:
                            self.current_session.contacts_made.append("Friend made while carousing")
                    elif result_type == CarousingResult.LOST_ITEM:
                        items_lost.append("Minor item")
                    elif result_type == CarousingResult.ARRESTED:
                        if self.current_session:
                            self.current_session.complications.append("Arrested for disorderly conduct")
                    break
        else:
            events.append("Enjoyed a night out without incident")

        return DowntimeDay(
            day_number=day_number,
            activity=DowntimeActivity.CAROUSING,
            success=True,
            gold_spent=gold_cost,
            gold_earned=gold_earned,
            xp_earned=xp_earned,
            events=events,
            items_gained=items_gained,
            items_lost=items_lost,
            relationships_changed=relationships,
            notes=f"Spent {gold_cost} gp carousing, earned {xp_earned} XP",
        )

    def _handle_working(self, day_number: int, params: Dict[str, Any]) -> DowntimeDay:
        """Handle a day of paid work."""
        profession = params.get("profession", "laborer")
        skill_level = params.get("skill_level", "unskilled")

        # Daily wages by skill level
        wages = {
            "unskilled": 1,  # 1 sp
            "skilled": 5,   # 5 sp
            "expert": 20,   # 2 gp
            "master": 50,   # 5 gp
        }

        daily_wage = wages.get(skill_level, 1)

        return DowntimeDay(
            day_number=day_number,
            activity=DowntimeActivity.WORKING,
            success=True,
            gold_earned=daily_wage,
            notes=f"Worked as {profession}, earned {daily_wage} sp",
        )

    def _handle_recruiting(self, day_number: int, params: Dict[str, Any]) -> DowntimeDay:
        """Handle recruiting hirelings."""
        hireling_type = params.get("type", "torchbearer")
        gold_spent = params.get("gold_spent", 10)

        # Recruitment check (2d6 + gold modifier)
        roll = random.randint(1, 6) + random.randint(1, 6)
        gold_modifier = gold_spent // 10
        modified_roll = roll + gold_modifier

        success = modified_roll >= 9

        events = []
        if success:
            events.append(f"Successfully recruited a {hireling_type}")
            if self.current_session:
                self.current_session.contacts_made.append(f"{hireling_type} (hireling)")
        else:
            events.append(f"Failed to find a suitable {hireling_type}")

        return DowntimeDay(
            day_number=day_number,
            activity=DowntimeActivity.RECRUITING,
            success=success,
            gold_spent=gold_spent,
            events=events,
            notes=f"Recruiting {hireling_type}: roll {roll}+{gold_modifier}={modified_roll} vs DC 9",
        )

    def _handle_spell_research(self, day_number: int, params: Dict[str, Any]) -> DowntimeDay:
        """Handle spell research."""
        spell_name = params.get("spell", "unknown spell")
        spell_level = params.get("level", 1)
        gold_spent = params.get("gold_spent", 100 * spell_level)

        # Spell research takes weeks: spell_level * 2 weeks
        days_required = spell_level * 14

        # Use research project system
        params_updated = {
            "type": "spell",
            "subject": spell_name,
            "library": True,
            "gold_spent": gold_spent,
        }

        result = self._handle_research(day_number, params_updated)
        result.activity = DowntimeActivity.SPELL_RESEARCH
        result.notes = f"Researching {spell_name} (level {spell_level})"

        return result

    def _handle_item_creation(self, day_number: int, params: Dict[str, Any]) -> DowntimeDay:
        """Handle magic item creation."""
        item_name = params.get("item", "unknown item")
        item_value = params.get("value", 1000)
        gold_spent = params.get("gold_spent", item_value // 2)

        # Magic item creation takes 1 day per 100 gp value
        days_required = max(7, item_value // 100)

        params_updated = {
            "type": "magic_item",
            "item": item_name,
            "gold_spent": gold_spent,
        }

        result = self._handle_crafting(day_number, params_updated)
        result.activity = DowntimeActivity.ITEM_CREATION
        result.notes = f"Creating magic item: {item_name}"

        return result

    def end_downtime(self) -> DowntimeSession:
        """
        End the current downtime session.

        Returns:
            The completed DowntimeSession with all results
        """
        if not self.current_session:
            raise ValueError("No active downtime session")

        session = self.current_session

        # Compile any active projects into session
        char_id = session.character_id
        if char_id in self.active_training:
            session.training_progress.extend(self.active_training[char_id])
        if char_id in self.active_research:
            session.research_progress.extend(self.active_research[char_id])
        if char_id in self.active_crafting:
            session.crafting_progress.extend(self.active_crafting[char_id])
        if char_id in self.faction_standings:
            session.faction_progress.extend(self.faction_standings[char_id].values())

        self.current_session = None
        return session

    def calculate_level_training_cost(self, current_level: int) -> Dict[str, int]:
        """
        Calculate the cost to train to the next level.

        Args:
            current_level: Character's current level

        Returns:
            Dict with gold cost and days required
        """
        # OSE standard: 1 week per current level, 100 gp per level
        return {
            "gold": current_level * 100,
            "days": current_level * 7,
        }

    def get_available_activities(
        self,
        location: str,
        character_class: Optional[str] = None,
    ) -> List[DowntimeActivity]:
        """
        Get activities available at a location.

        Args:
            location: The settlement or location name
            character_class: Optional character class for class-specific activities

        Returns:
            List of available DowntimeActivity types
        """
        # Base activities available everywhere
        activities = [
            DowntimeActivity.REST,
            DowntimeActivity.RECOVERY,
            DowntimeActivity.WORKING,
            DowntimeActivity.CAROUSING,
        ]

        # Most settlements have training
        activities.append(DowntimeActivity.TRAINING)

        # Larger settlements have more options
        if location in ["Castle Brackenwold", "Prigwort", "Lankshorn"]:
            activities.extend([
                DowntimeActivity.RESEARCH,
                DowntimeActivity.RECRUITING,
                DowntimeActivity.CRAFTING,
            ])

        # Magic-user specific
        if character_class in ["Magic-User", "Elf"]:
            activities.append(DowntimeActivity.SPELL_RESEARCH)
            activities.append(DowntimeActivity.ITEM_CREATION)

        # Faction work is always available if you know a faction
        activities.append(DowntimeActivity.FACTION_WORK)

        return list(set(activities))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize downtime engine state."""
        return {
            "active_training": {
                char_id: [
                    {
                        "training_type": t.training_type.value,
                        "target": t.target,
                        "days_required": t.days_required,
                        "days_completed": t.days_completed,
                        "gold_cost": t.gold_cost,
                        "gold_paid": t.gold_paid,
                        "trainer_id": t.trainer_id,
                        "notes": t.notes,
                    }
                    for t in trainings
                ]
                for char_id, trainings in self.active_training.items()
            },
            "active_research": {
                char_id: [
                    {
                        "research_type": r.research_type.value,
                        "subject": r.subject,
                        "progress_points": r.progress_points,
                        "points_required": r.points_required,
                        "sources_consulted": r.sources_consulted,
                        "discoveries": r.discoveries,
                        "gold_spent": r.gold_spent,
                    }
                    for r in projects
                ]
                for char_id, projects in self.active_research.items()
            },
            "faction_standings": {
                char_id: {
                    faction_id: {
                        "faction_id": f.faction_id,
                        "faction_name": f.faction_name,
                        "current_standing": f.current_standing,
                        "reputation_points": f.reputation_points,
                        "points_to_next_level": f.points_to_next_level,
                        "completed_missions": f.completed_missions,
                        "known_contacts": f.known_contacts,
                        "active_mission": f.active_mission,
                    }
                    for faction_id, f in factions.items()
                }
                for char_id, factions in self.faction_standings.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DowntimeEngine":
        """Deserialize downtime engine state."""
        engine = cls()

        # Restore training
        for char_id, trainings in data.get("active_training", {}).items():
            engine.active_training[char_id] = [
                TrainingProgress(
                    training_type=TrainingType(t["training_type"]),
                    target=t["target"],
                    days_required=t["days_required"],
                    days_completed=t["days_completed"],
                    gold_cost=t["gold_cost"],
                    gold_paid=t["gold_paid"],
                    trainer_id=t.get("trainer_id"),
                    notes=t.get("notes", ""),
                )
                for t in trainings
            ]

        # Restore research
        for char_id, projects in data.get("active_research", {}).items():
            engine.active_research[char_id] = [
                ResearchProject(
                    research_type=ResearchType(r["research_type"]),
                    subject=r["subject"],
                    progress_points=r["progress_points"],
                    points_required=r["points_required"],
                    sources_consulted=r.get("sources_consulted", []),
                    discoveries=r.get("discoveries", []),
                    gold_spent=r.get("gold_spent", 0),
                )
                for r in projects
            ]

        # Restore faction standings
        for char_id, factions in data.get("faction_standings", {}).items():
            engine.faction_standings[char_id] = {
                faction_id: FactionProgress(
                    faction_id=f["faction_id"],
                    faction_name=f["faction_name"],
                    current_standing=f["current_standing"],
                    reputation_points=f["reputation_points"],
                    points_to_next_level=f["points_to_next_level"],
                    completed_missions=f.get("completed_missions", []),
                    known_contacts=f.get("known_contacts", []),
                    active_mission=f.get("active_mission"),
                )
                for faction_id, f in factions.items()
            }

        return engine
