# NaturalGAIA Generation Pipeline

This repository contains the generation pipeline for **NaturalGAIA**, an agentic benchmark constructed from Wikidata knowledge graphs. The pipeline automates the process of crawling subgraphs, generating logical task skeletons, and refining them into natural language queries using LLMs.

## 📂 Project Structure

```text
.
├── config/              # Configuration files (Tools & LLM settings)
├── src/                 # Source code
│   ├── builder.py       # Knowledge graph crawler & builder
│   ├── generator.py     # Logical task skeleton generator
│   ├── llm_client.py    # LLM API client (Multi-provider support)
│   └── utils.py         # Utilities (Logger, etc.)
├── data/                # Generated datasets (Graphs & Tasks)
├── logs/                # Runtime logs
└── main.py              # Entry point
```

## 🚀 Quick Start

### 1. Installation
```bash
pip install -r requirements.txt
```

### 2. Configuration
Copy the example config:

```bash
cp config/llm_config.example.yaml config/llm_config.yaml
```
Edit `config/llm_config.yaml` to add your API Keys (OpenAI/DeepSeek/etc.) and Proxy settings.

### 3. Usage
Run the full pipeline:

```bash
# Basic run (Taylor Swift seed)
python main.py

# Custom run (Different seed entity and scale)
python main.py --seed 42 --seed_entity Q2 --seed_label Earth --nodes 500 --tasks 50
```

## 🛠️ Tech Stack

- **Data Source:** Wikidata (via SPARQL)
- **Graph Processing:** NetworkX
- **LLM Integration:** OpenAI SDK / HTTPX
- **Concurrency:** ThreadPoolExecutor

## 📄 License
MIT License