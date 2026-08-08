# Bank Statement Analyzer

A self-hosted Streamlit app that turns bank statement PDFs — password-protected
or not, from HDFC, ICICI, Kotak, SBI, DBS, or most other Indian banks — into a
categorized income/spend dashboard, a filterable transaction table, and an
optional chat panel you can point at Claude's API or a fully local model.

Everything runs on your own machine (or your own Fly.io app). Parsing and
categorization never leave the box; the only thing that can leave is what you
explicitly ask the "Ask AI" tab, and only to whichever model you configure.

## Features

- **Upload PDFs directly** — password-protected statements are unlocked in
  memory (pypdf), nothing is written to disk unencrypted.
- **Multi-bank parsing** — a bank-agnostic engine reconciles every transaction
  against the statement's own printed running balance, so it isn't hostage to
  knowing each bank's exact column layout. HDFC and ICICI have been tuned
  against real statements; Kotak/SBI/DBS use sensible defaults (see
  [Supported banks](#supported-banks--parsing-notes)).
- **Editable categorization** — a keyword-rule YAML file drives spend/income
  categories, editable from the sidebar with no code changes.
- **Multi-statement / multi-bank** — upload several accounts at once; an
  optional heuristic flags likely transfers between your own accounts so they
  don't get double-counted as both spend and income.
- **Dashboard** — income by source, spend by category, month-over-month
  trend, and balance-over-time charts (Plotly).
- **Raw data table** — filter by bank/category/direction/search text, flag
  low-confidence parsed rows for review, export to CSV.
- **Ask AI (optional)** — a chat panel backed by either Claude's API or any
  local OpenAI-compatible model server (Ollama, LM Studio, vLLM), using tool
  calls to query your real transaction data rather than guessing numbers.
- **Docker + Fly.io ready** — one Dockerfile, one `fly.toml`.

## Quickstart — run locally (no Docker)

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501, upload a statement in the sidebar, enter its
password if it has one, and click **Parse statements**.

## Quickstart — Docker

```bash
docker build -t statement-analyzer .
docker run -p 8501:8501 statement-analyzer
```

Open http://localhost:8501.

### Docker Compose

`docker-compose.yml` is set up so you can pass a Claude API key or point at a
local model server via environment variables instead of typing them into the
UI every run:

```bash
# optional — skip either/both and configure them in the sidebar instead
export ANTHROPIC_API_KEY=sk-ant-...
export LOCAL_LLM_BASE_URL=http://host.docker.internal:11434/v1

docker compose up --build
```

`host.docker.internal` is how the container reaches a model server (e.g.
Ollama) running on your host machine — `docker-compose.yml` already maps it.

## Deploying to Fly.io

1. [Install flyctl](https://fly.io/docs/flyctl/install/) and `fly auth login`.
2. From this directory:
   ```bash
   fly launch --no-deploy
   ```
   It'll detect `fly.toml` and offer to reuse it — say yes, pick/confirm an
   app name (edit the `app` line in `fly.toml` if you want a specific one
   ahead of time), and decline creating a Postgres/Redis database (not
   needed).
3. If you want a default Claude API key baked in as a secret (otherwise just
   paste it into the sidebar each session):
   ```bash
   fly secrets set ANTHROPIC_API_KEY=sk-ant-...
   ```
4. Deploy:
   ```bash
   fly deploy
   ```
5. `fly open` to launch it in your browser.

By default the app scales to zero when idle (`auto_stop_machines = "stop"` in
`fly.toml`) so you're not paying for a VM sitting there between uses — the
first request after a while just takes a few seconds longer to wake it up.

**A note on hosting this remotely at all:** you're uploading bank statements
to a server. Fly's free/hobby tier is a single small VM you control, not a
shared platform reading your data, but if that tradeoff doesn't sit right for
your statements, the local/Docker path keeps everything on your own machine.

## Connecting an LLM for the "Ask AI" tab

The chat panel is entirely optional — everything else in the app works
without it. When enabled, it uses tool calling so the model looks up real
numbers from your parsed data (category totals, monthly trends, filtered
transaction search) instead of guessing.

### Option A — Claude API

1. Get an API key from the [Anthropic Console](https://console.anthropic.com/settings/keys)
   (Anthropic's developer platform — separate from a claude.ai subscription).
2. In the sidebar, choose **Claude API**, paste the key, and enter a model
   name. Check the
   [models overview](https://docs.anthropic.com/en/docs/about-claude/models)
   for the current model IDs available to your account — pricing and exact
   names change over time, so this README deliberately doesn't hardcode one.
3. Or skip the UI field and set an environment variable before launching
   (`ANTHROPIC_API_KEY`, and optionally `ANTHROPIC_MODEL`) — the sidebar
   picks those up as defaults.

**Privacy:** using this option sends tool-call *results* (category totals,
matching transaction rows — never the raw PDF) to Anthropic's API each time
you ask a question. If that's not acceptable for your statements, use a local
model instead.

**Cost:** this is metered API usage, billed by Anthropic separately from any
claude.ai subscription — a few cents per question for a typical exchange, but
check current pricing on the page above.

### Option B — a local model (nothing leaves your machine)

Any server that speaks the OpenAI `chat.completions` API works. Two easy
options:

**Ollama** (simplest):
```bash
# install: https://ollama.com/download
ollama pull llama3.1        # or qwen2.5, mistral-nemo, etc — pick one that
                             # supports tool/function calling for best results
ollama serve                 # usually already running as a background service
```
In the sidebar: **Local model**, Base URL `http://localhost:11434/v1`, Model
name `llama3.1`.

**LM Studio**: load a model, start its local server (Developer tab → Start
Server), then use Base URL `http://localhost:1234/v1` and whatever model name
LM Studio shows for it.

**Running the app itself in Docker, model server on your host machine:** use
`http://host.docker.internal:11434/v1` (already the default in
`docker-compose.yml`) instead of `localhost` — from inside the container,
`localhost` means the container, not your host.

**Model capability note:** the app tries function/tool calling first (most
accurate — it grounds answers in real query results). If the model or server
doesn't support it, it automatically falls back to a one-shot summary stuffed
into the prompt, which still works but is less precise for row-level
questions ("which transactions..." vs "how much did I spend on..."). Larger,
more recent local models (Llama 3.1 8B+, Qwen2.5 7B+, Mistral Nemo) generally
support tool calling through Ollama; very small models often don't.

## Supported banks & parsing notes

| Bank | Status |
|---|---|
| HDFC | Tuned and verified against real statements — reconciles exactly. |
| ICICI | Tuned and verified against real statements — typically reconciles within ~1%. |
| Kotak, SBI, DBS | Generic profile, not yet verified against real statements from these banks. |

The parser works in two passes:

1. **Table extraction** (`src/parsers/table_engine.py`) — if pdfplumber finds
   real tagged table structure in the PDF with recognizable column headers
   (Date/Narration/Debit/Credit/Balance or common variants), it uses that
   directly. Most reliable when it applies.
2. **Line-based fallback** (`src/parsers/line_engine.py`) — for the common
   case of a print-formatted (not tagged-table) statement. Rather than
   needing to know each bank's column order, it reconciles every row against
   the statement's own *printed, cumulative* balance: given where the
   running balance started, the direction and size of every later
   transaction can be derived from how much the balance moved — no
   bank-specific column parsing required. This is what makes Kotak/SBI/DBS
   support possible without sample statements to hand-tune against.

Every parsed statement's running balance is checked against its own printed
closing balance (the **Parsing Details** tab shows this per file). A clean
reconciliation is a strong trust signal; a drift means some rows were
assigned by best-fit guessing rather than certainty — those rows are also
individually flagged with a lower `confidence` score, filterable in the raw
data table.

### Adding or improving a bank parser

Most of the work is in `src/parsers/profiles.py` — a `BankProfile` is just:
phrases that mark an opening-balance line, column header words (for the
table engine), date formats to try, and narration prefixes that mark where a
new transaction's text starts (for reattaching wrapped lines correctly). Add
or edit one for Kotak/SBI/DBS once you have a real statement to check the
**Parsing Details** reconciliation against, and adjust the profile until it
comes out clean. `src/parsers/line_engine.py` and `table_engine.py` shouldn't
need bank-specific changes — the profile is the extension point.

## Editing categorization rules

`src/rules_default.yaml` ships with a broad default rule set (salary,
loans/EMI, investments, insurance, shopping, food delivery, medical, travel,
utilities, etc). Open **2 · Categorization rules → Edit rules (YAML)** in the
sidebar to add your own — common additions:

- Family members' names, for transfers you make/receive regularly
- Specific merchants the defaults miss
- A `direction: credit` or `direction: debit` on a rule to restrict it (e.g.
  a "Salary" rule shouldn't match a debit)

Rules are checked top to bottom; the first keyword match wins, so put
specific rules above general ones. Click **Reset to default** to get back to
the shipped ruleset at any time — edits only live in the current browser
session unless you save the YAML to `src/rules_default.yaml` yourself.

## Multi-account transfer detection

With 2+ accounts loaded, "Detect transfers between my own accounts" (on by
default) looks for a debit in one account and a credit in a *different*
account for the same amount within a few days, and tags both as an internal
transfer — excluded from the income/expense totals so moving your own money
around doesn't inflate either number. It's a heuristic, not a certainty;
review flagged rows in the raw data table (category = "Internal Transfer (own
accounts)") if a total looks off.

## Project layout

```
app.py                     Streamlit UI — the only file that talks to Streamlit
src/
  models.py                 Transaction / Statement dataclasses
  pdf_utils.py               decrypt + text/table extraction (pypdf + pdfplumber)
  bank_detect.py              bank identification from statement letterhead
  parsers/
    profiles.py               per-bank tuning knobs — start here for a new bank
    table_engine.py            structured extraction when the PDF has real tables
    line_engine.py             bank-agnostic balance-reconciliation fallback
    utils.py                   shared regex/date/amount helpers
  categorize.py                keyword rule engine
  rules_default.yaml           the default rule set (editable from the UI)
  analysis.py                   category/monthly summaries, transfer detection
  llm/
    base.py                     shared LLMClient interface + system prompt
    anthropic_client.py          Claude API backend (native tool use)
    openai_compatible.py         Ollama/LM Studio/vLLM/OpenAI backend
    tools.py                     the query functions the model can call
    chat.py                      client factory
  ui/charts.py                   Plotly figure builders
```

## Troubleshooting

- **"Couldn't find any dated transaction rows"** — the parser couldn't locate
  a transaction table at all. Try selecting the bank manually instead of
  Auto-detect (sidebar), and check the PDF actually contains a normal text
  layer (a scanned image statement needs OCR first, which this app doesn't
  do).
- **Large reconciliation drift in Parsing Details** — check the low-confidence
  filter in the raw data table to see which specific rows the parser wasn't
  sure about; for Kotak/SBI/DBS this is where you'd start tuning that bank's
  `BankProfile`.
- **"That password didn't work"** — some banks use a different case/format
  than you'd expect (e.g. PAN in caps, or DOB as DDMMYYYY) — check the
  password hint your bank's statement email gives you.
- **Local model chat gives vague answers** — it likely fell back to the
  non-tool-calling path; try a model/server combination that supports OpenAI
  function calling (see [Option B](#option-b--a-local-model-nothing-leaves-your-machine)).
- **Docker container can't reach my local Ollama** — use
  `host.docker.internal` instead of `localhost` in the base URL (see above).

## Security notes

- Uploaded PDFs and their passwords live only in the Streamlit process's
  memory for the session — nothing is written to disk by default.
- Category rules and chat history are session state only; closing the tab
  clears them (nothing is persisted unless you add your own storage).
- If you use Claude API, tool-call results are sent to Anthropic per query —
  see [Option A](#option-a--claude-api) above.
- Don't commit a `.env` file or paste API keys into files you commit —
  `.gitignore` already excludes `.env` and `.streamlit/secrets.toml`.
