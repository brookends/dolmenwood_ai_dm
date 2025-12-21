"""
JSON Content Loader for Dolmenwood AI DM.

Provides a reliable way to load game content from manually curated JSON files,
bypassing the fragile PDF extraction process.

Usage:
    from content_loader import ContentLoader
    
    loader = ContentLoader("data/content")
    result = loader.load_all()
    print(f"Loaded {result['monsters']} monsters")
"""

from .loader import ContentLoader, LoadResult
from .extractor import LLMExtractor, ExtractionConfig

__all__ = [
    "ContentLoader",
    "LoadResult", 
    "LLMExtractor",
    "ExtractionConfig",
]
