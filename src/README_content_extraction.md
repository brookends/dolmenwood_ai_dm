# Dolmenwood Content System

This directory contains game content in JSON format for the Dolmenwood AI DM.

## Directory Structure

```
data/content/
├── monsters/       # Monster stat blocks
├── spells/         # Spell definitions  
├── items/          # Equipment, weapons, armor, magic items
├── hexes/          # Hex location descriptions
├── npcs/           # Non-player characters
└── rules/          # Game rules and mechanics
```

## File Format

Each subdirectory contains JSON files. You can use:
- Single-item files (one monster/spell/etc per file)
- Array files (multiple items in one file)

See the `_examples/` subdirectory in each folder for format templates.

## Loading Content

### From Python

```python
from content_loader import ContentLoader

# Load all content
loader = ContentLoader("data/content")
result = loader.load_all()
print(f"Loaded {result.total} items")

# Load and import to databases
loader.load_and_import(state_manager, rules_retriever)
```

### From Command Line

```bash
# Load content when starting the game
python src/main.py --load-content

# Load content and skip vector indexing
python src/main.py --load-content --skip-indexing
```

## Creating Content

# Extract monsters from pages 10-20 of the Monster Book
cd src
python -m content_loader.extractor \
  --pdf "../data/pdfs/core/Dolmenwood_Monster_Book.pdf" \
  --type monsters \
  --pages 10-20

# Once all JSON files exist, run
python src/main.py --load-content 

# This calls Claude API, costs ~$0.05-0.10, takes ~30 seconds
# Output: data/content/monsters/Dolmenwood_Monster_Book_p10-20_extracted.json

### Extraction Tips

- **Extract in batches**: Do 10-30 pages at a time for better results
- **Review everything**: Claude makes mistakes, especially with complex stat blocks
- **Check formatting**: Ensure damage dice, special abilities are correct
- **Add missing IDs**: Generate unique IDs if Claude missed them

## Content Types

### Monsters

Required fields:
- `name`: Monster name
- `monster_id`: Unique ID (lowercase, underscores)
- `hd`: Hit dice (string like "2+1" or "3*")
- `ac`: Armor class (integer, descending)

See `monsters/_examples/example_monster.json` for full schema.

### Spells

Required fields:
- `name`: Spell name
- `spell_id`: Unique ID
- `level`: Spell level (integer)
- `magic_type`: "arcane" or "divine"
- `description`: Spell effect description

See `spells/_examples/example_spell.json` for full schema.

### Items

Required fields:
- `name`: Item name
- `item_id`: Unique ID
- `type`: Item category (weapon, armor, adventuring_gear, etc.)

See `items/_examples/example_items.json` for full schema.

### Hexes

Required fields:
- `hex_id`: 4-digit hex code (e.g., "0506")
- `coordinates`: [x, y] array
- `terrain_type`: Terrain category

See `hexes/_examples/example_hex.json` for full schema.

### NPCs

Required fields:
- `name`: NPC name
- `npc_id`: Unique ID
- `kindred`: Race/species

See `npcs/_examples/example_npc.json` for full schema.

### Rules

Required fields:
- `title`: Rule title
- `rule_id`: Unique ID
- `category`: Rule category
- `content`: Full rule text

See `rules/_examples/example_rules.json` for full schema.

## Validation

All content is validated against Pydantic models when loaded. If a file has errors, you'll see warnings in the console with the specific issues.

Common validation errors:
- Missing required fields
- Wrong field types (string vs integer)
- Invalid enum values (e.g., wrong `terrain_type`)

## Source Attribution

All content should include a `source` object:

```json
{
  "source": {
    "source_id": "players_book",
    "source_type": "official",
    "source_name": "Dolmenwood Player's Book",
    "page_reference": "p. 45"
  }
}
```

Valid `source_type` values:
- `official`: Official Dolmenwood content
- `homebrew`: Custom/fan content
- `third_party`: Other OSR sources
