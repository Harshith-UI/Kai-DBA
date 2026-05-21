# Kai

AI-powered Oracle DBA Operations Assistant — a RAG system that searches a knowledge base of runbooks and operational documentation to answer technical support questions.

## Architecture

Kai uses a **parent-child chunking** strategy:

1. Documents are split into **parent chunks** (large sections on `##` headings) and **child chunks** (precise subsections on `##` + `###` headings)
2. Only child chunks are embedded and vector-indexed for high-precision semantic search
3. Matching children are mapped back to their parent chunks, which provide full context to the LLM
4. **Search on child, answer from parent** — small chunks for accuracy, large chunks for completeness

```
User Question → Embed → Vector Search (child chunks) → Map to Parent → LLM → Answer
```

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3 |
| Web Framework | FastAPI |
| LLM | OpenAI gpt-4o-mini |
| Embeddings | OpenAI text-embedding-3-small |
| Orchestration | LangChain |
| Vector DB (primary) | Oracle Autonomous Database 19c (AI Vector Search) |
| Vector DB (alternative) | Pinecone |
| Document Loaders | PyPDFLoader, TextLoader, CSVLoader |

## Project Structure

```
.
├── api.py              # FastAPI web server (POST /ask)
├── main.py             # CLI entry point with n8n fallback
├── chain.py            # LangChain RAG chain (Pinecone-based)
├── retrieve.py         # Vector retrieval strategies (Pinecone)
├── pc_ingest.py        # Ingestion pipeline (Pinecone)
├── oracle_chain.py     # LLM chain (Oracle-backed)
├── oracle_retrieve.py  # Vector search + parent-child retrieval (Oracle)
├── oracle_ingest.py    # Ingestion pipeline (Oracle)
├── db.py               # Oracle Autonomous DB connection helper
├── utils.py            # Shared utilities (chunking, embeddings, loaders)
├── wallet/             # Oracle Autonomous DB wallet (TLS certificates)
├── sizeextension.md    # Sample runbook for ingestion
└── .env                # Environment variables (API keys, DB credentials)
```

## Prerequisites

- Python 3.9+
- Oracle Autonomous Database 19c+ with AI Vector Search enabled
- OpenAI API key
- (Optional) Pinecone account and API key

## Setup

```bash
# Clone the repository
git clone <repo-url>
cd Kai

# Install dependencies
pip install -r requirements.txt

# Create a .env file with the following variables
cp .env.example .env
```

### Environment Variables

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key for embeddings and LLM |
| `PINECONE_API_KEY` | Pinecone API key (optional, for Pinecone backend) |
| `ORACLE_USER` | Oracle Autonomous DB username |
| `ORACLE_PASSWORD` | Oracle Autonomous DB password |
| `ORACLE_DSN` | Oracle DB connection string |
| `ORACLE_WALLET_PATH` | Path to Oracle wallet directory |
| `WALLET_PASSWORD` | Oracle wallet password |

Place the Oracle wallet files in the `wallet/` directory.

## Ingestion

Populate the knowledge base with runbook documents before querying.

```bash
# Oracle backend (primary)
python oracle_ingest.py

# Pinecone backend (alternative)
python -c "from pc_ingest import insert_pinecone; insert_pinecone('yourfile.md', 'index-name')"
```

By default, `oracle_ingest.py` ingests `sizeextension.md`. Modify the filename in the script to ingest other documents.

### Document Format

Knowledge base documents should use Markdown headings:
- `##` for major sections → becomes a **parent chunk**
- `###` for subsections → becomes a **child chunk**

## Usage

### API Server

```bash
uvicorn api:app --reload
```

```bash
# Ask a question
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How to rollback a tablespace extension?"}'
```

Response:
```json
{
  "answer": "1. Summary\n   ...\n2. Actions / Guidance\n   ...\n3. Expected Outcome\n   ..."
}
```

### CLI

```bash
python main.py
```

Runs a pre-configured question against the Oracle backend. Falls back to an n8n webhook if no relevant documents are found.

### Standalone Retrieval Test

```bash
python oracle_retrieve.py
```

## How It Works

1. **Ingestion** — Documents are loaded, split into parent/child chunks with stable UUIDs, and upserted into the `TICKETS` table using `MERGE` (idempotent re-ingestion)
2. **Retrieval** — User question is embedded via `text-embedding-3-small`, vector similarity search runs on child rows (`VECTOR_DISTANCE < 0.4`), matching child IDs are mapped to parent IDs, and parent content is fetched
3. **Generation** — Parent content + question are sent to `gpt-4o-mini` with a structured prompt producing Summary → Actions → Expected Outcome

## Security

**Before pushing to a public or team repository:**
- Ensure `.env` is listed in `.gitignore` and not committed
- Rotate any API keys and database credentials that may have been exposed in the `.env` file
- Keep the `wallet/` directory out of version control

