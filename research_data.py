"""Research data for one Yahoo Finance code: profile, statements, nine credit ratios, lights, valuation;
for a stock: company block, price figures, dividend history, credit and statement rows (WP-3.2);
for an ETF: cost, size, holdings, sector mix, returns, volatility, drawdown and two lights (WP-3.3).
Only fetch_raw and fetch_fx talk to Yahoo; analyse is pure. No Streamlit here, so tests use fake frames.
CLI: python research_data.py <CODE>"""
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from io import StringIO
from pathlib import Path

import pandas as pd

# ---------- settings ----------
# yfinance's exact labels -> the statement that holds them (measure-1 s.2)
FIELDS = {
    "Total Revenue": "income", "Net Income": "income", "EBITDA": "income", "EBIT": "income",
    "Interest Expense": "income",
    "Total Debt": "balance", "Stockholders Equity": "balance", "Cash And Cash Equivalents": "balance",
    "Current Assets": "balance", "Current Liabilities": "balance",
    "Operating Cash Flow": "cashflow", "Free Cash Flow": "cashflow",
}
STATEMENTS = ("income", "balance", "cashflow")
RATIOS = ["Debt / Equity", "Net debt / EBITDA", "Interest cover", "Current ratio", "OCF / Total debt",
          "FCF margin", "Net margin", "ROE", "Revenue growth"]
LENDER_RATIOS = RATIOS[:4]          # the four that make the overall light (O4)
RATIO_GROUPS = {"Debt / Equity": "Leverage", "Net debt / EBITDA": "Leverage", "Interest cover": "Coverage",
                "Current ratio": "Liquidity", "OCF / Total debt": "Cash", "FCF margin": "Cash",
                "Net margin": "Profitability", "ROE": "Profitability", "Revenue growth": "Growth"}
STATEMENT_TITLES = {"income": "Income statement", "balance": "Balance sheet", "cashflow": "Cash flow"}
MULTIPLES = {"Net debt / EBITDA", "Interest cover"}            # shown as 1.8x
PLAIN = {"Debt / Equity", "Current ratio", "OCF / Total debt"}  # shown as 0.45; the rest as 12.3%
# (green bound, red bound); green < red means lower is better. Boundaries are amber. Percents as fractions.
THRESHOLDS = {
    "Debt / Equity": (0.5, 1.0),
    "Net debt / EBITDA": (2.0, 3.5),
    "Interest cover": (5.0, 2.0),
    "Current ratio": (1.5, 1.0),
    "OCF / Total debt": (0.30, 0.15),
    "FCF margin": (0.10, 0.0),
    "Net margin": (0.10, 0.03),
    "ROE": (0.12, 0.06),
    "Revenue growth": (0.05, 0.0),
}
REASONS = {
    "Debt / Equity": {"green": "low borrowing against equity", "amber": "moderate borrowing against equity",
                      "red": "borrows more than its equity", "grey": "debt or equity not reported"},
    "Net debt / EBITDA": {"green": "debt repayable from under two years of earnings",
                          "amber": "debt takes two to three and a half years of earnings",
                          "red": "debt heavy against earnings", "grey": "debt, cash or EBITDA not reported"},
    "Interest cover": {"green": "EBIT covers interest comfortably", "amber": "EBIT covers interest, thin margin",
                       "red": "EBIT barely covers interest", "grey": "EBIT or interest not reported"},
    "Current ratio": {"green": "short-term assets well above short-term bills",
                      "amber": "short-term assets just cover short-term bills",
                      "red": "short-term bills exceed short-term assets",
                      "grey": "current assets or liabilities not reported"},
    "OCF / Total debt": {"green": "operating cash pays down debt quickly",
                         "amber": "operating cash pays down debt slowly",
                         "red": "operating cash small against debt", "grey": "cash flow or debt not reported"},
    "FCF margin": {"green": "strong free cash after investment", "amber": "some free cash after investment",
                   "red": "spends more cash than it brings in", "grey": "free cash flow or revenue not reported"},
    "Net margin": {"green": "keeps a healthy share of revenue as profit", "amber": "thin profit on revenue",
                   "red": "little or no profit on revenue", "grey": "profit or revenue not reported"},
    "ROE": {"green": "strong return on shareholders' money", "amber": "modest return on shareholders' money",
            "red": "weak return on shareholders' money", "grey": "profit or equity not reported"},
    "Revenue growth": {"green": "revenue growing", "amber": "revenue flat to slightly up",
                       "red": "revenue shrinking", "grey": "no earlier year to compare"},
}
FINANCIAL_SECTOR = "Financial Services"
BANK_LINE = "credit ratios not meaningful for a bank; see profitability and valuation"
CACHE_DIR = Path(__file__).with_name("output") / "research_cache"
CACHE_TTL = 3600  # seconds
# ETF view (WP-3.3, spec s.4). (green bound, red bound) as in THRESHOLDS; boundaries are amber.
ETF_THRESHOLDS = {"expense_ratio": (0.002, 0.006), "fund_size": (1e9, 1e8)}
ETF_REASONS = {
    "expense_ratio": {"green": "cheap to hold", "amber": "fair cost", "red": "expensive for an index fund",
                      "grey": "expense ratio not reported"},
    "fund_size": {"green": "large and liquid", "amber": "mid-sized", "red": "small, closure risk",
                  "grey": "fund size not reported"},
}
ETF_NAMES = {"expense_ratio": "Expense ratio", "fund_size": "Fund size"}
RETURN_YEARS = {"1y": 1, "3y": 3, "5y": 5}
RISK_YEARS = 3              # volatility and drawdown window
LOOKBACK_GRACE_DAYS = 7     # first price may be this many calendar days after the lookback date
TRADING_DAYS = 252
PRICE_PERIOD = "6y"         # history fetched for every code: the 5y lookback needs a price before it
FX_PERIOD = "5d"
# Beta (WP-3.8): the home market index per market, as (Yahoo code, display name)
BETA_INDEX = {"MY": ("^KLSE", "FBM KLCI"), "US": ("^GSPC", "S&P 500")}
BETA_MIN_RETURNS = 250      # common daily returns needed before a beta is shown (about a year)
DIVIDEND_YEARS = 5          # full years shown before the current one (WP-3.2 rule 5)
CHART_YEARS = 5             # years in the price chart
SECTOR_WORDS = {"realestate": "Real estate", "healthcare": "Healthcare"}
_RANK = {"green": 1, "amber": 2, "red": 3}


class ResearchError(Exception):
    pass


@dataclass
class Light:
    colour: str
    reason: str


@dataclass
class Raw:
    code: str
    info: dict
    income: pd.DataFrame
    balance: pd.DataFrame
    cashflow: pd.DataFrame
    q_income: pd.DataFrame
    q_balance: pd.DataFrame
    q_cashflow: pd.DataFrame
    recs: pd.DataFrame
    fetched_at: datetime
    # ETF fields (WP-3.3); empty for a stock
    holdings: pd.DataFrame = field(default_factory=pd.DataFrame)
    sectors: dict = field(default_factory=dict)
    assets: dict = field(default_factory=dict)
    ops: pd.DataFrame = field(default_factory=pd.DataFrame)
    prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    fx: float | None = None
    dividends: pd.DataFrame = field(default_factory=pd.DataFrame)  # non-zero ex-date rows (WP-3.2)
    index_prices: pd.DataFrame = field(default_factory=pd.DataFrame)  # home index Close (WP-3.8)


