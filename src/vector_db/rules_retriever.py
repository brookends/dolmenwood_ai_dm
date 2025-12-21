"""
Dolmenwood AI Dungeon Master - Vector Database Rules Retriever

This module provides semantic search functionality using ChromaDB
with OpenAI embeddings for rules, monsters, locations, spells, and items.

Features:
- Multiple specialized collections for different content types
- OpenAI text-embedding-3-small for high-quality embeddings
- Metadata filtering for precise searches
- Source-aware retrieval with attribution
- Batch indexing for PDF extraction results

Author: AI Dungeon Master Project
Version: 1.0
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Union

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

# Configure logging
logger = logging.getLogger(__name__)


class CollectionType(str, Enum):
    """Types of collections in the vector database."""
    RULES = "rules"
    MONSTERS = "monsters"
    LOCATIONS = "locations"  # Hex locations
    SPELLS = "spells"
    ITEMS = "items"
    NPCS = "npcs"
    ADVENTURES = "adventures"  # Adventure locations/rooms
    LORE = "lore"  # General world lore and setting info


@dataclass
class SearchResult:
    """A single search result from the vector database."""
    id: str
    content: str
    metadata: dict[str, Any]
    distance: float
    collection: CollectionType
    
    @property
    def relevance_score(self) -> float:
        """Convert distance to a relevance score (0-1, higher is better)."""
        # ChromaDB uses L2 distance by default
        # Convert to relevance score: 1 / (1 + distance)
        return 1.0 / (1.0 + self.distance)
    
    @property
    def source_id(self) -> Optional[str]:
        """Get source ID from metadata."""
        return self.metadata.get("source_id")
    
    @property
    def source_page(self) -> Optional[str]:
        """Get source page reference from metadata."""
        return self.metadata.get("page_reference")
    
    def to_context_string(self) -> str:
        """Format as context string for LLM."""
        source_info = ""
        if self.source_id:
            source_info = f" [Source: {self.source_id}"
            if self.source_page:
                source_info += f", {self.source_page}"
            source_info += "]"
        
        return f"{self.content}{source_info}"


@dataclass
class SearchOptions:
    """Options for vector search."""
    n_results: int = 5
    min_relevance: float = 0.0
    include_metadata: bool = True
    source_filter: Optional[str] = None
    category_filter: Optional[str] = None
    level_filter: Optional[int] = None
    type_filter: Optional[str] = None


class EmbeddingProvider:
    """Abstract embedding provider interface."""
    
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents."""
        raise NotImplementedError
    
    def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        raise NotImplementedError


class OpenAIEmbeddings(EmbeddingProvider):
    """OpenAI embedding provider using text-embedding-3-small."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "text-embedding-3-small"):
        """
        Initialize OpenAI embeddings.
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var).
            model: Embedding model to use.
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key required. Set OPENAI_API_KEY environment variable.")
        
        self.model = model
        self._client: Optional[Any] = None
    
    @property
    def client(self):
        """Lazy-load OpenAI client."""
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
        return self._client
    
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents."""
        if not texts:
            return []
        
        # OpenAI has a limit on batch size
        batch_size = 100
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = self.client.embeddings.create(
                model=self.model,
                input=batch
            )
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)
        
        return all_embeddings
    
    def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        response = self.client.embeddings.create(
            model=self.model,
            input=text
        )
        return response.data[0].embedding


class MockEmbeddings(EmbeddingProvider):
    """Mock embedding provider for testing without API calls."""
    
    def __init__(self, dimension: int = 1536):
        self.dimension = dimension
    
    def _hash_to_embedding(self, text: str) -> list[float]:
        """Generate deterministic pseudo-embeddings from text hash."""
        import struct
        
        # Create hash of text
        text_hash = hashlib.sha256(text.encode()).digest()
        
        # Generate embedding from hash (deterministic)
        embedding = []
        for i in range(self.dimension):
            # Use different parts of hash for each dimension
            idx = i % 32
            value = text_hash[idx] / 255.0 - 0.5  # Normalize to [-0.5, 0.5]
            # Add variation based on position
            value += (i / self.dimension - 0.5) * 0.1
            embedding.append(value)
        
        return embedding
    
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents."""
        return [self._hash_to_embedding(text) for text in texts]
    
    def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        return self._hash_to_embedding(text)


