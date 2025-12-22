"""
LLM-Assisted Content Extractor for Dolmenwood AI DM.

Uses Claude to extract structured content from PDF pages, outputting JSON files
for human review and correction before final import.

Usage:
    # From command line:
    python -m content_loader.extractor --pdf monster_book.pdf --pages 10-20 --type monsters
    
    # From code:
    extractor = LLMExtractor(api_key="...")
    results = extractor.extract_monsters(pdf_path, pages=[10, 11, 12])
    extractor.save_results(results, "data/content/monsters/extracted.json")
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Literal

logger = logging.getLogger(__name__)

# Content type definitions with extraction prompts
EXTRACTION_PROMPTS = {
    "monsters": '''Extract all monster stat blocks from this text. For each monster, NPC, or other creature with a stat block, output a JSON object with these fields:

{
  "name": "Monster Name",
  "monster_id": "monster_name_lowercase",  // lowercase, underscores for spaces

  // Core Stats
  "armor_class": 17,  // AC as integer (Dolmenwood uses ascending AC)
  "hit_dice": "5d8",  // Hit Dice as string (e.g., "1d8", "2d8+1", "3d8*")
  "hp": 22,  // Average HP if given, otherwise null
  "level": 5,  // Monster level/HD number (extract from "Level X" if present)
  "movement": "60' Burrow 20'",  // Full movement description as string
  "speed": 60,  // Base speed in feet (extract first number from movement)
  "burrow_speed": 20,  // Burrow speed if listed, otherwise null
  "fly_speed": null,  // Fly speed if listed, otherwise null
  "swim_speed": null,  // Swim speed if listed, otherwise null

  // Combat
  "attacks": ["Bite (+4, 2d6)", "Tail (+4, 2d4)"],  // List of attack strings with bonuses
  "damage": ["2d6", "2d4"],  // List of damage dice (extract from attacks)

  // Saving Throws - CRITICAL: Extract individual save values
  "save_doom": 10,  // Save vs Doom (look for "D10" or "Doom 10")
  "save_ray": 11,   // Save vs Ray (look for "R11" or "Ray 11")
  "save_hold": 12,  // Save vs Hold (look for "H12" or "Hold 12")
  "save_blast": 13, // Save vs Blast (look for "B13" or "Blast 13")
  "save_spell": 14, // Save vs Spell (look for "S14" or "Spell 14")
  "saves_as": null, // Legacy format like "F2" (Fighter 2) - use if individual saves not listed

  "morale": 9,  // Morale score (2-12)

  // Treasure
  "treasure_type": null,  // Single letter treasure type if given
  "hoard": "C6 + R7 + M4",  // Hoard composition if given (Dolmenwood format)
  "possessions": "None",  // Individual possessions description

  // Monster Classification
  "size": "Large",  // Size category (Tiny, Small, Medium, Large, Huge, Gargantuan)
  "monster_type": "Dragon",  // Type (Dragon, Undead, Beast, Humanoid, Aberration, etc.)
  "sentience": "Sentient",  // Sentient, Semi-Sentient, or Non-Sentient
  "alignment": "Chaotic",  // Lawful, Neutral, or Chaotic
  "intelligence": null,  // Intelligence description if given

  // Abilities and Features
  "special_abilities": [
    "Surprise: When lying in wait beneath earth, opposing side has 4-in-6 chance of being surprised",
    "Sleeping in lair: 50% chance of being asleep if encountered in lair",
    "Immunities: Suffer half damage from mundane weapons. Immune to acid and poison.",
    "Dark sight: Can see normally without light",
    "Breath (thrice a day): Vomit caustic black bile in 10' wide, 30' long stream. Damage equal to current HP (Save vs Blast for half)",
    "Commanding growl (thrice a day): Single target must Save vs Spell or obey command for 1 Round"
  ],
  "immunities": ["acid", "poison", "mundane fire", "lightning", "cold"],
  "resistances": ["magical fire", "magical lightning", "magical cold"],  // Half damage
  "vulnerabilities": [],  // Weaknesses if listed

  // Roleplaying Information
  "description": "30' long, with lumpy flesh, brown-black scales, patches of fur or feathers, and leering, lupine faces. Burrow into the earth to surprise prey. Delight in killing for its own sake.",
  "behavior": "Savage, rapacious, destructive",  // Behavior trait from "Behaviour" field
  "speech": "Growling, broken sentences. Basic Woldish, Wyrm",  // Speech/Languages
  "traits": [
    "Reeks of sulphur",
    "Eyes of phosphorescent amber",
    "Plume of lustrous, black feathers around the neck",
    "Thorns along sides",
    "Salivates and froths at the mouth",
    "Scales covered with moss"
  ],  // Physical/descriptive traits (numbered list in source)

  // Encounter Information
  "number_appearing": "1",  // Number appearing (extract number before "in lair" percentage)
  "lair_percentage": 50,  // Percentage in lair (extract from "50% in lair")
  "encounter_scenarios": [
    "Coiled around a dead horse, in battle with a knight (Level 3)",
    "Lying in wait beneath a mound of freshly dug earth topped with the bloody corpse of an old woman",
    "Crashing through forest in blood rage, levelling small trees. Has ravaged woodland huts and hungers for more flesh",
    "Enraged and coiled around an 8' sphere of black energy containing a magician. Reeks of sulphur"
  ],  // Sample encounter scenarios (numbered "ENCOUNTERS" list)
  "lair_descriptions": [
    "Nest of a giant bird—possibly still containing unhatched egg—amid branches of mighty tree. Wyrm adept at climbing trunk",
    "Muddy hole burrowed out of side of a hill",
    "Nest of feathers and furs in deepest hole of natural cave network. Bones and ravaged remains strewn outside",
    "At base of natural canyon, overgrown with brambles. Collects blood of victims in basin at centre of treasure hoard"
  ],  // Sample lair descriptions (numbered "LAIRS" list)

  "xp_value": 460,  // XP value
  "habitat": []  // Habitat types if given (forest, swamp, etc.)
}

IMPORTANT EXTRACTION NOTES:
1. **Saving Throws**: Always extract individual save values (D, R, H, B, S format). Look for patterns like "Saves D10 R11 H12 B13 S14"
2. **Special Abilities**: Extract full ability descriptions including mechanics, usage limits, and save DCs
3. **Immunities/Resistances**: Parse from ability text (e.g., "Immune to acid" → add "acid" to immunities array)
4. **Traits**: Extract numbered descriptive traits list (usually 1-6 random traits)
5. **Encounters/Lairs**: Extract numbered scenario/lair description lists separately
6. **Movement**: Parse into base speed plus special movement types (burrow, fly, swim)
7. **Size/Type/Sentience**: Usually on same line (e.g., "Large Dragon—Sentient—Chaotic")

If a field is not present in the source, use null for single values or [] for arrays.
Output as a JSON array of monster objects.
Only extract actual monster stat blocks, not references or mentions.''',

    "spells": '''Extract all spells, knacks, glamours, runes, and magical abilities from this text.

MAGIC TYPES in Dolmenwood:
- "arcane" - Wizard/Magic-User spells learned from spellbooks
- "divine" - Cleric/Friar spells granted by faith
- "knack" - Mossling racial semi-magical crafts
- "fairy_glamour" - Elf, Grimalkin, and Woodgrue innate magical abilities  
- "rune" - Fairy Runic magic only available to Elf, Grimalkin, and Woodgrue

For STANDARD SPELLS (arcane/divine with spell levels 1-6), output:
{
  "name": "Spell Name",
  "spell_id": "spell_name_lowercase",
  "level": 1,
  "magic_type": "arcane",
  "duration": "1 turn",
  "range": "60'",
  "description": "Full spell description...",
  "reversible": false,
  "reversed_name": null
}

For NON-TIERED RACIAL ABILITIES (Fairy Glamours and Rune magic only), output:
{
  "name": "Spell Name",
  "spell_id": "spell_name_lowercase",
  "level": null, // Enter 'null' if magic_type == fairy_glamour; Enter 1, 2, or 3 for lesser, greater, or mighty rune
  "magic_type": "fairy_glamour",
  "duration": "1 turn",
  "range": "60'",
  "description": "Full spell description...",
  "reversible": false,
  "reversed_name": null,
  "kindred": ["Elf", "Grimalkin", "Woodgrue", "Special"]  // Race/kindred/class that has this ability (Elf, Grimalkin, and Woodgrue-only. Special included for unique story-related scenarios )
}


For TIERED RACIAL ABILITIES (knacks that grant powers at specific character levels), output:
{
  "name": "Ability Name",
  "spell_id": "type_name_lowercase",
  "level": null,
  "magic_type": "knack",  // or "fairy_glamour" or "rune"
  "duration": null,
  "range": null,
  "description": "Brief overall description of the ability",
  "reversible": false,
  "reversed_name": null,
  "kindred": "Mossling",  // Race/kindred/class that has this ability (Mossling-only)
  "abilities": [
    {"level": 1, "name": "Ability Name", "description": "What it does at character level 1"},
    {"level": 3, "name": "Ability Name", "description": "What it does at character level 3"},
    {"level": 5, "name": "Ability Name", "description": "What it does at character level 5"},
    {"level": 7, "name": "Ability Name", "description": "What it does at character level 7"}
  ]
}

Note: The "abilities" array should contain one entry for each character level that grants a new power.
The levels may vary (e.g., 1/3/5/7 for Mossling knacks, or different levels for other types).

Output as a JSON array.
Extract ALL magical abilities: standard spells, racial abilities, class features, etc.
Only extract actual definitions, not tables of contents or spell lists.''',

    "items": '''Extract all items/equipment/trinkets from this text. For each item, output a JSON object:

{
  "name": "Item Name",
  "item_id": "item_name_lowercase",
  "type": "weapon",  // weapon, armor, shield, ammunition, adventuring_gear, tool, container, food, clothing, mount, vehicle, service
  "cost_sp": 100,  // Cost in silver pieces (convert from gp: 1gp = 10sp)
  "weight_coins": 10,  // Weight in coins (10 coins = 1 pound) or null
  "damage": "1d8",  // For weapons, otherwise null
  "ac_bonus": 2,  // For armor/shields, otherwise null
  "description": "Item description...",
  "properties": ["two-handed", "slow"]  // Special properties
}

Output as a JSON array of item objects.''',

    "hexes": '''Extract hex locations from Dolmenwood campaign book pages using the standardized format.

Each hex page contains: HEADER (hex number, name, flavour text), GEOGRAPHICAL INFO (terrain, region, travel cost, encounters, ley lines, foraging), and FEATURES.

For each hex, output a JSON object with ALL available information:

{
  // HEADER INFORMATION
  "hex_id": "0102",  // 4-digit hex ID (XXYY format from top of page)
  "coordinates": [1, 2],  // [x, y] parsed from hex_id (01 = x:1, 02 = y:2)
  "name": "The Whispering Pines",  // Hex name from header
  "flavour_text": "Ancient pine trees tower overhead, their needles rustling in an eerie whisper. The air is thick with the scent of moss and decay.",  // Player-facing description from header

  // GEOGRAPHICAL INFO (from left box)
  "terrain_type": "forest",  // fungal_forest, forest, swamp, meadow, hills, mountains, plains, moor, etc.
  "terrain_description": "Fungal forest, Aldweald",  // Full terrain line (includes region)
  "region": "Aldweald",  // Extract region name (Aldweald, Mulchgrove, High Wold, Prigwort, etc.)
  "travel_point_cost": 2,  // TP cost from parentheses after terrain (e.g., "Fungal forest (2 TP)")

  // Lost / Encounters section
  "lost_chance": 3,  // X-in-6 chance from "Lost X-in-6" line
  "encounter_chance": 2,  // X-in-6 chance from "Encounters X-in-6" line
  "special_encounter_chance": 3,  // X-in-6 if "Special encounter: X-in-6" listed, otherwise null
  "special_encounters": ["2d6 Goatmen"],  // Creatures for special encounter if listed
  "encounter_table": "Aldweald",  // Which regional encounter table (usually same as region)

  // Ley Lines (if present)
  "ley_lines": ["Spells cast within the hex have their duration doubled"],  // List ley line effects if mentioned

  // Foraging (if special yields beyond standard)
  "foraging_yields": ["Devil's Grease", "Knobbled Mandrake", "Velvet Flounder"],  // Unusual/magical species found

  // FEATURES (main content - multiple features per hex)
  "features": [
    {
      "name": "The Crooked Oak Inn",  // Feature name/title
      "description": "A weathered two-story inn built around a massive oak tree. The innkeeper, a gruff woodgrue named Bramblethwick, serves mushroom stew and beetle ale to weary travelers. Three rooms available for 5sp/night.",  // Full feature description
      "is_hidden": false,  // true if marked "Hidden", false otherwise
      "feature_type": "inn",  // inn, lair, tomb, settlement, pool, castle, ruins, shrine, standing_stone, etc.
      "npcs": ["Bramblethwick the Innkeeper"],  // NPCs in this feature
      "monsters": [],  // Monsters in this feature (if lair)
      "treasure": "",  // Treasure if mentioned
      "hooks": ["Bramblethwick mentions travelers going missing on the north road"]  // Adventure hooks
    },
    {
      "name": "Barrow of the Green King",
      "description": "An ancient burial mound covered in luminescent moss. The entrance is sealed with a stone carved with warding runes. Inside lies the tomb of a forgotten fairy king. 2d6 Barrowbogeys guard the entrance.",
      "is_hidden": true,  // MARKED AS HIDDEN - requires searching
      "feature_type": "tomb",
      "npcs": [],
      "monsters": ["2d6 Barrowbogeys"],
      "treasure": "Hoard: C + R3 + M2",
      "hooks": ["Local legends speak of a crown that grants command over the woodland dead"]
    }
  ],

  // Additional extracted content (legacy/supplemental)
  "description": "Full referee-facing hex description",  // Complete DM description (if different from flavour_text)
  "npcs": ["Bramblethwick", "Old Meg the Herbalist"],  // All NPCs in hex (extracted from all features)
  "items": [],  // Notable items if listed separately
  "secrets": ["The Green King can be awakened with a specific ritual"],  // Secret information
  "dm_notes": "Consider adding a random encounter with the Cold Prince's scouts",  // Referee notes/suggestions

  // Page layout info
  "adjacent_hexes": ["0101", "0103", "0201", "0202"],  // Neighboring hex IDs if visible on local map

  "page_reference": "p. 42"  // Source page number
}

CRITICAL EXTRACTION GUIDELINES:

1. **Header Information**:
   - hex_id: 4-digit code from page header (e.g., "0102")
   - name: Hex name/title
   - flavour_text: The evocative description meant to be read to players

2. **Geographical Info Box (left side)**:
   - Parse "Terrain: Fungal forest (2 TP), Aldweald"
     → terrain_type: "fungal_forest"
     → travel_point_cost: 2
     → region: "Aldweald"
   - Parse "Lost 3-in-6 / Encounters 2-in-6"
     → lost_chance: 3
     → encounter_chance: 2
   - Look for "Special encounter: X-in-6 with [creatures]"
   - Extract ley line effects if mentioned
   - Note unusual foraging yields beyond "Edible fungi and plants"

3. **Features Section** (main hex content):
   - Each distinct location/thing is a feature
   - Check for "Hidden" marker → is_hidden: true
   - Extract COMPLETE feature descriptions
   - Categorize by type: inn, lair, tomb, settlement, pool, castle, ruins, shrine, standing_stone, bridge, ford, monastery, tower, cave, grove, etc.
   - Extract NPCs, monsters, treasure, hooks from each feature

4. **Hidden vs Non-Hidden**:
   - "Hidden" features require searching to discover
   - Non-hidden features are encountered by passing through
   - Mark is_hidden correctly for exploration mechanics

5. **What NOT to Extract**:
   - Page numbers/headers/footers
   - "See p. XXX" cross-references (note them in dm_notes instead)
   - Map legend information

6. **Terrain Types** (standardize):
   - fungal_forest, forest, dark_forest, swamp, bog, meadow, farmland, hills, mountains, moor, heath, scrubland, plains, river, lake, marsh, settlement, ruins, castle, dungeon

7. **Regions** (common in Dolmenwood):
   - Aldweald, Mulchgrove, High Wold, Prigwort, Brackenwold, Hag's Addle, Dreg, etc.

EXAMPLE MINIMAL OUTPUT (if hex is sparse):
{
  "hex_id": "0515",
  "coordinates": [5, 15],
  "name": "Empty Moorland",
  "flavour_text": "Windswept moors stretch to the horizon.",
  "terrain_type": "moor",
  "region": "High Wold",
  "travel_point_cost": 1,
  "lost_chance": 2,
  "encounter_chance": 2,
  "features": []
}

Output as a JSON array of hex objects.
Extract ALL information present - this is critical for exploration and encounter mechanics!'''

    "npcs": '''Extract all NPCs from this text. For each NPC, output a JSON object:

{
  "name": "NPC Name",
  "npc_id": "npc_name_lowercase",
  "kindred": "Human",  // Human, Elf, Dwarf, Halfling, Woodgrue, Mossling, etc.
  "occupation": "Innkeeper",
  "location_id": "0102",  // Hex ID where found, if known
  "description": "Physical description...",
  "personality": "Personality traits...",
  "motivation": "What they want...",
  "secrets": ["Secret 1"],
  "stat_block": null,  // Include monster-style stats if given, otherwise null
  "is_combatant": false
}

Output as a JSON array of NPC objects.''',

    "rules": '''Extract game rules and mechanics from this text, preserving FULL CONTEXT and original presentation.

IMPORTANT: Do NOT break rules into small discrete pieces. Extract complete sections/pages that preserve:
- All explanatory text and context
- All examples and clarifications
- All tables, lists, and procedures
- The natural flow of the original text

For each logical section (page, major topic, or cohesive rule area), output a JSON object:

{
  "title": "Section Title or Topic",  // e.g., "Combat Sequence", "Morale Checks", "Time and Movement"
  "rule_id": "section_title_lowercase",  // lowercase, underscores for spaces
  "category": "combat",  // combat, exploration, magic, character, equipment, monsters, setting, procedures
  "subcategory": "melee",  // Optional finer categorization (e.g., "melee", "initiative", "damage")
  "content": "COMPLETE section text with ALL context...",  // PRESERVE EVERYTHING - do not summarize!
  "section_type": "major_section",  // Options: "full_page", "major_section", "subsection", "discrete_rule", "table", "procedure"
  "page_reference": "p. 42",  // Page number from source
  "tags": ["combat", "initiative", "surprise", "d6"],  // Keywords for searchability
  "examples": [],  // Leave empty if examples are already in content (preferred)
  "related_rules": []  // IDs of related sections (if obvious)
}

EXTRACTION GUIDELINES:

1. **Preserve Full Context**: Include ALL explanatory text, not just mechanics
   - Keep introductory paragraphs
   - Keep transitional text between rules
   - Keep clarifying statements
   - Keep designer notes and rationale

2. **Section Boundaries**: Identify logical breaking points:
   - Full page if it covers one cohesive topic
   - Major section if page has multiple distinct topics
   - Subsection for detailed breakdowns within a topic
   - Discrete rule only for standalone, self-contained rules

3. **Content Field**: This is the primary field - make it comprehensive!
   - Copy the text EXACTLY as written
   - Preserve formatting indicators (bullets, numbers, headers)
   - Include ALL examples inline
   - Include ALL tables and lists
   - Do NOT summarize or condense

4. **Section Types**:
   - "full_page": Entire page is one cohesive topic
   - "major_section": Significant topic that may span pages
   - "subsection": Detailed part of a larger section
   - "discrete_rule": Single, self-contained rule
   - "table": Reference table or chart
   - "procedure": Step-by-step process

5. **Tags**: Add relevant keywords for searchability
   - Game mechanics mentioned (initiative, morale, damage, etc.)
   - Dice referenced (d6, d20, 2d6, etc.)
   - Related concepts
   - Page elements (table, example, procedure, etc.)

6. **What to Extract**:
   - Core rules and mechanics
   - Procedures and sequences
   - Tables and charts (preserve structure in text)
   - Examples and clarifications
   - Optional rules and variants
   - Designer notes and explanations

7. **What to Skip**:
   - Table of contents
   - Page headers/footers
   - Purely decorative elements
   - Cross-reference lists (unless they contain actual rules)

EXAMPLE OUTPUT:

For a page about "Combat Sequence", extract as ONE section preserving all text:
{
  "title": "Combat Sequence",
  "rule_id": "combat_sequence",
  "category": "combat",
  "subcategory": "procedures",
  "content": "When combat begins, follow these steps in order:\n\n1. Determine Surprise\nEach side rolls 1d6. A result of 1-2 indicates surprise...\n\n2. Declare Actions\nPlayers declare what their characters will do. The DM declares monster actions...\n\n[Include ALL remaining text verbatim, including examples, special cases, etc.]",
  "section_type": "major_section",
  "page_reference": "p. 42",
  "tags": ["combat", "sequence", "initiative", "surprise", "d6", "procedure"],
  "examples": [],
  "related_rules": []
}

Output as a JSON array of rule section objects.
Remember: PRESERVE CONTEXT - do not fragment the rules!'''
}


# Get project root (parent of src/)
PROJECT_ROOT = Path(__file__).parent.parent.parent


@dataclass
class ExtractionConfig:
    """Configuration for LLM extraction."""
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 16384  # Maximum output tokens (increased for full-context rule extraction)
    temperature: float = 0.0  # Deterministic for extraction
    content_type: str = "monsters"
    output_dir: str = ""  # Will be set to PROJECT_ROOT/data/content in __post_init__
    
    def __post_init__(self):
        if not self.output_dir:
            self.output_dir = str(PROJECT_ROOT / "data" / "content")


@dataclass
class ExtractionResult:
    """Result of an extraction operation."""
    content_type: str
    items: list[dict[str, Any]]
    source_file: str
    pages: list[int]
    errors: list[str] = field(default_factory=list)
    raw_response: str = ""


class LLMExtractor:
    """
    Extract structured content from PDFs using Claude.
    
    Sends PDF text to Claude with specialized prompts for each content type,
    then saves the results as JSON for human review.
    
    Example:
        extractor = LLMExtractor()
        
        # Extract monsters from pages 10-20
        result = extractor.extract(
            pdf_path="monster_book.pdf",
            content_type="monsters",
            pages=range(10, 21)
        )
        
        # Save for review
        extractor.save_result(result, "data/content/monsters/extracted_p10-20.json")
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        config: Optional[ExtractionConfig] = None
    ):
        """
        Initialize the extractor.
        
        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            config: Extraction configuration
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. "
                "Set ANTHROPIC_API_KEY environment variable or pass api_key parameter."
            )
        
        self.config = config or ExtractionConfig()
        self._client = None
    
    @property
    def client(self):
        """Lazy-load Anthropic client."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "anthropic package required. Install with: pip install anthropic"
                )
        return self._client
    
    def _extract_pdf_text(
        self, 
        pdf_path: str, 
        pages: Optional[list[int]] = None
    ) -> tuple[str, list[int]]:
        """
        Extract text from PDF pages.
        
        Args:
            pdf_path: Path to PDF file
            pages: List of page numbers (1-indexed), or None for all pages
            
        Returns:
            Tuple of (extracted text, list of page numbers)
        """
        try:
            # Try pymupdf first, fall back to fitz
            try:
                import pymupdf as fitz
            except ImportError:
                import fitz
            
            doc = fitz.open(pdf_path) if hasattr(fitz, 'open') else fitz.Document(pdf_path)
            
            # Determine which pages to extract
            if pages is None:
                pages = list(range(1, len(doc) + 1))
            
            # Validate page numbers
            valid_pages = [p for p in pages if 1 <= p <= len(doc)]
            
            # Extract text from each page
            text_parts = []
            for page_num in valid_pages:
                page = doc[page_num - 1]  # 0-indexed internally
                text = page.get_text()
                text_parts.append(f"--- PAGE {page_num} ---\n{text}")
            
            doc.close()
            
            return "\n\n".join(text_parts), valid_pages
            
        except Exception as e:
            raise RuntimeError(f"Failed to extract PDF text: {e}")
    
    def _call_claude(
        self,
        text: str,
        content_type: str,
        additional_context: str = ""
    ) -> str:
        """
        Call Claude API with extraction prompt.
        
        Args:
            text: PDF text to analyze
            content_type: Type of content to extract
            additional_context: Optional additional instructions
            
        Returns:
            Claude's response text
        """
        if content_type not in EXTRACTION_PROMPTS:
            raise ValueError(f"Unknown content type: {content_type}")
        
        system_prompt = f"""You are a precise data extractor for tabletop RPG content.
Your task is to extract structured data from rulebook text.

Rules:
1. Only extract actual content, not tables of contents or references
2. Use null for missing fields, don't guess
3. Output valid JSON only - no markdown, no explanations
4. Preserve exact wording for descriptions and rules text
5. Generate IDs by lowercasing names and replacing spaces with underscores

{additional_context}"""

        user_prompt = f"""{EXTRACTION_PROMPTS[content_type]}

--- BEGIN SOURCE TEXT ---
{text}
--- END SOURCE TEXT ---

Extract all {content_type} from the text above. Output only a JSON array, no other text."""

        response = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )
        
        return response.content[0].text
    
    def _fix_json(self, text: str) -> str:
        """
        Attempt to fix common JSON errors from LLM output.
        """
        # Remove trailing commas before } or ]
        text = re.sub(r',\s*}', '}', text)
        text = re.sub(r',\s*]', ']', text)
        
        return text
    
    def _fix_truncated_json(self, text: str) -> str:
        """
        Attempt to fix truncated JSON arrays.
        
        If the response was cut off mid-object, try to salvage
        the complete objects we do have.
        """
        text = text.strip()
        
        # If it starts with [ but doesn't end with ], it's truncated
        if text.startswith('[') and not text.rstrip().endswith(']'):
            logger.warning("Detected truncated JSON array, attempting to salvage...")
            
            # Find the last complete object by finding last "},"  or "}" before incomplete part
            # Work backwards to find a valid closing point
            
            # Try to find the last complete object
            last_complete = text.rfind('},')
            if last_complete > 0:
                # Take everything up to and including this }, then close the array
                salvaged = text[:last_complete + 1] + '\n]'
                logger.info(f"Salvaged JSON: kept {last_complete + 1} of {len(text)} chars")
                return salvaged
            
            # Try finding just a closing brace
            last_brace = text.rfind('}')
            if last_brace > 0:
                salvaged = text[:last_brace + 1] + '\n]'
                logger.info(f"Salvaged JSON: kept {last_brace + 1} of {len(text)} chars")
                return salvaged
        
        return text
    
    def _parse_response(self, response: str) -> list[dict[str, Any]]:
        """
        Parse Claude's JSON response.
        
        Handles common issues like markdown code blocks, trailing commas,
        and truncated responses.
        """
        # Remove markdown code blocks if present
        text = response.strip()
        if text.startswith("```"):
            # Remove opening ```json or ```
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            # Remove closing ```
            text = re.sub(r"\n?```\s*$", "", text)
        
        # First attempt: parse as-is
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]
            else:
                return []
        except json.JSONDecodeError:
            pass
        
        # Second attempt: fix common issues (trailing commas)
        fixed_text = self._fix_json(text)
        try:
            data = json.loads(fixed_text)
            logger.info("JSON parsed after fixing trailing commas")
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]
            else:
                return []
        except json.JSONDecodeError:
            pass
        
        # Third attempt: handle truncated response
        salvaged_text = self._fix_truncated_json(fixed_text)
        if salvaged_text != fixed_text:
            try:
                data = json.loads(salvaged_text)
                logger.info(f"JSON parsed after salvaging truncated response")
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return [data]
                else:
                    return []
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse even after salvage attempt: {e}")
        
        # All attempts failed
        logger.error(f"Failed to parse JSON response")
        logger.error(f"Response length: {len(text)} chars")
        # Check if it looks truncated
        if text.startswith('[') and not text.rstrip().endswith(']'):
            logger.error("Response appears to be truncated (array not closed)")
            logger.error("Try extracting fewer pages at a time")
        return []
    
    def extract(
        self,
        pdf_path: str,
        content_type: str,
        pages: Optional[list[int]] = None,
        additional_context: str = ""
    ) -> ExtractionResult:
        """
        Extract content from a PDF.
        
        Args:
            pdf_path: Path to the PDF file
            content_type: Type of content to extract (monsters, spells, etc.)
            pages: Specific pages to extract from (1-indexed), or None for all
            additional_context: Additional instructions for Claude
            
        Returns:
            ExtractionResult with extracted items
        """
        logger.info(f"Extracting {content_type} from {pdf_path}")
        
        # Extract text from PDF
        text, actual_pages = self._extract_pdf_text(pdf_path, pages)
        logger.info(f"Extracted text from {len(actual_pages)} pages")
        
        # Check text length and warn if very long
        if len(text) > 100000:
            logger.warning(
                f"Text is very long ({len(text)} chars). "
                "Consider extracting fewer pages at a time."
            )
        
        # Call Claude
        try:
            response = self._call_claude(text, content_type, additional_context)
        except Exception as e:
            return ExtractionResult(
                content_type=content_type,
                items=[],
                source_file=pdf_path,
                pages=actual_pages,
                errors=[f"API call failed: {e}"]
            )
        
        # Parse response
        items = self._parse_response(response)
        
        result = ExtractionResult(
            content_type=content_type,
            items=items,
            source_file=pdf_path,
            pages=actual_pages,
            raw_response=response
        )
        
        logger.info(f"Extracted {len(items)} {content_type}")
        return result
    
    def extract_monsters(
        self, 
        pdf_path: str, 
        pages: Optional[list[int]] = None
    ) -> ExtractionResult:
        """Convenience method for monster extraction."""
        return self.extract(pdf_path, "monsters", pages)
    
    def extract_spells(
        self, 
        pdf_path: str, 
        pages: Optional[list[int]] = None
    ) -> ExtractionResult:
        """Convenience method for spell extraction."""
        return self.extract(pdf_path, "spells", pages)
    
    def extract_items(
        self, 
        pdf_path: str, 
        pages: Optional[list[int]] = None
    ) -> ExtractionResult:
        """Convenience method for item extraction."""
        return self.extract(pdf_path, "items", pages)
    
    def extract_hexes(
        self, 
        pdf_path: str, 
        pages: Optional[list[int]] = None
    ) -> ExtractionResult:
        """Convenience method for hex extraction."""
        return self.extract(pdf_path, "hexes", pages)
    
    def extract_npcs(
        self, 
        pdf_path: str, 
        pages: Optional[list[int]] = None
    ) -> ExtractionResult:
        """Convenience method for NPC extraction."""
        return self.extract(pdf_path, "npcs", pages)
    
    def extract_rules(
        self, 
        pdf_path: str, 
        pages: Optional[list[int]] = None
    ) -> ExtractionResult:
        """Convenience method for rules extraction."""
        return self.extract(pdf_path, "rules", pages)
    
    def save_result(
        self,
        result: ExtractionResult,
        output_path: Optional[str] = None,
        include_metadata: bool = True
    ) -> str:
        """
        Save extraction result to a JSON file.
        
        Args:
            result: ExtractionResult to save
            output_path: Output file path (auto-generated if None)
            include_metadata: Include extraction metadata in output
            
        Returns:
            Path to saved file
        """
        if output_path is None:
            # Auto-generate output path
            output_dir = Path(self.config.output_dir) / result.content_type
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Create filename from source and pages
            source_name = Path(result.source_file).stem
            if result.pages:
                page_range = f"p{result.pages[0]}-{result.pages[-1]}"
            else:
                page_range = "all"
            
            output_path = output_dir / f"{source_name}_{page_range}_extracted.json"
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Prepare output data
        if include_metadata:
            output_data = {
                "_metadata": {
                    "source_file": result.source_file,
                    "pages": result.pages,
                    "content_type": result.content_type,
                    "item_count": len(result.items),
                    "errors": result.errors,
                    "note": "Review and correct this data before importing"
                },
                "items": result.items
            }
        else:
            output_data = result.items
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved {len(result.items)} items to {output_path}")
        
        # If parsing failed but we have raw response, save it for manual recovery
        if len(result.items) == 0 and result.raw_response:
            raw_path = output_path.with_suffix('.raw.txt')
            with open(raw_path, 'w', encoding='utf-8') as f:
                f.write(result.raw_response)
            logger.info(f"Saved raw response to {raw_path} for manual recovery")
            print(f"💾 Raw response saved to: {raw_path}")
            print("   You can manually fix the JSON and re-save as .json")
        
        return str(output_path)


