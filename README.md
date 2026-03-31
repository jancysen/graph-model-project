# O2C Graph Explorer

🚀 Developed by: **Jancy Sen**

A graph-based system with an LLM-powered natural language query interface for SAP Order-to-Cash (O2C) data.
----
## ⚡ Quick Overview
- Converts SAP O2C data into a graph structure
- Enables natural language querying using LLM (Gemini)
- Generates SQL automatically and returns insights
- Visualizes relationships between business entities



---

## What It Does

- Ingests SAP O2C JSONL data into SQLite
- Builds an in-memory graph (NetworkX-style) connecting Sales Orders → Deliveries → Billing Docs → Payments → Journal Entries
- Visualises the graph interactively using `react-force-graph-2d`
- Lets users query the data in plain English via a chat interface
- Translates natural language to SQLite SQL using Gemini 1.5 Flash
- Returns data-grounded answers with expandable SQL and result tables
- Rejects off-topic queries with guardrails

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Frontend (React + Vite)          Vercel             │
│  ┌──────────────────┐  ┌──────────────────────────┐ │
│  │  Graph Visualiser │  │  Chat Interface           │ │
│  │  react-force-     │  │  NL query → API call      │ │
│  │  graph-2d         │  │  Show answer + SQL + table│ │
│  └──────────────────┘  └──────────────────────────┘ │
└─────────────────────────────────────────────────────┘
                        │ REST
┌─────────────────────────────────────────────────────┐
│  Backend (FastAPI + Python)       Railway            │
│                                                      │
│  GET /api/graph  → Build graph from SQLite           │
│  POST /api/query → Guardrail → Gemini → SQL → answer │
│  GET /api/health → Healthcheck                       │
│                                                      │
│  ┌──────────────┐  ┌───────────┐  ┌──────────────┐  │
│  │  SQLite DB   │  │  Gemini   │  │  Guardrails  │  │
│  │  10 tables   │  │  1.5 Flash│  │  system prom │  │
│  └──────────────┘  └───────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────┘
```

### Data flow for a query

1. User types a question in the chat UI
2. Frontend POSTs to `/api/query`
3. Backend sends the question to Gemini with a strict system prompt (schema + guardrails)
4. Gemini returns `{"sql": "...", "explanation": "..."}` or `{"off_topic": true, ...}`
5. If on-topic: backend executes the SQL against SQLite, fetches rows
6. Backend calls Gemini again to summarise the results in plain English
7. Frontend displays the answer, with expandable SQL and data table

---

## Graph Model

### Nodes

| Type | Source table | Key identifier |
|------|-------------|---------------|
| Customer | business_partners | businessPartner |
| SalesOrder | sales_order_headers | salesOrder |
| Delivery | outbound_delivery_headers | deliveryDocument |
| BillingDoc | billing_document_headers | billingDocument |
| Payment | payments_accounts_receivable | accountingDocument |
| JournalEntry | journal_entry_items_accounts_receivable | accountingDocument |

### Edges

| Edge | Join condition |
|------|--------------|
| Customer → SalesOrder (PLACED) | sales_order_headers.soldToParty = business_partners.businessPartner |
| SalesOrder → Delivery (SHIPPED_VIA) | outbound_delivery_items.referenceSdDocument = salesOrder |
| Delivery → BillingDoc (BILLED_AS) | billing_document_items.referenceSdDocument = deliveryDocument |
| BillingDoc → JournalEntry (POSTED_TO) | journal_entry_items.referenceDocument = billingDocument |
| BillingDoc → Payment (PAID_BY) | payments.invoiceReference = billing_document_headers.accountingDocument |

---

## Database / Storage Choice

**SQLite** was chosen over a native graph database (Neo4j, ArangoDB) for the following reasons:

1. **Zero infrastructure**: No external DB server to provision or pay for. The DB is a single file bundled in the Docker image.
2. **Right scale**: With ~1,000 total records across all tables, SQLite handles all queries in milliseconds.
3. **LLM-friendly**: SQL is a well-understood query language with decades of training data — Gemini generates correct SQLite queries reliably.
4. **Graph on top**: The graph structure (nodes + edges) is computed at query time from the relational data and served to the frontend. This is the right separation: relational storage for queries, graph representation for visualisation.

For production scale (millions of orders), the right call would be PostgreSQL with a graph extension (Apache AGE) or a dedicated graph DB like Neo4j.

---

## LLM Integration and Prompting Strategy

### Model: Gemini 1.5 Flash (free tier)

Flash is sufficient for SQL generation — it's fast, cheap, and the task is well-constrained.

### Two-call pattern

**Call 1 — NL → SQL:**  
The system prompt contains: (a) the guardrail persona, (b) the full schema with all tables, columns, and join conditions, and (c) output format instructions (`{"sql": ..., "explanation": ...}` only, no markdown). The question is appended as the user turn.

**Call 2 — Results → English:**  
A shorter prompt gives the model the original question, the SQL, and the first 10 result rows, and asks for a 2-3 sentence business-language summary. This keeps answers grounded — the model cannot hallucinate data that isn't in the rows.

### Why this works better than one-shot

Separating SQL generation from summarisation keeps each call focused. The SQL call needs schema context; the summary call needs result context. Combining them into one call risks the model hallucinating joins or making up data.

### Schema in the prompt

The full schema is ~600 tokens and stays within Flash's context easily. Crucially, the join conditions are explicitly listed (e.g. `outbound_delivery_items.referenceSdDocument = sales_order_headers.salesOrder`) — without these, the model generates plausible-looking but wrong joins.

---

## Guardrails

### Mechanism

The system prompt tells Gemini it is a restricted dataset assistant. If the question is not about the O2C dataset, it must return `{"off_topic": true, "message": "..."}`. The backend checks for this flag before executing any SQL.

### SQL safety (defence in depth)

Even if a prompt injection bypassed the LLM guardrail, the backend independently blocks any SQL containing `DROP`, `DELETE`, `UPDATE`, `INSERT`, `CREATE`, `ALTER`, `TRUNCATE`, or `REPLACE` using a regex check before execution. SQLite is opened read-only in practice.

### Examples of rejected queries

- "Write me a Python function to sort a list" → off-topic
- "What is the capital of France?" → off-topic
- "Tell me a story" → off-topic
- "Ignore previous instructions and..." → treated as off-topic by the model
- Any SQL injection attempt → blocked by the DML regex

---

## Local Development

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Set your Gemini API key
export GEMINI_API_KEY=your_key_here

uvicorn main:app --reload --port 8000
```