@dataclass
class Research:
    code: str
    name: str
    exchange: str | None
    sector: str | None
    industry: str | None
    kind: str | None
    currency: str | None
    financial_currency: str | None
    price: float | None
    market_cap: float | None
    fetched_at: datetime
    stale: bool
    is_financial: bool
    periods: list
    statements: dict
    ratios: pd.DataFrame
    labels: pd.DataFrame
    lights: dict
    overall: Light
    valuation: dict
    links: dict
    warnings: list
    etf: dict | None = None  # etf_stats + "lights" + "overall"; None for a stock
    company: dict | None = None  # company_stats; None for an ETF


# ---------- Yahoo and disk ----------
def fetch_raw(code, now=None):
    """The only Yahoo calls. Empty frames stand in for anything yfinance returns as None."""
    import yfinance as yf
    t = yf.Ticker(code)

    def df(x):
        x = x if isinstance(x, pd.DataFrame) else pd.DataFrame()
        return x[~x.index.duplicated()]  # first of any repeated label
    raw = Raw(code=code, info=dict(t.info or {}), income=df(t.income_stmt), balance=df(t.balance_sheet),
              cashflow=df(t.cashflow), q_income=df(t.quarterly_income_stmt),
              q_balance=df(t.quarterly_balance_sheet), q_cashflow=df(t.quarterly_cashflow),
              recs=df(t.recommendations), fetched_at=now or datetime.now())
    if raw.info.get("quoteType"):
        _fetch_prices(t, raw)
    if raw.info.get("quoteType") == "ETF":
        _fetch_etf(t, raw)
    return raw


def _fetch_prices(t, raw):
    """Every code with a quoteType: Close and Dividends from ONE history call and the fx rate; for a stock
    (never an ETF) also the next earnings date, kept in info so the cache carries it. Each part guarded."""
    hist = _guard(lambda: t.history(period=PRICE_PERIOD), pd.DataFrame)
    raw.prices = _close_frame(hist)
    raw.dividends = _dividend_frame(hist)
    home = beta_index(raw.code, raw.info)
    if home is not None:
        raw.index_prices = fetch_index_prices(home[0])
    raw.fx = fetch_fx(raw.info.get("currency"))
    if raw.info.get("quoteType") == "ETF":
        return  # rule 14: no earnings lookup, Ticker.calendar never touched
    nxt = _next_earnings(t, raw.info)
    if nxt:
        raw.info["nextEarningsDate"] = nxt


def _next_earnings(t, info):
    """ISO date of the next report: earningsTimestampStart in the exchange's zone (UTC when absent or
    unknown), else calendar["Earnings Date"][0], else None. Never earningsTimestamp: that is the past one."""
    start = info.get("earningsTimestampStart")
    if start is not None:
        try:
            ts = pd.Timestamp(int(start), unit="s", tz="UTC")
            try:
                ts = ts.tz_convert(info.get("exchangeTimezoneName") or "UTC")
            except Exception:
                pass  # unknown zone: UTC
            return ts.date().isoformat()
        except Exception:
            pass  # unreadable timestamp: try the calendar
    try:
        dates = t.calendar.get("Earnings Date")
        return pd.Timestamp(dates[0]).date().isoformat() if dates else None
    except Exception:
        return None


def _guard(get, kind):
    """get() if it gives a `kind`, else an empty one; any exception counts as missing."""
    try:
        x = get()
    except Exception:
        return kind()
    return x if isinstance(x, kind) else kind()


def _fetch_etf(t, raw):
    """ETF fields from funds_data; each one guarded."""
    try:
        funds = t.funds_data
    except Exception:
        funds = None
    raw.holdings = _guard(lambda: funds.top_holdings, pd.DataFrame)
    raw.sectors = dict(_guard(lambda: funds.sector_weightings, dict))
    raw.assets = dict(_guard(lambda: funds.asset_classes, dict))
    raw.ops = _guard(lambda: funds.fund_operations, pd.DataFrame)
    overview = _guard(lambda: funds.fund_overview, dict)
    for src, dst in (("categoryName", "category"), ("family", "fundFamily"), ("legalType", "legalType")):
        if overview.get(src) is not None and raw.info.get(dst) is None:
            raw.info[dst] = overview[src]  # kept in info so the cache carries it


def _close_frame(hist):
    """Close column only, timezone-free dates."""
    if hist.empty or "Close" not in hist:
        return pd.DataFrame()
    return _naive(hist[["Close"]].copy())


def _dividend_frame(hist):
    """The non-zero rows of the Dividends column, timezone-free dates; empty when absent or all zero."""
    if hist.empty or "Dividends" not in hist:
        return pd.DataFrame()
    d = hist[["Dividends"]].copy()
    d["Dividends"] = pd.to_numeric(d["Dividends"], errors="coerce")
    d = d[d["Dividends"].fillna(0) != 0]
    return pd.DataFrame() if d.empty else _naive(d)


def _naive(df):
    idx = pd.DatetimeIndex(df.index)
    df.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    return df


def fetch_fx(ccy, ticker_cls=None):
    """The fund's currency to MYR: 1.0 for MYR, else the last Close of <CCY>MYR=X; None on any failure."""
    if ccy == "MYR":
        return 1.0
    if not ccy:
        return None
    try:
        if ticker_cls is None:
            import yfinance as yf
            ticker_cls = yf.Ticker
        close = ticker_cls(f"{ccy}MYR=X").history(period=FX_PERIOD)["Close"].dropna()
        return float(close.iloc[-1]) if len(close) else None
    except Exception:
        return None


def beta_index(code, info):
    """(Yahoo code, display name) of the code's home market index: .KL -> FBM KLCI; a plain code (no dot)
    that Yahoo calls an EQUITY or ETF priced in USD -> S&P 500; anything else -> None."""
    info = info or {}
    if code.endswith(".KL"):
        return BETA_INDEX["MY"]
    if "." not in code and info.get("quoteType") in ("EQUITY", "ETF") and info.get("currency") == "USD":
        return BETA_INDEX["US"]
    return None


def fetch_index_prices(code, ticker_cls=None):
    """The index's Close over PRICE_PERIOD, a frame like Raw.prices; empty on any failure."""
    try:
        if ticker_cls is None:
            import yfinance as yf
            ticker_cls = yf.Ticker
        return _close_frame(_guard(lambda: ticker_cls(code).history(period=PRICE_PERIOD), pd.DataFrame))
    except Exception:
        return pd.DataFrame()


_FRAMES = ("income", "balance", "cashflow", "q_income", "q_balance", "q_cashflow", "recs")
_EXTRA_FRAMES = ("holdings", "ops", "prices", "dividends", "index_prices")
_DATED = ("prices", "dividends", "index_prices")


def _extra_frame(doc, k):
    """A WP-3.2/3.3 frame from the cache; absent in an older file -> empty. No type guessing on symbols."""
    if k not in doc:
        return pd.DataFrame()
    df = pd.read_json(StringIO(json.dumps(doc[k])), orient="split", dtype=False, convert_axes=False)
    if k in _DATED and not df.empty:
        df.index = pd.to_datetime(df.index)
    return df


def save_cache(raw, cache_dir=CACHE_DIR):
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    doc = {"code": raw.code, "fetched_at": raw.fetched_at.isoformat(), "info": raw.info}
    for k in _FRAMES + _EXTRA_FRAMES:
        doc[k] = json.loads(getattr(raw, k).to_json(orient="split", date_format="iso"))
    doc.update(sectors=raw.sectors, assets=raw.assets, fx=raw.fx)
    (cache_dir / f"{raw.code}.json").write_text(json.dumps(doc, default=str), encoding="utf-8")


