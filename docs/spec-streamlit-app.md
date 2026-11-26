# Spec: the Streamlit app (WP-2 Portfolio page, WP-3 Research page)

**Written:** 2026-10-27, from the grilling session of 2026-10-18 (rounds 1 and 2)
and the follow-up on 2026-10-27. **Status: WP-2 (Portfolio page) is built,
2026-10-29; WP-2.1 (Monthly and Chart sheets) is built, 2026-10-30; WP-3.1
(the Research data layer, `research_data.py`) is built, 2026-10-31; WP-3.3
(the Research page with its ETF view) is built, 2026-11-01; WP-3.2 (the
stock view) is built, 2026-11-05; WP-3.4 (snapshots and the Library page)
is built, 2026-11-11; WP-2.2 (Portfolio page layout) is built,
2026-11-15; WP-3.4.1 (Compare with today on the Library) is built,
2026-11-16. The rest is plan; each build starts only
on the owner's word.**

---

## 0. What the app is

A local web app on this PC. Streamlit turns one Python script into a web page:
you run one command (or a `.bat`), the browser opens `http://localhost:8501`,
and that page is the app. No hosting, no login, no server beyond your laptop.
The app stops when you close the window.

Three pages (tabs on the left):

| page | reads | writes |
|---|---|---|
| Portfolio | `Portfolio_Tracker.xlsx` (written nightly by the tracker) | nothing |
| Research | Yahoo Finance via `yfinance`, one code at a time; the Holdings sheet for the chips. Built: code box, chips, tiles, ETF view (WP-3.3); stock view (WP-3.2) | one JSON snapshot per Save, optional Excel download (WP-3.4, 3.5) |
| Research library | the `research/` folder of snapshots | nothing (reopens a snapshot) |

Read-only against Moomoo. The app never trades and never calls OpenD.

```
Moomoo OpenD ─┐
Yahoo Finance ┼─► portfolio_tracker.py ─► Portfolio_Tracker.xlsx ─┐
Settings ─────┘                                                   ├─► app.py (Streamlit)
Yahoo Finance ─────────────────────────────────────► research/ ───┘
```

## 1. Rulings from the grilling (settled)

| # | ruling | source |
|---|---|---|
| S1 | Research page is a **tool used before buying**. Narrow and fast beats feature count. | Q1 |
| S2 | Universe: any single code typed, Bursa (`5398.KL`) or US (`AAPL`); **stocks and ETFs**. Unit trusts out (no source). Current holdings shown as quick-pick chips. | Q2, Q18 |
| S3 | **yfinance for everything** on the Research page, both markets. Moomoo is the Portfolio page's source only. | Q3, Q15 |
| S4 | Credit block = nine ratios computed from the statements, not vendor ratios. | Q4, Q17 |
| S5 | Periods: four annual years side by side, newest left, plus a TTM column when quarterly data exists. No fifth year. | Q5, Q19 |
| S6 | Valuation block: P/E, forward P/E, P/B, dividend yield, EV/EBITDA, market cap, price vs analyst mean target (upside %), buy/hold/sell count. No fair-value model of our own. | Q6 |
| S7 | **No news** in version 1. Links to the Yahoo Finance page and the Bursa or SEC filings page instead. | Q7, Q16 |
| S8 | Excel download per stock: Summary, Income, Balance, Cashflow, Valuation sheets, styled with the tracker's `write_table`. | Q8 |
| S9 | Tracker gains two sheets it writes itself: **Monthly** and **Chart**. No manual pivot tables. | Q12 |
| S10 | Snapshots: one JSON per Save under `research/`, with a notes box filled before saving. Library page lists and reopens them. | Q13 |
| S11 | ETF block replaces the credit block for ETFs (see section 4). Lights on expense ratio and fund size only. | Q18 |
| S12 | No scheduled research refresh in v1. | Q20 |
| S13 | AI commentary (Claude API) is a later package, off by default. | Q21 |
| S14 | "XR" means XIRR; it lives on the Portfolio page, not on a stock. | Q17 |

## 2. Decisions ruled 2026-10-29 (were open O1-O4; now settled)

