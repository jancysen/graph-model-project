import os
import json
import sqlite3
import re
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from openai import OpenAI
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="O2C Graph Query API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Config ────────────────────────────────────────────────────────────────────
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")
DB_PATH = Path(__file__).parent / "data" / "o2c.db"
DATA_DIR = Path(__file__).parent / "data" / "raw"

# ── DB Schema (for LLM context) ───────────────────────────────────────────────
SCHEMA_DESCRIPTION = """
SQLite database with these tables (SAP Order-to-Cash data):

sales_order_headers: salesOrder(PK), salesOrderType, salesOrganization, soldToParty(FK→business_partners), 
  creationDate, totalNetAmount, overallDeliveryStatus, overallOrdReltdBillgStatus, transactionCurrency,
  requestedDeliveryDate, customerPaymentTerms

sales_order_items: salesOrder(FK→sales_order_headers), salesOrderItem, material(FK→products),
  requestedQuantity, requestedQuantityUnit, netAmount, materialGroup, productionPlant, storageLocation,
  salesDocumentRjcnReason, itemBillingBlockReason

billing_document_headers: billingDocument(PK), billingDocumentType, creationDate, billingDocumentDate,
  billingDocumentIsCancelled, totalNetAmount, transactionCurrency, companyCode, fiscalYear,
  accountingDocument, soldToParty(FK→business_partners)

billing_document_items: billingDocument(FK→billing_document_headers), billingDocumentItem,
  material(FK→products), billingQuantity, netAmount, referenceSdDocument(FK→outbound_delivery_headers.deliveryDocument),
  referenceSdDocumentItem

outbound_delivery_headers: deliveryDocument(PK), creationDate, deliveryBlockReason,
  overallGoodsMovementStatus, overallPickingStatus, shippingPoint, actualGoodsMovementDate

outbound_delivery_items: deliveryDocument(FK→outbound_delivery_headers), deliveryDocumentItem,
  actualDeliveryQuantity, plant, referenceSdDocument(FK→sales_order_headers.salesOrder),
  referenceSdDocumentItem, storageLocation

payments_accounts_receivable: accountingDocument(PK), accountingDocumentItem, companyCode, fiscalYear,
  clearingDate, clearingAccountingDocument, amountInTransactionCurrency, transactionCurrency,
  customer(FK→business_partners), invoiceReference, salesDocument, postingDate

journal_entry_items_accounts_receivable: accountingDocument, accountingDocumentItem, companyCode, fiscalYear,
  glAccount, referenceDocument(FK→billing_document_headers.billingDocument), profitCenter, transactionCurrency,
  amountInTransactionCurrency, postingDate, customer(FK→business_partners), clearingDate,
  clearingAccountingDocument, accountingDocumentType

business_partners: businessPartner(PK), customer, businessPartnerFullName, businessPartnerName,
  businessPartnerCategory, creationDate

products: product(PK), productType, productOldId, grossWeight, weightUnit, baseUnit, division, industrySector

billing_document_cancellations: billingDocument(PK), billingDocumentType, billingDocumentIsCancelled,
  cancelledBillingDocument, totalNetAmount, soldToParty, accountingDocument

Key relationships / joins:
- Sales Order → Delivery: outbound_delivery_items.referenceSdDocument = sales_order_headers.salesOrder
- Delivery → Billing: billing_document_items.referenceSdDocument = outbound_delivery_headers.deliveryDocument
- Billing → Journal: journal_entry_items_accounts_receivable.referenceDocument = billing_document_headers.billingDocument
- Billing → Payment: payments_accounts_receivable.invoiceReference = billing_document_headers.accountingDocument
  OR join via customer + amount
- Customer: business_partners.businessPartner is used as soldToParty in orders and billing docs
"""