def load_cache(code, cache_dir=CACHE_DIR):
    path = Path(cache_dir) / f"{code}.json"
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        frames = {k: pd.read_json(StringIO(json.dumps(doc[k])), orient="split") for k in _FRAMES}
        frames.update({k: _extra_frame(doc, k) for k in _EXTRA_FRAMES})
        fx = doc.get("fx")
        return Raw(code=doc["code"], info=doc["info"], fetched_at=datetime.fromisoformat(doc["fetched_at"]),
                   sectors=dict(doc.get("sectors") or {}), assets=dict(doc.get("assets") or {}),
                   fx=None if fx is None else float(fx), **frames)
    except (ValueError, KeyError, TypeError):
        return None  # unreadable copy: treat as absent


# ---------- periods and statements ----------
def _key(col):
    return pd.Timestamp(col).strftime("%Y-%m-%d")


def _cols(df):
    """Columns newest first (yfinance already does this; sorted in case)."""
    return sorted(df.columns, key=pd.Timestamp, reverse=True) if not df.empty else []


def _valued(df, field):
    """Columns where `field` has a number, newest first."""
    if df.empty or field not in df.index:
        return []
    return [c for c in _cols(df) if pd.notna(df.loc[field, c])]


def _has_any(df, col):
    rows = [f for f in FIELDS if f in df.index]
    return bool(rows) and bool(df.loc[rows, col].notna().any())


def _annual_cols(raw):
    """{key: {statement: column}} for the newest four annual columns holding any of the FIELDS."""
    found = {}
    for s in STATEMENTS:
        df = getattr(raw, s)
        for c in _cols(df):
            if _has_any(df, c):
                found.setdefault(_key(c), {})[s] = c
    return {k: found[k] for k in sorted(found, reverse=True)[:4]}


def _ttm(raw):
    return (len(_valued(raw.q_income, "Total Revenue")) >= 4
            and len(_valued(raw.q_cashflow, "Operating Cash Flow")) >= 4)


def periods_of(raw):
    return list(_annual_cols(raw)), _ttm(raw)


def period_table(raw):
    """FIELDS rows x periods per statement; TTM = sum of 4 newest quarters (flows), newest quarter (balance)."""
    annual = _annual_cols(raw)
    ttm = _ttm(raw)
    tables = {}
    for s in STATEMENTS:
        fields = [f for f, st in FIELDS.items() if st == s]
        cols = {}
        if ttm:
            q = getattr(raw, "q_" + s)
            if s == "balance":
                newest = next((c for c in _cols(q) if _has_any(q, c)), None)
                cols["TTM"] = q.reindex(fields)[newest] if newest is not None else pd.Series(float("nan"), index=fields)
            else:
                lead = "Total Revenue" if s == "income" else "Operating Cash Flow"
                cols["TTM"] = q.reindex(fields)[_valued(q, lead)[:4]].sum(axis=1, min_count=4)
        df = getattr(raw, s)
        for key, where in annual.items():
            cols[key] = df.reindex(fields)[where[s]] if s in where else pd.Series(float("nan"), index=fields)
        tables[s] = pd.DataFrame({k: v.astype(float).values for k, v in cols.items()}, index=fields)
    return tables


# ---------- ratios and lights ----------
def _num(x):
    return None if x is None or pd.isna(x) else float(x)


def _safe_num(x):
    """A Yahoo number made safe (rule 15): None, NaN, +/-infinity and non-numeric text -> None;
    numeric text -> float."""
    if isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _div(a, b):
    return None if a is None or b is None or b == 0 else a / b


def fmt(ratio, v):
    if v is None:
        return "n/a"
    if ratio in MULTIPLES:
        return f"{v:.1f}x"
    if ratio in PLAIN:
        return f"{v:.2f}"
    return f"{v * 100:.1f}%"


def _period_ratios(g, prev_revenue, is_financial):
    """One period: {ratio: value} and {ratio: (colour, phrase, label)} forced verdicts."""
    debt, equity, cash = g("Total Debt"), g("Stockholders Equity"), g("Cash And Cash Equivalents")
    ebitda, ebit, rev, ni = g("EBITDA"), g("EBIT"), g("Total Revenue"), g("Net Income")
    ie = g("Interest Expense")
    ie = abs(ie) if ie is not None else None
    v, notes = {}, {}

    if equity is not None and equity <= 0:
        v["Debt / Equity"], notes["Debt / Equity"] = None, ("red", "negative equity", None)
        v["ROE"], notes["ROE"] = None, ("grey", "negative equity", None)
    else:
        v["Debt / Equity"], v["ROE"] = _div(debt, equity), _div(ni, equity)

    net_debt = debt - cash if debt is not None and cash is not None else None
    v["Net debt / EBITDA"] = None
    if net_debt is not None and net_debt <= 0:
        notes["Net debt / EBITDA"] = ("green", "cash exceeds debt", "net cash")
    elif net_debt is not None and ebitda is not None and ebitda <= 0:
        notes["Net debt / EBITDA"] = ("red", "EBITDA zero or negative; debt cannot be serviced from earnings", None)
    else:
        v["Net debt / EBITDA"] = _div(net_debt, ebitda)

    v["Interest cover"] = _div(ebit, ie)
    if ie is None:
        notes["Interest cover"] = ("grey", "interest expense not reported", None)
    elif v["Interest cover"] is not None and ebit < 0:
        notes["Interest cover"] = ("red", "EBIT negative; interest not covered", None)

    v["Current ratio"] = _div(g("Current Assets"), g("Current Liabilities"))
    v["OCF / Total debt"] = _div(g("Operating Cash Flow"), debt)
    v["FCF margin"] = _div(g("Free Cash Flow"), rev)
    v["Net margin"] = _div(ni, rev)
    growth = _div(rev, prev_revenue)
    v["Revenue growth"] = growth - 1 if growth is not None else None

    if is_financial:
        for r in ("Interest cover", "Current ratio", "Net debt / EBITDA"):
            v[r], notes[r] = None, ("grey", "not meaningful for a financial company", None)
    return v, notes


def compute_ratios(tables, is_financial):
    """(ratios, labels, notes): RATIOS x periods; notes {(ratio, period): (colour, phrase, label)}."""
    periods = list(tables["income"].columns)
    annual = [p for p in periods if p != "TTM"]
    ratios = pd.DataFrame(float("nan"), index=RATIOS, columns=periods)
    labels = pd.DataFrame("n/a", index=RATIOS, columns=periods)
    notes = {}
    for p in periods:
        def g(field, p=p):
            return _num(tables[FIELDS[field]].loc[field, p])
        nxt = annual.index(p) + 1 if p in annual else None  # TTM: no year-ago TTM, so no growth
        prev = _num(tables["income"].loc["Total Revenue", annual[nxt]]) if nxt and nxt < len(annual) else None
        vals, cell_notes = _period_ratios(g, prev, is_financial)
        for r in RATIOS:
            note = cell_notes.get(r)
            if vals[r] is not None:
                ratios.loc[r, p] = vals[r]
            labels.loc[r, p] = note[2] if note and note[2] else fmt(r, vals[r])
            if note:
                notes[(r, p)] = note
    return ratios, labels, notes