| # | question | ruling |
|---|---|---|
| O1 | **Data portability (Q14).** Commit the workbook as well as the snapshots? | **(a) Snapshots only.** The house rule stands: `Portfolio_Tracker.xlsx` is personal data and never enters git. `research/` snapshots (public company data plus your notes) are committed and pushed nightly (WP-3.6). No ADR needed. |
| O2 | **Traffic-light thresholds.** | **Section 5 as written**, kept as settings at the top of `research_data.py`, one edit away. |
| O3 | **Financial-sector companies** (banks, insurers; Yahoo `sector == "Financial Services"`). | **(a) Show "n/a"** for interest cover, current ratio and net debt/EBITDA; light the other six. The **overall light is grey** for these companies with the line "credit ratios not meaningful for a bank; see profitability and valuation", so the headline never lies. A bank block (CET1, NPL ratio, cost/income, loan/deposit) is wanted but queued as **WP-3.7**, because yfinance does not reliably expose those fields, least of all for Bursa banks. |
| O4 | **Overall light per company.** | **(b) Worst of leverage, coverage and liquidity.** Profitability and growth are shown but do not drive the headline. Exception: O3 grey. |

## 3. Research page, stock view

**Workflow.** Type a code or click a chip. The app fetches (cached one hour),
computes, and shows the blocks below. Type a note. Click **Save** to write a
snapshot. Click **Download Excel** for a one-stock workbook.

**Header tiles.** Name, exchange, sector, price, market cap, overall light.

**Credit block.** Nine ratios, one row each, a column per period (4 annual +
TTM), a light on the newest period, and a one-line "why" under each light.

| group | ratio | formula (yfinance fields) |
|---|---|---|
| Leverage | Debt / Equity | Total Debt / Stockholders Equity |
| Leverage | Net debt / EBITDA | (Total Debt - Cash And Cash Equivalents) / EBITDA |
| Coverage | Interest cover | EBIT / Interest Expense |
| Liquidity | Current ratio | Current Assets / Current Liabilities |
| Cash | OCF / Total debt | Operating Cash Flow / Total Debt |
| Cash | FCF margin | Free Cash Flow / Total Revenue |
| Profitability | Net margin | Net Income / Total Revenue |
| Profitability | ROE | Net Income / Stockholders Equity |
| Growth | Revenue growth | Revenue this year / last year - 1 |

Rules: a zero or missing denominator shows "n/a", never a crash or an
infinity. Net cash (debt below cash) shows "net cash" and is green.

**Valuation block.** As S6. Upside % = mean target / price - 1.

**Statements.** Three expandable tables (income, balance, cash flow), same
periods, reporting currency shown in the title.

**Links.** Yahoo Finance quote page; Bursa announcements (for `.KL`) or SEC
EDGAR (for US).

**Notes + Save.** A text box and a Save button. Save writes
`research/<CODE>_<YYYY-MM-DD>.json`; a second save of the code that day
gets `_2`, then `_3`, never overwriting (owner, 2026-11-11). It holds the
note and the finished result with the price chart: every figure, light and
table the page shows, as it was that day, so a later change to a limit does
not recolour it (owner, 2026-11-11; was ratios, lights and valuation only).
The raw Yahoo reply is not stored. Built in WP-3.4 (`research_store.py`).

**Built 2026-10-31 (WP-3.1).** The data layer only (`research_data.py`); the
page is WP-3.2. Rulings taken at the build:
- Periods: the newest four fiscal years that hold any figure (an empty year
  is dropped), headed by the year-end date `YYYY-MM-DD`, newest first. TTM
  (trailing twelve months) comes first, only when Yahoo has four quarters of
  revenue and operating cash flow: flows are the sum of the newest four
  quarters, balance items the newest quarter. Fewer quarters: no TTM column.
  Quarters but no full year: TTM only, with a warning.
- Revenue growth is n/a on TTM (Yahoo gives no year-ago TTM) and on the
  oldest year.
- Interest cover uses Interest Expense without its sign; when Yahoo has none,
  n/a, "interest expense not reported". Negative EBIT: shown negative, red.