GUARDRAIL_SYSTEM = """You are a data query assistant for an SAP Order-to-Cash (O2C) dataset.
Your ONLY job is to answer questions about this specific dataset: sales orders, deliveries, billing documents, payments, products, and business partners.

STRICT RULES:
1. Only answer questions related to the O2C dataset and business data within it.
2. If asked anything unrelated (general knowledge, coding help, creative writing, opinions, etc.), respond EXACTLY with: {"off_topic": true, "message": "This system is designed to answer questions related to the Order-to-Cash dataset only. Please ask about orders, deliveries, billing documents, payments, products, or customers."}
3. For valid queries, respond with valid JSON only: {"sql": "<sqlite query>", "explanation": "<1 sentence what the query does>"}
4. Use only tables and columns from the schema provided.
5. Limit results to 50 rows unless asked for more.
6. Do not use DROP, DELETE, UPDATE, INSERT, CREATE, or any DML/DDL.
7. Always use proper SQLite syntax.

""" + SCHEMA_DESCRIPTION

# ── Ingest ────────────────────────────────────────────────────────────────────
def load_jsonl(folder: str) -> list[dict]:
    records = []
    path = DATA_DIR / folder
    if not path.exists():
        return records
    for f in path.glob("*.jsonl"):
        with open(f) as fp:
            for line in fp:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except:
                        pass
    return records

def flatten(obj: dict) -> dict:
    """Flatten nested dicts one level deep."""
    flat = {}
    for k, v in obj.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                flat[f"{k}_{k2}"] = v2
        else:
            flat[k] = v
    return flat

def build_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    tables = {
        "sales_order_headers": "sales_order_headers",
        "sales_order_items": "sales_order_items",
        "billing_document_headers": "billing_document_headers",
        "billing_document_items": "billing_document_items",
        "billing_document_cancellations": "billing_document_cancellations",
        "outbound_delivery_headers": "outbound_delivery_headers",
        "outbound_delivery_items": "outbound_delivery_items",
        "payments_accounts_receivable": "payments_accounts_receivable",
        "journal_entry_items_accounts_receivable": "journal_entry_items_accounts_receivable",
        "business_partners": "business_partners",
        "products": "products",
        "plants": "plants",
        "product_descriptions": "product_descriptions",
    }

    for table, folder in tables.items():
        records = load_jsonl(folder)
        if not records:
            continue
        flat_records = [flatten(r) for r in records]
        cols = list(flat_records[0].keys())
        col_defs = ", ".join(f'"{c}" TEXT' for c in cols)
        cur.execute(f'DROP TABLE IF EXISTS "{table}"')
        cur.execute(f'CREATE TABLE "{table}" ({col_defs})')
        placeholders = ", ".join("?" for _ in cols)
        for rec in flat_records:
            vals = [str(rec.get(c, "")) if rec.get(c) is not None else None for c in cols]
            cur.execute(f'INSERT INTO "{table}" VALUES ({placeholders})', vals)
        print(f"  {table}: {len(flat_records)} rows, cols: {cols[:5]}...")

    conn.commit()
    conn.close()
    print("DB built.")

