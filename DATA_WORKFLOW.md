# Data Storage and Retrieval Workflow

This document explains how data is stored in Oracle DB in this project, how `parent_id` works, and how a user question becomes a final answer.

## Purpose

This project uses a parent-child chunking strategy for retrieval:

- **Child chunks** are used for vector search.
- **Parent chunks** are used as the final context sent to the LLM.

The idea is:

1. Search on smaller, more precise child chunks
2. Use the matching child's `parent_id`
3. Fetch the larger parent section
4. Send that parent content to the LLM for answer generation

## Main Files

- [`utils.py`](/Users/harshith/Desktop/Projects/RAG/Kai/utils.py)  
  Creates stable IDs and builds parent/child chunks
- [`oracle_ingest.py`](/Users/harshith/Desktop/Projects/RAG/Kai/oracle_ingest.py)  
  Stores parent and child rows in Oracle
- [`oracle_retrieve.py`](/Users/harshith/Desktop/Projects/RAG/Kai/oracle_retrieve.py)  
  Searches matching child vectors and fetches parent content
- [`oracle_chain.py`](/Users/harshith/Desktop/Projects/RAG/Kai/oracle_chain.py)  
  Sends retrieved parent content to the LLM
- [`api.py`](/Users/harshith/Desktop/Projects/RAG/Kai/api.py)  
  Entry point for `/ask`

## Oracle Table Structure

From the SQL used in ingestion, the table being written to is `TICKETS`.

Logical structure:

| Column | Meaning |
|---|---|
| `ID` | Unique ID for this row |
| `PARENT_ID` | `NULL` for parent rows, filled for child rows |
| `SECTION` | Section name from `##` heading |
| `SUBSECTION` | Subsection name from `###` heading |
| `CONTENT` | Text stored for this chunk |
| `VECTOR` | Embedding vector, used only for child rows |

## What Gets Stored

Both parent chunks and child chunks are stored in the **same table**.

### Parent row

A parent row represents a top-level section.

- Created from `##` headings
- Has no parent
- Does not store an embedding vector

Example:

| ID | PARENT_ID | SECTION | SUBSECTION | CONTENT | VECTOR |
|---|---|---|---|---|---|
| `P100` | `NULL` | `Rollback Procedure` | `NULL` | full parent section text | `NULL` |

### Child row

A child row represents a smaller searchable subsection inside a parent section.

- Created from `##` + `###` structure
- Stores `parent_id`
- Stores the embedding vector

Example:

| ID | PARENT_ID | SECTION | SUBSECTION | CONTENT | VECTOR |
|---|---|---|---|---|---|
| `C201` | `P100` | `Rollback Procedure` | `If resize failed` | subsection text | embedding |

## How Parent and Child IDs Are Created

In [`utils.py`](/Users/harshith/Desktop/Projects/RAG/Kai/utils.py), IDs are created using `stable_chunk_id(...)`.

This uses `uuid5`, which means:

- the same input produces the same ID every time
- re-ingestion updates the same rows instead of creating duplicates

### Parent ID generation

Parent ID is created from:

- source file name
- string `"parent"`
- section name

Conceptually:

```text
stable_chunk_id(source_name, "parent", section)
```

### Child ID generation

Child ID is created from:

- source file name
- string `"child"`
- section name
- subsection name
- child content

Conceptually:

```text
stable_chunk_id(source_name, "child", section, subsection, child_content)
```

## How Parent-Child Mapping Works

Inside `parent_child(...)` in [`utils.py`](/Users/harshith/Desktop/Projects/RAG/Kai/utils.py), the code first creates all parent chunks and stores them in a temporary map:

```text
"Rollback Procedure" -> P100
"Validation" -> P170
"Pre-checks" -> P220
```

This map is called `section_parent_map`.

Then when child chunks are created, the code checks the child's section and assigns the matching `parent_id`.

So if this child belongs to section `Rollback Procedure`, it gets:

```text
parent_id = P100
```

That is the core link between child and parent rows in Oracle.

## Document Chunking Rules

The project uses Markdown headers to split documents.

### Parent splitter

Parent chunks are split only on:

```md
## Section
```

So each `##` section becomes one parent.

### Child splitter

Child chunks are split on:

```md
## Section
### Subsection
```

So each smaller subsection becomes a child.

## Ingestion Workflow

This is what happens when `ingest_oracle(filename)` runs in [`oracle_ingest.py`](/Users/harshith/Desktop/Projects/RAG/Kai/oracle_ingest.py).

### Step 1: Load the source file

The file is loaded by `load_data(filename)` from [`utils.py`](/Users/harshith/Desktop/Projects/RAG/Kai/utils.py).

Supported file types:

- `.pdf`
- `.txt`
- `.md`
- `.csv`

### Step 2: Split into parent and child chunks

`parent_child(content, source_name=filename)` returns:

- `parent_chunks`
- `child_chunks`

### Step 3: Store parent rows

For every parent chunk, Oracle stores:

- `ID`
- `PARENT_ID = NULL`
- `SECTION`
- `SUBSECTION = NULL`
- `CONTENT`
- `VECTOR = NULL`