class LocalEmbeddings(EmbeddingProvider):
    """
    Local embedding provider using sentence-transformers.
    
    Runs entirely locally - no API calls, no costs.
    Uses the all-MiniLM-L6-v2 model by default (fast and good quality).
    
    Resource Requirements:
        - RAM: ~1-2GB for model + processing
        - CPU: Works on CPU but slow (~50-100 items/minute)
        - GPU: Optional, significantly faster if available
    """
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2", batch_size: int = 32):
        """
        Initialize local embeddings.
        
        Args:
            model_name: HuggingFace model name. Good options:
                - "all-MiniLM-L6-v2" (fast, 384 dims, ~80MB)
                - "all-mpnet-base-v2" (better quality, 768 dims, ~420MB)
            batch_size: Number of texts to embed at once. Lower = less memory.
        """
        self.model_name = model_name
        self.batch_size = batch_size
        self._model = None
    
    @property
    def model(self):
        """Lazy-load the model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading local embedding model: {self.model_name}")
                logger.info("This may take a moment and use ~1GB RAM...")
                self._model = SentenceTransformer(self.model_name)
                logger.info(f"Local embedding model loaded (dim={self._model.get_sentence_embedding_dimension()})")
            except ImportError:
                raise ImportError(
                    "sentence-transformers required for local embeddings. "
                    "Install with: pip install sentence-transformers torch transformers"
                )
        return self._model
    
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of documents with batching for memory efficiency.
        
        Processes in small batches to avoid memory exhaustion.
        """
        if not texts:
            return []
        
        import gc
        
        all_embeddings = []
        total = len(texts)
        
        for i in range(0, total, self.batch_size):
            batch = texts[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (total + self.batch_size - 1) // self.batch_size
            
            if total > self.batch_size:
                logger.info(f"Embedding batch {batch_num}/{total_batches} ({i+1}-{min(i+len(batch), total)}/{total})")
            
            # Encode batch
            embeddings = self.model.encode(batch, show_progress_bar=False)
            all_embeddings.extend([emb.tolist() for emb in embeddings])
            
            # Free memory between batches
            del embeddings
            gc.collect()
        
        return all_embeddings
    
    def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        embedding = self.model.encode(text)
        return embedding.tolist()


class RulesRetriever:
    """
    Vector database for semantic search of Dolmenwood rules and content.
    
    Uses ChromaDB for vector storage and OpenAI embeddings for text encoding.
    Supports multiple collections for different content types with metadata
    filtering and source attribution.
    
    Example:
        >>> retriever = RulesRetriever("./data/vectordb")
        >>> retriever.index_rules(rules_list)
        >>> results = retriever.search_rules("how does morale work", n_results=3)
        >>> for result in results:
        ...     print(f"{result.relevance_score:.2f}: {result.content[:100]}...")
    """
    
    # Collection configurations
    COLLECTION_CONFIGS = {
        CollectionType.RULES: {
            "name": "dolmenwood_rules",
            "metadata_fields": ["category", "title", "source_id", "page_reference", "content_type"],
        },
        CollectionType.MONSTERS: {
            "name": "dolmenwood_monsters",
            "metadata_fields": ["name", "hit_dice", "alignment", "source_id", "habitat"],
        },
        CollectionType.LOCATIONS: {
            "name": "dolmenwood_locations",
            "metadata_fields": ["hex_id", "name", "terrain", "source_id", "has_settlement"],
        },
        CollectionType.SPELLS: {
            "name": "dolmenwood_spells",
            "metadata_fields": ["name", "level", "magic_type", "source_id", "reversible"],
        },
        CollectionType.ITEMS: {
            "name": "dolmenwood_items",
            "metadata_fields": ["name", "type", "cost", "source_id", "is_magical"],
        },
        CollectionType.NPCS: {
            "name": "dolmenwood_npcs",
            "metadata_fields": ["name", "location", "faction", "source_id", "is_combatant"],
        },
        CollectionType.ADVENTURES: {
            "name": "dolmenwood_adventures",
            "metadata_fields": ["adventure_id", "location_number", "name", "source_id"],
        },
        CollectionType.LORE: {
            "name": "dolmenwood_lore",
            "metadata_fields": ["topic", "category", "source_id", "page_reference"],
        },
    }
    
    def __init__(
        self,
        persist_directory: str = "./data/vectordb",
        embedding_provider: Optional[EmbeddingProvider] = None,
        use_mock_embeddings: bool = False,
        use_local_embeddings: bool = False,
        api_key: Optional[str] = None
    ):
        """
        Initialize the Rules Retriever.
        
        Args:
            persist_directory: Directory to persist ChromaDB data.
            embedding_provider: Custom embedding provider (overrides other options).
            use_mock_embeddings: Use mock embeddings for testing (no API calls, poor quality).
            use_local_embeddings: Use local sentence-transformers (no API calls, good quality).
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var).
        """
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        
        # Initialize embedding provider (priority: custom > local > mock > openai)
        if embedding_provider:
            self.embeddings = embedding_provider
        elif use_local_embeddings:
            self.embeddings = LocalEmbeddings()
            logger.info("Using local embeddings (sentence-transformers)")
        elif use_mock_embeddings:
            self.embeddings = MockEmbeddings()
            logger.info("Using mock embeddings (no API calls)")
        else:
            self.embeddings = OpenAIEmbeddings(api_key=api_key)
            logger.info("Using OpenAI embeddings")
        
        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=str(self.persist_directory),
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # Initialize collections
        self._collections: dict[CollectionType, chromadb.Collection] = {}
        self._init_collections()
        
        logger.info(f"RulesRetriever initialized with persist directory: {self.persist_directory}")
    
    def _init_collections(self) -> None:
        """Initialize all collections."""
        for collection_type, config in self.COLLECTION_CONFIGS.items():
            collection = self.client.get_or_create_collection(
                name=config["name"],
                metadata={"type": collection_type.value}
            )
            self._collections[collection_type] = collection
            logger.debug(f"Initialized collection: {config['name']}")
    
    def _get_collection(self, collection_type: CollectionType) -> chromadb.Collection:
        """Get a collection by type."""
        return self._collections[collection_type]
    
    def _generate_id(self, content: str, prefix: str = "doc") -> str:
        """Generate a unique ID for a document."""
        content_hash = hashlib.md5(content.encode()).hexdigest()[:12]
        return f"{prefix}_{content_hash}"
    
    # =========================================================================
    # INDEXING METHODS
    # =========================================================================
    
    def index_rules(
        self,
        rules: list[Any],
        batch_size: int = 100
    ) -> int:
        """
        Index game rules into the vector database.
        
        Args:
            rules: List of GameRule objects to index.
            batch_size: Number of documents to process at once.
            
        Returns:
            Number of rules indexed.
        """
        collection = self._get_collection(CollectionType.RULES)
        indexed = 0
        
        for i in range(0, len(rules), batch_size):
            batch = rules[i:i + batch_size]
            
            ids = []
            documents = []
            metadatas = []
            
            for rule in batch:
                # Create searchable text
                doc_text = f"{rule.title}\n\n{rule.content}"
                doc_id = rule.rule_id if hasattr(rule, 'rule_id') else self._generate_id(doc_text, "rule")
                
                # Build metadata
                metadata = {
                    "category": rule.category,
                    "title": rule.title,
                    "content_type": rule.content_type.value if hasattr(rule, 'content_type') and rule.content_type else "rule",
                }
                
                # Add source info if available
                if hasattr(rule, 'source') and rule.source:
                    metadata["source_id"] = rule.source.source_id
                    if rule.source.page_reference:
                        metadata["page_reference"] = rule.source.page_reference
                
                ids.append(doc_id)
                documents.append(doc_text)
                metadatas.append(metadata)
            
            # Generate embeddings and upsert
            embeddings = self.embeddings.embed_documents(documents)
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings
            )
            indexed += len(batch)
            logger.debug(f"Indexed {indexed} rules...")
        
        logger.info(f"Indexed {indexed} rules total")
        return indexed
    
    def index_monsters(
        self,
        monsters: list[Any],
        batch_size: int = 100
    ) -> int:
        """
        Index monster stat blocks into the vector database.
        
        Args:
            monsters: List of MonsterStatBlock objects.
            batch_size: Number to process at once.
            
        Returns:
            Number of monsters indexed.
        """
        collection = self._get_collection(CollectionType.MONSTERS)
        indexed = 0
        
        for i in range(0, len(monsters), batch_size):
            batch = monsters[i:i + batch_size]
            
            ids = []
            documents = []
            metadatas = []
            
            for monster in batch:
                # Create rich searchable text
                doc_text = self._format_monster_text(monster)
                doc_id = monster.monster_id if hasattr(monster, 'monster_id') else self._generate_id(doc_text, "mon")
                
                # Build metadata
                metadata = {
                    "name": monster.name,
                    "hit_dice": monster.hit_dice,
                    "alignment": monster.alignment if hasattr(monster, 'alignment') else "Neutral",
                    "armor_class": monster.armor_class,
                    "morale": monster.morale,
                }
                
                # Add habitat as comma-separated string
                if hasattr(monster, 'habitat') and monster.habitat:
                    metadata["habitat"] = ",".join(monster.habitat) if isinstance(monster.habitat, list) else str(monster.habitat)
                
                # Add source info
                if hasattr(monster, 'source') and monster.source:
                    metadata["source_id"] = monster.source.source_id
                
                ids.append(doc_id)
                documents.append(doc_text)
                metadatas.append(metadata)
            
            embeddings = self.embeddings.embed_documents(documents)
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings
            )
            indexed += len(batch)
        
        logger.info(f"Indexed {indexed} monsters")
        return indexed
    
    def _format_monster_text(self, monster: Any) -> str:
        """Format monster data as searchable text."""
        parts = [
            f"# {monster.name}",
            f"AC {monster.armor_class}, HD {monster.hit_dice}, ML {monster.morale}",
        ]
        
        if hasattr(monster, 'movement') and monster.movement:
            parts.append(f"Movement: {monster.movement}")
        
        if hasattr(monster, 'attacks') and monster.attacks:
            attacks_str = ", ".join(monster.attacks) if isinstance(monster.attacks, list) else str(monster.attacks)
            parts.append(f"Attacks: {attacks_str}")
        
        if hasattr(monster, 'special_abilities') and monster.special_abilities:
            abilities_str = ", ".join(monster.special_abilities) if isinstance(monster.special_abilities, list) else str(monster.special_abilities)
            parts.append(f"Special: {abilities_str}")
        
        if hasattr(monster, 'description') and monster.description:
            parts.append(f"\n{monster.description}")
        
        return "\n".join(parts)
    
    def index_locations(
        self,
        locations: list[Any],
        batch_size: int = 100
    ) -> int:
        """
        Index hex locations into the vector database.
        
        Args:
            locations: List of HexLocation objects.
            batch_size: Number to process at once.
            
        Returns:
            Number of locations indexed.
        """
        collection = self._get_collection(CollectionType.LOCATIONS)
        indexed = 0
        
        for i in range(0, len(locations), batch_size):
            batch = locations[i:i + batch_size]
            
            ids = []
            documents = []
            metadatas = []
            
            for location in batch:
                doc_text = self._format_location_text(location)
                doc_id = location.hex_id if hasattr(location, 'hex_id') else self._generate_id(doc_text, "hex")
                
                metadata = {
                    "hex_id": location.hex_id,
                    "name": location.name if hasattr(location, 'name') else f"Hex {location.hex_id}",
                    "terrain": location.terrain_type.value if hasattr(location, 'terrain_type') and location.terrain_type else "unknown",
                }
                
                # Settlement info
                if hasattr(location, 'settlements') and location.settlements:
                    metadata["has_settlement"] = "true"
                    metadata["settlement_names"] = ",".join([s.name for s in location.settlements if hasattr(s, 'name')])
                else:
                    metadata["has_settlement"] = "false"
                
                # Source info
                if hasattr(location, 'source') and location.source:
                    metadata["source_id"] = location.source.source_id
                
                ids.append(doc_id)
                documents.append(doc_text)
                metadatas.append(metadata)
            
            embeddings = self.embeddings.embed_documents(documents)
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings
            )
            indexed += len(batch)
        
        logger.info(f"Indexed {indexed} locations")
        return indexed
    
    def _format_location_text(self, location: Any) -> str:
        """Format hex location as searchable text."""
        parts = [f"# Hex {location.hex_id}"]
        
        if hasattr(location, 'name') and location.name:
            parts.append(f"**{location.name}**")
        
        if hasattr(location, 'terrain_type') and location.terrain_type:
            terrain = location.terrain_type.value if hasattr(location.terrain_type, 'value') else str(location.terrain_type)
            parts.append(f"Terrain: {terrain}")
        
        if hasattr(location, 'description') and location.description:
            parts.append(f"\n{location.description}")
        
        if hasattr(location, 'points_of_interest') and location.points_of_interest:
            parts.append("\nPoints of Interest:")
            for poi in location.points_of_interest:
                parts.append(f"- {poi}")
        
        if hasattr(location, 'settlements') and location.settlements:
            parts.append("\nSettlements:")
            for settlement in location.settlements:
                name = settlement.name if hasattr(settlement, 'name') else str(settlement)
                parts.append(f"- {name}")
        
        return "\n".join(parts)
    
    def index_spells(
        self,
        spells: list[Any],
        batch_size: int = 100
    ) -> int:
        """
        Index spells into the vector database.
        
        Args:
            spells: List of Spell objects.
            batch_size: Number to process at once.
            
        Returns:
            Number of spells indexed.
        """
        collection = self._get_collection(CollectionType.SPELLS)
        indexed = 0
        
        for i in range(0, len(spells), batch_size):
            batch = spells[i:i + batch_size]
            
            ids = []
            documents = []
            metadatas = []
            
            for spell in batch:
                doc_text = self._format_spell_text(spell)
                doc_id = spell.spell_id if hasattr(spell, 'spell_id') else self._generate_id(doc_text, "spell")
                
                metadata = {
                    "name": spell.name,
                    "level": spell.level,
                    "magic_type": spell.magic_type.value if hasattr(spell.magic_type, 'value') else str(spell.magic_type),
                    "reversible": "true" if hasattr(spell, 'reversible') and spell.reversible else "false",
                }
                
                if hasattr(spell, 'source') and spell.source:
                    metadata["source_id"] = spell.source.source_id
                
                ids.append(doc_id)
                documents.append(doc_text)
                metadatas.append(metadata)
            
            embeddings = self.embeddings.embed_documents(documents)
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings
            )
            indexed += len(batch)
        
        logger.info(f"Indexed {indexed} spells")
        return indexed
    
    def _format_spell_text(self, spell: Any) -> str:
        """Format spell as searchable text."""
        magic_type = spell.magic_type.value if hasattr(spell.magic_type, 'value') else str(spell.magic_type)
        
        parts = [
            f"# {spell.name}",
            f"Level {spell.level} {magic_type} spell",
        ]
        
        if hasattr(spell, 'duration') and spell.duration:
            parts.append(f"Duration: {spell.duration}")
        
        if hasattr(spell, 'range') and spell.range:
            parts.append(f"Range: {spell.range}")
        
        if hasattr(spell, 'reversible') and spell.reversible:
            parts.append("(Reversible)")
        
        if hasattr(spell, 'description') and spell.description:
            parts.append(f"\n{spell.description}")
        
        return "\n".join(parts)
    
    def index_items(
        self,
        items: list[Any],
        batch_size: int = 100
    ) -> int:
        """
        Index items into the vector database.
        
        Args:
            items: List of Item objects.
            batch_size: Number to process at once.
            
        Returns:
            Number of items indexed.
        """
        collection = self._get_collection(CollectionType.ITEMS)
        indexed = 0
        
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            
            ids = []
            documents = []
            metadatas = []
            
            for item in batch:
                doc_text = self._format_item_text(item)
                doc_id = item.item_id if hasattr(item, 'item_id') else self._generate_id(doc_text, "item")
                
                metadata = {
                    "name": item.name,
                    "type": item.type.value if hasattr(item.type, 'value') else str(item.type),
                    "cost": item.cost_sp if hasattr(item, 'cost_sp') else 0,
                    "is_magical": "true" if hasattr(item, 'is_magical') and item.is_magical else "false",
                }
                
                if hasattr(item, 'source') and item.source:
                    metadata["source_id"] = item.source.source_id
                
                ids.append(doc_id)
                documents.append(doc_text)
                metadatas.append(metadata)
            
            embeddings = self.embeddings.embed_documents(documents)
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings
            )
            indexed += len(batch)
        
        logger.info(f"Indexed {indexed} items")
        return indexed
    
    def _format_item_text(self, item: Any) -> str:
        """Format item as searchable text."""
        item_type = item.type.value if hasattr(item.type, 'value') else str(item.type)
        
        parts = [f"# {item.name}", f"Type: {item_type}"]
        
        if hasattr(item, 'cost_sp') and item.cost_sp:
            parts.append(f"Cost: {item.cost_sp} sp")
        
        if hasattr(item, 'weight') and item.weight:
            parts.append(f"Weight: {item.weight}")
        
        if hasattr(item, 'damage') and item.damage:
            parts.append(f"Damage: {item.damage}")
        
        if hasattr(item, 'ac_bonus') and item.ac_bonus:
            parts.append(f"AC Bonus: {item.ac_bonus}")
        
        if hasattr(item, 'is_magical') and item.is_magical:
            parts.append("(Magical)")
            if hasattr(item, 'magical_properties') and item.magical_properties:
                parts.append(f"Properties: {item.magical_properties}")
        
        if hasattr(item, 'description') and item.description:
            parts.append(f"\n{item.description}")
        
        return "\n".join(parts)
    
    def index_npcs(
        self,
        npcs: list[Any],
        batch_size: int = 100
    ) -> int:
        """
        Index NPCs into the vector database.
        
        Args:
            npcs: List of NPC objects.
            batch_size: Number to process at once.
            
        Returns:
            Number of NPCs indexed.
        """
        collection = self._get_collection(CollectionType.NPCS)
        indexed = 0
        
        for i in range(0, len(npcs), batch_size):
            batch = npcs[i:i + batch_size]
            
            ids = []
            documents = []
            metadatas = []
            
            for npc in batch:
                doc_text = self._format_npc_text(npc)
                doc_id = npc.npc_id if hasattr(npc, 'npc_id') else self._generate_id(doc_text, "npc")
                
                metadata = {
                    "name": npc.name,
                    "is_combatant": "true" if hasattr(npc, 'is_combatant') and npc.is_combatant else "false",
                }
                
                if hasattr(npc, 'location_id') and npc.location_id:
                    metadata["location"] = npc.location_id
                
                if hasattr(npc, 'faction') and npc.faction:
                    metadata["faction"] = npc.faction
                
                if hasattr(npc, 'source') and npc.source:
                    metadata["source_id"] = npc.source.source_id
                
                ids.append(doc_id)
                documents.append(doc_text)
                metadatas.append(metadata)
            
            embeddings = self.embeddings.embed_documents(documents)
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings
            )
            indexed += len(batch)
        
        logger.info(f"Indexed {indexed} NPCs")
        return indexed
    
    def _format_npc_text(self, npc: Any) -> str:
        """Format NPC as searchable text."""
        parts = [f"# {npc.name}"]
        
        if hasattr(npc, 'kindred') and npc.kindred:
            parts.append(f"Kindred: {npc.kindred}")
        
        if hasattr(npc, 'occupation') and npc.occupation:
            parts.append(f"Occupation: {npc.occupation}")
        
        if hasattr(npc, 'faction') and npc.faction:
            parts.append(f"Faction: {npc.faction}")
        
        if hasattr(npc, 'personality') and npc.personality:
            parts.append(f"Personality: {npc.personality}")
        
        if hasattr(npc, 'appearance') and npc.appearance:
            parts.append(f"Appearance: {npc.appearance}")
        
        if hasattr(npc, 'goals') and npc.goals:
            parts.append(f"Goals: {', '.join(npc.goals) if isinstance(npc.goals, list) else npc.goals}")
        
        if hasattr(npc, 'initial_dialogue') and npc.initial_dialogue:
            parts.append(f"\nDialogue: \"{npc.initial_dialogue}\"")
        
        return "\n".join(parts)
    
    def index_adventure_locations(
        self,
        locations: list[Any],
        batch_size: int = 100
    ) -> int:
        """
        Index adventure locations (keyed rooms/areas) into the vector database.
        
        Args:
            locations: List of AdventureLocation objects.
            batch_size: Number to process at once.
            
        Returns:
            Number of locations indexed.
        """
        collection = self._get_collection(CollectionType.ADVENTURES)
        indexed = 0
        
        for i in range(0, len(locations), batch_size):
            batch = locations[i:i + batch_size]
            
            ids = []
            documents = []
            metadatas = []
            
            for location in batch:
                doc_text = self._format_adventure_location_text(location)
                doc_id = location.location_id if hasattr(location, 'location_id') else self._generate_id(doc_text, "advloc")
                
                metadata = {
                    "adventure_id": location.adventure_id if hasattr(location, 'adventure_id') else "",
                    "name": location.name,
                }
                
                if hasattr(location, 'number') and location.number:
                    metadata["location_number"] = location.number
                
                if hasattr(location, 'source') and location.source:
                    metadata["source_id"] = location.source.source_id
                
                ids.append(doc_id)
                documents.append(doc_text)
                metadatas.append(metadata)
            
            embeddings = self.embeddings.embed_documents(documents)
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings
            )
            indexed += len(batch)
        
        logger.info(f"Indexed {indexed} adventure locations")
        return indexed
    
    def _format_adventure_location_text(self, location: Any) -> str:
        """Format adventure location as searchable text."""
        parts = []
        
        if hasattr(location, 'number') and location.number:
            parts.append(f"# {location.number}. {location.name}")
        else:
            parts.append(f"# {location.name}")
        
        if hasattr(location, 'read_aloud') and location.read_aloud:
            parts.append(f"\n> {location.read_aloud}")
        
        if hasattr(location, 'description') and location.description:
            parts.append(f"\n{location.description}")
        
        if hasattr(location, 'features') and location.features:
            parts.append("\nFeatures:")
            for feature in location.features:
                parts.append(f"- {feature}")
        
        if hasattr(location, 'creatures') and location.creatures:
            parts.append(f"\nCreatures: {', '.join(location.creatures)}")
        
        if hasattr(location, 'treasure') and location.treasure:
            parts.append(f"\nTreasure: {location.treasure}")
        
        return "\n".join(parts)
    
    def index_lore(
        self,
        lore_entries: list[dict[str, Any]],
        batch_size: int = 100
    ) -> int:
        """
        Index world lore entries into the vector database.
        
        Args:
            lore_entries: List of dicts with 'topic', 'content', 'category', and optionally 'source_id'.
            batch_size: Number to process at once.
            
        Returns:
            Number of entries indexed.
        """
        collection = self._get_collection(CollectionType.LORE)
        indexed = 0
        
        for i in range(0, len(lore_entries), batch_size):
            batch = lore_entries[i:i + batch_size]
            
            ids = []
            documents = []
            metadatas = []
            
            for entry in batch:
                doc_text = f"# {entry.get('topic', 'Lore')}\n\n{entry.get('content', '')}"
                doc_id = entry.get('id', self._generate_id(doc_text, "lore"))
                
                metadata = {
                    "topic": entry.get('topic', ''),
                    "category": entry.get('category', 'general'),
                }
                
                if entry.get('source_id'):
                    metadata["source_id"] = entry['source_id']
                
                if entry.get('page_reference'):
                    metadata["page_reference"] = entry['page_reference']
                
                ids.append(doc_id)
                documents.append(doc_text)
                metadatas.append(metadata)
            
            embeddings = self.embeddings.embed_documents(documents)
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings
            )
            indexed += len(batch)
        
        logger.info(f"Indexed {indexed} lore entries")
        return indexed
    
    def index_extraction_result(self, result: Any) -> dict[str, int]:
        """
        Index all content from a PDF extraction result.
        
        Args:
            result: ExtractionResult from PDF processor.
            
        Returns:
            Dict with counts of indexed items per type.
        """
        counts = {}
        
        if hasattr(result, 'rules') and result.rules:
            counts['rules'] = self.index_rules(result.rules)
        
        if hasattr(result, 'monsters') and result.monsters:
            counts['monsters'] = self.index_monsters(result.monsters)
        
        if hasattr(result, 'hexes') and result.hexes:
            counts['locations'] = self.index_locations(result.hexes)
        
        if hasattr(result, 'spells') and result.spells:
            counts['spells'] = self.index_spells(result.spells)
        
        if hasattr(result, 'items') and result.items:
            counts['items'] = self.index_items(result.items)
        
        if hasattr(result, 'npcs') and result.npcs:
            counts['npcs'] = self.index_npcs(result.npcs)
        
        if hasattr(result, 'adventure_locations') and result.adventure_locations:
            counts['adventure_locations'] = self.index_adventure_locations(result.adventure_locations)
        
        logger.info(f"Indexed extraction result: {counts}")
        return counts
    
    # =========================================================================
    # SEARCH METHODS
    # =========================================================================
    
    def _build_where_filter(self, options: SearchOptions) -> Optional[dict]:
        """Build ChromaDB where filter from options."""
        conditions = []
        
        if options.source_filter:
            conditions.append({"source_id": options.source_filter})
        
        if options.category_filter:
            conditions.append({"category": options.category_filter})
        
        if options.level_filter is not None:
            conditions.append({"level": options.level_filter})
        
        if options.type_filter:
            conditions.append({"type": options.type_filter})
        
        if not conditions:
            return None
        elif len(conditions) == 1:
            return conditions[0]
        else:
            return {"$and": conditions}
    
    def _search_collection(
        self,
        collection_type: CollectionType,
        query: str,
        options: SearchOptions
    ) -> list[SearchResult]:
        """Search a single collection."""
        collection = self._get_collection(collection_type)
        
        # Generate query embedding
        query_embedding = self.embeddings.embed_query(query)
        
        # Build filter
        where_filter = self._build_where_filter(options)
        
        # Execute search
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=options.n_results,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )
        
        # Convert to SearchResult objects
        search_results = []
        
        if results['ids'] and results['ids'][0]:
            for i, doc_id in enumerate(results['ids'][0]):
                distance = results['distances'][0][i] if results['distances'] else 0.0
                
                # Filter by minimum relevance
                relevance = 1.0 / (1.0 + distance)
                if relevance < options.min_relevance:
                    continue
                
                search_results.append(SearchResult(
                    id=doc_id,
                    content=results['documents'][0][i] if results['documents'] else "",
                    metadata=results['metadatas'][0][i] if results['metadatas'] else {},
                    distance=distance,
                    collection=collection_type
                ))
        
        return search_results
    
    def search_rules(
        self,
        query: str,
        n_results: int = 5,
        category: Optional[str] = None,
        source_id: Optional[str] = None,
        min_relevance: float = 0.0
    ) -> list[SearchResult]:
        """
        Search for relevant game rules.
        
        Args:
            query: Natural language query.
            n_results: Maximum results to return.
            category: Optional category filter (e.g., 'combat', 'magic').
            source_id: Optional source filter.
            min_relevance: Minimum relevance score (0-1).
            
        Returns:
            List of SearchResult objects.
        """
        options = SearchOptions(
            n_results=n_results,
            min_relevance=min_relevance,
            source_filter=source_id,
            category_filter=category
        )
        return self._search_collection(CollectionType.RULES, query, options)
    
    def search_monsters(
        self,
        query: str,
        n_results: int = 5,
        source_id: Optional[str] = None,
        min_relevance: float = 0.0
    ) -> list[SearchResult]:
        """
        Search for monsters by description, abilities, or name.
        
        Args:
            query: Natural language query.
            n_results: Maximum results to return.
            source_id: Optional source filter.
            min_relevance: Minimum relevance score.
            
        Returns:
            List of SearchResult objects.
        """
        options = SearchOptions(
            n_results=n_results,
            min_relevance=min_relevance,
            source_filter=source_id
        )
        return self._search_collection(CollectionType.MONSTERS, query, options)
    
    def search_locations(
        self,
        query: str,
        n_results: int = 5,
        source_id: Optional[str] = None,
        min_relevance: float = 0.0
    ) -> list[SearchResult]:
        """
        Search for hex locations by description or features.
        
        Args:
            query: Natural language query.
            n_results: Maximum results to return.
            source_id: Optional source filter.
            min_relevance: Minimum relevance score.
            
        Returns:
            List of SearchResult objects.
        """
        options = SearchOptions(
            n_results=n_results,
            min_relevance=min_relevance,
            source_filter=source_id
        )
        return self._search_collection(CollectionType.LOCATIONS, query, options)
    
    def search_spells(
        self,
        query: str,
        n_results: int = 5,
        level: Optional[int] = None,
        magic_type: Optional[str] = None,
        source_id: Optional[str] = None,
        min_relevance: float = 0.0
    ) -> list[SearchResult]:
        """
        Search for spells by effect, name, or description.
        
        Args:
            query: Natural language query.
            n_results: Maximum results to return.
            level: Optional spell level filter.
            magic_type: Optional magic type filter ('arcane', 'divine').
            source_id: Optional source filter.
            min_relevance: Minimum relevance score.
            
        Returns:
            List of SearchResult objects.
        """
        options = SearchOptions(
            n_results=n_results,
            min_relevance=min_relevance,
            source_filter=source_id,
            level_filter=level,
            type_filter=magic_type
        )
        return self._search_collection(CollectionType.SPELLS, query, options)
    
    def search_items(
        self,
        query: str,
        n_results: int = 5,
        item_type: Optional[str] = None,
        source_id: Optional[str] = None,
        min_relevance: float = 0.0
    ) -> list[SearchResult]:
        """
        Search for items by name, type, or properties.
        
        Args:
            query: Natural language query.
            n_results: Maximum results to return.
            item_type: Optional item type filter ('weapon', 'armor', etc.).
            source_id: Optional source filter.
            min_relevance: Minimum relevance score.
            
        Returns:
            List of SearchResult objects.
        """
        options = SearchOptions(
            n_results=n_results,
            min_relevance=min_relevance,
            source_filter=source_id,
            type_filter=item_type
        )
        return self._search_collection(CollectionType.ITEMS, query, options)
    
    def search_npcs(
        self,
        query: str,
        n_results: int = 5,
        source_id: Optional[str] = None,
        min_relevance: float = 0.0
    ) -> list[SearchResult]:
        """
        Search for NPCs by name, description, or role.
        
        Args:
            query: Natural language query.
            n_results: Maximum results to return.
            source_id: Optional source filter.
            min_relevance: Minimum relevance score.
            
        Returns:
            List of SearchResult objects.
        """
        options = SearchOptions(
            n_results=n_results,
            min_relevance=min_relevance,
            source_filter=source_id
        )
        return self._search_collection(CollectionType.NPCS, query, options)
    
    def search_adventures(
        self,
        query: str,
        n_results: int = 5,
        adventure_id: Optional[str] = None,
        min_relevance: float = 0.0
    ) -> list[SearchResult]:
        """
        Search adventure locations by description or contents.
        
        Args:
            query: Natural language query.
            n_results: Maximum results to return.
            adventure_id: Optional filter to specific adventure.
            min_relevance: Minimum relevance score.
            
        Returns:
            List of SearchResult objects.
        """
        options = SearchOptions(
            n_results=n_results,
            min_relevance=min_relevance
        )
        
        # Custom filter for adventure_id
        if adventure_id:
            collection = self._get_collection(CollectionType.ADVENTURES)
            query_embedding = self.embeddings.embed_query(query)
            
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where={"adventure_id": adventure_id},
                include=["documents", "metadatas", "distances"]
            )
            
            search_results = []
            if results['ids'] and results['ids'][0]:
                for i, doc_id in enumerate(results['ids'][0]):
                    distance = results['distances'][0][i] if results['distances'] else 0.0
                    relevance = 1.0 / (1.0 + distance)
                    if relevance >= min_relevance:
                        search_results.append(SearchResult(
                            id=doc_id,
                            content=results['documents'][0][i] if results['documents'] else "",
                            metadata=results['metadatas'][0][i] if results['metadatas'] else {},
                            distance=distance,
                            collection=CollectionType.ADVENTURES
                        ))
            return search_results
        
        return self._search_collection(CollectionType.ADVENTURES, query, options)
    
    def search_lore(
        self,
        query: str,
        n_results: int = 5,
        category: Optional[str] = None,
        source_id: Optional[str] = None,
        min_relevance: float = 0.0
    ) -> list[SearchResult]:
        """
        Search world lore by topic or content.
        
        Args:
            query: Natural language query.
            n_results: Maximum results to return.
            category: Optional category filter.
            source_id: Optional source filter.
            min_relevance: Minimum relevance score.
            
        Returns:
            List of SearchResult objects.
        """
        options = SearchOptions(
            n_results=n_results,
            min_relevance=min_relevance,
            source_filter=source_id,
            category_filter=category
        )
        return self._search_collection(CollectionType.LORE, query, options)
    
    def search_all(
        self,
        query: str,
        n_results_per_collection: int = 3,
        collections: Optional[list[CollectionType]] = None,
        min_relevance: float = 0.0
    ) -> dict[CollectionType, list[SearchResult]]:
        """
        Search across multiple collections simultaneously.
        
        Args:
            query: Natural language query.
            n_results_per_collection: Max results per collection.
            collections: Collections to search (defaults to all).
            min_relevance: Minimum relevance score.
            
        Returns:
            Dict mapping collection type to search results.
        """
        if collections is None:
            collections = list(CollectionType)
        
        options = SearchOptions(
            n_results=n_results_per_collection,
            min_relevance=min_relevance
        )
        
        results = {}
        for collection_type in collections:
            try:
                collection_results = self._search_collection(collection_type, query, options)
                if collection_results:
                    results[collection_type] = collection_results
            except Exception as e:
                logger.warning(f"Error searching {collection_type.value}: {e}")
        
        return results
    
    def get_context_for_query(
        self,
        query: str,
        max_tokens: int = 2000,
        include_rules: bool = True,
        include_monsters: bool = True,
        include_locations: bool = True,
        include_spells: bool = False,
        include_items: bool = False
    ) -> str:
        """
        Get formatted context string for LLM prompt.
        
        Searches relevant collections and formats results into a
        context string suitable for inclusion in a prompt.
        
        Args:
            query: The user's query or action.
            max_tokens: Approximate maximum tokens for context.
            include_rules: Include rules in search.
            include_monsters: Include monsters in search.
            include_locations: Include locations in search.
            include_spells: Include spells in search.
            include_items: Include items in search.
            
        Returns:
            Formatted context string with source attributions.
        """
        collections = []
        if include_rules:
            collections.append(CollectionType.RULES)
        if include_monsters:
            collections.append(CollectionType.MONSTERS)
        if include_locations:
            collections.append(CollectionType.LOCATIONS)
        if include_spells:
            collections.append(CollectionType.SPELLS)
        if include_items:
            collections.append(CollectionType.ITEMS)
        
        all_results = self.search_all(
            query,
            n_results_per_collection=3,
            collections=collections,
            min_relevance=0.0  # Don't filter by relevance - let caller decide
        )
        
        # Flatten and sort by relevance
        flat_results = []
        for collection_results in all_results.values():
            flat_results.extend(collection_results)
        
        flat_results.sort(key=lambda r: r.relevance_score, reverse=True)
        
        # Build context string with token budget
        context_parts = []
        estimated_tokens = 0
        tokens_per_char = 0.25  # Rough estimate
        
        for result in flat_results:
            result_text = result.to_context_string()
            result_tokens = len(result_text) * tokens_per_char
            
            if estimated_tokens + result_tokens > max_tokens:
                break
            
            context_parts.append(f"[{result.collection.value.upper()}]\n{result_text}")
            estimated_tokens += result_tokens
        
        return "\n\n---\n\n".join(context_parts)
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    def get_collection_stats(self) -> dict[str, int]:
        """Get document counts for all collections."""
        stats = {}
        for collection_type, collection in self._collections.items():
            stats[collection_type.value] = collection.count()
        return stats
    
    def clear_collection(self, collection_type: CollectionType) -> None:
        """Clear all documents from a collection."""
        config = self.COLLECTION_CONFIGS[collection_type]
        self.client.delete_collection(config["name"])
        self._collections[collection_type] = self.client.create_collection(
            name=config["name"],
            metadata={"type": collection_type.value}
        )
        logger.info(f"Cleared collection: {collection_type.value}")
    
    def clear_all_collections(self) -> None:
        """Clear all collections."""
        for collection_type in CollectionType:
            self.clear_collection(collection_type)
        logger.info("Cleared all collections")
    
    def delete_by_source(self, source_id: str) -> dict[str, int]:
        """
        Delete all documents from a specific source across collections.
        
        Args:
            source_id: Source ID to delete.
            
        Returns:
            Dict with counts of deleted documents per collection.
        """
        deleted_counts = {}
        
        for collection_type, collection in self._collections.items():
            # Get IDs with matching source
            results = collection.get(
                where={"source_id": source_id},
                include=[]
            )
            
            if results['ids']:
                collection.delete(ids=results['ids'])
                deleted_counts[collection_type.value] = len(results['ids'])
        
        logger.info(f"Deleted documents from source {source_id}: {deleted_counts}")
        return deleted_counts


# Module-level convenience function
def create_retriever(
    persist_directory: str = "./data/vectordb",
    use_mock_embeddings: bool = False,
    use_local_embeddings: bool = False,
    api_key: Optional[str] = None
) -> RulesRetriever:
    """
    Create a new RulesRetriever instance.
    
    Args:
        persist_directory: Directory for ChromaDB data.
        use_mock_embeddings: Use mock embeddings (testing only, poor quality).
        use_local_embeddings: Use local sentence-transformers (free, good quality).
        api_key: OpenAI API key (if using OpenAI embeddings).
    
    Returns:
        Configured RulesRetriever instance.
    """
    return RulesRetriever(
        persist_directory=persist_directory,
        use_mock_embeddings=use_mock_embeddings,
        use_local_embeddings=use_local_embeddings,
        api_key=api_key
    )