def parse_page_range(page_spec: str) -> list[int]:
    """
    Parse a page specification into a list of page numbers.
    
    Examples:
        "10" -> [10]
        "10-20" -> [10, 11, ..., 20]
        "1,5,10-15" -> [1, 5, 10, 11, 12, 13, 14, 15]
    """
    pages = []
    for part in page_spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            pages.extend(range(int(start), int(end) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def main():
    """Command-line interface for the extractor."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Extract structured content from Dolmenwood PDFs using Claude"
    )
    
    parser.add_argument(
        "--pdf",
        required=True,
        help="Path to the PDF file"
    )
    
    parser.add_argument(
        "--type",
        required=True,
        choices=["monsters", "spells", "items", "hexes", "npcs", "rules"],
        help="Type of content to extract"
    )
    
    parser.add_argument(
        "--pages",
        help="Pages to extract (e.g., '10-20' or '1,5,10-15'). Default: all pages"
    )
    
    parser.add_argument(
        "--output",
        help="Output file path (default: auto-generated)"
    )
    
    parser.add_argument(
        "--output-dir",
        default=None,
        help=f"Output directory (default: {PROJECT_ROOT / 'data' / 'content'})"
    )
    
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-20250514",
        help="Claude model to use"
    )

    parser.add_argument(
        "--max-tokens",
        type=int,
        default=16384,
        help="Maximum output tokens (default: 16384). Use higher values for lengthy rule sections. Claude max: ~16384 for most models"
    )

    parser.add_argument(
        "--context",
        default="",
        help="Additional context/instructions for Claude"
    )

    parser.add_argument(
        "--api-key",
        metavar="KEY",
        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Parse pages
    pages = None
    if args.pages:
        try:
            pages = parse_page_range(args.pages)
            print(f"📄 Extracting from pages: {pages}")
        except ValueError as e:
            print(f"❌ Invalid page specification: {e}")
            return 1
    
    # Create extractor
    try:
        config = ExtractionConfig(
            model=args.model,
            max_tokens=args.max_tokens,
            output_dir=args.output_dir or "",  # Empty string triggers default in __post_init__
            content_type=args.type
        )
        extractor = LLMExtractor(api_key=args.api_key, config=config)
    except ValueError as e:
        print(f"❌ {e}")
        return 1
    
    # Extract content
    print(f"🔍 Extracting {args.type} from {args.pdf}...")
    result = extractor.extract(
        pdf_path=args.pdf,
        content_type=args.type,
        pages=pages,
        additional_context=args.context
    )
    
    if result.errors:
        print(f"⚠️  Errors during extraction:")
        for error in result.errors:
            print(f"   - {error}")
    
    # Save results
    output_path = extractor.save_result(result, args.output)
    
    print(f"✅ Extracted {len(result.items)} {args.type}")
    print(f"📁 Saved to: {output_path}")
    print()
    print("Next steps:")
    print(f"  1. Review and correct the JSON file: {output_path}")
    print(f"  2. Move corrected file to: data/content/{args.type}/")
    print(f"  3. Import with: game.load_content()")
    
    return 0


if __name__ == "__main__":
    exit(main())