# ── Graph data ────────────────────────────────────────────────────────────────
def build_graph_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    nodes = {}
    edges = []

    def add_node(id_, label, type_, props={}):
        if id_ not in nodes:
            nodes[id_] = {"id": id_, "label": label, "type": type_, "properties": props}

    # Sales orders
    rows = conn.execute("SELECT * FROM sales_order_headers LIMIT 100").fetchall()
    for r in rows:
        r = dict(r)
        add_node(f"SO-{r['salesOrder']}", r['salesOrder'], "SalesOrder", {
            "amount": r.get("totalNetAmount"), "currency": r.get("transactionCurrency"),
            "status": r.get("overallDeliveryStatus"), "date": r.get("creationDate","")[:10],
            "customer": r.get("soldToParty")
        })
        # Customer node
        cid = r.get("soldToParty","")
        if cid:
            add_node(f"BP-{cid}", cid, "Customer", {"id": cid})
            edges.append({"source": f"BP-{cid}", "target": f"SO-{r['salesOrder']}", "label": "PLACED"})

    # Delivery headers
    rows = conn.execute("SELECT * FROM outbound_delivery_headers LIMIT 100").fetchall()
    for r in rows:
        r = dict(r)
        add_node(f"DEL-{r['deliveryDocument']}", r['deliveryDocument'], "Delivery", {
            "status": r.get("overallGoodsMovementStatus"), "date": r.get("creationDate","")[:10],
            "pickingStatus": r.get("overallPickingStatus")
        })

    # Delivery items → link to sales orders
    rows = conn.execute("SELECT * FROM outbound_delivery_items").fetchall()
    for r in rows:
        r = dict(r)
        so = r.get("referenceSdDocument","")
        deldoc = r.get("deliveryDocument","")
        if so and deldoc:
            src = f"SO-{so}"
            tgt = f"DEL-{deldoc}"
            if src in nodes and tgt in nodes:
                if not any(e["source"]==src and e["target"]==tgt for e in edges):
                    edges.append({"source": src, "target": tgt, "label": "SHIPPED_VIA"})

    # Billing document headers
    rows = conn.execute("SELECT * FROM billing_document_headers LIMIT 163").fetchall()
    for r in rows:
        r = dict(r)
        add_node(f"BILL-{r['billingDocument']}", r['billingDocument'], "BillingDoc", {
            "amount": r.get("totalNetAmount"), "currency": r.get("transactionCurrency"),
            "cancelled": r.get("billingDocumentIsCancelled"), "date": r.get("billingDocumentDate","")[:10],
            "accountingDoc": r.get("accountingDocument")
        })

    # Billing items → link to deliveries
    rows = conn.execute("SELECT * FROM billing_document_items").fetchall()
    for r in rows:
        r = dict(r)
        bill = r.get("billingDocument","")
        deldoc = r.get("referenceSdDocument","")
        if bill and deldoc:
            src = f"DEL-{deldoc}"
            tgt = f"BILL-{bill}"
            if src in nodes and tgt in nodes:
                if not any(e["source"]==src and e["target"]==tgt for e in edges):
                    edges.append({"source": src, "target": tgt, "label": "BILLED_AS"})

    # Payments
    rows = conn.execute("SELECT * FROM payments_accounts_receivable LIMIT 120").fetchall()
    for r in rows:
        r = dict(r)
        pid = r.get("accountingDocument","")
        add_node(f"PAY-{pid}", pid, "Payment", {
            "amount": r.get("amountInTransactionCurrency"), "currency": r.get("transactionCurrency"),
            "date": r.get("clearingDate","")[:10], "customer": r.get("customer")
        })
        # Link payment to billing via accountingDocument
        invoice_ref = r.get("invoiceReference","")
        if invoice_ref:
            tgt = f"BILL-{invoice_ref}"
            if tgt in nodes:
                edges.append({"source": tgt, "target": f"PAY-{pid}", "label": "PAID_BY"})

    # Journal entries → link to billing
    rows = conn.execute("SELECT * FROM journal_entry_items_accounts_receivable LIMIT 123").fetchall()
    for r in rows:
        r = dict(r)
        ref_doc = r.get("referenceDocument","")
        acct_doc = r.get("accountingDocument","")
        if ref_doc and acct_doc:
            jid = f"JE-{acct_doc}-{r.get('accountingDocumentItem','1')}"
            add_node(jid, acct_doc, "JournalEntry", {
                "amount": r.get("amountInTransactionCurrency"), "glAccount": r.get("glAccount"),
                "date": r.get("postingDate","")[:10]
            })
            src = f"BILL-{ref_doc}"
            if src in nodes:
                edges.append({"source": src, "target": jid, "label": "POSTED_TO"})

    # Enrich customer nodes with business partner names
    rows = conn.execute("SELECT * FROM business_partners").fetchall()
    for r in rows:
        r = dict(r)
        bp = r.get("businessPartner","")
        nid = f"BP-{bp}"
        if nid in nodes:
            nodes[nid]["label"] = r.get("businessPartnerName", bp)[:20]
            nodes[nid]["properties"]["name"] = r.get("businessPartnerFullName","")

    conn.close()
    return {"nodes": list(nodes.values()), "edges": edges}

# ── LLM Query ─────────────────────────────────────────────────────────────────
def _openrouter_client() -> OpenAI:
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not set")
    return OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )

