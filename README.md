# Financial Statement Analyser

A self-hosted Streamlit app that pulls together three optional sources of
your financial life — bank statement PDFs, a personal finance-tracking
spreadsheet, and an INDmoney portfolio snapshot — into one dashboard: net
worth, categorized income/spend, investments and SIPs, budget-vs-actual, a
filterable transaction table, and a chat panel you can point at Claude's API
or a fully local model.

Everything runs on your own machine (or your own Fly.io app). Parsing and
categorization never leave the box; the only thing that can leave is what you
explicitly ask the "Ask AI" tab, and only to whichever model you configure.

## The three data sources (all optional, load any subset)

| Source | What it needs | How fresh |
|---|---|---|
| **Bank statements** | PDF upload, password if any | As current as your last download |
| **Personal finance sheet** | `.xlsx` upload | As current as your last export from Drive |
| **INDmoney portfolio** | JSON upload, or a local-only live connect | See [below](#3--indmoney-portfolio) for both options |

Bank statements and the personal sheet are always file uploads — nothing the
app polls on its own. INDmoney additionally supports connecting live (see
below), but that connection is still local-only and session-only by design;
see why under each source below.

## Features

- **Upload PDFs directly** — password-protected statements are unlocked in
  memory (pypdf), nothing is written to disk unencrypted.
- **Multi-bank parsing** — a bank-agnostic engine reconciles every transaction
  against the statement's own printed running balance, so it isn't hostage to
  knowing each bank's exact column layout. Also detects and separates linked
  sub-account ledgers (e.g. a PPF account printed in the same PDF as your
  savings account) so they don't get merged into the wrong statement. HDFC
  and ICICI have been tuned against real statements; Kotak/SBI/DBS use
  sensible defaults (see [Supported banks](#supported-banks--parsing-notes)).
- **Editable categorization** — a keyword-rule YAML file drives spend/income
  categories, editable from the sidebar with no code changes.
- **Multi-statement / multi-bank** — upload several accounts at once; an
  optional heuristic flags likely transfers between your own accounts so they
  don't get double-counted as both spend and income.
- **Net worth** — combines INDmoney's portfolio total (assets by type, sector,
  market cap, loans, credit cards) with your personal sheet's manually-tracked
  totals and your banks' latest closing balances, clearly labeled by source
  rather than silently merged into one number that might double-count.
- **Investments & SIPs** — INDmoney holdings by asset type with P&L, active
  SIPs and total monthly commitment, sector/market-cap breakdowns.
- **Budget vs. actual** — compares your personal sheet's planned monthly
  budget against your real average monthly spend per category, computed from
  categorized bank transactions.
- **Dashboard** — income by source, spend by category, month-over-month
  trend, and balance-over-time charts (Plotly).
- **Raw data table** — filter by bank/category/direction/search text, flag
  low-confidence parsed rows for review, export to CSV.
- **Ask AI (optional)** — a chat panel backed by either Claude's API or any
  local OpenAI-compatible model server (Ollama, LM Studio, vLLM), using tool
  calls across all three data sources to answer from real numbers rather
  than guessing.
- **Docker + Fly.io ready** — one Dockerfile, one `fly.toml`.

## Quickstart — run locally (no Docker)

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501 and drop whichever files you have (bank statement
PDFs, personal sheet, INDmoney snapshot — any subset) into the sidebar's
uploader. Each file gets a "Type" dropdown — Bank Statement, Personal
Finance, or Portfolio — defaulted from its extension; everything parses
automatically as soon as it's tagged (bank statements also get an optional
bank hint and password field, since some are password-protected).

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
   And, since this app will be reachable on the public internet, set a
   password (see [Restricting access](#restricting-access-password-gate)
   below) — do this *before* your first deploy if you can, so the app is
   never open without one:
   ```bash
   fly secrets set APP_PASSWORD=choose-something-not-guessable
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
(and, if you use them, your personal net-worth spreadsheet and portfolio
snapshot) to a server. Fly's free/hobby tier is a single small VM you
control, not a shared platform reading your data, but if that tradeoff
doesn't sit right for data this sensitive, the local/Docker path keeps
everything on your own machine.

## Restricting access (password gate)

Anyone with your Fly.io URL can otherwise open the app and use it — nothing
of *yours* is exposed (there's no persistent storage; each browser session's
uploads live only in that session's memory), but it's still your app running
on your bill, doing its own thing for whoever finds the link. A single shared
password behind `APP_PASSWORD` closes that:

```bash
fly secrets set APP_PASSWORD=choose-something-not-guessable
```

Setting the secret alone is enough — `src/auth.py` picks it up automatically
and puts a password screen in front of everything else, no redeploy required
(Fly restarts the machine with the new secret in place). Leave `APP_PASSWORD`
unset — the default, and how local dev runs — and the app has no gate at all.

This is a shared secret, not real auth: one password for anyone you give it
to, no per-user accounts, no rate limiting on guesses, no audit log. Good
enough to keep a personal deployment off the open internet's radar; not a
substitute for proper auth if that ever matters more (e.g. multiple people
each needing their own login).

To run the same gate locally: `APP_PASSWORD=whatever streamlit run app.py`.

## Connecting an LLM for the "Ask AI" tab

The chat panel is entirely optional — everything else in the app works
without it. When enabled, it uses tool calling so the model looks up real
numbers from whichever data sources are loaded (bank transactions, personal
sheet, INDmoney portfolio) instead of guessing.

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
matching transaction rows, portfolio/sheet figures — never the raw PDF,
sheet, or JSON files themselves) to Anthropic's API each time you ask a
question. If that's not acceptable for data this sensitive, use a local
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
| ICICI | Tuned and verified against real statements — typically reconciles within ~1%. Also handles ICICI's habit of printing a linked PPF sub-account ledger in the same PDF (auto-detected and excluded from the main statement). |
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
   support possible without sample statements to hand-tune against. It also
   detects multiple ledgers in one PDF (a linked PPF/FD sub-account) by
   splitting on repeated opening-balance ("B/F") lines and keeping only the
   largest one as the main statement.

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
utilities, etc). Open **Categorization rules → Edit rules (YAML)** in the
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

## 2 · Personal finance sheet

If you keep a personal spreadsheet tracking investments, a monthly budget, or
a property loan, the app can read it — as a plain `.xlsx` upload (sidebar,
tagged "Personal Finance"), the same pattern as a bank statement, not a live
Google Sheets API connection. Live API access would mean this app holding a
standing credential to your Drive; a file you export when you want fresh
numbers keeps the same one-shot trust model as everything else here.

**To get the file:** open your sheet in Google Sheets → File → Download →
Microsoft Excel (.xlsx), then upload that file in the sidebar and tag it
"Personal Finance".

**What it reads**, from a spreadsheet built around four tabs (adjust
`src/sources/personal_sheet.py` if your own sheet's tab names or layout
differ — see that file's docstrings for the exact layout each parser
expects):

- **Investments** tab → itemized holdings by section (mutual funds, FDs,
  RDs, savings, provident fund, fixed assets, liabilities) — feeds the Net
  Worth tab.
- **MonthlyYearly Expenses** tab → your planned monthly budget — feeds
  Budget vs. Actual.
- **NirmanPayments** tab (or similarly named) → a property loan's EMI
  schedule (date/interest/principal) and summary stats — feeds the EMI chart
  in Budget vs. Actual. The rest of that tab (ad-hoc payment notes, disbursement
  timelines) is too unstructured to parse reliably and is left out.
- **My_Savings_Investments** tab (or similarly named) → just the "Total
  Surplus" figure and any per-property equity-share breakdown, since the
  rest of that tab tends to re-aggregate the Investments tab.

**Two tabs are never opened**, by name pattern (`trading`, `saving[s]_?scheme`
— case-insensitive): whatever you use those for stays untouched.

## 3 · INDmoney portfolio

There are two ways to get INDmoney data into this app. Both produce the same
`IndmoneyPortfolio` object internally (`src/sources/indmoney.py`), so
everything downstream — Net Worth, Investments & SIPs, Ask AI — behaves
identically either way.

### Option A — connect live (local use only)

INDmoney runs its own public MCP server (`mcp.indmoney.com`) with standard
OAuth 2.1 + PKCE and self-service dynamic client registration — it's a
separate, INDmoney-operated endpoint, not something routed through Claude.
`src/indmoney_oauth.py` and `src/indmoney_mcp_client.py` implement a minimal
client against it directly, so the app can pull a fresh snapshot itself
without Claude in the loop at all.

Click **Connect INDmoney** in the sidebar's "🔗 Connect INDmoney live instead"
expander (below the file uploader). This:

1. Registers this app as an OAuth client with INDmoney (happens silently,
   once per session — no manual approval step on INDmoney's side).
2. Gives you a link to INDmoney's own login page. You authenticate there
   directly (mobile + OTP + MPIN) — this app never sees your INDmoney
   credentials, only the OAuth redirect back with an authorization code.
3. Exchanges that code for an access token and immediately fetches your
   net worth, holdings, and SIPs over the MCP protocol.

**Why this is local-only, session-only, by design:**

- The OAuth redirect URI is fixed to `http://localhost:8501/`. If you deploy
  this app elsewhere (Fly.io, etc.), INDmoney's login can't redirect back to
  it — Option A only works when you're running the app on your own machine
  and browsing to `localhost`. Use Option B (snapshot upload) on a hosted
  deployment.
- The access/refresh tokens live only in Streamlit's `session_state` — never
  written to disk, never persisted across a restart. Closing the tab or
  restarting the app means reconnecting.
- There's a **Disconnect** button (revokes the token with INDmoney and clears
  it from session state) and a **Refresh now** button (re-fetches without a
  full re-login, using the stored refresh token) once connected.

### Option B — upload a snapshot (works anywhere, including hosted deployments)

This is the original approach: ask Claude — in a separate conversation, using
Claude's own INDmoney connector — to export your portfolio to a JSON file,
then upload that file in the sidebar's file uploader and tag it "Portfolio",
the same way you'd upload a bank statement. Refresh it whenever you want
current numbers. This is the only option available on a hosted deployment,
since Option A's redirect can't reach a non-localhost app.

**To generate a snapshot**, in a Claude conversation with the INDmoney
connector available, ask something like:

> Using the INDmoney tools, call `networth_snapshot`, then `networth_holdings`
> for each asset type that has a non-zero value in that snapshot (typically
> MF, IND_STOCK, US_STOCK, EPF, PPF, FD), then `mf_sips` and
> `indian_stocks_sips`. Assemble the results into one JSON file with this
> exact shape and give it to me to download:
> ```json
> {
>   "exported_at": "<current ISO8601 timestamp>",
>   "networth_snapshot": { ...raw networth_snapshot result... },
>   "holdings": { "MF": [...], "IND_STOCK": [...], "...": [...] },
>   "sips": { "mf": [...raw mf_sips result...], "stocks": [...raw indian_stocks_sips result...] }
> }
> ```

Upload the resulting file in the sidebar. `src/sources/indmoney.py` has the
full schema this parser expects if you want to build the export differently.

**Privacy note specific to Option B:** because the export happens inside
a Claude conversation, that data already passed through Claude once before
it ever reaches this app — the same privacy consideration as the Ask AI tab
(see [Connecting an LLM](#connecting-an-llm-for-the-ask-ai-tab)) applies to
generating the snapshot itself, regardless of which LLM option you pick
inside the app afterward.

## Project layout

```
app.py                        Streamlit UI — the only file that talks to Streamlit
src/
  auth.py                       optional shared-password gate (APP_PASSWORD)
  models.py                    Transaction / Statement dataclasses
  pdf_utils.py                  decrypt + text/table extraction (pypdf + pdfplumber)
  bank_detect.py                 bank identification from statement letterhead
  parsers/
    profiles.py                  per-bank tuning knobs — start here for a new bank
    table_engine.py               structured extraction when the PDF has real tables
    line_engine.py                bank-agnostic balance-reconciliation fallback
    utils.py                      shared regex/date/amount helpers
  categorize.py                 keyword rule engine
  rules_default.yaml            the default rule set (editable from the UI)
  analysis.py                    category/monthly summaries, transfer detection
  budget_compare.py              maps sheet budget categories onto spend categories
  sources/
    personal_sheet.py             personal finance-tracking .xlsx parser
    indmoney.py                    INDmoney portfolio parser (shared by upload + live fetch)
  indmoney_oauth.py                OAuth 2.1 + PKCE client for INDmoney's MCP server (live connect)
  indmoney_mcp_client.py            minimal MCP Streamable HTTP client (live connect)
  llm/
    context.py                    bundles all loaded data sources for the tools
    base.py                       shared LLMClient interface + system prompt
    anthropic_client.py           Claude API backend (native tool use)
    openai_compatible.py          Ollama/LM Studio/vLLM/OpenAI backend
    tools.py                      the query functions the model can call
    chat.py                       client factory
  ui/charts.py                    Plotly figure builders
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
- **"Couldn't parse this sheet"** — your tab names or layout likely differ
  from what `src/sources/personal_sheet.py` expects; open that file and
  compare its docstrings against your sheet's actual structure.
- **Budget vs. Actual is empty** — the category names in your sheet's budget
  tab don't match any entry in `BUDGET_TO_SPEND_CATEGORY` in
  `src/budget_compare.py`; add your own sheet's category names there.
- **Net worth numbers look duplicated** — the Net Worth tab intentionally
  shows INDmoney and the personal sheet as separate panels rather than
  merging them, since anything you track manually *and* link in INDmoney
  (e.g. mutual funds) would otherwise be double-counted. Treat the personal
  sheet panel as "what INDmoney doesn't already cover."
- **Local model chat gives vague answers** — it likely fell back to the
  non-tool-calling path; try a model/server combination that supports OpenAI
  function calling (see [Option B](#option-b--a-local-model-nothing-leaves-your-machine)).
- **Docker container can't reach my local Ollama** — use
  `host.docker.internal` instead of `localhost` in the base URL (see above).

## Security notes

- Uploaded PDFs, spreadsheets, JSON snapshots, and any passwords live only in
  the Streamlit process's memory for the session — nothing is written to disk
  by default.
- Category rules and chat history are session state only; closing the tab
  clears them (nothing is persisted unless you add your own storage).
- If you use Claude API in the Ask AI tab, tool-call results are sent to
  Anthropic per query — see [Option A](#option-a--claude-api) above.
- If you use Option B (snapshot upload), the snapshot's *generation* (not its
  use inside this app) happens in a separate Claude conversation with the
  INDmoney connector — see the privacy note under
  [INDmoney portfolio](#3--indmoney-portfolio). Option A (live connect) never
  routes through Claude at all — your INDmoney login and portfolio data go
  directly between this app and INDmoney's own servers.
- If you use Option A, the access token lives only in `session_state` for
  that browser session and only works when the app is reachable at
  `localhost` — see [Option A](#option-a--connect-live-local-use-only) above.
- Don't commit a `.env` file, an exported sheet/snapshot, or API keys into
  files you commit — `.gitignore` already excludes `.env`,
  `.streamlit/secrets.toml`, and `data/` (a reasonable place to keep your own
  exports locally without risking an accidental commit).