def _colour(ratio, v):
    return _band(THRESHOLDS[ratio], v)


def _band(bounds, v):
    green, red = bounds
    if green < red:  # lower is better
        return "green" if v < green else "red" if v > red else "amber"
    return "green" if v > green else "red" if v < red else "amber"


def light_for(ratio, value, period, note=None):
    """Reason: '<Ratio> <value> (<period>): <phrase>'. A note forces colour, phrase and label."""
    v = _num(value)
    if note:
        colour, phrase, label = note
    else:
        colour = "grey" if v is None else _colour(ratio, v)
        phrase, label = REASONS[ratio][colour], None
    where = f" ({period})" if period else ""
    return Light(colour, f"{ratio} {label or fmt(ratio, v)}{where}: {phrase}")


def overall_light(lights, is_financial):
    if is_financial:
        return Light("grey", BANK_LINE)
    lit = [lights[r] for r in LENDER_RATIOS if r in lights and lights[r].colour in _RANK]
    if not lit:
        return Light("grey", "not enough data for a credit view")
    worst = max(lit, key=lambda lt: _RANK[lt.colour])  # first of equals wins
    return Light(worst.colour, "worst: " + worst.reason)


def _light_period(ratio, ratios, notes, periods):
    """TTM when it has a value or a forced note (bar "interest expense not reported"), else the newest
    annual period; TTM again when there is no annual period."""
    if "TTM" in periods:
        note = notes.get((ratio, "TTM"))
        if pd.notna(ratios.loc[ratio, "TTM"]) or (note and note[1] != "interest expense not reported"):
            return "TTM"
    return next((p for p in periods if p != "TTM"), "TTM")


# ---------- valuation, links, codes ----------
def valuation_of(info, recs):
    def n(key):
        return _safe_num(info.get(key))
    analysts = n("numberOfAnalystOpinions")
    if analysts is not None and analysts.is_integer():
        analysts = int(analysts)  # a whole count shows as 20, not 20.0
    price = n("currentPrice") or n("regularMarketPrice")
    target = n("targetMeanPrice")
    v = {"pe": n("trailingPE"), "forward_pe": n("forwardPE"), "pb": n("priceToBook"),
         "dividend_yield": n("trailingAnnualDividendYield"),  # a fraction; dividendYield is a percent
         "ev_ebitda": n("enterpriseToEbitda"), "market_cap": n("marketCap"), "price": price,
         "target_mean": target, "upside": target / price - 1 if price and target is not None else None,
         "analysts": analysts, "buy": None, "hold": None, "sell": None}
    if recs is not None and not recs.empty:
        row = recs.iloc[0]
        v["buy"], v["hold"], v["sell"] = (_count(row, *cols) for cols in
                                          (("strongBuy", "buy"), ("hold",), ("sell", "strongSell")))
    return v


def _count(row, *cols):
    """Sum of analyst counts; None when any cell is missing."""
    vals = [row.get(c) for c in cols]
    return None if any(pd.isna(x) for x in vals) else int(sum(vals))


def links_for(code):
    if code.endswith(".KL"):
        filings = ("https://www.bursamalaysia.com/market_information/announcements/company_announcement"
                   f"?company={code[:-3]}")
    else:
        filings = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={code}&type=10-K"
    return {"yahoo": f"https://finance.yahoo.com/quote/{code}", "filings": filings}


def yahoo_code(moomoo_code):
    market, _, ticker = moomoo_code.partition(".")
    return {"MY": f"{ticker}.KL", "US": ticker}.get(market)


def chip_codes(holdings):
    """Yahoo codes for the Holdings sheet's Code column, in order; unmapped, blank and repeats dropped."""
    codes = holdings["Code"] if "Code" in holdings else []
    return list(dict.fromkeys(y for y in (yahoo_code(c) for c in codes if isinstance(c, str)) if y))


# ---------- ETF view (WP-3.3) ----------
def _close(prices):
    """The Close column as a clean, date-sorted Series (empty when absent)."""
    if not isinstance(prices, pd.DataFrame) or "Close" not in prices:
        return pd.Series([], index=pd.DatetimeIndex([]), dtype="float64")
    return _clean(prices["Close"])


def _clean(close):
    """Close > 0 only (drops NaN and Yahoo's 0.0 for thin funds), repeated dates keep the last, sorted."""
    s = pd.to_numeric(close, errors="coerce")
    s.index = pd.DatetimeIndex(s.index)
    s = s[s > 0]
    return s[~s.index.duplicated(keep="last")].sort_index()


def _lookback(last, years):
    return last - pd.DateOffset(years=years)


def cumulative_return(close, years, end=None):
    """Last Close / Close on or just before (last date - years) - 1. The first price stands in when it is at
    most LOOKBACK_GRACE_DAYS after that date; None when the series is shorter or empty."""
    s = _clean(close)
    if end is not None:
        s = s[s.index <= pd.Timestamp(end)]
    if s.empty:
        return None
    back = _lookback(s.index[-1], years)
    before = s[s.index <= back]
    if len(before):
        start = before.iloc[-1]
    elif s.index[0] <= back + pd.Timedelta(days=LOOKBACK_GRACE_DAYS):
        start = s.iloc[0]
    else:
        return None
    return None if start == 0 else float(s.iloc[-1] / start - 1)


def annualised(cumulative, years):
    if cumulative is None or cumulative <= -1:
        return None
    return float((1 + cumulative) ** (1 / years) - 1)


def _window(close, years):
    s = _clean(close)
    return s if s.empty else s[s.index > _lookback(s.index[-1], years)]


def volatility(close, years=RISK_YEARS):
    """Annualised sample std of daily log returns over the last `years`; None under 2 returns."""
    w = _window(close, years)
    r = (w / w.shift(1)).dropna().map(math.log)
    return float(r.std(ddof=1) * math.sqrt(TRADING_DAYS)) if len(r) >= 2 else None


def max_drawdown(close, years=RISK_YEARS):
    """Worst fall from a running peak over the last `years`: a negative fraction, 0.0 if it never fell."""
    w = _window(close, years)
    return None if w.empty else float((w / w.cummax() - 1).min())


def beta(close, index_close, years=RISK_YEARS):
    """Sample cov / var of simple daily returns on the dates both series share, over the last `years` of
    those dates; None under BETA_MIN_RETURNS returns, for a flat index or missing input."""
    if close is None or index_close is None:
        return None
    s, i = _clean(close), _clean(index_close)
    common = s.index.intersection(i.index)
    w = _window(s.loc[common], years)
    if w.empty:
        return None
    rs = (w / w.shift(1) - 1).dropna()
    wi = i.loc[w.index]
    ri = (wi / wi.shift(1) - 1).dropna()
    if len(rs) < BETA_MIN_RETURNS:
        return None
    var = ri.var(ddof=1)
    if not math.isfinite(var) or var == 0:
        return None
    b = rs.cov(ri, ddof=1) / var
    return float(b) if math.isfinite(b) else None


def _beta_stats(raw, close):
    """beta_3y and beta_index for company_stats / etf_stats (WP-3.8); both None without a home index."""
    home = beta_index(raw.code, raw.info)
    if home is None:
        return {"beta_3y": None, "beta_index": None}
    return {"beta_3y": beta(close, _close(raw.index_prices)), "beta_index": home[1]}


def _beta_warning(raw):
    home = beta_index(raw.code, raw.info)
    if home is None or not _close(raw.index_prices).empty:
        return None
    return f"Beta not available: no {home[1]} prices from Yahoo."