### Step 4: Store child rows

For every child chunk:

1. The child content is converted to an embedding
2. The embedding is stored in `VECTOR`
3. The row is stored with the matching `PARENT_ID`

### Step 5: Commit

After all rows are inserted or updated, the transaction is committed.

## Retrieval Workflow

This is what happens when a user asks a question through `/ask`.

### Step 1: API receives the question

[`api.py`](/Users/harshith/Desktop/Projects/RAG/Kai/api.py) receives:

```json
{
  "question": "How to rollback tablespace extension?"
}
```

### Step 2: Convert question into an embedding

In [`oracle_retrieve.py`](/Users/harshith/Desktop/Projects/RAG/Kai/oracle_retrieve.py), the question is embedded using OpenAI embeddings.

Conceptually:

```text
"How to rollback tablespace extension?"
-> [0.12, -0.44, 0.91, ...]
```

### Step 3: Search Oracle on child vectors

Oracle runs this search:

```sql
SELECT PARENT_ID
FROM TICKETS
WHERE VECTOR IS NOT NULL
ORDER BY VECTOR_DISTANCE(VECTOR, :query_vector, COSINE)
FETCH FIRST 3 ROWS ONLY
```

Important detail:

- `WHERE VECTOR IS NOT NULL` means only **child rows** are searched
- parent rows are not directly vector searched

### Step 4: Get matching parent IDs

Suppose the top matches are:

| Child ID | Parent ID |
|---|---|
| `C201` | `P100` |
| `C305` | `P170` |
| `C202` | `P100` |

Then the code removes duplicates and keeps:

```text
[P100, P170]
```

### Step 5: Fetch parent content

For each parent ID, Oracle runs:

```sql
SELECT CONTENT
FROM TICKETS
WHERE ID = :parent_id
```

This returns the larger parent sections.

Example:

- `P100` -> rollback section text
- `P170` -> validation section text

### Step 6: Build final context

If multiple parents are found, the code formats them like:

```text
--- Parent Section 1 ---

[content of parent 1]

--- Parent Section 2 ---

[content of parent 2]
```

### Step 7: Send context to the LLM

[`oracle_chain.py`](/Users/harshith/Desktop/Projects/RAG/Kai/oracle_chain.py) gets:

- the original question
- the fetched parent content

The LLM is instructed to answer using only that context.

### Step 8: Return final answer

The API returns:

```json
{
  "answer": "formatted final answer"
}
```

## End-to-End Example

Assume the source markdown contains:

```md
## Rollback Procedure
This section explains how rollback works.

### If resize failed
Check datafile status and restore from backup.

### If extension caused issues
Revert changes and validate tablespace state.
```

### Stored parent row

| ID | PARENT_ID | SECTION | SUBSECTION | CONTENT | VECTOR |
|---|---|---|---|---|---|
| `P100` | `NULL` | `Rollback Procedure` | `NULL` | `This section explains how rollback works.` | `NULL` |

### Stored child rows

| ID | PARENT_ID | SECTION | SUBSECTION | CONTENT | VECTOR |
|---|---|---|---|---|---|
| `C201` | `P100` | `Rollback Procedure` | `If resize failed` | `Check datafile status and restore from backup.` | embedding |
| `C202` | `P100` | `Rollback Procedure` | `If extension caused issues` | `Revert changes and validate tablespace state.` | embedding |

### User asks

```text
How to rollback tablespace extension?
```

### Search stage

The question embedding is compared to child vectors.

Oracle may return:

| Matching child | Returned `PARENT_ID` |
|---|---|
| `C201` | `P100` |
| `C202` | `P100` |

After duplicate removal:

```text
[P100]
```

### Parent fetch stage

Then Oracle fetches:

```text
SELECT CONTENT FROM TICKETS WHERE ID = P100
```

Returned content:

```text
This section explains how rollback works.
```

That content becomes the context for the LLM answer.

### Final answer stage

The LLM receives:

- question: `How to rollback tablespace extension?`
- context: parent content retrieved from Oracle

Then it returns the final formatted answer through the API.

## Why This Design Is Used

This project separates retrieval precision from answer context.

### Child chunks

- smaller
- more searchable
- better for semantic matching

### Parent chunks

- larger
- more complete
- better for answer generation

So the design is:

- **search on child**
- **answer from parent**

## Quick Memory Version

If you come back after a long break, remember this:

1. Source document is split into parent and child chunks
2. Both are stored in Oracle table `TICKETS`
3. Parent rows have `PARENT_ID = NULL` and `VECTOR = NULL`
4. Child rows have `PARENT_ID = parent row ID` and `VECTOR = embedding`
5. User question is embedded
6. Oracle vector search finds matching child rows
7. Child rows return `PARENT_ID`
8. Parent `CONTENT` is fetched
9. Parent content is sent to the LLM
10. API returns the final answer

## One-Line Summary

The Oracle DB stores a two-level chunk hierarchy in one table, where child rows are used to find the right topic and parent rows are used to provide the final context for the answer.
