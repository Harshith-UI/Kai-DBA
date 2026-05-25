# Kai

**K**nowledge **A**ssistant for **I**nternal Ops — AI-powered Oracle DBA assistant that searches a knowledge base of runbooks and operational documentation to answer technical support questions. Falls back to an n8n ticket sanitizer webhook when no relevant docs are found.

## Architecture

Kai uses a **parent-child chunking** strategy:

1. Documents are split into **parent chunks** (large sections on `##` headings) and **child chunks** (precise subsections on `##` + `###` headings)
2. Only child chunks are embedded and vector-indexed for high-precision semantic search
3. Matching children are mapped back to their parent chunks, which provide full context to the LLM
4. **Search on child, answer from parent** — small chunks for accuracy, large chunks for completeness

```
User Question → Embed → Vector Search (child chunks) → Map to Parent → LLM → Answer
                                                                              ↓
                                              (fallback) → n8n Webhook → Sanitize
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
| Automation | n8n (ticket sanitizer webhook fallback) |

## Project Structure

```
.
├── api.py              # FastAPI web server (POST /ask)
├── main.py             # CLI entry point with n8n webhook fallback
├── chain.py            # LangChain RAG chain (Pinecone-based)
├── retrieve.py         # Vector retrieval strategies (Pinecone: similarity, MMR, multi-query)
├── pc_ingest.py        # Ingestion pipeline (Pinecone)
├── oracle_chain.py     # LLM chain with structured prompt (Oracle-backed)
├── oracle_retrieve.py  # Vector search + parent-child retrieval with distance scoring (Oracle)
├── oracle_ingest.py    # Ingestion pipeline with MERGE-based idempotent upsert (Oracle)
├── db.py               # Oracle Autonomous DB connection helper with TLS wallet
├── utils.py            # Shared utilities (parent-child chunking, stable UUIDs, embeddings, loaders)
├── wallet/             # Oracle Autonomous DB wallet (TLS certificates)
├── sizeextension.md    # Sample runbook for ingestion (tablespace extension procedure)
├── DATA_WORKFLOW.md    # Deep dive: data storage, parent-child mapping, retrieval flow
├── requirements.txt    # Python dependencies
└── .env                # Environment variables (API keys, DB credentials, webhook config)
```

## Prerequisites

- Python 3.9+
- Oracle Autonomous Database 19c+ with AI Vector Search enabled
- OpenAI API key
- (Optional) Pinecone account and API key
- (Optional) n8n instance with a ticket sanitizer webhook

## Setup

```bash
# Clone the repository
git clone <repo-url>
cd Kai

# Install dependencies
pip install -r requirements.txt

# Create a .env file
# WARNING: Do NOT commit .env to version control (already in .gitignore)
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key for embeddings and LLM |
| `ORACLE_USER` | Yes | Oracle Autonomous DB username |
| `ORACLE_PASSWORD` | Yes | Oracle Autonomous DB password |
| `ORACLE_DSN` | Yes | Oracle DB connection string |
| `ORACLE_WALLET_PATH` | Yes | Path to Oracle wallet directory |
| `WALLET_PASSWORD` | Yes | Oracle wallet password |
| `REDACT_URL` | No | n8n webhook URL for ticket sanitizer fallback |
| `REDACT_KEY` | No | API key for n8n webhook header authentication |
| `PINECONE_API_KEY` | No | Pinecone API key (optional, for Pinecone backend) |

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

### CLI with n8n Fallback

```bash
python main.py
```

The CLI flow:
1. Embeds the question and searches the Oracle vector DB
2. If relevant docs are found → generates an answer via LLM
3. If **no** relevant docs are found → POSTs the question to the configured n8n webhook (`REDACT_URL`) with header-based authentication (`REDACT_KEY`) for external ticket sanitization

```
main.py → retrieve_oracle() → found? → yes → get_oracle_answer() → print answer
                               ↓ no
                          n8n webhook → sanitize ticket
```

### Standalone Retrieval Test

```bash
python oracle_retrieve.py
```

## Vector Search Backends

| Backend | File | Retrieval Strategies |
|---|---|---|
| **Oracle AI Vector Search** | `oracle_retrieve.py` | Cosine distance < 0.4, parent-child mapping, distance scoring |
| **Pinecone** | `retrieve.py` | Similarity search, MMR, MultiQueryRetriever |

## How It Works

1. **Ingestion** — Documents are loaded, split into parent/child chunks with stable UUIDs, and upserted into the `TICKETS` table using `MERGE` (idempotent re-ingestion). Parent rows store content only; child rows store content + embedding vectors.
2. **Retrieval** — User question is embedded via `text-embedding-3-small`, vector similarity search runs on child rows (`VECTOR_DISTANCE < 0.4`), matching child IDs are mapped to parent IDs, and parent content is fetched.
3. **Generation** — Parent content + question are sent to `gpt-4o-mini` with a structured prompt producing Summary → Actions → Expected Outcome.
4. **Fallback** — If no relevant vectors are found, the question is forwarded to an n8n webhook for manual or automated ticket sanitization.

## Security

- `.env` is in `.gitignore` — never commit secrets
- The `wallet/` directory is excluded from version control
- n8n webhook uses header-based authentication (`X-API-Key`)
- All API keys and credentials must be rotated if exposed

## Reference

- [`DATA_WORKFLOW.md`](./DATA_WORKFLOW.md) — detailed documentation of the parent-child chunking strategy, Oracle table structure, ID generation, and end-to-end retrieval flow
- [`sizeextension.md`](./sizeextension.md) — sample Oracle tablespace extension runbook used for ingestion testing