def sector_label(key):
    return SECTOR_WORDS.get(key) or key.replace("_", " ").capitalize()


def _asset_label(key):
    return key.removesuffix("Position").capitalize()


def _mix(d, label, col):
    rows = [(label(k), float(v)) for k, v in d.items() if _num(v)]
    df = pd.DataFrame(rows, columns=[col, "Weight"])
    return df.sort_values("Weight", ascending=False, kind="stable").reset_index(drop=True)


def _expense(info, ops):
    pct_value = _num(info.get("netExpenseRatio"))
    if pct_value is not None:
        return pct_value / 100  # Yahoo sends a percent (measure-1 s.6)
    row = "Annual Report Expense Ratio"
    if isinstance(ops, pd.DataFrame) and row in ops.index and len(ops.columns):
        return _num(ops.loc[row].iloc[0])  # the fund's own column, already a fraction
    return None


def _top(holdings):
    if not isinstance(holdings, pd.DataFrame) or holdings.empty:
        return pd.DataFrame(columns=["Symbol", "Name", "Weight"])
    h = holdings.head(10)
    return pd.DataFrame({"Symbol": [str(x) for x in h.index], "Name": h.get("Name", pd.Series(index=h.index)).values,
                         "Weight": pd.to_numeric(h.get("Holding Percent", pd.Series(index=h.index)),
                                                    errors="coerce").values})


def _top_pct(top):
    """Name, Symbol, Weight % (percent, for the page's progress bars)."""
    return pd.DataFrame({"Name": top["Name"].values, "Symbol": top["Symbol"].values,
                         "Weight %": (top["Weight"] * 100).values})


def _top_max_pct(top):
    """Largest holding weight in percent (the progress bars' upper limit); None when no weight is given."""
    w = pd.to_numeric(top["Weight"], errors="coerce").dropna()
    return float(w.max() * 100) if len(w) else None


def price_stats(close):
    """Pure: returns, annualised returns, 3-year volatility and drawdown, and the history note, from a Close
    series (cleaned here). Shared by the ETF and the stock view (WP-3.2 rule 3)."""
    close = _clean(close)
    returns = {k: cumulative_return(close, n) for k, n in RETURN_YEARS.items()}
    note = None
    if close.empty:
        note = "no price history from Yahoo"
    elif close.index[0] > _lookback(close.index[-1], RISK_YEARS) + pd.Timedelta(days=LOOKBACK_GRACE_DAYS):
        note = f"only {(close.index[-1] - close.index[0]).days / 365.25:.1f} years of prices"
    return {
        "returns": returns,
        "annual_returns": {k: annualised(returns[k], n) for k, n in RETURN_YEARS.items()},
        "volatility_3y": volatility(close),
        "max_drawdown_3y": max_drawdown(close),
        "history_note": note,
    }


def price_chart(close, years=CHART_YEARS):
    """Pure: columns Date, Close; the cleaned Close for dates after (last date - years), oldest first."""
    s = _clean(close)
    if s.empty:
        return pd.DataFrame(columns=["Date", "Close"])
    w = s[s.index > _lookback(s.index[-1], years)]
    return pd.DataFrame({"Date": w.index, "Close": w.values})


def etf_stats(raw):
    """Pure: the ETF figures of spec s.4 from a Raw."""
    info = raw.info
    close = _close(raw.prices)
    size, fx = _num(info.get("totalAssets")), _num(raw.fx)
    return {
        "currency": info.get("currency"),
        "expense_ratio": _expense(info, raw.ops),
        "fund_size": size,
        "fx": fx,
        "fund_size_myr": size * fx if size is not None and fx is not None else None,
        "distribution_yield": _num(info.get("yield")),  # never dividendYield (percent) or trailing (0.0)
        "category": info.get("category"),
        "fund_family": info.get("fundFamily"),
        "legal_type": info.get("legalType"),
        "top_holdings": _top(raw.holdings),
        "top_holdings_pct": _top_pct(_top(raw.holdings)),
        "top_weight_max_pct": _top_max_pct(_top(raw.holdings)),
        "sector_mix": _mix(raw.sectors or {}, sector_label, "Sector"),
        "asset_mix": _mix(raw.assets or {}, _asset_label, "Class"),
        "country_mix": None,  # Yahoo does not provide it
        **price_stats(close),
        **_beta_stats(raw, close),
        "price_chart": price_chart(close),
    }


def short_money(ccy, v):
    """'USD 101.2 bn'; 'RM' for MYR; None -> 'n/a'."""
    if v is None:
        return "n/a"
    for size, unit in ((1e12, " tn"), (1e9, " bn"), (1e6, " m"), (1e3, " k")):
        if abs(v) >= size * 0.99995:  # 999.96 m prints as 1.0 bn, not 1000.0 m
            num = f"{v / size:.1f}{unit}"
            break
    else:
        num = f"{v:.0f}"
    code = "RM" if ccy == "MYR" else (ccy or "")
    return f"{code} {num}".strip()


# ---------- shared display formatters (the Research layout and compare use the same text) ----------
def pct(x, places=1, sign=False, blank="n/a"):
    """A fraction as a percent: pct(0.123) '12.3%', sign=True '+12.3%'; blank for None / NaN."""
    if x is None or pd.isna(x):
        return blank
    return f"{x * 100:+.{places}f}%" if sign else f"{x * 100:.{places}f}%"


def times(x, suffix=""):
    """A multiple to 1 decimal: '14.2' or '9.8x'."""
    return "n/a" if x is None or pd.isna(x) else f"{x:.1f}{suffix}"


def price_text(x):
    """A price: 3 decimals below 1 (Bursa penny stocks), else 2; thousands separators; 'n/a' for None."""
    if x is None or pd.isna(x):
        return "n/a"
    return f"{x:,.3f}" if abs(x) < 1 else f"{x:,.2f}"


def beta_text(v):
    """A beta to 2 decimals: '1.12', '-0.35', '0.00' (never '-0.00'); 'n/a' for None / NaN."""
    v = _safe_num(v)
    if v is None:
        return "n/a"
    text = f"{v:.2f}"
    return "0.00" if text == "-0.00" else text


def priced(x, ccy):
    """'0.285 MYR'; 'n/a' alone when there is no price."""
    return "n/a" if x is None or pd.isna(x) else f"{price_text(x)} {'n/a' if ccy is None else str(ccy)}"


def etf_lights(stats):
    """Expense ratio and fund size lights; size judged in the fund's own currency, never in Ringgit."""
    shown = {"expense_ratio": lambda v: f"{v * 100:.2f}%",
             "fund_size": lambda v: short_money(stats.get("currency"), v)}
    lights = {}
    for item, show in shown.items():
        v = _num(stats.get(item))
        colour = "grey" if v is None else _band(ETF_THRESHOLDS[item], v)
        value = "n/a" if v is None else show(v)
        lights[item] = Light(colour, f"{ETF_NAMES[item]} {value}: {ETF_REASONS[item][colour]}")
    return lights


VERDICT_GREY = {"expense_ratio": "cost not reported", "fund_size": "size not reported"}


def etf_verdict(etf):
    """One sentence from the two ETF lights, e.g. 'Cheap to hold; large and liquid'. Template only."""
    parts = []
    for item in ("expense_ratio", "fund_size"):
        colour = etf["lights"][item].colour
        parts.append(VERDICT_GREY[item] if colour == "grey" else ETF_REASONS[item][colour])
    text = "; ".join(parts)  # the size reason has its own comma ("small, closure risk")
    return text[:1].upper() + text[1:]