- Net debt at or below zero: "net cash", green. EBITDA zero or negative with
  net debt: n/a, red. Equity zero or negative: D/E red, ROE grey, both
  "negative equity".
- Boundaries fall on the amber side (D/E of exactly 0.5 or 1.0 is amber).
  Thresholds and reason phrases are settings at the top of the module
  (`THRESHOLDS`, `REASONS`).
- Light period: TTM when the ratio has a value there or a forced note (net
  cash, EBITDA zero or negative, negative equity); else the newest year.
  "Interest expense not reported" at TTM falls back to the newest year. The
  reason names the period: "<ratio> <value> (<period>): <phrase>".
- Overall light: worst of D/E, net debt / EBITDA, interest cover and current
  ratio, grey ignored; reason "worst: " plus that ratio's reason. None lit:
  grey "not enough data for a credit view". Banks: O3.
- Cache: one JSON per code in `output/research_cache/` (gitignored), kept one
  hour (`CACHE_TTL`); a copy exactly an hour old is stale. When the fetch
  fails, or Yahoo silently returns nothing while the old copy had figures, the
  old copy is shown, marked stale ("Yahoo unreachable; showing figures fetched
  <time>"), and is not overwritten. No copy: a plain error.
- Dividend yield is `trailingAnnualDividendYield`, a fraction; never
  `dividendYield`, which Yahoo gives as a percent.
- Not found: Yahoo raises nothing for a bad code. No `quoteType` and no annual
  income: error "Yahoo has no data for <code>". A `quoteType` but no
  statements (new listing, ETF): no periods, all n/a, overall grey "no
  financial statements from Yahoo".
- Warnings: EBITDA equal to EBIT with no depreciation from Yahoo (seen on
  `5398.KL`), "EBITDA may equal EBIT"; statements in a currency other than the
  price's; fewer than four years.
- Console smoke: `python research_data.py 5398.KL` prints profile, ratios,
  lights and the overall light. Not a test; needs internet.

**Built 2026-11-05 (WP-3.2).** The stock view on the page. Owner's choices
(2026-11-05): a Company block and a dividend history as extras (a peers
table is left for later); key statement lines only; market cap in Ringgit.
Rulings taken at the build:
- Data from Yahoo, for every code it knows (stocks and ETFs): six years of
  daily prices, the dividends paid in that span (from the same request), and
  the rate to Ringgit. For a stock only, the next earnings date: Yahoo's
  `earningsTimestampStart` turned into a date in the exchange's own time
  zone, else Yahoo's earnings calendar, else none. Never `earningsTimestamp`
  (without "Start"), which is the last report, not the next. Any part Yahoo
  fails to give is left empty; saved copies from before this package still
  load.
- Price figures (returns, volatility, drawdown) are worked out by one shared
  function (`price_stats`), so the ETF and stock views use the same rules.
  Beta (WP-3.8) is worked out by one shared function too (`beta`), called
  from `company_stats` and `etf_stats`.
- Company block: what the company does (Yahoo's description, in a fold-out
  box, with the website link), sector and industry, the 52-week range with
  how far up it the price sits ("now 68% of the way up"), the share held by
  insiders and by institutions, and the next earnings date. The position
  uses Yahoo's quoted price, not the chart's last price, because the 52-week
  range is the real traded range while the chart prices are adjusted for
  dividends. Anything missing shows "n/a" (the employee count is often
  missing for Bursa stocks).
- Market cap tile: in Ringgit, with the original in brackets for a foreign
  stock ("RM 21.4 tn (USD 5.0 tn)"); amounts of a million million and more
  read "tn".
- Credit health: one table, a row per ratio with its group (Leverage,
  Coverage, Liquidity, Cash, Profitability, Growth), a column per period
  (TTM first, then the years, newest left), the light badge and its reason.
  A note under it names the four ratios the overall light comes from. A bank
  gets the bank line first; a code with no statements gets a line saying so
  and no table.
- Price and risk: a five-year price chart (adjusted for dividends and
  splits), then the same return and risk figures as the ETF view.
- Valuation: P/E, forward P/E, P/B, EV/EBITDA, dividend yield, analyst
  target with the upside or downside, and the buy / hold / sell count. Each
  has a one-sentence help tip.
- Dividends: a table of the last five full years plus this year "so far",
  newest first: per-share total in the listing currency (4 decimals) and the
  number of payments. A year with no payment shows 0, so a skipped year is
  visible; years before the stock listed are left out. The payout ratio
  (share of profit paid out) sits beside it.
- Statements: three fold-out tables (income, balance sheet, cash flow) with
  the twelve figures the ratios use, in millions of the reporting currency,
  thousands separated, a blank where Yahoo has nothing.
- Round 2 (after the first review): prices under 1 show 3 decimals ("0.285
  – 0.455"; Bursa penny stocks move in steps of 0.005), on both views; a
  Yahoo number sent as text, NaN (not a number) or infinity becomes "n/a"
  instead of crashing the page; an ETF no longer asks for an earnings date;
  the no-dividend line reads "No dividends in the years shown".
- Console smoke now also prints the company block and the dividend table.
- First look (2026-11-07, WP-3.2.1): the header (price, market cap, fund size
  on both views), 52-week range, next earnings, dividend yield, analyst target
  and analyst count are plain text that wraps, not metric tiles, so a long value
  is never cut off with "..."; a row never mixes the two kinds.

## 4. Research page, ETF view

Detected from yfinance `quoteType == "ETF"`. The credit block is replaced by:

| item | light |
|---|---|
| Expense ratio | green < 0.20%, amber 0.20-0.60%, red > 0.60% |
| Fund size (total assets) | green > USD 1 bn, amber 100 m-1 bn, red < 100 m |
| Distribution yield | none |
| Top ten holdings (name, weight) | none |
| Sector mix, country mix | none |
| 1 / 3 / 5-year returns | none |
| 3-year volatility, max drawdown (from price history) | none |
| 3-year beta against the home market index (WP-3.8) | none |

Snapshot and Excel download work the same way.

**Built 2026-11-01 (WP-3.3).** The page shell and this view. Rulings taken
at the build:
- Data from Yahoo, only for an ETF: top holdings, sector and asset weights,
  fund facts, six years of daily prices, and the rate from the fund's
  currency to Ringgit (`<CCY>MYR=X`, e.g. `USDMYR=X`; 1.0 for a Ringgit
  fund). Any part Yahoo fails to give is left empty; the page never crashes.
  Old cache files without these parts still load.
- Expense ratio: Yahoo's `netExpenseRatio` (a percent, divided by 100), else
  the fund-operations row. Distribution yield: `yield` only.
- Fund size: shown in Ringgit with the original in brackets ("RM 430.0 bn
  (USD 101.2 bn)"). The light uses the figure in the fund's own currency.
- Returns 1 / 3 / 5 years: cumulative (last price / price on or just before
  the start date, minus 1; Yahoo's prices already include dividends), with
  the annualised rate under it ("7.0% a year"). The start price may be up to
  7 days late (weekends, holidays); later than that, n/a.
- Volatility (how much the price swings, as a yearly figure) and max
  drawdown (the worst fall from a peak) over the last 3 years. Shorter
  history: worked out on what there is, with a note "only <n> years of
  prices".
- Beta (WP-3.8, owner 2026-11-23): how much the price moved with its home
  market index over the last 3 years, two decimals, a third tile after
  Volatility and Max drawdown on both views. The index is FBM KLCI (`^KLSE`)
  for a `.KL` code and S&P 500 (`^GSPC`) for a US code (no dot in the code,
  a stock or ETF, priced in USD); settings `BETA_INDEX` and
  `BETA_MIN_RETURNS` at the top of `research_data.py`. Only days both the
  code and the index traded count; simple daily returns; covariance over the
  index's variance. The tile's help names the index ("Against FBM KLCI, last
  3 years. 1.00 moves in step with the market."). n/a when:
  - the code has no home market index (HK, SG, crypto, an index itself):
    help "No home market index for this code.";
  - fewer than 250 common daily returns (about a year);
  - Yahoo gives no index prices: also the warning line "Beta not available:
    no <index> prices from Yahoo.".
  Yahoo's own beta (5-year monthly, missing for ETFs) is not used. The index
  prices are kept in the code's own cache file; an old cache file loads with
  none.
- Prices are cleaned first: missing and zero prices dropped, repeated dates
  kept once, sorted by date.
- Lights: expense ratio and fund size as the table above, boundaries on the
  amber side; limits in `ETF_THRESHOLDS`. Overall light: the worse of the
  two, grey ignored; both grey: "no cost or size data".
- Stale copy: when a fresh fetch brings back no prices but the saved copy
  has them, the saved copy is shown, marked stale, and not overwritten.
- The page: code box (or a chip for each holding), header tiles, then the
  ETF block. The page computes no number; formatting only.
- **Gap: country mix.** Yahoo does not provide it; the page says "Country
  mix: not provided by Yahoo".
- **Caveat: non-USD funds.** The size limits (1 bn, 100 m) are applied to
  the raw number in the fund's own currency, so a Ringgit fund is judged
  against RM 1 bn, not USD 1 bn (owner, 2026-11-01). The Ringgit figure is
  for display only.

Polish round (rules 10-15, after the owner's first look, 2026-11-01):
- Nothing is cut off: the fund or company name is a heading, with exchange,
  category (or sector) and code on one line under it. The tiles hold only
  price, fund size (or market cap) and the overall light.
- "Refresh from Yahoo" button beside the code box: fetches now and saves,
  skipping the hour-old saved copy (`research(code, force=True)`). If Yahoo
  fails, the saved copy is still shown, marked stale. A caption says "Data
  as of <time>, Yahoo Finance; saved copies are reused for an hour".
- Lights are coloured badges (green, amber, red, grey, colours in
  `LIGHT_CSS`) with the colour word, on the overall tile and in the
  cost-and-size table.
- Verdict line under the name, ETFs only: one sentence joined from the two
  light phrases, e.g. "Cheap to hold; large and liquid". A fixed template
  (`etf_verdict`), no AI. A grey item reads "cost not reported" / "size not
  reported".
- Sections in order: Costs and size, Returns and risk, What it holds, Links.
  Top ten holdings show weight as a bar; the percent figures and the bar's
  top limit come from `research_data.py` (a plain table when Yahoo gives no
  weights). Each return and risk figure has a one-sentence help tip.
- `.streamlit/config.toml` (tracked) holds the colour theme for both pages,
  and turns off Streamlit's first-run email prompt (`showEmailPrompt =
  false`) and its usage statistics (`gatherUsageStats = false`).

Added 2026-11-05 (WP-3.2): a five-year price chart at the top of "Returns
and risk", the same chart as the stock view. Nothing else on this view
changed apart from 3-decimal prices under 1.

## 5. Proposed thresholds (open decision O2)

Newest period only. Written as settings at the top of the module.

| ratio | green | amber | red |
|---|---|---|---|
| Debt / Equity | < 0.5 | 0.5-1.0 | > 1.0 |
| Net debt / EBITDA | < 2.0x | 2.0-3.5x | > 3.5x |
| Interest cover | > 5x | 2-5x | < 2x |
| Current ratio | > 1.5 | 1.0-1.5 | < 1.0 |
| OCF / Total debt | > 0.30 | 0.15-0.30 | < 0.15 |
| FCF margin | > 10% | 0-10% | < 0 |
| Net margin | > 10% | 3-10% | < 3% |
| ROE | > 12% | 6-12% | < 6% |
| Revenue growth | > 5% | 0-5% | < 0 |

Each light carries a one-line reason, e.g. "Interest cover 1.8x: EBIT barely
covers interest". The reasons are what make the page read as credit analysis.

## 6. Research library page

A table of every file in `research/`: date, code, name, overall light, first
line of the note. Newest first. Pick one to reopen that snapshot in the
Research layout, marked "saved on <date>" (built, WP-3.4). A **Refresh**
button that shows today's figures beside the saved ones, so you see what
moved, is its own step, WP-3.4.1 (owner, 2026-11-11).

**Built 2026-11-16 (WP-3.4.1).** The button is labelled "Compare with today"
and compares one snapshot with today's result only (owner, 2026-11-16;
snapshot against snapshot and a timeline were not chosen). A click fetches
the code (the one-hour copy is reused) and draws a "What moved" table above
the saved view: Saved | Today | Change for the headline figures and every
light, neutral ▲ / ▼, "n/a" on a side with no figure. The saved view is not
refreshed and nothing is stored. Rulings: PLAN.md, WP-3.4.1.

**Beta (WP-3.8, 2026-11-23).** A new snapshot carries Beta and its index
name inside the stock or ETF figures (format 1 unchanged). A snapshot saved
before WP-3.8 reopens with Beta n/a and never crashes. "What moved" gains a
"Beta" row in Returns and risk, right after Max drawdown, for both views:
the change is the difference of the shown values; an old snapshot shows
n/a on the saved side.

Later (not v1): filter by code or light, search within notes.

## 7. Portfolio page (WP-2)

Reads the workbook only. Shows:
- Tiles: total value, XIRR, simple return, days since anchor.
- Allocation vs target per bucket, with drift and the BUY/SELL suggestion
  (same numbers as the Summary sheet).
- Value vs blended benchmark line chart from Daily_Log.
- Monthly table (from the new Monthly sheet, S9).
- Holdings table.

Nothing is recomputed in the app; the tracker's numbers are the truth.

**Built 2026-10-29.** Rulings taken at the build:
- The fourth tile shows the anchor date ("Measured since ..."), not a day
  count. Subtracting dates is a computation; the tracker can write the count
  in WP-2.1.
- Total value is `Moomoo total (RM)` from the last Daily_Log row.
- The chart is return % vs blended benchmark %, not value vs blend.
- The Monthly table shows a placeholder line until WP-2.1 adds the sheet.

**Updated 2026-10-30 (WP-2.1).** Tile 4 is now "Days since anchor": it shows
"Day <n>" with "since <anchor>" under it, read from the `Days since anchor`
column the tracker writes on each Daily_Log row. It falls back to "Measured
since ..." when that cell is blank. The page still does no date maths.

**Updated 2026-11-15 (WP-2.2).** Layout only, no new figure. Order: the
four tiles; one row with the allocation table (left, narrower) beside a
compact chart (right: shorter, legend across the top, no date label); then
tabs Holdings, Returns, Monthly. In Holdings only, "Unrealised P/L (RM)"
shows a green ▲ above 0 and a red ▼ below 0, minus sign kept ("▼ -56.40");
0 shows "0.00" with no arrow, a blank stays "n/a". Every Holdings column is
kept; its other numbers show at most 4 decimals with trailing zeros dropped,
as before. The Portfolio page is full width and the other pages centred,
set in `app.py`: Streamlit keeps the last page's width, so each page states
its own. Side effect: the Settings "Wide mode" switch resets on a page change.

## 8. Tracker additions (S9)

- **Monthly** sheet: month, end value, deposits, withdrawals, trade count,
  month return. Built from Daily_Log and Cashflow by a pure function.
- **Chart** sheet: value vs blend, an openpyxl line chart.
Both rewritten every run, so they never go stale.

**Built 2026-10-30 (WP-2.1).** Rulings taken at the build:
- Monthly columns: Month (`YYYY-MM`), End value (RM), Deposits (RM),
  Withdrawals (RM, shown positive), Trades, Month return %, Note. Header in
  row 1, no title row.
- Month return % is simple, with flows counted at the start of the month:
  (end - start - net flows) / (start + net flows). Blank when the bottom is 0.
  Start is the anchor total for the first month, else last month's end value.
- Each month is a window between logged days: from the previous month's last
  logged day (not included) to this month's last logged day (included).
  Deposits, withdrawals and trades count in the window they fall in. Flows and
  trades on the anchor day are inside the opening value and count in no month;
  rows before the anchor are left out.
- Note: "from <anchor>" on the first month, "to <last logged date>" on the
  open month, both when one month is both, blank otherwise.
- Chart: return % vs blended benchmark %, not value vs blend. The chart reads
  a copied block (table `ChartData`) on the Chart sheet, never Daily_Log
  cells. Both axes are shown (openpyxl hides them unless told). No chart when
  there is no return yet.

## 9. Code shape

```
app.py                  Streamlit entry; page switcher, sets each page's width (built; width WP-2.2)
portfolio_data.py       load the workbook into plain DataFrames; pick tiles and chart series; no Streamlit
pages/portfolio.py      WP-2 (built); layout and P/L arrows WP-2.2 (built)
pages/research.py       Research page: code box, chips, tiles, ETF block (built, WP-3.3); stock view (built, WP-3.2); Save snapshot (built, WP-3.4); draws through research_view.py
research_view.py        the Research layout drawing, shared by the Research and Library pages (built, WP-3.4); draws only
pages/library.py        Library page: lists and reopens snapshots (built, WP-3.4); Compare with today (built, WP-3.4.1)
research_data.py        fetch (cached), ratios, lights: pure functions (built, WP-3.1); ETF data, stats and lights (`etf_stats`, `etf_lights`, `etf_overall`, `chip_codes`; built, WP-3.3); stock view data (`price_stats`, `company_stats`, `dividend_history`, `credit_rows`, `statement_rows`; built, WP-3.2); `compare` for What moved (built, WP-3.4.1); `beta_index`, `beta`, `beta_text` (built, WP-3.8)
research_store.py       save / list / load snapshots (built, WP-3.4)
research_excel.py       one-stock workbook, reuses write_table
research/               snapshots (tracked; workbook is not, see O1)
run_app.bat             streamlit run app.py (built)
```

Pure functions take plain DataFrames so tests use fakes, as the tracker does.
`streamlit` and `plotly` join `requirements.txt` with exact pins.

## 10. Awkward cases to handle

- Yahoo returns no fundamentals (delisted, new listing): show what came back,
  light nothing, say why.
- Yahoo rate limit or outage: cached result if any, else a plain error line.
- Fiscal years not aligned with calendar years: column headers use the fiscal
  year-end date, not the year number.
- Reporting currency differs from the listing currency (some Bursa companies
  report in USD): show the currency; do not convert.
- Financials (banks, insurers): O3, n/a on three ratios and a grey headline.
- Non-Latin characters in names: already handled in the tracker; reuse.

**Handled 2026-10-31 (WP-3.1, data side).** No fundamentals (an error for an
unknown code; no periods and a grey light for a new listing). Outage (the
stale cached copy, also when Yahoo fails silently with empty replies).
Fiscal year-end headers. Currency mismatch (a warning, no conversion).
Financials (O3). What the page says for each is WP-3.2; non-Latin names too.

**Handled 2026-11-01 (WP-3.3, ETF side).** A zero or missing price is
dropped, not shown as a -100% fall. A partial Yahoo failure (no prices)
keeps the good saved copy, marked stale. Country mix: not provided by Yahoo.

**Handled 2026-11-05 (WP-3.2, page side).** What the stock view says:
- No statements (new listing, index, mutual fund): "Yahoo has no financial
  statements for this code, so the ratios cannot be worked out." No credit
  table and no Statements section.
- Bank or insurer: the bank line in a blue box above the credit table (O3).
- Outage: the saved copy, with "Showing a saved copy; Yahoo was
  unreachable" and its fetch time.
- Currency mismatch, EBITDA may equal EBIT, fewer than four years, short
  price history: one caption line each above the header.
- Fiscal year-end dates head the credit columns; the statement unit line
  names the reporting currency ("MYR millions").
- No prices: "Price history: not provided by Yahoo for this code." No prices
  and no dividends: "Dividend history: not provided by Yahoo for this code."
  Prices but no dividends: the zero table and "No dividends in the years
  shown".
- Any missing or unusable Yahoo number (text, NaN, infinity): "n/a".
- Not handled: London stocks' pence label (PLAN.md, "Later").

## 11. Later packages (queued, not v1)

Library filter and search. Refresh-and-compare on the library (WP-3.4.1,
owner 2026-11-11; built 2026-11-16 as "Compare with today", see section 6).
**ETF compare:**
two codes side by side plus a holdings-overlap check. News feed.
AI commentary. Scheduled refresh of holdings. Bank block (WP-3.7, see O3). Fifth year
from another source. TTM for everything.