def query_llm(user_question: str) -> dict:
    client = _openrouter_client()

    prompt = f"""{GUARDRAIL_SYSTEM}

User question: {user_question}

Respond with valid JSON only. No markdown, no backticks."""

    response = client.chat.completions.create(
        model=OPENROUTER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences if present
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"^```\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        return json.loads(raw)
    except Exception:
        raise HTTPException(status_code=500, detail=f"LLM parse error: {raw[:200]}")

def run_sql(sql: str) -> dict:
    # Safety: block write operations
    forbidden = re.compile(r"\b(DROP|DELETE|UPDATE|INSERT|CREATE|ALTER|TRUNCATE|REPLACE)\b", re.I)
    if forbidden.search(sql):
        raise HTTPException(status_code=400, detail="Write operations are not allowed.")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
        cols = [d[0] for d in cur.description] if cur.description else []
        return {"columns": cols, "rows": rows}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SQL error: {e}")
    finally:
        conn.close()

# ── Routes ────────────────────────────────────────────────────────────────────
@app.on_event("startup")
def startup():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        print("Building SQLite DB...")
        build_db()
    else:
        print("DB already exists, skipping build.")

# ── Graph highlight extraction ───────────────────────────────────────────────
# Maps SQL result column names → graph node ID prefix
_COL_TO_PREFIX: dict[str, str] = {
    "salesorder":         "SO",
    "salesDocument":      "SO",
    "billingdocument":    "BILL",
    "billingdoc":         "BILL",
    "deliverydocument":   "DEL",
    "delivery":           "DEL",
    "accountingdocument": "PAY",
    "businesspartner":    "BP",
    "soldtoparty":        "BP",
    "customer":           "BP",
}

def extract_highlighted_nodes(columns: list[str], rows: list[dict]) -> list[str]:
    """Return a deduplicated list of graph node IDs inferred from SQL result columns."""
    node_ids: set[str] = set()
    for col in columns:
        col_lower = col.lower()
        for key, prefix in _COL_TO_PREFIX.items():
            if key in col_lower:
                for row in rows:
                    val = row.get(col)
                    if val:
                        node_ids.add(f"{prefix}-{val}")
                break
    return list(node_ids)

class QueryRequest(BaseModel):
    question: str

@app.get("/api/graph")
def get_graph():
    if not DB_PATH.exists():
        raise HTTPException(status_code=500, detail="DB not ready")
    return build_graph_data()

@app.post("/api/query")
def query(req: QueryRequest):
    llm_result = query_llm(req.question)

    # Off-topic guardrail
    if llm_result.get("off_topic"):
        return {"answer": llm_result["message"], "sql": None, "data": None, "off_topic": True}

    sql = llm_result.get("sql","")
    explanation = llm_result.get("explanation","")

    if not sql:
        return {"answer": "I couldn't generate a query for that question.", "sql": None, "data": None}

    data = run_sql(sql)

    # Ask OpenRouter to summarize the results
    client = _openrouter_client()
    rows_preview = json.dumps(data["rows"][:10], indent=2)
    total = len(data["rows"])

    summary_prompt = f"""You are a business data analyst. Summarize these query results in 2-3 clear sentences.
Question asked: {req.question}
SQL query: {sql}
Total rows returned: {total}
First 10 rows: {rows_preview}

Be specific with numbers. Do not make up data not in the results. Keep it concise."""

    summary_resp = client.chat.completions.create(
        model=OPENROUTER_MODEL,
        messages=[{"role": "user", "content": summary_prompt}],
        temperature=0.3,
    )
    answer = summary_resp.choices[0].message.content.strip()

    highlighted_node_ids = extract_highlighted_nodes(data["columns"], data["rows"])

    return {
        "answer": answer,
        "sql": sql,
        "explanation": explanation,
        "data": data,
        "off_topic": False,
        "highlighted_node_ids": highlighted_node_ids,
    }

@app.get("/api/health")
def health():
    return {"status": "ok", "db_exists": DB_PATH.exists()}
