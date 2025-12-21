# Start the game
python src/main.py

# With options
python src/main.py --dm-style terse --mock-embeddings

# Ingest PDF content first
python -m content_loader.extractor \
  --pdf "../data/pdfs/core/Dolmenwood_Monster_Book.pdf" \
  --type monsters \
  --pages 10-20

# Ollama usage
# First, install Ollama and pull a model
ollama pull llama3.2

# Run with Ollama
python src/main.py --llm-provider ollama --llm-model llama3.2

```



### Architecture
```
┌─────────────────────────────────────────────────────────────┐
│                      DolmenwoodCLI                          │
│                   (Command Interface)                        │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                     DolmenwoodGame                          │
│                    (Orchestrator)                            │
└──────┬──────────────────────┬──────────────────────┬────────┘
       │                      │                      │
┌──────▼──────┐    ┌──────────▼──────────┐    ┌─────▼─────┐
│ GameState   │    │    DolmenwoodDM     │    │ Rules     │
│ Manager     │    │   (Claude Agent)    │    │ Retriever │
│ (SQLite)    │    │                     │    │ (ChromaDB)│
└─────────────┘    └──────────┬──────────┘    └───────────┘
                              │
                   ┌──────────▼──────────┐
                   │  Tool Handlers      │
                   │  (Dice, Combat,     │
                   │   Magic, Social)    │
                   └─────────────────────┘
