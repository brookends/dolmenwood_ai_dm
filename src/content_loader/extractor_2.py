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
    "monsters": '''Extract all monster stat blocks from this text. For each monster, output a JSON object with these fields:

{
  "name": "Monster Name",
  "monster_id": "monster_name_lowercase",  // lowercase, underscores for spaces
  "hd": "2+1",  // Hit Dice as string (e.g., "1", "2+1", "3*", "4**")
  "hp": null,  // Average HP if given, otherwise null
  "ac": 7,  // Armor Class as integer (descending AC)
  "ac_ascending": 12,  // Ascending AC if given, otherwise null
  "movement": "120' (40')",  // Movement rate as string
  "attacks": [
    {"name": "Claw", "damage": "1d4", "count": 2},
    {"name": "Bite", "damage": "1d8", "count": 1}
  ],
  "special_abilities": [
    {"name": "Regeneration", "description": "Regains 1 HP per round"}
  ],
  "save_as": "F2",  // Save as Fighter 2, etc.
  "morale": 8,
  "alignment": "Chaotic",  // Lawful, Neutral, or Chaotic
  "xp": 50,
  "number_appearing": "1d6",
  "treasure_type": "B",
  "description": "A brief description of the monster..."
}

If a field is not present in the source, use null.
Output as a JSON array of monster objects.
Only extract actual monster stat blocks, not references or mentions.''',

    "spells": '''Extract all spells, knacks, and magical abilities from this text.

For STANDARD SPELLS (arcane/divine), output:
{
  "name": "Spell Name",
  "spell_id": "spell_name_lowercase",
  "level": 1,
  "magic_type": "arcane",  // "arcane", "divine", "knack", or "special"
  "duration": "1 turn",
  "range": "60'",
  "description": "Full spell description...",
  "reversible": false,
  "reversed_name": null
}

For KNACKS (Mossling racial abilities) or similar tiered abilities, output:
{
  "name": "Knack Name",
  "spell_id": "knack_name_lowercase", 
  "level": null,
  "magic_type": "knack",
  "duration": null,
  "range": null,
  "description": "Brief description of the knack",
  "reversible": false,
  "reversed_name": null,
  "kindred": "Mossling",  // Race/kindred that has this ability
  "abilities": [
    {"level": 1, "name": "Ability Name", "description": "What it does at level 1"},
    {"level": 3, "name": "Ability Name", "description": "What it does at level 3"},
    {"level": 5, "name": "Ability Name", "description": "What it does at level 5"},
    {"level": 7, "name": "Ability Name", "description": "What it does at level 7"}
  ]
}

Output as a JSON array of spell/knack objects.
Extract ALL magical abilities including racial knacks, not just arcane/divine spells.
Only extract actual definitions, not tables of contents or references.''',

    "items": '''Extract all items/equipment from this text. For each item, output a JSON object:

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

    "hexes": '''Extract all hex location descriptions from this text. For each hex, output a JSON object:

{
  "hex_id": "0102",  // 4-digit hex ID (XXYY format)
  "coordinates": [1, 2],  // [x, y] parsed from hex_id
  "location_name": "Name of Location",
  "terrain_type": "forest",  // forest, swamp, hills, mountains, plains, river, lake, settlement, ruins, dungeon
  "description": "Full description of the hex...",
  "special_encounters": ["Encounter 1", "Encounter 2"],
  "settlements": ["Village Name"],
  "npcs": ["NPC Name"],
  "points_of_interest": ["Interesting feature"],
  "hooks": ["Adventure hook or rumor"]
}

Output as a JSON array of hex objects.''',

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

    "rules": '''Extract game rules and mechanics from this text. For each distinct rule, output a JSON object:

{
  "title": "Rule Title",
  "rule_id": "rule_title_lowercase",
  "category": "combat",  // combat, exploration, magic, character, equipment, monsters, setting, procedures
  "content": "Full rule text...",
  "examples": ["Example of rule in play"],
  "page_reference": "p. 42"
}

Output as a JSON array of rule objects.
Focus on mechanical rules, not flavor text or examples.'''
}


# Get project root (parent of src/)
PROJECT_ROOT = Path(__file__).parent.parent.parent


@dataclass
class ExtractionConfig:
    """Configuration for LLM extraction."""
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 8192  # Increased for longer extractions
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
