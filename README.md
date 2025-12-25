# NaturalGAIA Generation Pipeline

[**中文文档**](README_zh.md) | English

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
├── visualization/       # Interactive visualization GUI
│   └── app.py           # Streamlit application for task & graph exploration
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

### 4. Interactive Visualization

Launch the Streamlit-based GUI for exploring generated tasks and knowledge graphs:

```bash
streamlit run visualization/app.py
```

**Features:**
- **Task Analysis Panel**
  - Browse and search through generated tasks
  - View refined natural language queries and ground truth answers
  - Inspect multi-hop reasoning chains with an interactive timeline
  - Filter tasks by complexity and path length

- **Graph Exploration Panel**
  - Interactive knowledge graph visualization with force-directed layout
  - Node degree-based color coding (Red=Hub, Yellow=Bridge, Blue=Leaf)
  - Click-to-inspect node details and connections
  - Adjustable node limit for performance tuning
  - Physics-based stabilization for smooth interaction

### 📦 Dependency Management

If you add new libraries, please update `requirements.txt` to keep the environment reproducible.

**Option 1: Using pipreqs (Recommended for clean dependencies)**
This generates requirements based on actual imports in the project, avoiding local clutter.

```bash
# Install pipreqs if you haven't
pip install pipreqs

# Generate requirements.txt (force overwrite)
pipreqs . --force --ignore venv,data,logs,visualization,wikidata --encoding=utf-8
```

**Option 2: Using pip freeze (Standard)**

```bash
pip freeze > requirements.txt
```

## 🛠️ Tech Stack

- **Data Source:** Wikidata (via SPARQL)
- **Graph Processing:** NetworkX
- **LLM Integration:** OpenAI SDK / HTTPX
- **Concurrency:** ThreadPoolExecutor
- **Visualization:** Streamlit + Streamlit-Agraph

## 📄 License
MIT License