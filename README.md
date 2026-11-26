# moomoo-portfolio-tracker

A personal investment tracker for a Moomoo (Malaysia) account, with a small
Streamlit app for looking at the portfolio and researching stocks and ETFs.

It is one person's tool, shared as an example. It is not financial advice.

## What it does

- **Tracker** (`portfolio_tracker.py`): reads holdings, cash, trades and cash
  flow from your own Moomoo account through OpenD (Moomoo's local gateway
  program) and writes `Portfolio_Tracker.xlsx`: summary, monthly returns,
  holdings, a daily log, trades and cash flow.
- **Returns**: money-weighted return (XIRR) and simple return, worked out from
  Moomoo's own cash-flow records.
- **Allocation**: each holding sits in a bucket (local, regional, global) with
  a target weight, and a bucket is flagged when it drifts too far.
- **Benchmarks**: FBM KLCI, Asia ex-Japan (AAXJ), World (VT) and a blend, from
  Yahoo Finance.
- **App** (`app.py`), three pages:
  - Portfolio: tiles, allocation, return chart, holdings and monthly tables.
  - Research: type a Yahoo code (for example `5398.KL` or `VT`) to see company
    or fund figures, credit ratios with traffic lights, valuation, dividends,
    returns, volatility, max drawdown and beta.
  - Library: save a research result with a note, reopen it later and compare
    it with today's figures.

## What you need

- Python 3.11 or newer, on Windows (the `.bat` files are for Windows; the
  Python commands work anywhere).
- A Moomoo account, with Moomoo OpenD running and logged in on
  `127.0.0.1:11111`. Only the tracker needs this. The Research page needs
  only an internet connection.

## Set up

    pip install -r requirements.txt
    pip install pytest              # only for the tests

Then open `portfolio_tracker.py` and edit the settings at the top:

| setting | what to put |
|---|---|
| `START_DATE` | the day your first deposit landed |
| `TARGETS` | your target weight for each bucket |
| `BUCKETS` | which bucket each of your non-Bursa holdings belongs to |
| `SAVINGS_START`, `SAVINGS_RATE` | an outside savings pot to compare against, or 0 |

The values in this repo are examples.

## Run

    python portfolio_tracker.py        # writes Portfolio_Tracker.xlsx (needs OpenD)
    python -m streamlit run app.py     # opens the app on localhost:8501
    python research_data.py 5398.KL    # research figures in the console
    python -m pytest tests -q          # unit tests, no account or internet needed
    python verify_tracker.py           # data-only checks, ends RESULT: PASS / FAIL

Without a Moomoo account you can still use the Research and Library pages from
the sidebar. The Portfolio page needs the workbook the tracker writes.

## Your data stays with you

- The tracker only reads from your account. It places no orders.
- `Portfolio_Tracker.xlsx` and `tracker_log.txt` hold your real figures. They
  are in `.gitignore`; do not commit them.
- Nothing is sent anywhere except the price and company lookups to Yahoo
  Finance.

## Notes

- Limits for the Research traffic lights are fixed rules at the top of
  `research_data.py`, not a judgement.
- `docs/spec-streamlit-app.md` is the working spec for the app. It mentions
  planning notes and step numbers (WP-x.y) that are not part of this repo.