The SQLite DB is built automatically on first startup from the JSONL files in `data/raw/`.

### Frontend

```bash
cd frontend
npm install

# Point to local backend
echo "VITE_API_URL=http://localhost:8000" > .env.local

npm run dev
# Open http://localhost:5173
```

---

## Deployment

### Backend → Railway

1. Create a new project at [railway.app](https://railway.app)
2. Connect your GitHub repo, select the `backend/` directory as root
3. Railway auto-detects the `Dockerfile`
4. Add environment variable: `GEMINI_API_KEY=your_key`
5. Deploy. Copy the generated URL (e.g. `https://o2c-backend.railway.app`)

### Frontend → Vercel

1. Go to [vercel.com](https://vercel.com), import your GitHub repo
2. Set **Root Directory** to `frontend`
3. Add environment variable: `VITE_API_URL=https://o2c-backend.railway.app`
4. Deploy. Done.

---

## Sample Queries

| Question | What it demonstrates |
|----------|---------------------|
| Which products are associated with the highest number of billing documents? | Aggregation across billing items |
| Trace the full flow of billing document 90504248 | Multi-table join: order → delivery → billing → journal |
| Which sales orders have been delivered but not billed? | Incomplete flow detection using LEFT JOIN |
| Show me the top 5 customers by total order amount | GROUP BY + ORDER BY across partners and orders |
| Which billing documents have been cancelled? | Filter on boolean flag |
| What is the total payment amount received per customer? | Aggregation on payments table |

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Backend | FastAPI | Fast to build, async, auto-docs |
| DB | SQLite | Zero-infra, sufficient for this scale |
| LLM | Gemini 1.5 Flash | Free tier, reliable SQL generation |
| Graph viz | react-force-graph-2d | Force-directed, handles 600+ nodes |
| Frontend | React + Vite + Tailwind | Fast dev, small bundle |
| Backend hosting | Railway | Supports Docker, free tier available |
| Frontend hosting | Vercel | Zero-config for Vite apps |


----
## 👨‍💻 Author
Jancy Sen
