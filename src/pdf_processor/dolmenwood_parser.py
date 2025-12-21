"""
Dolmenwood AI Dungeon Master - PDF Processor (v1.1)

This module handles extraction and parsing of content from Dolmenwood PDF
rulebooks and adventure modules. It converts raw PDF text into structured 
data models with source tracking for conflict resolution.

v1.1 Features:
- Source tracking via SourceReference on all extracted content
- Adventure module support (AdventureLocation, AdventureModule)
- Integration with ContentManager for source registration
- Content type classification for context-aware retrieval

Supported content types:
- Game rules (from Player's Book)
- Monster stat blocks (from Monster Book)
- Hex descriptions (from Campaign Book)
- Spells (from Player's Book)
- Equipment tables (from Player's Book)
- Adventure locations and modules (from adventure PDFs)

Author: AI Dungeon Master Project
Version: 1.1
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Generator, Optional

import fitz  # PyMuPDF
import pdfplumber

# Import data models
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from data_models import (
    GameRule,
    MonsterStatBlock,
    HexLocation,
    Spell,
    Item,
    NPC,
    ItemType,
    MagicType,
    TerrainType,
    generate_id,
    # v1.1 models
    SourceReference,
    ContentSource,
    SourceType,
    ContentType,
    AdventureLocation,
    AdventureModule,
    AdventureType,
)

# Import ContentManager for source registration
from content_manager import ContentManager, create_content_manager

# Configure logging
logger = logging.getLogger(__name__)


# =============================================================================
# EXCEPTIONS
# =============================================================================

class PDFProcessorError(Exception):
    """Base exception for PDF processor errors."""
    pass


class PDFExtractionError(PDFProcessorError):
    """Error during PDF text extraction."""
    pass


class ParseError(PDFProcessorError):
    """Error during content parsing."""
    pass


class FileNotFoundError(PDFProcessorError):
    """PDF file not found."""
    pass


class SourceNotRegisteredError(PDFProcessorError):
    """Source must be registered before extraction."""
    pass


# =============================================================================
# ENUMERATIONS
# =============================================================================

class BookType(str, Enum):
    """Types of Dolmenwood source books."""
    PLAYERS_BOOK = "players_book"
    CAMPAIGN_BOOK = "campaign_book"
    MONSTER_BOOK = "monster_book"


class ContentSection(str, Enum):
    """Content section types in rulebooks."""
    RULES = "rules"
    SPELLS = "spells"
    EQUIPMENT = "equipment"
    MONSTERS = "monsters"
    HEXES = "hexes"
    NPCS = "npcs"
    CLASSES = "classes"
    KINDREDS = "kindreds"
    ADVENTURE = "adventure"


# =============================================================================
# DATA CLASSES FOR INTERMEDIATE PARSING
# =============================================================================

@dataclass
class ExtractedPage:
    """Represents extracted content from a single PDF page."""
    page_number: int
    text: str
    tables: list[list[list[str]]]
    images: list[bytes]
    source_id: Optional[str] = None
    
    @property
    def has_tables(self) -> bool:
        return len(self.tables) > 0
    
    @property
    def has_images(self) -> bool:
        return len(self.images) > 0


@dataclass
class TextChunk:
    """A chunk of text with metadata for vector embedding."""
    content: str
    source_book: str
    page_start: int
    page_end: int
    category: str
    title: Optional[str] = None
    source_id: Optional[str] = None
    content_type: ContentType = ContentType.CORE_RULE
    
    def to_game_rule(self) -> GameRule:
        """Convert chunk to GameRule model with source tracking."""
        source_ref = None
        if self.source_id:
            source_ref = SourceReference(
                source_id=self.source_id,
                book_code=self.source_id,
                page_reference=f"p.{self.page_start}" if self.page_start == self.page_end 
                              else f"pp.{self.page_start}-{self.page_end}",
                section=self.category
            )
        
        return GameRule(
            category=self.category,
            title=self.title or f"Rule from page {self.page_start}",
            content=self.content,
            page_reference=f"p.{self.page_start}" if self.page_start == self.page_end 
                          else f"pp.{self.page_start}-{self.page_end}",
            source_book=self.source_book,
            source=source_ref,
            content_type=self.content_type
        )


@dataclass
class ExtractionResult:
    """Complete extraction result from all PDFs with v1.1 source tracking."""
    rules: list[GameRule]
    spells: list[Spell]
    items: list[Item]
    monsters: list[MonsterStatBlock]
    hexes: list[HexLocation]
    npcs: list[NPC]
    # v1.1: Adventure content
    adventure_locations: list[AdventureLocation] = field(default_factory=list)
    adventure_modules: list[AdventureModule] = field(default_factory=list)
    # Tracking
    errors: list[str] = field(default_factory=list)
    sources_processed: list[str] = field(default_factory=list)
    
    @property
    def total_items(self) -> int:
        return (
            len(self.rules) + 
            len(self.spells) + 
            len(self.items) + 
            len(self.monsters) + 
            len(self.hexes) + 
            len(self.npcs) +
            len(self.adventure_locations) +
            len(self.adventure_modules)
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "rules": [r.model_dump() for r in self.rules],
            "spells": [s.model_dump() for s in self.spells],
            "items": [i.model_dump() for i in self.items],
            "monsters": [m.model_dump() for m in self.monsters],
            "hexes": [h.model_dump() for h in self.hexes],
            "npcs": [n.model_dump() for n in self.npcs],
            "adventure_locations": [loc.model_dump() for loc in self.adventure_locations],
            "adventure_modules": [mod.model_dump() for mod in self.adventure_modules],
            "errors": self.errors,
            "sources_processed": self.sources_processed,
            "summary": {
                "total_rules": len(self.rules),
                "total_spells": len(self.spells),
                "total_items": len(self.items),
                "total_monsters": len(self.monsters),
                "total_hexes": len(self.hexes),
                "total_npcs": len(self.npcs),
                "total_adventure_locations": len(self.adventure_locations),
                "total_adventure_modules": len(self.adventure_modules),
                "total_errors": len(self.errors),
                "sources_count": len(self.sources_processed)
            }
        }
    
    def merge(self, other: "ExtractionResult") -> "ExtractionResult":
        """Merge another ExtractionResult into this one."""
        return ExtractionResult(
            rules=self.rules + other.rules,
            spells=self.spells + other.spells,
            items=self.items + other.items,
            monsters=self.monsters + other.monsters,
            hexes=self.hexes + other.hexes,
            npcs=self.npcs + other.npcs,
            adventure_locations=self.adventure_locations + other.adventure_locations,
            adventure_modules=self.adventure_modules + other.adventure_modules,
            errors=self.errors + other.errors,
            sources_processed=self.sources_processed + other.sources_processed
        )


# =============================================================================
# REGEX PATTERNS FOR PARSING
# =============================================================================

class ParsePatterns:
    """Compiled regex patterns for content extraction."""
    
    # Monster stat block patterns (OSE format)
    STAT_BLOCK_FULL = re.compile(
        r"(?P<n>[A-Z][a-zA-Z\s\-']+)\s*\n"
        r"AC\s*(?P<ac>\d+)(?:\s*\[(?P<ac_desc>\d+)\])?"
        r".*?HD\s*(?P<hd>[\d+\-\*]+)"
        r"(?:.*?HP\s*(?P<hp>\d+))?"
        r".*?MV\s*(?P<mv>[0-9'()\s]+)"
        r".*?#AT\s*(?P<attacks>[^,\n]+)"
        r".*?SV\s*(?P<saves>[A-Z]\d+)"
        r".*?ML\s*(?P<morale>\d+)"
        r"(?:.*?AL\s*(?P<alignment>[A-Za-z]+))?"
        r"(?:.*?XP\s*(?P<xp>[\d,]+))?",
        re.DOTALL | re.MULTILINE
    )
    
    # Simpler stat line patterns for fallback
    STAT_LINE_AC = re.compile(r"AC\s*(\d+)(?:\s*\[(\d+)\])?", re.IGNORECASE)
    STAT_LINE_HD = re.compile(r"HD\s*([\d+\-\*]+)", re.IGNORECASE)
    STAT_LINE_HP = re.compile(r"HP\s*(\d+)", re.IGNORECASE)
    STAT_LINE_MV = re.compile(r"MV\s*([0-9'()\s]+)", re.IGNORECASE)
    STAT_LINE_AT = re.compile(r"#AT\s*(.+?)(?:,|SV|$)", re.IGNORECASE)
    STAT_LINE_SV = re.compile(r"SV\s*([A-Z]\d+)", re.IGNORECASE)
    STAT_LINE_ML = re.compile(r"ML\s*(\d+)", re.IGNORECASE)
    STAT_LINE_AL = re.compile(r"AL\s*(Lawful|Neutral|Chaotic)", re.IGNORECASE)
    STAT_LINE_XP = re.compile(r"XP\s*([\d,]+)", re.IGNORECASE)
    STAT_LINE_NA = re.compile(r"(?:NA|No\.?\s*App(?:earing)?\.?)\s*([0-9d+\-()]+)", re.IGNORECASE)
    STAT_LINE_TT = re.compile(r"(?:TT|Treasure)\s*([A-Z]+(?:\s*\+\s*[A-Z]+)*)", re.IGNORECASE)
    
    # Hex description patterns
    HEX_HEADER = re.compile(
        r"(?P<hex_id>\d{4})\s*[-–—]\s*(?P<name>.+?)(?:\n|$)",
        re.MULTILINE
    )
    
    # Spell patterns
    SPELL_HEADER = re.compile(
        r"(?P<n>[A-Z][a-zA-Z\s']+)\s*\n"
        r"(?:Level:\s*(?P<level>\d+))?"
        r"(?:.*?Duration:\s*(?P<duration>[^\n]+))?"
        r"(?:.*?Range:\s*(?P<range>[^\n]+))?",
        re.DOTALL
    )
    
    SPELL_LEVEL = re.compile(r"Level:\s*(\d+)", re.IGNORECASE)
    SPELL_DURATION = re.compile(r"Duration:\s*(.+?)(?:\n|Range:|$)", re.IGNORECASE | re.DOTALL)
    SPELL_RANGE = re.compile(r"Range:\s*(.+?)(?:\n|Duration:|$)", re.IGNORECASE | re.DOTALL)
    SPELL_REVERSIBLE = re.compile(r"\(Reversible\)", re.IGNORECASE)
    
    # Equipment table patterns
    EQUIPMENT_ROW = re.compile(
        r"(?P<n>[A-Za-z][\w\s,]+?)\s+"
        r"(?P<cost>[\d,]+)\s*(?:sp|gp|cp)?\s+"
        r"(?P<weight>[\d.]+)?",
        re.IGNORECASE
    )
    
    # Section header patterns
    SECTION_HEADER_H1 = re.compile(r"^#+\s+(.+)$", re.MULTILINE)
    SECTION_HEADER_CAPS = re.compile(r"^([A-Z][A-Z\s]{3,})$", re.MULTILINE)
    SECTION_HEADER_NUMBERED = re.compile(r"^(\d+\.?\s+[A-Z].+)$", re.MULTILINE)
    
    # v1.1: Adventure room/location patterns
    ROOM_HEADER = re.compile(
        r"(?:Room\s+)?(?P<number>\d+[A-Za-z]?)\s*[:\.\-–—]\s*(?P<name>[^\n]+)",
        re.MULTILINE
    )
    
    READ_ALOUD = re.compile(
        r"(?:Read\s+(?:Aloud|the\s+following):|Boxed\s+Text:|\")\s*(?P<text>[^\"]+)\"?",
        re.IGNORECASE | re.DOTALL
    )
    
    # Page break indicators
    PAGE_BREAK = re.compile(r"\f|\n{3,}|^---+$", re.MULTILINE)
    
    # Damage notation
    DAMAGE_DICE = re.compile(r"(\d+d\d+(?:[+-]\d+)?)")


# =============================================================================
# MAIN PDF PROCESSOR CLASS (v1.1)
# =============================================================================

class DolmenwoodPDFProcessor:
    """
    Process Dolmenwood PDFs into structured data with source tracking.
    
    v1.1 Features:
    - All extracted content includes SourceReference for attribution
    - Adventure module support for location-based content
    - Integration with ContentManager for source registration
    - Content type classification for improved retrieval
    
    Example usage:
        # With ContentManager integration
        content_manager = ContentManager("./data/sources.db")
        processor = DolmenwoodPDFProcessor(
            pdf_paths={
                "players_book": "path/to/players.pdf",
                "monster_book": "path/to/monsters.pdf"
            },
            content_manager=content_manager
        )
        result = processor.extract_all()
        print(f"Extracted {result.total_items} items from {len(result.sources_processed)} sources")
    
    Attributes:
        pdf_paths: Dictionary mapping book type to file path.
        content_manager: Optional ContentManager for source tracking.
        patterns: Compiled regex patterns for parsing.
        _cache: Internal cache for extracted pages.
        _registered_sources: Set of source IDs that have been registered.
    """
    
    def __init__(
        self, 
        pdf_paths: dict[str, str],
        content_manager: Optional[ContentManager] = None
    ):
        """
        Initialize the PDF processor.
        
        Args:
            pdf_paths: Dictionary mapping book identifiers to file paths.
                Expected keys: "players_book", "campaign_book", "monster_book"
                Can also include adventure module identifiers.
            content_manager: Optional ContentManager for source registration
                and tracking. If not provided, source tracking is disabled.
        
        Raises:
            FileNotFoundError: If a specified PDF file doesn't exist.
        """
        self.pdf_paths: dict[str, Path] = {}
        self.content_manager = content_manager
        self.patterns = ParsePatterns()
        self._cache: dict[str, list[ExtractedPage]] = {}
        self._registered_sources: set[str] = set()
        
        # Validate and store paths
        for book_type, path in pdf_paths.items():
            if path is not None:
                path_obj = Path(path)
                if not path_obj.exists():
                    logger.warning(f"PDF not found: {path}")
                else:
                    self.pdf_paths[book_type] = path_obj
        
        logger.info(f"Initialized PDF processor with {len(self.pdf_paths)} books")
    
    # =========================================================================
    # SOURCE REGISTRATION (v1.1)
    # =========================================================================
    
    def _create_source_reference(
        self,
        source_id: str,
        page_reference: Optional[str] = None,
        section: Optional[str] = None
    ) -> Optional[SourceReference]:
        """Create a SourceReference for content attribution."""
        if not source_id:
            return None
        
        # Get book code from source ID
        book_code = source_id
        if self.content_manager:
            source = self.content_manager.get_source(source_id)
            if source:
                book_code = source.book_code
        
        return SourceReference(
            source_id=source_id,
            book_code=book_code,
            page_reference=page_reference,
            section=section
        )
    
    def register_source(
        self,
        source_id: str,
        source_type: SourceType,
        book_name: str,
        file_path: str
    ) -> Optional[ContentSource]:
        """
        Register a PDF source with the ContentManager.
        
        Args:
            source_id: Unique identifier for the source.
            source_type: Type of source (CORE_RULEBOOK, ADVENTURE_MODULE, etc.)
            book_name: Human-readable name of the book.
            file_path: Path to the PDF file.
        
        Returns:
            ContentSource if registered, None if no ContentManager.
        """
        if not self.content_manager:
            logger.debug("No ContentManager configured, skipping source registration")
            return None
        
        # Compute file hash for integrity tracking
        file_hash = None
        path_obj = Path(file_path)
        if path_obj.exists():
            file_hash = ContentManager.compute_file_hash(file_path)
            page_count = self.get_page_count(file_path)
        else:
            page_count = None
        
        source = ContentSource(
            source_id=source_id,
            source_type=source_type,
            book_name=book_name,
            book_code=source_id,
            file_path=file_path,
            file_hash=file_hash,
            page_count=page_count,
            imported_at=datetime.now(),
            last_updated=datetime.now()
        )
        
        self.content_manager.register_source(source)
        self._registered_sources.add(source_id)
        
        logger.info(f"Registered source: {source_id} ({book_name})")
        return source
    
    def _ensure_source_registered(self, source_id: str, file_path: str) -> None:
        """Ensure a source is registered before extraction."""
        if not self.content_manager:
            return
        
        if source_id in self._registered_sources:
            return
        
        # Determine source type from source_id
        if source_id in [BookType.PLAYERS_BOOK.value, BookType.MONSTER_BOOK.value]:
            source_type = SourceType.CORE_RULEBOOK
        elif source_id == BookType.CAMPAIGN_BOOK.value:
            source_type = SourceType.CAMPAIGN_SETTING
        else:
            source_type = SourceType.ADVENTURE_MODULE
        
        # Generate book name
        book_names = {
            BookType.PLAYERS_BOOK.value: "Dolmenwood Player's Book",
            BookType.CAMPAIGN_BOOK.value: "Dolmenwood Campaign Book",
            BookType.MONSTER_BOOK.value: "Dolmenwood Monster Book"
        }
        book_name = book_names.get(source_id, f"Adventure: {source_id.replace('_', ' ').title()}")
        
        self.register_source(source_id, source_type, book_name, file_path)
    
    # =========================================================================
    # MAIN EXTRACTION METHODS
    # =========================================================================
    
    def extract_all(self) -> ExtractionResult:
        """
        Extract all content from all available PDFs with source tracking.
        
        Returns:
            ExtractionResult containing all extracted data with source references.
        """
        logger.info("Starting full extraction from all PDFs")
        
        rules: list[GameRule] = []
        spells: list[Spell] = []
        items: list[Item] = []
        monsters: list[MonsterStatBlock] = []
        hexes: list[HexLocation] = []
        npcs: list[NPC] = []
        adventure_locations: list[AdventureLocation] = []
        adventure_modules: list[AdventureModule] = []
        errors: list[str] = []
        sources_processed: list[str] = []
        
        # Extract from Player's Book
        if BookType.PLAYERS_BOOK.value in self.pdf_paths:
            try:
                source_id = BookType.PLAYERS_BOOK.value
                path = str(self.pdf_paths[source_id])
                self._ensure_source_registered(source_id, path)
                
                rules.extend(self.extract_rules(path, source_id))
                spells.extend(self.extract_spell_list(path, source_id))
                items.extend(self.extract_equipment_tables(path, source_id))
                sources_processed.append(source_id)
            except Exception as e:
                error_msg = f"Error extracting from Player's Book: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        # Extract from Monster Book
        if BookType.MONSTER_BOOK.value in self.pdf_paths:
            try:
                source_id = BookType.MONSTER_BOOK.value
                path = str(self.pdf_paths[source_id])
                self._ensure_source_registered(source_id, path)
                
                monsters.extend(self.extract_stat_blocks(path, source_id))
                sources_processed.append(source_id)
            except Exception as e:
                error_msg = f"Error extracting from Monster Book: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        # Extract from Campaign Book
        if BookType.CAMPAIGN_BOOK.value in self.pdf_paths:
            try:
                source_id = BookType.CAMPAIGN_BOOK.value
                path = str(self.pdf_paths[source_id])
                self._ensure_source_registered(source_id, path)
                
                hexes.extend(self.extract_hex_descriptions(path, source_id))
                npcs.extend(self.extract_npcs(path, source_id))
                sources_processed.append(source_id)
            except Exception as e:
                error_msg = f"Error extracting from Campaign Book: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        # Extract from adventure modules (any path not matching core book types)
        core_book_types = {bt.value for bt in BookType}
        for source_id, path_obj in self.pdf_paths.items():
            if source_id not in core_book_types:
                try:
                    path = str(path_obj)
                    self._ensure_source_registered(source_id, path)
                    
                    # Extract adventure content
                    adv_result = self.extract_adventure_module(path, source_id)
                    adventure_locations.extend(adv_result.get("locations", []))
                    if adv_result.get("module"):
                        adventure_modules.append(adv_result["module"])
                    # Adventures may also have monsters
                    monsters.extend(adv_result.get("monsters", []))
                    npcs.extend(adv_result.get("npcs", []))
                    
                    sources_processed.append(source_id)
                except Exception as e:
                    error_msg = f"Error extracting from adventure {source_id}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
        
        result = ExtractionResult(
            rules=rules,
            spells=spells,
            items=items,
            monsters=monsters,
            hexes=hexes,
            npcs=npcs,
            adventure_locations=adventure_locations,
            adventure_modules=adventure_modules,
            errors=errors,
            sources_processed=sources_processed
        )
        
        logger.info(f"Extraction complete: {result.total_items} items from {len(sources_processed)} sources")
        return result
    
    def extract_rules(
        self, 
        pdf_path: str,
        source_id: Optional[str] = None
    ) -> list[GameRule]:
        """
        Extract game rules from the Player's Book with source tracking.
        
        Args:
            pdf_path: Path to the PDF file.
            source_id: Source identifier for tracking.
        
        Returns:
            List of GameRule objects with source references.
        """
        logger.info(f"Extracting rules from {pdf_path}")
        rules: list[GameRule] = []
        
        pages = self._extract_pages(pdf_path, source_id)
        
        # Rule categories to look for
        rule_categories = {
            "combat": ["combat", "attack", "damage", "initiative", "armor class", "saving throw"],
            "magic": ["spell", "magic", "arcane", "divine", "casting"],
            "skills": ["skill", "ability check", "thief", "listen", "search"],
            "travel": ["travel", "exploration", "hex", "encounter", "rest"],
            "equipment": ["equipment", "weapon", "armor", "gear", "encumbrance"],
            "character": ["character", "level", "experience", "class", "kindred", "advancement"],
            "dungeon": ["dungeon", "trap", "door", "light", "movement"],
            "wilderness": ["wilderness", "weather", "terrain", "navigation"],
            "social": ["reaction", "morale", "loyalty", "henchmen", "retainer"],
            "general": []
        }
        
        # Process pages and chunk into rules
        current_section = "general"
        section_text = ""
        section_title = ""
        section_start_page = 1
        
        for page in pages:
            # Check for section headers
            headers = self.patterns.SECTION_HEADER_CAPS.findall(page.text)
            if headers:
                # Save previous section
                if section_text.strip():
                    page_ref = f"p.{section_start_page}" if section_start_page == page.page_number - 1 \
                               else f"pp.{section_start_page}-{page.page_number - 1}"
                    
                    source_ref = self._create_source_reference(
                        source_id or BookType.PLAYERS_BOOK.value,
                        page_reference=page_ref,
                        section=current_section
                    )
                    
                    rules.append(GameRule(
                        category=current_section,
                        title=section_title or f"{current_section.title()} Rules",
                        content=self._clean_text(section_text),
                        page_reference=page_ref,
                        source_book="Dolmenwood Player's Book",
                        source=source_ref,
                        content_type=ContentType.CORE_RULE
                    ))
                
                # Start new section
                section_title = headers[0].strip().title()
                section_text = page.text
                section_start_page = page.page_number
                
                # Determine category
                text_lower = page.text.lower()
                for category, keywords in rule_categories.items():
                    if any(kw in text_lower for kw in keywords):
                        current_section = category
                        break
                else:
                    current_section = "general"
            else:
                section_text += "\n" + page.text
        
        # Save final section
        if section_text.strip() and pages:
            page_ref = f"pp.{section_start_page}-{pages[-1].page_number}"
            source_ref = self._create_source_reference(
                source_id or BookType.PLAYERS_BOOK.value,
                page_reference=page_ref,
                section=current_section
            )
            
            rules.append(GameRule(
                category=current_section,
                title=section_title or f"{current_section.title()} Rules",
                content=self._clean_text(section_text),
                page_reference=page_ref,
                source_book="Dolmenwood Player's Book",
                source=source_ref,
                content_type=ContentType.CORE_RULE
            ))
        
        # Create smaller chunks for better retrieval
        for rule in rules.copy():
            chunks = self.clean_and_chunk_text(rule.content, chunk_size=800)
            if len(chunks) > 1:
                for i, chunk in enumerate(chunks):
                    chunk_source_ref = self._create_source_reference(
                        source_id or BookType.PLAYERS_BOOK.value,
                        page_reference=rule.page_reference,
                        section=f"{rule.category}/chunk_{i+1}"
                    )
                    
                    rules.append(GameRule(
                        category=rule.category,
                        subcategory=f"chunk_{i+1}",
                        title=f"{rule.title} (Part {i+1})",
                        content=chunk,
                        page_reference=rule.page_reference,
                        source_book=rule.source_book,
                        related_rules=[rule.rule_id],
                        source=chunk_source_ref,
                        content_type=ContentType.CORE_RULE
                    ))
        
        logger.info(f"Extracted {len(rules)} rules")
        return rules
    
    def extract_stat_blocks(
        self, 
        pdf_path: str,
        source_id: Optional[str] = None
    ) -> list[MonsterStatBlock]:
        """
        Extract monster stat blocks with source tracking.
        
        Args:
            pdf_path: Path to the PDF file.
            source_id: Source identifier for tracking.
        
        Returns:
            List of MonsterStatBlock objects with source references.
        """
        logger.info(f"Extracting stat blocks from {pdf_path}")
        monsters: list[MonsterStatBlock] = []
        
        pages = self._extract_pages(pdf_path, source_id)
        full_text = "\n\n".join(page.text for page in pages)
        
        # Try to find complete stat blocks
        for match in self.patterns.STAT_BLOCK_FULL.finditer(full_text):
            try:
                monster = self._parse_stat_block_match(match, source_id)
                if monster:
                    monsters.append(monster)
            except Exception as e:
                logger.warning(f"Failed to parse stat block: {e}")
        
        # If no matches found, try line-by-line parsing
        if not monsters:
            logger.info("No full stat blocks found, trying line-by-line parsing")
            monsters.extend(self._extract_stat_blocks_fallback(pages, source_id))
        
        logger.info(f"Extracted {len(monsters)} monster stat blocks")
        return monsters
    
    def extract_hex_descriptions(
        self, 
        pdf_path: str,
        source_id: Optional[str] = None
    ) -> list[HexLocation]:
        """
        Extract hex descriptions with source tracking.
        
        Args:
            pdf_path: Path to the PDF file.
            source_id: Source identifier for tracking.
        
        Returns:
            List of HexLocation objects with source references.
        """
        logger.info(f"Extracting hex descriptions from {pdf_path}")
        hexes: list[HexLocation] = []
        
        pages = self._extract_pages(pdf_path, source_id)
        full_text = "\n".join(page.text for page in pages)
        
        # Find all hex entries
        hex_matches = list(self.patterns.HEX_HEADER.finditer(full_text))
        
        for i, match in enumerate(hex_matches):
            try:
                hex_id = match.group("hex_id")
                name = match.group("name").strip()
                
                # Get description (text until next hex or end)
                start_pos = match.end()
                if i + 1 < len(hex_matches):
                    end_pos = hex_matches[i + 1].start()
                else:
                    end_pos = len(full_text)
                
                description = full_text[start_pos:end_pos].strip()
                
                # Parse hex ID to coordinates
                x = int(hex_id[:2])
                y = int(hex_id[2:])
                
                # Determine terrain type
                terrain = self._infer_terrain_type(description)
                
                # Look for special encounters and NPCs
                encounters = self._extract_encounters_from_text(description)
                npc_refs = self._extract_npc_references(description)
                
                # Create source reference
                source_ref = self._create_source_reference(
                    source_id or BookType.CAMPAIGN_BOOK.value,
                    section=f"Hex {hex_id}"
                )
                
                hex_location = HexLocation(
                    hex_id=hex_id,
                    coordinates=(x, y),
                    terrain_type=terrain,
                    location_name=name if name != hex_id else None,
                    description=self._clean_text(description),
                    special_encounters=encounters,
                    npcs=npc_refs,
                    adjacent_hexes=self._calculate_adjacent_hexes(hex_id),
                    source=source_ref
                )
                hexes.append(hex_location)
                
            except Exception as e:
                logger.warning(f"Failed to parse hex entry: {e}")
        
        logger.info(f"Extracted {len(hexes)} hex descriptions")
        return hexes
    
    def extract_spell_list(
        self, 
        pdf_path: str,
        source_id: Optional[str] = None
    ) -> list[Spell]:
        """
        Extract spell descriptions with source tracking.
        
        Args:
            pdf_path: Path to the PDF file.
            source_id: Source identifier for tracking.
        
        Returns:
            List of Spell objects with source references.
        """
        logger.info(f"Extracting spells from {pdf_path}")
        spells: list[Spell] = []
        
        pages = self._extract_pages(pdf_path, source_id)
        full_text = "\n".join(page.text for page in pages)
        
        current_magic_type = MagicType.ARCANE
        current_level = 1
        
        # Split text into potential spell entries
        spell_sections = re.split(r"\n(?=[A-Z][a-z]+ \(|[A-Z][a-z]+\n(?:Level|Duration|Range):)", full_text)
        
        for section in spell_sections:
            if not section.strip():
                continue
            
            try:
                spell = self._parse_spell_section(section, current_magic_type, current_level, source_id)
                if spell:
                    spells.append(spell)
                    current_level = spell.level
            except Exception as e:
                logger.debug(f"Section not a spell: {e}")
        
        # Fallback: look for structured spell entries
        if not spells:
            spells.extend(self._extract_spells_fallback(pages, source_id))
        
        logger.info(f"Extracted {len(spells)} spells")
        return spells
    
    def extract_equipment_tables(
        self, 
        pdf_path: str,
        source_id: Optional[str] = None
    ) -> list[Item]:
        """
        Extract equipment tables with source tracking.
        
        Args:
            pdf_path: Path to the PDF file.
            source_id: Source identifier for tracking.
        
        Returns:
            List of Item objects with source references.
        """
        logger.info(f"Extracting equipment from {pdf_path}")
        items: list[Item] = []
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    tables = page.extract_tables()
                    
                    for table in tables:
                        if not table:
                            continue
                        
                        parsed_items = self._parse_equipment_table(
                            table, page_num + 1, source_id
                        )
                        items.extend(parsed_items)
        except Exception as e:
            logger.warning(f"pdfplumber extraction failed: {e}")
            items.extend(self._extract_equipment_fallback(pdf_path, source_id))
        
        logger.info(f"Extracted {len(items)} equipment items")
        return items
    
    def extract_npcs(
        self, 
        pdf_path: str,
        source_id: Optional[str] = None
    ) -> list[NPC]:
        """
        Extract NPC descriptions with source tracking.
        
        Args:
            pdf_path: Path to the PDF file.
            source_id: Source identifier for tracking.
        
        Returns:
            List of NPC objects with source references.
        """
        logger.info(f"Extracting NPCs from {pdf_path}")
        npcs: list[NPC] = []
        
        pages = self._extract_pages(pdf_path, source_id)
        
        npc_pattern = re.compile(
            r"([A-Z][a-z]+ [A-Z][a-z]+|[A-Z][a-z]+)\s*"
            r"\(([^)]+)\)"
            r"(?:[:\.]?\s*(.+?)(?=\n[A-Z]|\n\n|$))?",
            re.MULTILINE | re.DOTALL
        )
        
        for page in pages:
            for match in npc_pattern.finditer(page.text):
                try:
                    name = match.group(1).strip()
                    role_info = match.group(2).strip()
                    description = match.group(3).strip() if match.group(3) else ""
                    
                    if len(name) < 3 or name.lower() in ["the", "and", "for"]:
                        continue
                    
                    source_ref = self._create_source_reference(
                        source_id or BookType.CAMPAIGN_BOOK.value,
                        page_reference=f"p.{page.page_number}",
                        section="NPCs"
                    )
                    
                    npc = NPC(
                        name=name,
                        occupation=role_info,
                        description=description[:500] if description else f"{role_info} in Dolmenwood",
                        source=source_ref
                    )
                    npcs.append(npc)
                except Exception as e:
                    logger.debug(f"Failed to parse NPC: {e}")
        
        # Remove duplicates by name
        seen_names = set()
        unique_npcs = []
        for npc in npcs:
            if npc.name.lower() not in seen_names:
                seen_names.add(npc.name.lower())
                unique_npcs.append(npc)
        
        logger.info(f"Extracted {len(unique_npcs)} unique NPCs")
        return unique_npcs
    
    # =========================================================================
    # ADVENTURE MODULE EXTRACTION (v1.1)
    # =========================================================================
    
    def extract_adventure_module(
        self,
        pdf_path: str,
        source_id: str,
        adventure_title: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Extract content from an adventure module PDF.
        
        This method parses adventure-specific content including:
        - Keyed locations (rooms, areas)
        - Read-aloud text
        - Adventure synopsis and hooks
        - Monsters and NPCs specific to the adventure
        
        Args:
            pdf_path: Path to the adventure PDF.
            source_id: Source identifier for tracking.
            adventure_title: Optional override for adventure title.
        
        Returns:
            Dictionary containing:
            - module: AdventureModule object
            - locations: List of AdventureLocation objects
            - monsters: List of MonsterStatBlock objects
            - npcs: List of NPC objects
        """
        logger.info(f"Extracting adventure module from {pdf_path}")
        
        pages = self._extract_pages(pdf_path, source_id)
        full_text = "\n".join(page.text for page in pages)
        
        # Extract locations
        locations = self._extract_adventure_locations(pages, source_id)
        
        # Extract monsters from adventure
        monsters = self._extract_adventure_monsters(pages, source_id)
        
        # Extract NPCs from adventure
        npcs = self.extract_npcs(pdf_path, source_id)
        
        # Build the module metadata
        module = self._build_adventure_module(
            full_text=full_text,
            source_id=source_id,
            adventure_title=adventure_title,
            locations=locations,
            pdf_path=pdf_path
        )
        
        logger.info(f"Extracted adventure: {module.title} with {len(locations)} locations")
        
        return {
            "module": module,
            "locations": locations,
            "monsters": monsters,
            "npcs": npcs
        }
    
    def _extract_adventure_locations(
        self,
        pages: list[ExtractedPage],
        source_id: str
    ) -> list[AdventureLocation]:
        """Extract keyed locations from adventure pages."""
        locations: list[AdventureLocation] = []
        
        full_text = "\n".join(page.text for page in pages)
        
        # Find room headers
        room_matches = list(self.patterns.ROOM_HEADER.finditer(full_text))
        
        for i, match in enumerate(room_matches):
            try:
                number = match.group("number")
                name = match.group("name").strip()
                
                # Get room content until next room
                start_pos = match.end()
                if i + 1 < len(room_matches):
                    end_pos = room_matches[i + 1].start()
                else:
                    end_pos = len(full_text)
                
                room_text = full_text[start_pos:end_pos].strip()
                
                # Extract read-aloud text
                read_aloud = None
                read_match = self.patterns.READ_ALOUD.search(room_text)
                if read_match:
                    read_aloud = read_match.group("text").strip()
                
                # Extract features from room description
                features = self._extract_room_features(room_text)
                
                # Extract creatures mentioned
                creatures = self._extract_creature_references(room_text)
                
                # Extract exits
                exits = self._extract_exits(room_text)
                
                # Determine page number
                page_num = self._find_page_for_position(pages, match.start())
                
                source_ref = self._create_source_reference(
                    source_id,
                    page_reference=f"p.{page_num}" if page_num else None,
                    section=f"Room {number}"
                )
                
                location = AdventureLocation(
                    location_id=generate_id(f"{source_id}_{number}"),
                    adventure_id=source_id,
                    name=f"Room {number}: {name}" if number else name,
                    short_name=name,
                    number=number,
                    read_aloud_text=read_aloud,
                    dm_notes=self._clean_text(room_text),
                    features=features,
                    creatures=creatures,
                    exits=exits,
                    source=source_ref
                )
                locations.append(location)
                
            except Exception as e:
                logger.warning(f"Failed to parse adventure location: {e}")
        
        return locations
    
    def _extract_adventure_monsters(
        self,
        pages: list[ExtractedPage],
        source_id: str
    ) -> list[MonsterStatBlock]:
        """Extract monster stat blocks from adventure module."""
        full_text = "\n\n".join(page.text for page in pages)
        monsters: list[MonsterStatBlock] = []
        
        # Use standard stat block extraction
        for match in self.patterns.STAT_BLOCK_FULL.finditer(full_text):
            try:
                monster = self._parse_stat_block_match(match, source_id)
                if monster:
                    monsters.append(monster)
            except Exception as e:
                logger.debug(f"Failed to parse adventure monster: {e}")
        
        return monsters
    
    def _build_adventure_module(
        self,
        full_text: str,
        source_id: str,
        adventure_title: Optional[str],
        locations: list[AdventureLocation],
        pdf_path: str
    ) -> AdventureModule:
        """Build AdventureModule from extracted content."""
        
        # Try to extract title from first page
        title = adventure_title
        if not title:
            first_lines = full_text[:500].split("\n")
            for line in first_lines:
                line = line.strip()
                if len(line) > 5 and len(line) < 100:
                    title = line
                    break
            title = title or source_id.replace("_", " ").title()
        
        # Try to extract synopsis/hook from early text
        synopsis = ""
        hook = ""
        
        # Look for "Introduction" or "Background" sections
        intro_match = re.search(
            r"(?:Introduction|Background|Synopsis)[\s:]+(.+?)(?=\n[A-Z]{2,}|\n\d+\.|$)",
            full_text[:3000],
            re.IGNORECASE | re.DOTALL
        )
        if intro_match:
            synopsis = self._clean_text(intro_match.group(1))[:500]
        
        hook_match = re.search(
            r"(?:Adventure Hook|Getting Started|How to Use)[\s:]+(.+?)(?=\n[A-Z]{2,}|\n\d+\.|$)",
            full_text[:3000],
            re.IGNORECASE | re.DOTALL
        )
        if hook_match:
            hook = self._clean_text(hook_match.group(1))[:500]
        
        # Determine adventure type
        text_lower = full_text.lower()
        if "dungeon" in text_lower or "level" in text_lower:
            adventure_type = AdventureType.DUNGEON_CRAWL
        elif "wilderness" in text_lower or "hex" in text_lower:
            adventure_type = AdventureType.WILDERNESS
        elif "town" in text_lower or "city" in text_lower or "village" in text_lower:
            adventure_type = AdventureType.URBAN
        else:
            adventure_type = AdventureType.MIXED
        
        # Get source from content manager
        source = None
        if self.content_manager:
            source = self.content_manager.get_source(source_id)
        
        return AdventureModule(
            adventure_id=source_id,
            title=title,
            adventure_type=adventure_type,
            locations=[loc.location_id for loc in locations],
            starting_location=locations[0].location_id if locations else None,
            hook=hook or "An adventure awaits...",
            synopsis=synopsis or "A Dolmenwood adventure.",
            conclusion="The adventure concludes.",
            source=source
        )
    
    def _extract_room_features(self, room_text: str) -> list[str]:
        """Extract notable features from room description."""
        features: list[str] = []
        
        # Look for common feature indicators
        feature_patterns = [
            r"(?:contains?|features?|includes?):\s*(.+?)(?:\.|$)",
            r"(?:a|an|the)\s+(large|small|old|ancient|wooden|stone|iron)\s+(\w+)",
        ]
        
        for pattern in feature_patterns:
            for match in re.finditer(pattern, room_text, re.IGNORECASE):
                feature = match.group(1).strip() if match.lastindex else match.group(0).strip()
                if feature and len(feature) < 100:
                    features.append(feature)
        
        return features[:10]  # Limit to 10 features
    
    def _extract_creature_references(self, text: str) -> list[str]:
        """Extract creature/monster references from text."""
        creatures: list[str] = []
        
        # Common monster names in Dolmenwood
        monster_keywords = [
            "goblin", "skeleton", "zombie", "ghost", "spider", "wolf",
            "bear", "troll", "ogre", "fairy", "elf", "dwarf", "giant",
            "demon", "devil", "undead", "beast", "creature"
        ]
        
        text_lower = text.lower()
        for keyword in monster_keywords:
            if keyword in text_lower:
                creatures.append(keyword.title())
        
        return list(set(creatures))
    
    def _extract_exits(self, room_text: str) -> dict[str, str]:
        """Extract exit directions from room description."""
        exits: dict[str, str] = {}
        
        # Look for directional exit mentions
        exit_pattern = re.compile(
            r"(?:door|passage|corridor|tunnel|exit|stairs?)\s+"
            r"(?:to the\s+)?(?P<direction>north|south|east|west|up|down)",
            re.IGNORECASE
        )
        
        for match in exit_pattern.finditer(room_text):
            direction = match.group("direction").lower()
            # We don't know the destination, mark as unknown
            exits[direction] = "unknown"
        
        return exits
    
    def _find_page_for_position(
        self, 
        pages: list[ExtractedPage], 
        position: int
    ) -> Optional[int]:
        """Find which page contains a text position."""
        current_pos = 0
        for page in pages:
            current_pos += len(page.text) + 1  # +1 for newline
            if current_pos > position:
                return page.page_number
        return pages[-1].page_number if pages else None
    
    # =========================================================================
    # STAT BLOCK PARSING
    # =========================================================================
    
    def parse_stat_block_text(
        self, 
        text: str,
        source_id: Optional[str] = None
    ) -> MonsterStatBlock:
        """
        Parse a text stat block into a structured MonsterStatBlock.
        
        Args:
            text: Raw text containing stat block.
            source_id: Source identifier for tracking.
        
        Returns:
            MonsterStatBlock with parsed values and source reference.
        
        Raises:
            ParseError: If text cannot be parsed into a valid stat block.
        """
        lines = text.strip().split("\n")
        if not lines:
            raise ParseError("Empty stat block text")
        
        name = lines[0].strip()
        stats_text = " ".join(lines[1:])
        
        # Extract individual stats
        ac_match = self.patterns.STAT_LINE_AC.search(stats_text)
        hd_match = self.patterns.STAT_LINE_HD.search(stats_text)
        hp_match = self.patterns.STAT_LINE_HP.search(stats_text)
        mv_match = self.patterns.STAT_LINE_MV.search(stats_text)
        at_match = self.patterns.STAT_LINE_AT.search(stats_text)
        sv_match = self.patterns.STAT_LINE_SV.search(stats_text)
        ml_match = self.patterns.STAT_LINE_ML.search(stats_text)
        al_match = self.patterns.STAT_LINE_AL.search(stats_text)
        xp_match = self.patterns.STAT_LINE_XP.search(stats_text)
        na_match = self.patterns.STAT_LINE_NA.search(stats_text)
        tt_match = self.patterns.STAT_LINE_TT.search(stats_text)
        
        # Validate required fields
        if not ac_match:
            raise ParseError(f"Missing AC in stat block for {name}")
        if not hd_match:
            raise ParseError(f"Missing HD in stat block for {name}")
        if not ml_match:
            raise ParseError(f"Missing ML in stat block for {name}")
        
        # Parse values
        ac = int(ac_match.group(1))
        hd = hd_match.group(1).strip()
        hp = int(hp_match.group(1)) if hp_match else None
        mv = mv_match.group(1).strip() if mv_match else "120' (40')"
        attacks = [at_match.group(1).strip()] if at_match else []
        saves_as = sv_match.group(1) if sv_match else "F1"
        morale = int(ml_match.group(1))
        alignment = al_match.group(1).title() if al_match else None
        xp = int(xp_match.group(1).replace(",", "")) if xp_match else 0
        number_appearing = na_match.group(1) if na_match else "1d6"
        treasure_type = tt_match.group(1) if tt_match else None
        
        morale = max(2, min(12, morale))
        
        # Extract damage from attacks
        damage = []
        if attacks:
            for attack in attacks:
                dmg_match = self.patterns.DAMAGE_DICE.search(attack)
                if dmg_match:
                    damage.append(dmg_match.group(1))
        
        # Create source reference
        source_ref = self._create_source_reference(source_id) if source_id else None
        
        return MonsterStatBlock(
            name=name,
            armor_class=ac,
            hit_dice=hd,
            hp=hp,
            movement=mv,
            attacks=attacks,
            damage=damage,
            saves_as=saves_as,
            morale=morale,
            alignment=alignment,
            xp_value=xp,
            number_appearing=number_appearing,
            treasure_type=treasure_type,
            description=f"A monster from Dolmenwood.",
            source=source_ref
        )
    
    def _parse_stat_block_match(
        self, 
        match: re.Match,
        source_id: Optional[str] = None
    ) -> Optional[MonsterStatBlock]:
        """Parse a regex match into a MonsterStatBlock."""
        try:
            name = match.group("n").strip()
            ac = int(match.group("ac"))
            hd = match.group("hd").strip()
            hp = int(match.group("hp")) if match.group("hp") else None
            mv = match.group("mv").strip() if match.group("mv") else "120' (40')"
            attacks_str = match.group("attacks").strip() if match.group("attacks") else ""
            attacks = [attacks_str] if attacks_str else []
            saves_as = match.group("saves") if match.group("saves") else "F1"
            morale = int(match.group("morale")) if match.group("morale") else 7
            alignment = match.group("alignment").title() if match.group("alignment") else None
            xp = int(match.group("xp").replace(",", "")) if match.group("xp") else 0
            
            morale = max(2, min(12, morale))
            
            # Extract damage
            damage = []
            if attacks_str:
                dmg_match = self.patterns.DAMAGE_DICE.search(attacks_str)
                if dmg_match:
                    damage.append(dmg_match.group(1))
            
            source_ref = self._create_source_reference(source_id) if source_id else None
            
            return MonsterStatBlock(
                name=name,
                armor_class=ac,
                hit_dice=hd,
                hp=hp,
                movement=mv,
                attacks=attacks,
                damage=damage,
                saves_as=saves_as,
                morale=morale,
                alignment=alignment,
                xp_value=xp,
                description=f"A creature of Dolmenwood.",
                source=source_ref
            )
        except Exception as e:
            logger.warning(f"Failed to parse stat block match: {e}")
            return None
    
    def _extract_stat_blocks_fallback(
        self, 
        pages: list[ExtractedPage],
        source_id: Optional[str] = None
    ) -> list[MonsterStatBlock]:
        """Fallback method for stat block extraction."""
        monsters: list[MonsterStatBlock] = []
        
        for page in pages:
            lines = page.text.split("\n")
            i = 0
            
            while i < len(lines):
                line = lines[i].strip()
                
                # Check if this looks like a monster name (capitalized, not too long)
                if (line and line[0].isupper() and len(line) < 50 and 
                    not line.startswith(("Page", "Chapter", "Table"))):
                    
                    # Look ahead for stat line indicators
                    next_lines = " ".join(lines[i+1:i+5])
                    
                    if self.patterns.STAT_LINE_AC.search(next_lines):
                        # Found potential stat block
                        stat_text = line + "\n" + next_lines
                        
                        try:
                            monster = self.parse_stat_block_text(stat_text, source_id)
                            monsters.append(monster)
                            i += 5  # Skip processed lines
                            continue
                        except ParseError:
                            pass
                
                i += 1
        
        return monsters
    
    # =========================================================================
    # SPELL PARSING
    # =========================================================================
    
    def _parse_spell_section(
        self, 
        section: str, 
        magic_type: MagicType, 
        default_level: int,
        source_id: Optional[str] = None
    ) -> Optional[Spell]:
        """Parse a text section into a Spell object."""
        lines = section.strip().split("\n")
        if not lines:
            return None
        
        name = lines[0].strip()
        
        # Filter out non-spell headers
        if len(name) < 2 or len(name) > 50:
            return None
        if name.upper() == name and len(name) > 3:  # All caps = header
            return None
        
        # Extract spell properties
        section_text = "\n".join(lines)
        
        level_match = self.patterns.SPELL_LEVEL.search(section_text)
        duration_match = self.patterns.SPELL_DURATION.search(section_text)
        range_match = self.patterns.SPELL_RANGE.search(section_text)
        reversible = bool(self.patterns.SPELL_REVERSIBLE.search(section_text))
        
        level = int(level_match.group(1)) if level_match else default_level
        duration = duration_match.group(1).strip() if duration_match else "Instantaneous"
        spell_range = range_match.group(1).strip() if range_match else "Touch"
        
        # Get description (everything after the stat line)
        description_start = 0
        for pattern in [self.patterns.SPELL_LEVEL, self.patterns.SPELL_DURATION, self.patterns.SPELL_RANGE]:
            match = pattern.search(section_text)
            if match:
                description_start = max(description_start, match.end())
        
        description = section_text[description_start:].strip()
        if not description:
            description = f"A level {level} {magic_type.value} spell."
        
        source_ref = self._create_source_reference(
            source_id or BookType.PLAYERS_BOOK.value,
            section="Spells"
        ) if source_id else None
        
        return Spell(
            name=name,
            level=level,
            magic_type=magic_type,
            duration=duration,
            range=spell_range,
            description=self._clean_text(description),
            reversible=reversible,
            source=source_ref
        )
    
    def _extract_spells_fallback(
        self, 
        pages: list[ExtractedPage],
        source_id: Optional[str] = None
    ) -> list[Spell]:
        """Fallback spell extraction method."""
        spells: list[Spell] = []
        
        for page in pages:
            # Look for spell-like entries
            entries = re.split(r"\n(?=[A-Z][a-z]+ ?\n)", page.text)
            
            for entry in entries:
                if "Level:" in entry or "Duration:" in entry or "Range:" in entry:
                    try:
                        spell = self._parse_spell_section(
                            entry, MagicType.ARCANE, 1, source_id
                        )
                        if spell:
                            spells.append(spell)
                    except Exception:
                        pass
        
        return spells
    
    # =========================================================================
    # EQUIPMENT PARSING
    # =========================================================================
    
    def _parse_equipment_table(
        self, 
        table: list[list], 
        page_num: int,
        source_id: Optional[str] = None
    ) -> list[Item]:
        """Parse an equipment table into Item objects."""
        items: list[Item] = []
        
        if not table or len(table) < 2:
            return items
        
        # Identify column types from header
        header = [str(cell).lower() if cell else "" for cell in table[0]]
        
        name_col = -1
        cost_col = -1
        weight_col = -1
        damage_col = -1
        ac_col = -1
        
        for i, h in enumerate(header):
            if "name" in h or "item" in h or "equipment" in h:
                name_col = i
            elif "cost" in h or "price" in h or "sp" in h or "gp" in h:
                cost_col = i
            elif "weight" in h or "enc" in h:
                weight_col = i
            elif "damage" in h or "dmg" in h:
                damage_col = i
            elif "ac" in h or "armor" in h:
                ac_col = i
        
        # Validate this is an equipment table - must have at least one equipment-related column
        # beyond just a name column (cost, weight, damage, or AC)
        is_equipment_table = (cost_col >= 0 or weight_col >= 0 or damage_col >= 0 or ac_col >= 0)
        if not is_equipment_table:
            return items
        
        # Default to first column if no name found but we have equipment columns
        if name_col == -1:
            name_col = 0
        
        # Parse data rows
        for row in table[1:]:
            if not row or len(row) <= name_col:
                continue
            
            try:
                name = str(row[name_col]).strip() if row[name_col] else ""
                if not name or len(name) < 2:
                    continue
                
                # Parse cost
                cost = 0
                if cost_col >= 0 and cost_col < len(row) and row[cost_col]:
                    cost_str = str(row[cost_col]).replace(",", "")
                    cost_match = re.search(r"(\d+)", cost_str)
                    if cost_match:
                        cost = int(cost_match.group(1))
                
                # Parse weight
                weight = 0.0
                if weight_col >= 0 and weight_col < len(row) and row[weight_col]:
                    weight_str = str(row[weight_col])
                    weight_match = re.search(r"([\d.]+)", weight_str)
                    if weight_match:
                        weight = float(weight_match.group(1))
                
                # Parse damage (for weapons)
                damage = None
                if damage_col >= 0 and damage_col < len(row) and row[damage_col]:
                    dmg_str = str(row[damage_col]).strip()
                    if dmg_str and dmg_str != "-":
                        damage = dmg_str
                
                # Determine item type
                item_type = self._infer_item_type(name, row, damage_col, ac_col)
                
                source_ref = self._create_source_reference(
                    source_id or BookType.PLAYERS_BOOK.value,
                    page_reference=f"p.{page_num}",
                    section="Equipment"
                )
                
                item = Item(
                    name=name,
                    type=item_type,
                    cost_sp=cost,
                    weight=weight,
                    damage=damage,
                    source=source_ref
                )
                items.append(item)
                
            except Exception as e:
                logger.debug(f"Failed to parse equipment row: {e}")
        
        return items
    
    def _extract_equipment_fallback(
        self, 
        pdf_path: str,
        source_id: Optional[str] = None
    ) -> list[Item]:
        """Fallback equipment extraction from text."""
        items: list[Item] = []
        pages = self._extract_pages(pdf_path, source_id)
        
        for page in pages:
            for match in self.patterns.EQUIPMENT_ROW.finditer(page.text):
                try:
                    name = match.group("n").strip()
                    cost = int(match.group("cost").replace(",", ""))
                    weight = float(match.group("weight")) if match.group("weight") else 0.0
                    
                    source_ref = self._create_source_reference(
                        source_id or BookType.PLAYERS_BOOK.value,
                        page_reference=f"p.{page.page_number}",
                        section="Equipment"
                    )
                    
                    item = Item(
                        name=name,
                        type=self._infer_item_type(name),
                        cost_sp=cost,
                        weight=weight,
                        source=source_ref
                    )
                    items.append(item)
                except Exception as e:
                    logger.debug(f"Failed to parse equipment line: {e}")
        
        return items
    
    # =========================================================================
    # PAGE EXTRACTION
    # =========================================================================
    
    def _extract_pages(
        self, 
        pdf_path: str,
        source_id: Optional[str] = None
    ) -> list[ExtractedPage]:
        """
        Extract all pages from a PDF file.
        
        Uses caching to avoid re-extracting the same PDF.
        
        Args:
            pdf_path: Path to PDF file.
            source_id: Source identifier for tracking.
        
        Returns:
            List of ExtractedPage objects.
        """
        # Check cache
        if pdf_path in self._cache:
            return self._cache[pdf_path]
        
        pages: list[ExtractedPage] = []
        
        try:
            doc = fitz.Document(pdf_path)
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                # Extract text
                text = page.get_text()
                
                # Extract tables (basic rectangles for now)
                tables: list[list[list[str]]] = []
                
                # Extract images (as bytes)
                images: list[bytes] = []
                for img in page.get_images():
                    try:
                        xref = img[0]
                        base_image = doc.extract_image(xref)
                        images.append(base_image["image"])
                    except Exception:
                        pass
                
                extracted_page = ExtractedPage(
                    page_number=page_num + 1,
                    text=text,
                    tables=tables,
                    images=images,
                    source_id=source_id
                )
                pages.append(extracted_page)
            
            doc.close()
            
        except Exception as e:
            raise PDFExtractionError(f"Failed to extract pages from {pdf_path}: {e}")
        
        # Cache results
        self._cache[pdf_path] = pages
        
        return pages
    
    # =========================================================================
    # TEXT PROCESSING
    # =========================================================================
    
    def clean_and_chunk_text(
        self, 
        text: str, 
        chunk_size: int = 1000,
        overlap: int = 100
    ) -> list[str]:
        """
        Clean and chunk text for vector embedding.
        
        Args:
            text: Raw text to process.
            chunk_size: Target size of each chunk in characters.
            overlap: Number of characters to overlap between chunks.
        
        Returns:
            List of text chunks.
        """
        # Clean text first
        text = self._clean_text(text)
        
        if len(text) <= chunk_size:
            return [text] if text else []
        
        chunks: list[str] = []
        sentences = self._split_sentences(text)
        
        current_chunk = ""
        for sentence in sentences:
            if len(current_chunk) + len(sentence) <= chunk_size:
                current_chunk += " " + sentence if current_chunk else sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                # Start new chunk with overlap
                if overlap > 0 and chunks:
                    last_chunk = chunks[-1]
                    overlap_text = last_chunk[-overlap:] if len(last_chunk) > overlap else last_chunk
                    current_chunk = overlap_text + " " + sentence
                else:
                    current_chunk = sentence
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def _clean_text(self, text: str) -> str:
        """Clean extracted text by removing artifacts and normalizing whitespace."""
        if not text:
            return ""
        
        text = re.sub(r"\f", "\n", text)
        text = re.sub(r"^\d+\s*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        
        # Fix common OCR issues
        text = text.replace("ﬁ", "fi")
        text = text.replace("ﬂ", "fl")
        text = text.replace("'", "'")
        text = text.replace(""", '"')
        text = text.replace(""", '"')
        
        return text.strip()
    
    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return [s.strip() for s in sentences if s.strip()]
    
    # =========================================================================
    # INFERENCE HELPERS
    # =========================================================================
    
    def _infer_item_type(
        self, 
        name: str, 
        row: Optional[list] = None,
        damage_col: int = -1,
        ac_col: int = -1
    ) -> ItemType:
        """Infer item type from name and table context."""
        name_lower = name.lower()
        
        weapon_keywords = ["sword", "axe", "mace", "dagger", "bow", "spear", "hammer",
                          "crossbow", "staff", "club", "flail", "halberd", "lance",
                          "morning star", "pole arm", "sling", "trident", "warhammer"]
        if any(kw in name_lower for kw in weapon_keywords):
            return ItemType.WEAPON
        
        armor_keywords = ["armor", "armour", "mail", "plate", "leather", "chain", "scale", "helm", "helmet"]
        if any(kw in name_lower for kw in armor_keywords):
            return ItemType.ARMOR
        
        if "shield" in name_lower:
            return ItemType.SHIELD
        
        if row and ac_col >= 0 and ac_col < len(row) and row[ac_col]:
            ac_val = str(row[ac_col]).strip()
            if ac_val and ac_val != "-":
                return ItemType.ARMOR
        
        if row and damage_col >= 0 and damage_col < len(row) and row[damage_col]:
            dmg_val = str(row[damage_col]).strip()
            if dmg_val and dmg_val != "-" and self.patterns.DAMAGE_DICE.search(dmg_val):
                return ItemType.WEAPON
        
        consumable_keywords = ["potion", "scroll", "ration", "oil", "torch", "candle", "food", "water"]
        if any(kw in name_lower for kw in consumable_keywords):
            return ItemType.CONSUMABLE
        
        treasure_keywords = ["gem", "jewel", "gold", "silver", "coin", "treasure"]
        if any(kw in name_lower for kw in treasure_keywords):
            return ItemType.TREASURE
        
        magic_keywords = ["wand", "ring", "amulet", "talisman", "enchanted", "magic", "+1", "+2", "+3"]
        if any(kw in name_lower for kw in magic_keywords):
            return ItemType.MAGIC
        
        return ItemType.GEAR
    
    def _infer_terrain_type(self, description: str) -> TerrainType:
        """Infer terrain type from hex description."""
        desc_lower = description.lower()
        
        terrain_keywords = {
            TerrainType.FOREST: ["forest", "wood", "tree", "grove", "copse", "sylvan"],
            TerrainType.SWAMP: ["swamp", "marsh", "bog", "mire", "wetland", "fen"],
            TerrainType.HILLS: ["hill", "ridge", "highland", "knoll", "tor"],
            TerrainType.MOUNTAINS: ["mountain", "peak", "cliff", "crag"],
            TerrainType.PLAINS: ["plain", "field", "meadow", "grassland", "farmland"],
            TerrainType.WATER: ["lake", "pond", "water", "shore", "river", "stream", "brook", "creek"],
            TerrainType.SETTLEMENT: ["village", "town", "city", "hamlet", "settlement"],
        }
        
        for terrain, keywords in terrain_keywords.items():
            if any(kw in desc_lower for kw in keywords):
                return terrain
        
        return TerrainType.FOREST
    
    def _extract_encounters_from_text(self, text: str) -> list[str]:
        """Extract encounter descriptions from text."""
        encounters: list[str] = []
        
        encounter_patterns = [
            r"(?:encounter|wandering|lair):\s*(.+?)(?=\n\n|\n[A-Z]|$)",
            r"(?:may be found|can be encountered|lives here):\s*(.+?)(?=\n\n|$)",
            r"\d+d\d+\s+([A-Za-z\s]+?)(?:\s+(?:guard|patrol|inhabit))"
        ]
        
        for pattern in encounter_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
                encounter = match.group(1).strip()
                if encounter and len(encounter) < 200:
                    encounters.append(encounter)
        
        return encounters
    
    def _extract_npc_references(self, text: str) -> list[str]:
        """Extract NPC name references from text."""
        npcs: list[str] = []
        
        name_pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b")
        
        exclude_words = {"The", "This", "That", "There", "These", "Those", "When", "Where",
                        "What", "Which", "While", "Within", "Without", "After", "Before",
                        "During", "Through", "About", "Against", "Between", "Into", "Upon"}
        
        for match in name_pattern.finditer(text):
            name = match.group(1)
            if name not in exclude_words and len(name) > 2:
                npcs.append(name)
        
        return list(set(npcs))[:10]
    
    def _calculate_adjacent_hexes(self, hex_id: str) -> list[str]:
        """Calculate adjacent hex IDs for a given hex."""
        try:
            x = int(hex_id[:2])
            y = int(hex_id[2:])
        except (ValueError, IndexError):
            return []
        
        if x % 2 == 0:
            offsets = [
                (-1, -1), (1, -1),
                (-1, 0), (1, 0),
                (-1, 1), (1, 1)
            ]
        else:
            offsets = [
                (-1, 0), (1, 0),
                (-1, 0), (1, 0),
                (-1, 1), (1, 1)
            ]
        
        adjacent: list[str] = []
        for dx, dy in offsets:
            nx, ny = x + dx, y + dy
            if 0 <= nx <= 99 and 0 <= ny <= 99:
                adjacent.append(f"{nx:02d}{ny:02d}")
        
        return list(set(adjacent))
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    def get_page_count(self, pdf_path: str) -> int:
        """Get the number of pages in a PDF."""
        try:
            doc = fitz.Document(pdf_path)
            count = len(doc)
            doc.close()
            return count
        except Exception:
            return 0
    
    def extract_page_text(self, pdf_path: str, page_number: int) -> str:
        """Extract text from a specific page."""
        try:
            doc = fitz.Document(pdf_path)
            if page_number < 1 or page_number > len(doc):
                return ""
            text = doc[page_number - 1].get_text()
            doc.close()
            return text
        except Exception:
            return ""
    
    def search_text(self, pdf_path: str, query: str) -> list[tuple[int, str]]:
        """Search for text in a PDF."""
        results: list[tuple[int, str]] = []
        pages = self._extract_pages(pdf_path)
        
        query_lower = query.lower()
        for page in pages:
            if query_lower in page.text.lower():
                idx = page.text.lower().find(query_lower)
                start = max(0, idx - 50)
                end = min(len(page.text), idx + len(query) + 50)
                context = page.text[start:end]
                results.append((page.page_number, f"...{context}..."))
        
        return results
    
    def clear_cache(self) -> None:
        """Clear the internal page cache."""
        self._cache.clear()
        logger.info("PDF cache cleared")
    
    def get_cache_info(self) -> dict[str, int]:
        """Get cache statistics."""
        return {
            "cached_files": len(self._cache),
            "cached_pages": sum(len(pages) for pages in self._cache.values())
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_processor(
    players_book: Optional[str] = None,
    campaign_book: Optional[str] = None,
    monster_book: Optional[str] = None,
    content_manager: Optional[ContentManager] = None
) -> DolmenwoodPDFProcessor:
    """
    Create a PDF processor with the specified books.
    
    Args:
        players_book: Path to Player's Book PDF.
        campaign_book: Path to Campaign Book PDF.
        monster_book: Path to Monster Book PDF.
        content_manager: Optional ContentManager for source tracking.
    
    Returns:
        Configured DolmenwoodPDFProcessor instance.
    """
    return DolmenwoodPDFProcessor(
        pdf_paths={
            BookType.PLAYERS_BOOK.value: players_book,
            BookType.CAMPAIGN_BOOK.value: campaign_book,
            BookType.MONSTER_BOOK.value: monster_book
        },
        content_manager=content_manager
    )


def create_adventure_processor(
    adventure_path: str,
    adventure_id: str,
    content_manager: Optional[ContentManager] = None
) -> DolmenwoodPDFProcessor:
    """
    Create a PDF processor for an adventure module.
    
    Args:
        adventure_path: Path to adventure PDF.
        adventure_id: Unique identifier for the adventure.
        content_manager: Optional ContentManager for source tracking.
    
    Returns:
        Configured DolmenwoodPDFProcessor instance.
    """
    return DolmenwoodPDFProcessor(
        pdf_paths={adventure_id: adventure_path},
        content_manager=content_manager
    )


def parse_stat_block(text: str, source_id: Optional[str] = None) -> MonsterStatBlock:
    """
    Convenience function to parse a single stat block.
    
    Args:
        text: Raw stat block text.
        source_id: Optional source identifier.
    
    Returns:
        MonsterStatBlock object.
    """
    processor = DolmenwoodPDFProcessor({})
    return processor.parse_stat_block_text(text, source_id)


def chunk_text(text: str, chunk_size: int = 1000) -> list[str]:
    """
    Convenience function to chunk text for embeddings.
    
    Args:
        text: Text to chunk.
        chunk_size: Target chunk size in characters.
    
    Returns:
        List of text chunks.
    """
    processor = DolmenwoodPDFProcessor({})
    return processor.clean_and_chunk_text(text, chunk_size)
