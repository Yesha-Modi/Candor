# CANDOR

**An analytics agent that would rather say "I don't know" than hand you a wrong number.**

Ask a business question in plain English. Get the SQL, the chart, and the answer — or get a
refusal, with the reason.

> 🚧 **In progress.** The data layer is complete and tested. The agent and its benchmark are
> being built — see [Roadmap](#roadmap).

---

## The problem

Every company has the same bottleneck. The people who need answers can't write SQL; the people
who can are a small team with a queue. A question becomes a ticket, the ticket takes three
days, and the meeting it was for already happened.

The obvious fix is to put a language model in the middle. Most attempts fail — and they fail in
a way that makes them worse than useless.

**They don't fail loudly. They fail silently.** The model returns a confident, cleanly
formatted, professional-looking number that happens to be wrong. The person asking has no way
to tell, because not knowing SQL was the whole reason they asked.

### Here is that failure, measured

Two queries against this database. Both run. Neither errors. Neither warns.

| | |
|---|---|
| Total order value, computed correctly | **R$15,843,550** |
| Same figure, after one careless join | **R$20,304,560** |
| Overcounted | **R$4,461,010 — 28.2%** |

The second query joins orders to order items and sums an order-level column. Each order is now
repeated once per item it contains, so its value is counted that many times.

What makes it worse than it looks: the row count only inflates by 14.2%, but the money inflates
by 28.2%. Orders with more items also have higher value, so the multiplication lands hardest on
the expensive ones. You cannot estimate the error from the row counts.

**This is what CANDOR is built to prevent.**

---

## The approach

Three things, and the third is the one that matters.

**1. The model is told what the business means.** Instead of being pointed at raw tables and
asked to guess, it is given defined metrics with their grain, filters, and join paths. It
composes answers from building blocks rather than inventing definitions.

**2. The model is allowed to say no.** Unanswerable questions get an explicit refusal.
Ambiguous ones get a clarifying question. Every answer shows the SQL it ran, the metrics it
used, and the assumptions it made.

**3. It ships with a report card.** 60 test questions with verified answers, scored and
published — including the failures, sorted into categories, with examples.

Most projects of this kind show the three questions that worked. This one publishes the ones
that didn't.

---

## What is built

```
raw (9 tables)  →  staging (9 views)  →  marts (6 tables)
     CSV              typed, renamed,        star schema
                      deduplicated
```

**Dimensions** — `dim_customers`, `dim_products`, `dim_sellers`, `dim_dates`
**Facts** — `fct_orders` (99,441 rows), `fct_order_items` (112,650 rows)

**71 dbt nodes, 55 data quality tests, all passing**, including six referential integrity
checks and a reconciliation test that verifies total item value computed two independent ways
agrees to the cent.

### The dataset

[Olist Brazilian E-Commerce](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) —
~100k real orders across nine related tables, including free-text customer reviews. Public,
messy, and complex enough that the questions require real joins.

---

## What the data turned out to be hiding

Four findings, each of which changed the design. All four came from checking a number rather
than accepting it.

### A customer is not a customer

The source `customers` table has **99,441 rows — exactly the same as the order count.** Olist
issues a new `customer_id` for every order. The actual person is `customer_unique_id`, and
there are **96,096** of those.

Build on the wrong column and "average orders per customer" is 1.00 — a number that looks
entirely reasonable and means nothing. The customer dimension is keyed on the person, and the
order counts reconcile back to 99,441 exactly.

### A review can belong to several orders

A uniqueness test on `review_id` failed: **789 IDs appear more than once.** Rather than
deleting the test, I investigated. All 789 duplicate groups have *identical* score and comment
text, each attached to a *different* order.

That is one review covering several orders — basket splitting, where a multi-seller purchase
becomes several order records. Deduplicating would have destroyed real links. The identity is
the **(review, order) pair**, now asserted by a custom test.

### 623 uncategorised products were two different problems

Splitting the count by cause: **610** products genuinely have no category in the source, but
**13** have a perfectly good Portuguese category simply missing from Olist's 71-row translation
table — `portateis_cozinha_e_preparadores_de_alimentos` and `pc_gamer`.

Only the first group is unknown. The other 13 were losing a label we already had. Fixed with a
fallback chain and a small override seed, kept separate from the source so it is clear which
translations are Olist's and which are mine.

### Eight orders claim delivery with no delivery date

96,478 orders are marked `delivered`, but only **96,470** of them have a delivery date — eight
do not. Separately, **six** orders carry a delivery date without `delivered` status. Those
eight get **empty** delivery times, not zero. Zero would drag every average down with two impossible same-day
deliveries. The `is_late` flag returns null rather than false for undelivered orders — because
otherwise a warehouse that stopped shipping entirely would show a perfect record.

---

## A note on checking

Three verification checks during this build looked reasonable and weren't:

| Check | Flaw |
|---|---|
| Table count after a fix | **Too narrow** — identical value whether the fix worked or not |
| Products still showing Portuguese names | **Too broad** — also matched the 7 categories whose English and Portuguese names are the same word |
| Row count from a catalog query | **Right answer, wrong question** — correct count, hidden columns |

Each produced a true statement that answered a different question than the one being asked.
Two questions now get asked before trusting any check: *what would this show me if the thing
were broken,* and *what else could produce this same number?*

---

## Current business numbers

Computed from the built models, filtered to delivered orders where relevant.

| Metric | Value |
|---|---|
| Orders | 99,441 |
| Delivered | 96,478 (97.0%) |
| Cancelled or unavailable | 1,234 |
| Distinct customers | 96,096 |
| Repeat customers | 2,997 (3.1%) |
| Total order value | R$15,843,550 |
| — items | R$13,591,640 |
| — freight | R$2,251,910 |
| Average delivery time | 12.5 days |
| Late deliveries | 7,827 (8.1% of delivered) |
| Orders with no line items | 775 |

---

## Stack

Everything here is free, with no paid tier anywhere in the project.

| Layer | Tool |
|---|---|
| Warehouse | DuckDB |
| Transformation | dbt Core |
| Language | Python 3.13 |
| LLM providers | Google Gemini (free tier), Groq, Ollama (local) |
| Orchestration | LangChain, LangGraph |
| SQL safety | sqlglot AST validation |
| Interface | Streamlit + Plotly |
| CI | GitHub Actions |

---

## Running it

```bash
git clone https://github.com/Yesha-Modi/candor.git
cd candor

py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows
# source .venv/bin/activate         # macOS / Linux

pip install -r requirements.txt
```

Download the [Olist dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) and
extract the nine CSVs into `data/raw/`. Then:

```bash
python -m src.ingest        # load CSVs into DuckDB
cd transform
dbt seed                    # load reference overrides
dbt build                   # build all models, run all tests
cd ..
python -m src.profile       # 16 data quality and reconciliation checks
```

---

## Repository layout

```
candor/
├── data/raw/           Olist CSVs (not committed)
├── db/                 DuckDB file (not committed)
├── src/
│   ├── config.py       Paths
│   ├── ingest.py       CSV → DuckDB
│   ├── peek.py         Quick inspection
│   └── profile.py      16 data quality checks
├── transform/          dbt project
│   ├── models/
│   │   ├── staging/    9 views: rename, type, clean
│   │   └── marts/      4 dimensions, 2 facts
│   ├── seeds/          Category translation overrides
│   └── tests/          Custom SQL assertions
├── eval/               Gold questions + harness (coming)
└── app/                Streamlit interface (coming)
```

---

## Roadmap

- [x] **Data layer** — ingestion, staging, star schema, 55 tests
- [ ] **Gold benchmark** — 60 questions with verified SQL, stratified into simple aggregates,
      multi-table joins, time series, **ambiguous**, and **unanswerable**
- [ ] **The agent** — semantic layer, retrieval, structured output, read-only execution with
      AST validation
- [ ] **The evaluation** — execution accuracy with and without the semantic layer, four models
      compared on accuracy / latency / cost, full failure taxonomy
- [ ] **The product** — Streamlit interface, live demo, CI running the benchmark on every push

---

## License

MIT