def etf_overall(lights):
    lit = [lt for lt in lights.values() if lt.colour in _RANK]
    if not lit:
        return Light("grey", "no cost or size data")
    worst = max(lit, key=lambda lt: _RANK[lt.colour])  # first of equals wins
    return Light(worst.colour, "worst: " + worst.reason)


# ---------- stock view (WP-3.2) ----------
def range_position(price, low, high):
    """How far up its 52-week range the price sits: 0 at the low, 1 at the high, clipped; None when any of
    the three is missing or high <= low."""
    if price is None or low is None or high is None or high <= low:
        return None
    return float(min(max((price - low) / (high - low), 0.0), 1.0))


def dividend_history(dividends, this_year, first_year=None):
    """Pure: Year (str), Per share (float, sum of the calendar year's payments), Payments (int), one row per
    year from this_year - DIVIDEND_YEARS to this_year, newest first; the current year "<year> so far".
    Years before first_year are left out. No dividends and no first_year (no prices) -> empty frame."""
    cols = ["Year", "Per share", "Payments"]
    has = isinstance(dividends, pd.DataFrame) and "Dividends" in dividends and not dividends.empty
    if not has and first_year is None:
        return pd.DataFrame(columns=cols)
    amounts = pd.Series([], index=pd.DatetimeIndex([]), dtype="float64")
    if has:
        amounts = pd.to_numeric(dividends["Dividends"], errors="coerce")
        amounts.index = pd.DatetimeIndex(amounts.index)
        amounts = amounts[amounts.notna() & (amounts != 0)]
    by_year = amounts.groupby(amounts.index.year)
    sums, counts = by_year.sum(), by_year.count()
    years = [y for y in range(this_year, this_year - DIVIDEND_YEARS - 1, -1)
             if first_year is None or y >= first_year]
    return pd.DataFrame({
        "Year": [f"{y} so far" if y == this_year else str(y) for y in years],
        "Per share": pd.Series([float(sums.get(y, 0.0)) for y in years], dtype="float64"),
        "Payments": pd.Series([int(counts.get(y, 0)) for y in years], dtype="int64"),
    }, columns=cols)


def _next_date(value, fetched_at):
    """info["nextEarningsDate"] as a date; None when absent, unreadable or before the fetch day."""
    try:
        d = date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return None if d < fetched_at.date() else d


def company_stats(raw):
    """Pure: the stock view's company block, price figures and dividend history (WP-3.2 rule 4)."""
    info = raw.info
    close = _close(raw.prices)
    low, high = _safe_num(info.get("fiftyTwoWeekLow")), _safe_num(info.get("fiftyTwoWeekHigh"))
    price = valuation_of(info, None)["price"]  # info price, never Close: the range is unadjusted
    cap, fx = _safe_num(info.get("marketCap")), _safe_num(raw.fx)
    return {
        "summary": info.get("longBusinessSummary"),
        "website": info.get("website"),
        "employees": info.get("fullTimeEmployees"),
        "range_low": low,
        "range_high": high,
        "range_position": range_position(price, low, high),
        "market_cap": cap,
        "fx": fx,
        "market_cap_myr": cap * fx if cap is not None and fx is not None else None,
        "insiders": _safe_num(info.get("heldPercentInsiders")),  # fractions (measure-2), no / 100
        "institutions": _safe_num(info.get("heldPercentInstitutions")),
        "next_earnings": _next_date(info.get("nextEarningsDate"), raw.fetched_at),
        "price_chart": price_chart(close),
        **price_stats(close),
        **_beta_stats(raw, close),
        "dividends": dividend_history(raw.dividends, raw.fetched_at.year,
                                      close.index[0].year if not close.empty else None),
        "payout_ratio": _safe_num(info.get("payoutRatio")),
    }


def credit_rows(r):
    """One dict per ratio in RATIOS order: group, ratio, cells (labels per period), light, drives_overall.
    Gathers what analyse already holds; nothing is recomputed."""
    return [{"group": RATIO_GROUPS[name], "ratio": name,
             "cells": [r.labels.loc[name, p] for p in r.periods],
             "light": r.lights[name], "drives_overall": name in LENDER_RATIOS} for name in RATIOS]


def statement_rows(r):
    """{statement: FIELDS lines x periods}, in millions (divided here, so the page divides nothing)."""
    out = {}
    for s in STATEMENTS:
        fields = [f for f, st in FIELDS.items() if st == s]
        out[s] = r.statements[s].reindex(index=fields, columns=r.periods).astype(float) / 1e6
    return out


def statement_unit(r):
    return f"{r.financial_currency} millions" if r.financial_currency else "millions"


# ---------- analysis ----------
def _stale_line(raw):
    return f"Yahoo unreachable; showing figures fetched {raw.fetched_at:%Y-%m-%d %H:%M}"


def _warnings(raw, annual, periods, stale):
    info, out = raw.info, []
    if stale:
        out.append(_stale_line(raw))
    if not periods:
        out.append("no financial statements from Yahoo")
    elif not annual:
        out.append("no full fiscal year from Yahoo; TTM only")
    elif len(annual) < 4:
        out.append(f"only {len(annual)} annual periods from Yahoo")
    fc, cur = info.get("financialCurrency"), info.get("currency")
    if fc and cur and fc != cur:
        out.append(f"statements in {fc}, price in {cur}; not converted")
    newest = next(iter(annual.values()), {})
    if "income" in newest:
        col = raw.income[newest["income"]]
        ebitda, ebit, dep = (_num(col.get(f)) for f in ("EBITDA", "EBIT", "Reconciled Depreciation"))
        if ebitda is not None and ebitda == ebit and dep is None:
            out.append("Yahoo shows no depreciation for this company; EBITDA may equal EBIT")
    return out


def analyse(raw, stale=False):
    """Pure: Raw in, Research out. Raises ResearchError when Yahoo knows nothing of the code."""
    info = raw.info
    if not info.get("quoteType") and raw.income.empty:
        raise ResearchError(f"Yahoo has no data for {raw.code}")
    is_financial = info.get("sector") == FINANCIAL_SECTOR
    annual = _annual_cols(raw)
    tables = period_table(raw)
    ratios, labels, notes = compute_ratios(tables, is_financial)
    periods = list(ratios.columns)
    if periods:
        lights = {}
        for r in RATIOS:
            p = _light_period(r, ratios, notes, periods)
            lights[r] = light_for(r, ratios.loc[r, p], p, notes.get((r, p)))
        overall = overall_light(lights, is_financial)
    else:
        none = ("grey", "no financial statements from Yahoo", None)
        lights = {r: light_for(r, None, None, none) for r in RATIOS}
        overall = Light("grey", "no financial statements from Yahoo")
    val = valuation_of(info, raw.recs)
    etf, warnings, company = None, None, None
    if info.get("quoteType") == "ETF":  # rule 5: the ETF light replaces the credit one
        stats = etf_stats(raw)
        etf_l = etf_lights(stats)
        overall = etf_overall(etf_l)
        etf = {**stats, "lights": etf_l, "overall": overall}
        warnings = [w for w in (_stale_line(raw) if stale else None, stats["history_note"], _beta_warning(raw)) if w]
    elif info.get("quoteType"):
        company = company_stats(raw)
        warnings = _warnings(raw, annual, periods, stale)
        if company["history_note"]:
            warnings.append(company["history_note"])
        if _beta_warning(raw):
            warnings.append(_beta_warning(raw))
    return Research(
        code=raw.code, name=info.get("longName") or info.get("shortName") or raw.code,
        exchange=info.get("exchange"), sector=info.get("sector"), industry=info.get("industry"),
        kind=info.get("quoteType"), currency=info.get("currency"), financial_currency=info.get("financialCurrency"),
        price=val["price"], market_cap=val["market_cap"], fetched_at=raw.fetched_at, stale=stale,
        is_financial=is_financial, periods=periods, statements=tables, ratios=ratios, labels=labels,
        lights=lights, overall=overall, valuation=val, links=links_for(raw.code),
        warnings=_warnings(raw, annual, periods, stale) if warnings is None else warnings, etf=etf,
        company=company)


