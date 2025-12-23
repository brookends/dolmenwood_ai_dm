"""
Dolmenwood AI DM - Dolmenwood Random Tables (v2.0)

This module contains all the random tables specific to the Dolmenwood setting.
All randomization MUST go through these tables to ensure consistency.

Tables include:
- Wilderness encounters (by terrain, region, season, time of day)
- Reaction tables with modifiers
- Hex features and landmarks
- Fairy influence signs
- Drune signs
- Seasonal oddities
- Morale modifiers
- Weather tables
- Rumors and hooks

Author: AI Dungeon Master Project
Version: 2.0
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class DolmenwoodRegion(str, Enum):
    """Regions of Dolmenwood with distinct encounter tables."""
    ALDWEALD = "aldweald"          # Ancient forest, fairy-touched
    MULCHGROVE = "mulchgrove"      # Decaying, fungal, undead
    HAGS_TEETH = "hags_teeth"      # Rocky, hilly, giant territory
    BRACKENWOLD = "brackenwold"    # Central, civilized
    NAGWOOD = "nagwood"            # Dark, drune influence
    LAKE_NYMPH = "lake_nymph"      # Waterways, nixies
    DOLMENWOOD_GENERAL = "dolmenwood_general"  # Generic table


class EncounterActivity(str, Enum):
    """What the encountered creatures are doing."""
    TRAVELING = "traveling"
    HUNTING = "hunting"
    GUARDING = "guarding"
    RESTING = "resting"
    PERFORMING_RITUAL = "performing_ritual"
    FORAGING = "foraging"
    FLEEING = "fleeing"
    PURSUING = "pursuing"


class FairyCourtAlignment(str, Enum):
    """Alignment with the fairy courts."""
    SUMMER_COURT = "summer_court"   # Cold Lodge
    WINTER_COURT = "winter_court"   # Nagwood/Drune allied
    NEUTRAL = "neutral"             # Unaligned fey
    MORTAL = "mortal"               # Non-fey creatures


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class EncounterEntry:
    """
    An entry in an encounter table.
    """
    name: str
    number_appearing: str  # Dice notation like "1d6" or "2d4+2"
    activity: EncounterActivity = EncounterActivity.TRAVELING
    court_alignment: FairyCourtAlignment = FairyCourtAlignment.MORTAL
    special_notes: str = ""
    lair_chance: int = 0  # Percentage chance of being in lair

    def roll_number_appearing(self) -> int:
        """Roll for number appearing."""
        return _roll_dice_notation(self.number_appearing)


@dataclass
class ReactionEntry:
    """
    An entry in the reaction table.
    """
    roll_range: tuple[int, int]  # (min, max) inclusive
    result: str
    combat_likely: bool
    can_negotiate: bool
    description: str


@dataclass
class TableResult:
    """
    Result from rolling on a random table.
    """
    table_name: str
    roll: int
    modified_roll: int
    result: Any
    modifiers_applied: dict[str, int] = field(default_factory=dict)
    description: str = ""

    @property
    def brief(self) -> str:
        """Get brief description."""
        return self.description or f"{self.table_name}: {self.result}"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _roll_dice_notation(notation: str) -> int:
    """Parse and roll dice notation like '2d6+3'."""
    import re

    notation = notation.strip().lower()

    # Handle simple number
    if notation.isdigit():
        return int(notation)

    # Parse XdY+Z format
    match = re.match(r"(\d*)d(\d+)([+-]\d+)?", notation)
    if not match:
        return 1

    count = int(match.group(1) or 1)
    sides = int(match.group(2))
    modifier = int(match.group(3) or 0)

    total = sum(random.randint(1, sides) for _ in range(count))
    return max(1, total + modifier)


def _roll_on_weighted_table(
    table: list[tuple[int, int, Any]],
    roll: Optional[int] = None,
    dice_sides: int = 20
) -> tuple[int, Any]:
    """
    Roll on a weighted table.

    Table format: [(low, high, result), ...]

    Returns:
        Tuple of (roll, result)
    """
    if roll is None:
        roll = random.randint(1, dice_sides)

    for low, high, result in table:
        if low <= roll <= high:
            return roll, result

    # Default to last entry if no match
    return roll, table[-1][2] if table else None


# =============================================================================
# ENCOUNTER TABLES
# =============================================================================

class EncounterTables:
    """
    Dolmenwood encounter tables organized by region, terrain, and time.
    """

    # Generic forest encounters
    FOREST_ENCOUNTERS = [
        (1, 1, EncounterEntry("Giant Spider", "1d3", EncounterActivity.HUNTING)),
        (2, 2, EncounterEntry("Wolf Pack", "2d4", EncounterActivity.HUNTING)),
        (3, 3, EncounterEntry("Wild Boar", "1d4", EncounterActivity.FORAGING)),
        (4, 4, EncounterEntry("Deer Herd", "2d6", EncounterActivity.FORAGING)),
        (5, 5, EncounterEntry("Woodsman", "1d3", EncounterActivity.TRAVELING)),
        (6, 6, EncounterEntry("Moss Dwarf", "1d6", EncounterActivity.FORAGING, FairyCourtAlignment.NEUTRAL)),
        (7, 7, EncounterEntry("Goatman", "2d4", EncounterActivity.TRAVELING)),
        (8, 8, EncounterEntry("Bandit", "2d6", EncounterActivity.GUARDING, lair_chance=25)),
        (9, 9, EncounterEntry("Sprite", "2d6", EncounterActivity.TRAVELING, FairyCourtAlignment.SUMMER_COURT)),
        (10, 10, EncounterEntry("Grimalkin", "1d3", EncounterActivity.HUNTING, FairyCourtAlignment.NEUTRAL)),
        (11, 11, EncounterEntry("Treant", "1", EncounterActivity.GUARDING, FairyCourtAlignment.NEUTRAL)),
        (12, 12, EncounterEntry("Will-o'-Wisp", "1d3", EncounterActivity.HUNTING, FairyCourtAlignment.WINTER_COURT)),
        (13, 14, EncounterEntry("Woodgrue", "2d4", EncounterActivity.FORAGING, FairyCourtAlignment.NEUTRAL)),
        (15, 16, EncounterEntry("Merchant", "1d4+2", EncounterActivity.TRAVELING)),
        (17, 18, EncounterEntry("Pilgrim", "2d6", EncounterActivity.TRAVELING)),
        (19, 19, EncounterEntry("Drune Patrol", "1d6+2", EncounterActivity.GUARDING, FairyCourtAlignment.WINTER_COURT)),
        (20, 20, EncounterEntry("Unicorn", "1", EncounterActivity.TRAVELING, FairyCourtAlignment.SUMMER_COURT)),
    ]

    # Aldweald (fairy-touched forest)
    ALDWEALD_ENCOUNTERS = [
        (1, 2, EncounterEntry("Sprite", "3d6", EncounterActivity.TRAVELING, FairyCourtAlignment.SUMMER_COURT)),
        (3, 4, EncounterEntry("Elf Noble", "1d4", EncounterActivity.HUNTING, FairyCourtAlignment.SUMMER_COURT)),
        (5, 5, EncounterEntry("Talking Animal", "1", EncounterActivity.TRAVELING, FairyCourtAlignment.NEUTRAL)),
        (6, 6, EncounterEntry("Dryad", "1", EncounterActivity.GUARDING, FairyCourtAlignment.NEUTRAL)),
        (7, 8, EncounterEntry("Pixie", "3d6", EncounterActivity.TRAVELING, FairyCourtAlignment.SUMMER_COURT)),
        (9, 9, EncounterEntry("Green Knight", "1", EncounterActivity.TRAVELING, FairyCourtAlignment.SUMMER_COURT)),
        (10, 11, EncounterEntry("Breggle", "1d6", EncounterActivity.FORAGING, FairyCourtAlignment.NEUTRAL)),
        (12, 13, EncounterEntry("Moss Dwarf", "2d4", EncounterActivity.FORAGING, FairyCourtAlignment.NEUTRAL)),
        (14, 14, EncounterEntry("Unicorn", "1", EncounterActivity.RESTING, FairyCourtAlignment.SUMMER_COURT)),
        (15, 16, EncounterEntry("Giant Moth", "1d3", EncounterActivity.RESTING)),
        (17, 17, EncounterEntry("Satyr", "1d4", EncounterActivity.RESTING, FairyCourtAlignment.NEUTRAL)),
        (18, 18, EncounterEntry("Treant", "1", EncounterActivity.GUARDING, FairyCourtAlignment.NEUTRAL)),
        (19, 19, EncounterEntry("Fairy Ring", "special", EncounterActivity.PERFORMING_RITUAL, FairyCourtAlignment.NEUTRAL)),
        (20, 20, EncounterEntry("Cold Prince/Princess", "1", EncounterActivity.HUNTING, FairyCourtAlignment.SUMMER_COURT)),
    ]

    # Mulchgrove (fungal decay)
    MULCHGROVE_ENCOUNTERS = [
        (1, 2, EncounterEntry("Fungal Zombie", "2d6", EncounterActivity.TRAVELING)),
        (3, 4, EncounterEntry("Giant Centipede", "1d6", EncounterActivity.HUNTING)),
        (5, 5, EncounterEntry("Corpse Flower", "1", EncounterActivity.HUNTING)),
        (6, 7, EncounterEntry("Will-o'-Wisp", "1d3", EncounterActivity.HUNTING, FairyCourtAlignment.WINTER_COURT)),
        (8, 9, EncounterEntry("Giant Slug", "1d3", EncounterActivity.FORAGING)),
        (10, 10, EncounterEntry("Swamp Hag", "1", EncounterActivity.PERFORMING_RITUAL, FairyCourtAlignment.WINTER_COURT)),
        (11, 12, EncounterEntry("Bog Mummy", "1d4", EncounterActivity.GUARDING)),
        (13, 13, EncounterEntry("Myconid", "2d6", EncounterActivity.FORAGING, FairyCourtAlignment.NEUTRAL)),
        (14, 15, EncounterEntry("Stirge", "2d6", EncounterActivity.HUNTING)),
        (16, 16, EncounterEntry("Wraith", "1", EncounterActivity.HUNTING)),
        (17, 18, EncounterEntry("Leech, Giant", "1d4", EncounterActivity.HUNTING)),
        (19, 19, EncounterEntry("Shambling Mound", "1", EncounterActivity.HUNTING)),
        (20, 20, EncounterEntry("Black Unicorn", "1", EncounterActivity.HUNTING, FairyCourtAlignment.WINTER_COURT)),
    ]

    # Nagwood (Drune territory)
    NAGWOOD_ENCOUNTERS = [
        (1, 3, EncounterEntry("Drune Cultist", "2d6", EncounterActivity.PERFORMING_RITUAL, FairyCourtAlignment.WINTER_COURT)),
        (4, 5, EncounterEntry("Drune Patrol", "1d6+2", EncounterActivity.GUARDING, FairyCourtAlignment.WINTER_COURT)),
        (6, 6, EncounterEntry("Drune Priest", "1d3", EncounterActivity.PERFORMING_RITUAL, FairyCourtAlignment.WINTER_COURT)),
        (7, 8, EncounterEntry("Wicked Tree", "1", EncounterActivity.GUARDING, FairyCourtAlignment.WINTER_COURT)),
        (9, 10, EncounterEntry("Wolf Pack", "2d6", EncounterActivity.HUNTING)),
        (11, 11, EncounterEntry("Werewolf", "1d3", EncounterActivity.HUNTING)),
        (12, 13, EncounterEntry("Ghost", "1", EncounterActivity.GUARDING)),
        (14, 14, EncounterEntry("Wight", "1d4", EncounterActivity.HUNTING)),
        (15, 15, EncounterEntry("Hellhound", "1d4", EncounterActivity.HUNTING, FairyCourtAlignment.WINTER_COURT)),
        (16, 17, EncounterEntry("Bat Swarm", "1", EncounterActivity.HUNTING)),
        (18, 18, EncounterEntry("Night Hag", "1", EncounterActivity.HUNTING, FairyCourtAlignment.WINTER_COURT)),
        (19, 19, EncounterEntry("Nag-Lord Servant", "1d3", EncounterActivity.TRAVELING, FairyCourtAlignment.WINTER_COURT)),
        (20, 20, EncounterEntry("Nag-Lord Manifestation", "1", EncounterActivity.PERFORMING_RITUAL, FairyCourtAlignment.WINTER_COURT)),
    ]

    @classmethod
    def get_regional_table(cls, region: DolmenwoodRegion) -> list:
        """Get the encounter table for a region."""
        tables = {
            DolmenwoodRegion.ALDWEALD: cls.ALDWEALD_ENCOUNTERS,
            DolmenwoodRegion.MULCHGROVE: cls.MULCHGROVE_ENCOUNTERS,
            DolmenwoodRegion.NAGWOOD: cls.NAGWOOD_ENCOUNTERS,
            DolmenwoodRegion.DOLMENWOOD_GENERAL: cls.FOREST_ENCOUNTERS,
        }
        return tables.get(region, cls.FOREST_ENCOUNTERS)


# =============================================================================
# REACTION TABLE
# =============================================================================

class ReactionTable:
    """
    OSE 2d6 reaction table with Dolmenwood modifiers.
    """

    REACTION_RESULTS = [
        ReactionEntry((2, 2), "hostile", True, False, "Immediate attack"),
        ReactionEntry((3, 5), "unfriendly", False, True, "Threatening, may attack"),
        ReactionEntry((6, 8), "neutral", False, True, "Uncertain, waiting"),
        ReactionEntry((9, 11), "indifferent", False, True, "Uninterested but not hostile"),
        ReactionEntry((12, 12), "friendly", False, True, "Helpful and willing to talk"),
    ]

    # Modifiers based on kindred/faction
    KINDRED_MODIFIERS = {
        # Elves get bonus with fairy-aligned
        "elf_fairy": +2,
        # Moss dwarves with forest folk
        "moss_dwarf_forest": +1,
        # Woodgrues with animals
        "woodgrue_animal": +2,
        # Grimalkin with cats
        "grimalkin_cat": +3,
        # Drune affiliation
        "drune_aligned": +2,
        "drune_opposed": -2,
        # Court alignments
        "same_court": +2,
        "opposing_court": -2,
    }

    # Situational modifiers
    SITUATION_MODIFIERS = {
        "armed_and_ready": -1,
        "outnumbered": -1,
        "bearing_gifts": +1,
        "speaking_language": +1,
        "prior_positive_contact": +2,
        "prior_negative_contact": -2,
        "trespassing": -1,
        "at_night": -1,
        "in_lair": -1,
    }

    @classmethod
    def roll_reaction(
        cls,
        cha_modifier: int = 0,
        modifiers: Optional[dict[str, int]] = None
    ) -> TableResult:
        """
        Roll on the reaction table.

        Args:
            cha_modifier: Charisma modifier of the speaking character.
            modifiers: Additional situational modifiers.

        Returns:
            TableResult with reaction outcome.
        """
        modifiers = modifiers or {}

        # Base roll
        roll = random.randint(1, 6) + random.randint(1, 6)

        # Calculate total modifier
        total_modifier = cha_modifier
        for mod_name, mod_value in modifiers.items():
            total_modifier += mod_value

        modified_roll = roll + total_modifier

        # Clamp to valid range
        clamped_roll = max(2, min(12, modified_roll))

        # Find result
        result = None
        for entry in cls.REACTION_RESULTS:
            if entry.roll_range[0] <= clamped_roll <= entry.roll_range[1]:
                result = entry
                break

        if result is None:
            result = cls.REACTION_RESULTS[2]  # Default to neutral

        return TableResult(
            table_name="reaction",
            roll=roll,
            modified_roll=modified_roll,
            result=result.result,
            modifiers_applied={"cha": cha_modifier, **modifiers},
            description=f"{result.description} (rolled {roll} + {total_modifier} = {modified_roll})"
        )


# =============================================================================
# MORALE TABLE
# =============================================================================

class MoraleTable:
    """
    OSE morale system with Dolmenwood modifiers.
    """

    # Base morale scores by creature type
    CREATURE_MORALE = {
        "mindless": 12,      # Undead, constructs
        "fanatical": 11,     # Drune cultists, zealots
        "elite": 10,         # Well-trained guards
        "trained": 9,        # Soldiers
        "normal": 7,         # Most creatures
        "cowardly": 5,       # Goblins, kobolds
        "animal": 6,         # Wild animals
    }

    # Morale modifiers
    MORALE_MODIFIERS = {
        # Positive
        "leader_present": +1,
        "defending_lair": +2,
        "winning_clearly": +1,
        "magical_compulsion": +3,
        "outnumber_enemies": +1,

        # Negative
        "leader_killed": -2,
        "half_casualties": -1,  # Built into OSE
        "first_blood": 0,       # Built into OSE
        "surprised": -1,
        "outnumbered": -1,
        "ambushed": -2,
        "facing_magic": -1,
    }

    @classmethod
    def check_morale(
        cls,
        morale_score: int,
        modifiers: Optional[dict[str, int]] = None
    ) -> TableResult:
        """
        Make a morale check.

        Args:
            morale_score: Base morale score.
            modifiers: Situational modifiers.

        Returns:
            TableResult with pass/fail.
        """
        modifiers = modifiers or {}

        # Calculate modified morale
        total_modifier = sum(modifiers.values())
        modified_morale = morale_score + total_modifier

        # Roll 2d6
        roll = random.randint(1, 6) + random.randint(1, 6)

        # Pass if roll <= morale
        passed = roll <= modified_morale

        return TableResult(
            table_name="morale",
            roll=roll,
            modified_roll=roll,  # Not modified
            result="pass" if passed else "fail",
            modifiers_applied=modifiers,
            description=f"Morale {'passed' if passed else 'failed'} ({roll} vs {modified_morale})"
        )


# =============================================================================
# FAIRY INFLUENCE SIGNS
# =============================================================================

class FairyInfluenceSigns:
    """
    Signs of fairy influence in Dolmenwood.
    """

    MINOR_SIGNS = [
        "Mushrooms growing in perfect circles",
        "Flowers blooming out of season",
        "Animals behaving strangely, watching travelers",
        "Faint music from no discernible source",
        "Paths that seem longer or shorter than expected",
        "Unusual mist that moves against the wind",
        "Trees with faces in their bark",
        "Unnaturally vibrant colors in foliage",
        "Strange echoes that repeat words incorrectly",
        "Footprints that lead nowhere",
    ]

    MODERATE_SIGNS = [
        "A fairy ring of standing stones",
        "Glamoured creatures pretending to be mundane",
        "Time moving strangely (hours feel like minutes)",
        "Food that tastes extraordinarily good but provides no sustenance",
        "Invisible servants completing small tasks",
        "Fey creatures openly watching from concealment",
        "Gifts appearing with no apparent giver",
        "Dreams that seem to predict the near future",
        "Speaking animals that deny having spoken",
        "Beautiful clearings that weren't there yesterday",
    ]

    MAJOR_SIGNS = [
        "Direct manifestation of a fairy noble",
        "Time dilation (days pass outside while hours inside)",
        "The boundary to Fairy becomes visible",
        "Mortal bargains being called due",
        "Wild Hunt horns echoing in the distance",
        "Fairy roads becoming accessible",
        "Major glamour affecting entire area",
        "Seasonal changes occurring in minutes",
        "The Cold Prince's attention upon the area",
        "Reality becoming fluid and malleable",
    ]

    @classmethod
    def roll_sign(cls, intensity: str = "minor") -> str:
        """
        Roll for a fairy influence sign.

        Args:
            intensity: "minor", "moderate", or "major"

        Returns:
            Description of the sign.
        """
        tables = {
            "minor": cls.MINOR_SIGNS,
            "moderate": cls.MODERATE_SIGNS,
            "major": cls.MAJOR_SIGNS,
        }
        table = tables.get(intensity, cls.MINOR_SIGNS)
        return random.choice(table)


# =============================================================================
# DRUNE SIGNS
# =============================================================================

class DruneSigns:
    """
    Signs of Drune activity in Dolmenwood.
    """

    WARNING_SIGNS = [
        "Carved runes on trees, glowing faintly",
        "Bones arranged in ritual patterns",
        "Stone dolmens humming with dark energy",
        "Dead animals posed in unnatural positions",
        "The smell of incense and blood",
        "Shadow creatures glimpsed at the edge of vision",
        "Unnatural cold despite the season",
        "Whispering voices speaking backwards",
        "Black candles left burning in hidden places",
        "Symbols drawn in blood on rocks",
    ]

    ACTIVE_SIGNS = [
        "Drune patrol markers (torn cloth, scratched symbols)",
        "Hidden observation posts",
        "Concealed pit traps or snares",
        "Drugged water sources",
        "Corrupted wildlife serving as sentries",
        "Recently used ritual sites",
        "Prisoners being transported",
        "Gathering of ingredients (herbs, blood, bones)",
        "Recruitment of desperate locals",
        "Construction of hidden shrines",
    ]

    RITUAL_SIGNS = [
        "Active sacrifice in progress",
        "Mass gathering of cultists",
        "Summoning of Nag-Lord servants",
        "Creation of undead",
        "Corruption of a fairy site",
        "Opening of a gateway to dark realms",
        "Transformation ritual",
        "Binding of a captured fairy",
        "Desecration of holy ground",
        "The Nag-Lord's attention drawn to the area",
    ]

    @classmethod
    def roll_sign(cls, intensity: str = "warning") -> str:
        """
        Roll for a Drune sign.

        Args:
            intensity: "warning", "active", or "ritual"

        Returns:
            Description of the sign.
        """
        tables = {
            "warning": cls.WARNING_SIGNS,
            "active": cls.ACTIVE_SIGNS,
            "ritual": cls.RITUAL_SIGNS,
        }
        table = tables.get(intensity, cls.WARNING_SIGNS)
        return random.choice(table)


# =============================================================================
# SEASONAL ODDITIES
# =============================================================================

class SeasonalOddities:
    """
    Strange occurrences by season in Dolmenwood.
    """

    SPRING_ODDITIES = [
        "New plants growing impossibly fast",
        "Animals giving birth to unusual offspring",
        "Ancient trees awakening and stretching",
        "Springs and streams changing course",
        "Buried things rising to the surface",
        "The forest seeming to breathe with new life",
        "Fairy mounds opening briefly",
        "Old magics renewing themselves",
    ]

    SUMMER_ODDITIES = [
        "The heat causing strange mirages",
        "Fairy revelries visible in the deepest woods",
        "Plants growing in bizarre formations",
        "Time seeming to slow in the deep shade",
        "Ancient standing stones humming with power",
        "Midsummer fires visible on distant hills",
        "The boundary to Fairy at its thinnest",
        "Speaking animals more common",
    ]

    AUTUMN_ODDITIES = [
        "The veil between worlds thinning",
        "Ghosts more visible and active",
        "The Wild Hunt beginning to ride",
        "Harvest spirits walking the fields",
        "Ancient bargains coming due",
        "Fairy roads becoming accessible",
        "Warnings from the dead in dreams",
        "The forest preparing for winter's sleep",
    ]

    WINTER_ODDITIES = [
        "The Nag-Lord's power at its height",
        "Drune activity increasing",
        "Cold things stirring in the darkness",
        "The Cold Prince's Hunt",
        "Frozen fairies trapped until spring",
        "Dark spirits freed by the long nights",
        "Ancient evils waking from slumber",
        "The barrier between life and death weakening",
    ]

    @classmethod
    def roll_oddity(cls, season: str) -> str:
        """
        Roll for a seasonal oddity.

        Args:
            season: "spring", "summer", "autumn", or "winter"

        Returns:
            Description of the oddity.
        """
        tables = {
            "spring": cls.SPRING_ODDITIES,
            "summer": cls.SUMMER_ODDITIES,
            "autumn": cls.AUTUMN_ODDITIES,
            "winter": cls.WINTER_ODDITIES,
        }
        table = tables.get(season, cls.AUTUMN_ODDITIES)
        return random.choice(table)


# =============================================================================
# HEX LANDMARKS
# =============================================================================

class HexLandmarks:
    """
    Random landmarks that can be found in hexes.
    """

    NATURAL_LANDMARKS = [
        "Ancient oak, gnarled and massive",
        "Crystal-clear spring",
        "Moss-covered boulder formation",
        "Deep ravine with a stream at the bottom",
        "Fallen tree forming a natural bridge",
        "Grove of silver birches",
        "Hollow tree large enough to shelter in",
        "Ring of standing stones",
        "Unusual rock outcropping",
        "Waterfall cascading into a pool",
    ]

    ARTIFICIAL_LANDMARKS = [
        "Crumbling stone tower",
        "Abandoned woodsman's hut",
        "Old stone bridge",
        "Ruined shrine to a forgotten god",
        "Carved waymarker",
        "Ancient burial mound",
        "Collapsed mine entrance",
        "Overgrown garden",
        "Dry well with strange carvings",
        "Stone circle used for unknown rituals",
    ]

    MYSTERIOUS_LANDMARKS = [
        "Tree with door-like markings",
        "Pool that reflects things strangely",
        "Cave entrance breathing cold air",
        "Statue of unknown origin",
        "Pit of uncertain depth",
        "Altar stained with old blood",
        "Tree growing around a skeleton",
        "Circle where nothing grows",
        "Mirror-like stone surface",
        "Archway leading nowhere visible",
    ]

    @classmethod
    def roll_landmark(cls, type_: str = "natural") -> str:
        """
        Roll for a landmark.

        Args:
            type_: "natural", "artificial", or "mysterious"

        Returns:
            Description of the landmark.
        """
        tables = {
            "natural": cls.NATURAL_LANDMARKS,
            "artificial": cls.ARTIFICIAL_LANDMARKS,
            "mysterious": cls.MYSTERIOUS_LANDMARKS,
        }
        table = tables.get(type_, cls.NATURAL_LANDMARKS)
        return random.choice(table)


# =============================================================================
# MASTER TABLE INTERFACE
# =============================================================================

class DolmenwoodTables:
    """
    Master interface for all Dolmenwood random tables.

    All randomization should go through this class.
    """

    def __init__(self):
        self.encounter_tables = EncounterTables()
        self.reaction_table = ReactionTable()
        self.morale_table = MoraleTable()
        self.fairy_signs = FairyInfluenceSigns()
        self.drune_signs = DruneSigns()
        self.seasonal_oddities = SeasonalOddities()
        self.hex_landmarks = HexLandmarks()

    def roll_encounter(
        self,
        region: DolmenwoodRegion = DolmenwoodRegion.DOLMENWOOD_GENERAL,
        time_of_day: str = "day",
        season: str = "autumn"
    ) -> TableResult:
        """
        Roll for a random encounter.

        Args:
            region: Region of Dolmenwood.
            time_of_day: "day" or "night"
            season: Current season.

        Returns:
            TableResult with encounter entry.
        """
        table = EncounterTables.get_regional_table(region)

        # Roll d20
        roll = random.randint(1, 20)

        # Apply time of day modifier
        modifier = 0
        if time_of_day == "night":
            modifier += 2  # More dangerous at night

        modified_roll = min(20, roll + modifier)

        # Find entry
        for low, high, entry in table:
            if low <= modified_roll <= high:
                return TableResult(
                    table_name=f"encounter_{region.value}",
                    roll=roll,
                    modified_roll=modified_roll,
                    result=entry,
                    modifiers_applied={"time": modifier},
                    description=f"{entry.name} ({entry.number_appearing})"
                )

        # Default to last entry
        _, _, entry = table[-1]
        return TableResult(
            table_name=f"encounter_{region.value}",
            roll=roll,
            modified_roll=modified_roll,
            result=entry,
            description=f"{entry.name} ({entry.number_appearing})"
        )

    def roll_reaction(
        self,
        cha_modifier: int = 0,
        modifiers: Optional[dict[str, int]] = None
    ) -> TableResult:
        """Roll a reaction check."""
        return ReactionTable.roll_reaction(cha_modifier, modifiers)

    def roll_morale(
        self,
        morale_score: int,
        modifiers: Optional[dict[str, int]] = None
    ) -> TableResult:
        """Roll a morale check."""
        return MoraleTable.check_morale(morale_score, modifiers)

    def roll_fairy_sign(self, intensity: str = "minor") -> str:
        """Roll for a fairy influence sign."""
        return FairyInfluenceSigns.roll_sign(intensity)

    def roll_drune_sign(self, intensity: str = "warning") -> str:
        """Roll for a Drune activity sign."""
        return DruneSigns.roll_sign(intensity)

    def roll_seasonal_oddity(self, season: str) -> str:
        """Roll for a seasonal oddity."""
        return SeasonalOddities.roll_oddity(season)

    def roll_landmark(self, type_: str = "natural") -> str:
        """Roll for a hex landmark."""
        return HexLandmarks.roll_landmark(type_)


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_dolmenwood_tables() -> DolmenwoodTables:
    """Create a new DolmenwoodTables instance."""
    return DolmenwoodTables()


# Singleton instance for convenience
_default_tables: Optional[DolmenwoodTables] = None


def get_tables() -> DolmenwoodTables:
    """Get the default tables instance."""
    global _default_tables
    if _default_tables is None:
        _default_tables = DolmenwoodTables()
    return _default_tables
