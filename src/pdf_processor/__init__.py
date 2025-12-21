"""
Dolmenwood PDF Processor Module

This module provides tools for extracting and parsing content from
Dolmenwood rulebook PDFs.

Main classes:
    DolmenwoodPDFProcessor: Main processor for extracting all content types
    
Convenience functions:
    create_processor: Create a processor with specified book paths
    parse_stat_block: Parse a single stat block text
    chunk_text: Chunk text for vector embeddings
"""

from .dolmenwood_parser import (
    # Main class
    DolmenwoodPDFProcessor,
    
    # Data classes
    ExtractedPage,
    TextChunk,
    ExtractionResult,
    
    # Enums
    BookType,
    ContentSection,
    
    # Exceptions
    PDFProcessorError,
    PDFExtractionError,
    ParseError,
    
    # Convenience functions
    create_processor,
    parse_stat_block,
    chunk_text,
)

__all__ = [
    # Main class
    "DolmenwoodPDFProcessor",
    
    # Data classes
    "ExtractedPage",
    "TextChunk", 
    "ExtractionResult",
    
    # Enums
    "BookType",
    "ContentSection",
    
    # Exceptions
    "PDFProcessorError",
    "PDFExtractionError",
    "ParseError",
    
    # Convenience functions
    "create_processor",
    "parse_stat_block",
    "chunk_text",
]