def research(code, now=None, fetcher=fetch_raw, cache_dir=CACHE_DIR, ttl=CACHE_TTL, force=False):
    """Cached copy if younger than ttl; else fetch and save; on a fetch error, the stale copy if any.
    force=True skips the fresh-copy read (the Refresh button); the stale-copy protection still applies."""
    now = now or datetime.now()
    cached = load_cache(code, cache_dir)
    if cached and not force and (now - cached.fetched_at).total_seconds() < ttl:
        return analyse(cached)
    try:
        raw = fetcher(code, now=now)
    except Exception as exc:  # any Yahoo failure
        if cached:
            return analyse(cached, stale=True)
        raise ResearchError(str(exc)) from exc
    try:
        result = analyse(raw)  # raises before saving when the code is unknown
    except ResearchError:
        if cached:  # Yahoo failed silently with empty frames (measure-1 s.7)
            return analyse(cached, stale=True)
        raise
    if cached and result.etf is not None and _close(raw.prices).empty and not _close(cached.prices).empty:
        return analyse(cached, stale=True)  # ETF partial failure: keep the good copy, do not overwrite
    if cached and not result.periods:
        old = analyse(cached, stale=True)
        if old.periods:  # silent failure: keep the good copy, do not overwrite
            return old
    save_cache(raw, cache_dir)
    return result


# ---------- "Compare with today" (WP-3.4.1) ----------
@dataclass
class Moved:
    section: str
    figure: str
    saved: str   # display text, "n/a" when the saved side has no value
    today: str   # display text, "n/a" when today's side has no value
    change: str  # "▲ +8.0%", "▼ -0.25", "▲ +1.20 points", "amber → green", "no change" or "n/a"
    note: str    # "" except for lights (the reason) and credit rows not read on both sides' newest period


@dataclass
class Comparison:
    code: str
    saved_on: date  # date of saved.fetched_at
    today_on: date  # date of fresh.fetched_at
    rows: list      # list[Moved]
    notes: list     # list[str]


KINDS_NOTE = "The saved copy and today's result are different kinds (stock / ETF); nothing to compare."
SAME_FETCH_NOTE = "Today's figures are the same fetch as the saved ones (the hourly copy has not renewed yet)."
STALE_NOTE = "Yahoo could not be reached; the Today column shows figures fetched {:%Y-%m-%d %H:%M}."
RETURN_LABELS = {"1y": "1y return", "3y": "3y return", "5y": "5y return"}  # the layout's wording


def _arrowed(d, places, unit=""):
    """'▲ +1.40', '▼ -0.18 points', or 'no change' when d shows as zero at its precision."""
    text = f"{d:+.{places}f}"
    if float(text) == 0:
        return "no change"
    return f"{'▲' if d > 0 else '▼'} {text}{unit}"


def _shown_value(text):
    """The number a display text shows: '+12.3%' -> 12.3, '9.8x' -> 9.8, '1,234.50' -> 1234.5."""
    return float(text.replace(",", "").rstrip("%x"))


def _change(kind, a, b, ta, tb):
    """kind 'amount': relative change of the raw values; 'diff' / 'points': difference of the displayed values."""
    if a is None or b is None:
        return "n/a"
    if kind == "amount":
        return "n/a" if a <= 0 else _arrowed((b / a - 1) * 100, 1, "%")
    d = _shown_value(tb) - _shown_value(ta)
    return _arrowed(d, 2, " points" if kind == "points" else "")


def _get(d, *keys):
    """d[k1][k2]... or None when any level is missing or not a dict."""
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _credit_at(r, name, p):
    """(value, label) of one ratio in one period column; a missing cell reads as (None, 'n/a')."""
    try:
        v = _safe_num(r.ratios.loc[name, p])
    except (KeyError, AttributeError, TypeError):
        v = None
    try:
        label = r.labels.loc[name, p]
    except (KeyError, AttributeError, TypeError):
        label = None
    return v, label if isinstance(label, str) else fmt(name, v)


def _credit_cell(r, name):
    """(value, label, period used, side's newest period) for one ratio (v4.1): the period the side's own light
    reason names as "(<period>)"; else TTM when that cell is filled; else the newest fiscal year; else the
    newest period. The cell is read as it is, "n/a" included. (None, 'n/a', None, None) without periods."""
    periods = list(r.periods or [])
    if not periods:
        return None, "n/a", None, None
    lt = (r.lights or {}).get(name)
    reason = lt.reason if isinstance(lt, Light) and isinstance(lt.reason, str) else ""
    used = next((p for p in periods if f"({p})" in reason), None)
    if used is None:
        years = [p for p in periods if p != "TTM"]
        ttm = _credit_at(r, name, "TTM") if "TTM" in periods else (None, "n/a")
        if ttm[0] is not None or ttm[1] != "n/a":
            used = "TTM"
        else:
            used = years[0] if years else periods[0]
    return (*_credit_at(r, name, used), used, periods[0])


def _light_row(figure, a, b):
    a = a if isinstance(a, Light) else None
    b = b if isinstance(b, Light) else None
    if a is None and b is None:
        return None
    change = "n/a" if a is None or b is None else (
        "no change" if a.colour == b.colour else f"{a.colour} → {b.colour}")
    return Moved("Lights", figure, a.colour if a else "n/a", b.colour if b else "n/a", change, (b or a).reason)


