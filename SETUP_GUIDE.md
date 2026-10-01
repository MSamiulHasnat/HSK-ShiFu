# HSK Knowledge Agent - Setup Guide

This guide walks you through setting up and running the HSK Knowledge Agent.

## System Requirements

- Python 3.8+
- 4GB RAM minimum (8GB+ recommended)
- 2GB disk space for vector store
- Active internet connection (for model downloads on first run)

## Installation Steps

### 1. Install Dependencies

```bash
cd HSK-ShiFu
pip install -r requirements.txt
```

This installs:
- `pypdf` & `pdfplumber` - PDF extraction
- `sentence-transformers` - Embeddings
- `faiss-cpu` - Vector store
- `anthropic` - Claude API
- `pyyaml` - Configuration
- `python-dotenv` - Environment variables

### 2. Set Up API Key

```bash
# On macOS/Linux:
export ANTHROPIC_API_KEY="sk-ant-..."

# On Windows:
set ANTHROPIC_API_KEY=sk-ant-...

# Or create .env file in project root:
ANTHROPIC_API_KEY=sk-ant-...
```

Get your API key from: https://console.anthropic.com/account/keys

### 3. Verify PDF Files

Confirm you have the HSK textbooks in the correct location:

```
HSK-ShiFu/
├── HSK-Textbooks/
│   ├── HSK-Level1-Version2.0.pdf
│   ├── HSK-Level2-Version2.0.pdf
│   └── HSK-Level3-Version3.0.pdf
├── config.yaml
├── requirements.txt
└── *.py
```

## Running the Pipeline

### Full Pipeline (All Steps)

```bash
python pipeline.py
```

This runs all 5 steps:
1. **Extract** - Text from PDFs (~8 min)
2. **Parse** - Structure into vocabulary/grammar/examples (~2 min)
3. **Vector Store** - Build FAISS embeddings (~15 min)
4. **Agent** - Initialize Claude RAG
5. **Knowledge Graph** - Prepare for graphify

**Total time: ~30 minutes on first run**

### Individual Steps

```bash
# Step 1: Extract PDFs only
python pipeline.py --step 1

# Step 2: Parse content
python pipeline.py --step 2

# Step 3: Build embeddings
python pipeline.py --step 3

# Step 4: Initialize agent
python pipeline.py --step 4

# Step 5: Knowledge graph prep
python pipeline.py --step 5
```

### Test Query

```bash
python pipeline.py --query "What does 我是学生 mean?"
```

Expected output:
```
Q: What does 我是学生 mean?

A: Based on HSK textbook materials...
[Full answer with citations]

Sources:
• VOCABULARY from HSK Level 1
• EXAMPLE from HSK Level 1
```

## Interactive Chat

After running the pipeline, use the interactive CLI:

```bash
python chat.py
```

This starts a multi-turn conversation where you can:
- Ask grammar questions
- Translate sentences
- Learn vocabulary
- All with verified HSK sources

Example session:
```
> 请解释 把 句式
[Agent explains 把 pattern with examples from HSK textbooks]

> 给我一个例子
[Agent provides example from HSK materials]

> exit
```

## Configuration

Edit `config.yaml` to customize:

```yaml
# Change Claude model
claude:
  model: "claude-3-opus-20250219"  # Use Opus for more complex analysis

# Adjust similarity threshold
vectorstore:
  similarity_threshold: 0.5  # Lower = broader search

# Change embedding model
embeddings:
  model: "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
```

## Troubleshooting

### "No module named 'pypdf'"
```bash
pip install --upgrade pypdf
```

### "FAISS index not found"
Re-run step 3:
```bash
python pipeline.py --step 3
```

### "ANTHROPIC_API_KEY not set"
Verify environment variable:
```bash
echo $ANTHROPIC_API_KEY  # Linux/Mac
echo %ANTHROPIC_API_KEY%  # Windows
```

### "Out of memory" during embedding
Reduce batch size in `config.yaml`:
```yaml
embeddings:
  batch_size: 8  # Default is 32
```

### Slow PDF extraction
The large PDFs (144MB) take time. This is normal. Check progress in console output.

## Verifying Installation

Quick verification checklist:

```bash
# 1. Check Python version
python --version  # Should be 3.8+

# 2. Check dependencies
pip list | grep -E "pypdf|sentence-transformers|faiss"

# 3. Check API key
python -c "import os; print('Key set:', bool(os.environ.get('ANTHROPIC_API_KEY')))"

# 4. Check PDFs exist
ls -lh HSK-Textbooks/

# 5. Test extraction
python pipeline.py --step 1
```

## Next Steps

1. **Run Full Pipeline**: `python pipeline.py`
2. **Test Queries**: `python pipeline.py --query "你的问题"`
3. **Interactive Chat**: `python chat.py`
4. **Integrate Graphify**: See PROJECT_OVERVIEW.md for graph integration
5. **Customize**: Edit `config.yaml` for your needs

## Output Structure

After running pipeline, you'll have:

```
hsk_data/
├── extracted_text/
│   ├── HSK_Level1_extracted.txt
│   ├── HSK_Level2_extracted.txt
│   └── HSK_Level3_extracted.txt
├── vocabulary.json          # Parsed vocabulary
├── grammar_rules.json       # Parsed grammar
├── example_sentences.json   # Parsed examples
├── faiss_index/
│   ├── faiss.index         # Vector database
│   └── metadata.json       # Vector metadata
├── hsk_extracted_data.json # Raw extraction
└── hsk_knowledge.db        # SQLite database (optional)
```

## Support

For issues:
1. Check logs: `tail -f hsk_agent.log`
2. Verify PDFs are readable: `pdfplumber` can open them
3. Verify Claude API key is active on Anthropic console
4. Ensure embedding model downloads (~500MB first time)

## Performance Notes

- **First run**: 30-40 minutes (includes model downloads)
- **Subsequent runs**: ~5 minutes (models cached)
- **Single query**: 2-5 seconds
- **Memory**: ~2GB for full index

Enjoy your HSK Knowledge Agent! 🎓