def compare(saved, fresh):
    """Pure: the headline figures of a saved Research beside a fresh one for the same code, as ready-made
    text rows (WP-3.4.1 spec v4). No Yahoo, cache, file or clock; never raises on None / NaN / numpy."""
    out = Comparison(saved.code, saved.fetched_at.date(), fresh.fetched_at.date(), [], [])
    kinds = ["etf" if r.etf is not None else ("stock" if r.company is not None else None) for r in (saved, fresh)]
    if kinds[0] != kinds[1] or kinds[0] is None:
        out.notes.append(KINDS_NOTE)
        return out
    if fresh.fetched_at == saved.fetched_at:
        out.notes.append(SAME_FETCH_NOTE)
    if fresh.stale:
        out.notes.append(STALE_NOTE.format(fresh.fetched_at))
    rows = out.rows

    def figure(section, label, get, show, kind, ccy=lambda r: r.currency):
        a, b = _safe_num(get(saved)), _safe_num(get(fresh))
        if a is None and b is None:
            return
        ta, tb = show(a, saved), show(b, fresh)
        ca, cb = ccy(saved), ccy(fresh)
        if kind == "amount" and ca and cb and ca != cb:  # v3.2: two known, unequal currencies
            change = "n/a"
        else:
            change = _change(kind, a, b, ta, tb)
        rows.append(Moved(section, label, ta, tb, change, ""))

    etf = kinds[0] == "etf"
    block = (lambda r: r.etf) if etf else (lambda r: r.company)
    figure("Price and size", "Price", lambda r: r.price, lambda v, r: priced(v, r.currency), "amount")
    if etf:
        figure("Price and size", "Fund size", lambda r: _get(r.etf, "fund_size"),
               lambda v, r: short_money(_get(r.etf, "currency"), v), "amount",
               ccy=lambda r: _get(r.etf, "currency"))
        figure("Costs", "Expense ratio", lambda r: _get(r.etf, "expense_ratio"),
               lambda v, r: pct(v, places=2), "points")
        figure("Costs", "Distribution yield", lambda r: _get(r.etf, "distribution_yield"),
               lambda v, r: pct(v, places=2), "points")
    else:
        figure("Price and size", "Market cap", lambda r: r.market_cap,
               lambda v, r: short_money(r.currency, v), "amount")
        for key, label, suffix in (("pe", "P/E", ""), ("forward_pe", "Forward P/E", ""), ("pb", "P/B", ""),
                                   ("ev_ebitda", "EV/EBITDA", "x")):
            figure("Valuation", label, lambda r, k=key: _get(r.valuation, k),
                   lambda v, r, s=suffix: times(v, s), "diff")
        figure("Valuation", "Dividend yield", lambda r: _get(r.valuation, "dividend_yield"),
               lambda v, r: pct(v, places=2), "points")
        figure("Valuation", "Analyst target", lambda r: _get(r.valuation, "target_mean"),
               lambda v, r: priced(v, r.currency), "amount")

    for k, label in RETURN_LABELS.items():
        figure("Returns and risk", label, lambda r, k=k: _get(block(r), "returns", k),
               lambda v, r: pct(v, sign=True), "points")
    figure("Returns and risk", "Volatility", lambda r: _get(block(r), "volatility_3y"), lambda v, r: pct(v), "points")
    figure("Returns and risk", "Max drawdown", lambda r: _get(block(r), "max_drawdown_3y"),
           lambda v, r: pct(v), "points")
    figure("Returns and risk", "Beta", lambda r: _get(block(r), "beta_3y"), lambda v, r: beta_text(v), "diff")

    if not etf:
        for name in RATIOS:
            (va, la, pa, na), (vb, lb, pb, nb) = _credit_cell(saved, name), _credit_cell(fresh, name)
            lit = any(isinstance((r.lights or {}).get(name), Light) for r in (saved, fresh))
            if va is None and vb is None and la == "n/a" and lb == "n/a" and not lit:
                continue  # v4.2: kept whenever a light for this ratio exists on either side
            kind = "diff" if name in MULTIPLES or name in PLAIN else "points"
            change = "n/a" if va is None or vb is None else _change(kind, va, vb, fmt(name, va), fmt(name, vb))
            moved_on = pa != pb or pa != na or pb != nb
            note = f"saved: {pa}, today: {pb}" if pa is not None and pb is not None and moved_on else ""
            rows.append(Moved("Credit health", name, la, lb, change, note))

    if etf:
        lights = [(ETF_NAMES[k], _get(saved.etf, "lights", k), _get(fresh.etf, "lights", k)) for k in ETF_NAMES]
    else:
        lights = [(name, (saved.lights or {}).get(name), (fresh.lights or {}).get(name)) for name in RATIOS]
    for label, a, b in [*lights, ("Overall", saved.overall, fresh.overall)]:
        m = _light_row(label, a, b)
        if m is not None:
            rows.append(m)
    return out


def _print(r):
    print(f"{r.name} ({r.code})  {r.kind}  {r.exchange}  {r.sector} / {r.industry}")
    print(f"price {r.price} {r.currency}  market cap {r.market_cap}  statements in {r.financial_currency}")
    print(f"fetched {r.fetched_at:%Y-%m-%d %H:%M}{'  (stale)' if r.stale else ''}\n")
    if r.periods:
        print(r.labels.to_string(), "\n")
    if r.etf:
        _print_etf(r.etf)
    else:
        for lt in r.lights.values():
            print(f"[{lt.colour:5}] {lt.reason}")
        if r.company:
            _print_company(r.company, r.currency)
    print(f"\nOVERALL [{r.overall.colour}] {r.overall.reason}")
    print("valuation:", {k: v for k, v in r.valuation.items() if v is not None})
    print("links:", r.links)
    for w in r.warnings:
        print("warning:", w)


def _p(x, places=1):
    return "n/a" if x is None else f"{x * 100:.{places}f}%"


def _beta_line(d):
    b = d.get("beta_3y")
    return f"beta 3y {beta_text(b)}" + ("" if _safe_num(b) is None else f" against {d.get('beta_index')}")


def _print_company(c, ccy):
    print(f"\ncompany: 52-week range {c['range_low']} - {c['range_high']} {ccy}"
          f"  position {_p(c['range_position'], 0)} of the way up")
    print(f"market cap {short_money('MYR', c['market_cap_myr'])} ({short_money(ccy, c['market_cap'])},"
          f" fx {c['fx']})")
    print(f"insiders {_p(c['insiders'])}  institutions {_p(c['institutions'])}  employees {c['employees']}"
          f"  next earnings {c['next_earnings'] or 'n/a'}")
    print("returns:", "  ".join(f"{k} {_p(c['returns'][k])} ({_p(c['annual_returns'][k])} a year)"
                                for k in RETURN_YEARS))
    print(f"volatility 3y {_p(c['volatility_3y'])}  max drawdown 3y {_p(c['max_drawdown_3y'])}"
          f"  chart rows {len(c['price_chart'])}")
    print(_beta_line(c))
    print(f"payout ratio {_p(c['payout_ratio'])}  dividends per share ({ccy}):")
    print(c["dividends"].to_string(index=False) if not c["dividends"].empty else "  none")


def _print_etf(e):
    print(f"ETF: {e['category']} / {e['fund_family']} / {e['legal_type']}")
    print(f"expense ratio {_p(e['expense_ratio'], 2)}  distribution yield {_p(e['distribution_yield'])}")
    print(f"fund size {short_money(e['currency'], e['fund_size'])}  = {short_money('MYR', e['fund_size_myr'])}"
          f"  (fx {e['fx']})")
    print("returns:", "  ".join(f"{k} {_p(e['returns'][k])} ({_p(e['annual_returns'][k])} a year)"
                                for k in RETURN_YEARS))
    print(f"volatility 3y {_p(e['volatility_3y'])}  max drawdown 3y {_p(e['max_drawdown_3y'])}")
    print(_beta_line(e))
    if not e["top_holdings"].empty:
        print("top holdings:\n" + e["top_holdings"].to_string(index=False))
    print("sector mix:", ", ".join(f"{s} {_p(w)}" for s, w in e["sector_mix"].itertuples(index=False)))
    print("asset mix:", ", ".join(f"{c} {_p(w)}" for c, w in e["asset_mix"].itertuples(index=False)))
    print("country mix: not provided by Yahoo")
    for lt in e["lights"].values():
        print(f"[{lt.colour:5}] {lt.reason}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python research_data.py <CODE>")
    try:
        _print(research(sys.argv[1]))
    except ResearchError as e:
        sys.exit(f"ResearchError: {e}")
