"""WP-3.1 research data layer tests (spec T1-T12). Fakes only: hand-made frames in
yfinance 1.7.0's shape (measure-1), round made-up numbers, no network, no workbook."""
import json
import math
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import research_data as rd  # noqa: E402

NAN = float("nan")
ABSENT = object()  # field value meaning "row not present in the frame"
T0 = datetime(2026, 10, 31, 9, 0, 0)

DE, ND, IC, CR = "Debt / Equity", "Net debt / EBITDA", "Interest cover", "Current ratio"
OCF, FCF, NM, ROE, GR = "OCF / Total debt", "FCF margin", "Net margin", "ROE", "Revenue growth"
RATIO_NAMES = [DE, ND, IC, CR, OCF, FCF, NM, ROE, GR]
LENDER = [DE, ND, IC, CR]
MULT = {ND, IC}
PLAIN = {DE, CR, OCF}

INCOME = ["Total Revenue", "Net Income", "EBITDA", "EBIT", "Interest Expense", "Reconciled Depreciation"]
BALANCE = ["Total Debt", "Stockholders Equity", "Cash And Cash Equivalents", "Current Assets",
           "Current Liabilities"]
CASHFLOW = ["Operating Cash Flow", "Free Cash Flow"]
TWELVE = [f for f in INCOME + BALANCE + CASHFLOW if f != "Reconciled Depreciation"]

BANK_LINE = "credit ratios not meaningful for a bank; see profitability and valuation"


# ---------- frame helpers (yfinance shape) ----------
def dates(*isos):
    return pd.DatetimeIndex(pd.to_datetime(list(isos))).as_unit("s")


def frame(labels, cols, rows):
    """rows: one dict per column (newest first), field -> value; missing = NaN; ABSENT everywhere drops the row."""
    data = {}
    for lab in labels:
        vals = [r.get(lab, NAN) for r in rows]
        if all(v is ABSENT for v in vals):
            continue
        data[lab] = [NAN if v is ABSENT else float(v) for v in vals]
    df = pd.DataFrame(data, index=cols, dtype="float64").T
    df.columns = cols
    return df


def stmts(cols, rows):
    return frame(INCOME, cols, rows), frame(BALANCE, cols, rows), frame(CASHFLOW, cols, rows)


def recs_frame(sb=2, b=3, h=4, s=1, ss=1):
    return pd.DataFrame({"period": ["0m", "-1m"], "strongBuy": [sb, 0], "buy": [b, 0], "hold": [h, 0],
                         "sell": [s, 0], "strongSell": [ss, 0]})


def make_raw(code, info, annual_cols, annual_rows, q_cols=None, q_rows=None, recs=None):
    inc, bal, cf = stmts(annual_cols, annual_rows)
    if q_cols is None:
        qi = qb = qc = pd.DataFrame()
    else:
        qi, qb, qc = stmts(q_cols, q_rows)
    return rd.Raw(code=code, info=info, income=inc, balance=bal, cashflow=cf, q_income=qi, q_balance=qb,
                  q_cashflow=qc, recs=recs if recs is not None else pd.DataFrame(), fetched_at=T0)


def info_eq(**kw):
    base = {"quoteType": "EQUITY", "shortName": "FAKE", "longName": "Fake Co", "exchange": "KLS",
            "sector": "Industrials", "industry": "Engineering & Construction", "currency": "MYR",
            "financialCurrency": "MYR", "currentPrice": 5.0, "marketCap": 5000.0}
    base.update(kw)
    return base


# One period of round numbers; expected ratios below are exact by hand.
BASE = {"Total Revenue": 1000, "Net Income": 100, "EBITDA": 200, "EBIT": 160, "Interest Expense": 40,
        "Reconciled Depreciation": 40, "Total Debt": 600, "Stockholders Equity": 1000,
        "Cash And Cash Equivalents": 200, "Current Assets": 900, "Current Liabilities": 600,
        "Operating Cash Flow": 150, "Free Cash Flow": -50}
SIMPLE_COLS = ["2026-12-31", "2025-12-31", "2024-12-31", "2023-12-31"]


def F(**kw):
    """field overrides with spaces: F(Total_Debt=1) -> {"Total Debt": 1}"""
    return {k.replace("_", " "): v for k, v in kw.items()}


def simple_raw(n_years=4, info=None, **newest):
    """Annual only (no quarters -> no TTM). Newest column = BASE + overrides; older columns are BASE
    with revenue 800, 640, 512 so growth on the newest is exactly 25%."""
    row0 = dict(BASE)
    row0.update(newest)
    rows = [row0] + [dict(BASE, **{"Total Revenue": 1000 * 0.8 ** i}) for i in range(1, n_years)]
    return make_raw("SIM.KL", info or info_eq(), dates(*SIMPLE_COLS[:n_years]), rows)


def sim(**kw):
    return simple_raw(**F(**kw))


def gamuda_like(n_quarters=6):
    """4 annual + 1 all-NaN oldest column; 6 quarters (oldest income column NaN); the newest quarter is the
    year end so TTM flows = newest annual; EBITDA == EBIT, Reconciled Depreciation NaN; FCF negative."""
    ann = dates("2026-07-31", "2025-07-31", "2024-07-31", "2023-07-31", "2022-07-31")
    y0 = dict(BASE, **{"EBIT": 200, "Reconciled Depreciation": NAN})
    rows = [y0] + [dict(y0, **{"Total Revenue": r, "Free Cash Flow": 20}) for r in (800, 700, 600)] + [{}]
    qd = dates("2026-07-31", "2026-04-30", "2026-01-31", "2025-10-31", "2025-07-31", "2025-04-30")
    qflow = {"Total Revenue": 250, "Net Income": 25, "EBITDA": 50, "EBIT": 50, "Interest Expense": 10,
             "Reconciled Depreciation": NAN, "Operating Cash Flow": 37.5, "Free Cash Flow": -12.5}
    qbal = {k: y0[k] for k in BALANCE}
    qrows = [dict(qflow, **qbal) for _ in range(5)] + [dict(qbal)]  # oldest quarter: flows NaN
    raw = make_raw("5398.KL", info_eq(longName="Gamuda-like Bhd", trailingAnnualDividendYield=0.02,
                                      dividendYield=2.0), ann, rows, qd, qrows, recs_frame())
    if n_quarters < 6:
        raw.q_income = raw.q_income.iloc[:, :n_quarters]
        raw.q_balance = raw.q_balance.iloc[:, :n_quarters]
        raw.q_cashflow = raw.q_cashflow.iloc[:, :n_quarters]
    return raw


def apple_like():
    """September year end; 4 annual; 5 quarters; Interest Expense NaN (newest 2 annual), absent quarterly."""
    ann = dates("2025-09-30", "2024-09-30", "2023-09-30", "2022-09-30")
    rows = []
    for i, ie in enumerate([NAN, NAN, 30, 30]):
        rows.append(dict(BASE, **{"Total Revenue": 1000 - 100 * i, "Interest Expense": ie, "Total Debt": 400,
                                  "Free Cash Flow": 100}))
    qd = dates("2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30")
    qrows = []
    for i, rev in enumerate([300, 250, 350, 260, 240]):
        qrows.append(dict(BASE, **{"Total Revenue": rev, "Net Income": 30, "EBITDA": 60, "EBIT": 50,
                                   "Interest Expense": ABSENT, "Reconciled Depreciation": 10,
                                   "Operating Cash Flow": 40, "Free Cash Flow": 30,
                                   "Total Debt": 500 if i == 0 else 400}))
    return make_raw("AAPL", info_eq(longName="Apple-like Inc.", exchange="NMS", sector="Technology",
                                    currency="USD", financialCurrency="USD"), ann, rows, qd, qrows)


def bank_like():
    return simple_raw(info=info_eq(sector="Financial Services", industry="Banks - Regional"))


def etf_like():
    """WP-3.3: extended with the ETF fields (made-up numbers). Set after construction so the fixture
    builds whether or not Raw has the new fields yet."""
    e = pd.DataFrame()
    raw = rd.Raw(code="VT", info=etf_info(), income=e, balance=e, cashflow=e, q_income=e, q_balance=e,
                 q_cashflow=e, recs=e, fetched_at=T0)
    raw.holdings = etf_holdings()
    raw.sectors = dict(ETF_SECTORS)
    raw.assets = dict(ETF_ASSETS)
    raw.ops = etf_ops()
    raw.prices = pd.DataFrame({"Close": five_year_close()})
    raw.fx = 4.25
    return raw


def nothing_like():
    e = pd.DataFrame()
    return rd.Raw(code="ZZZZNOPE.KL", info={"trailingPegRatio": None}, income=e, balance=e, cashflow=e,
                  q_income=e, q_balance=e, q_cashflow=e, recs=e, fetched_at=T0)


def cell(tables, field, period):
    """Find a field's value in whichever statement frame holds it."""
    for df in tables.values():
        if field in df.index and period in df.columns:
            v = df.loc[field, period]
            if not pd.isna(v):
                return v
    return NAN


# ---------- T1 periods ----------
def test_t1_gamuda_annual_keys_and_ttm():
    keys, ttm = rd.periods_of(gamuda_like())
    assert keys == ["2026-07-31", "2025-07-31", "2024-07-31", "2023-07-31"]
    assert ttm is True
    assert rd.analyse(gamuda_like()).periods == ["TTM", "2026-07-31", "2025-07-31", "2024-07-31", "2023-07-31"]


def test_t1_three_quarters_no_ttm():
    keys, ttm = rd.periods_of(gamuda_like(n_quarters=3))
    assert ttm is False and len(keys) == 4
    assert "TTM" not in rd.analyse(gamuda_like(n_quarters=3)).periods


def test_t1_apple_ttm_sums_four_quarters_and_takes_newest_balance():
    tables = rd.period_table(apple_like())
    assert cell(tables, "Total Revenue", "TTM") == pytest.approx(300 + 250 + 350 + 260)
    assert cell(tables, "Total Revenue", "TTM") != cell(tables, "Total Revenue", "2025-09-30")
    assert cell(tables, "Total Debt", "TTM") == pytest.approx(500)
    assert cell(tables, "Total Debt", "2025-09-30") == pytest.approx(400)
    r = rd.analyse(apple_like())
    assert r.periods[0] == "TTM" and r.periods[1] == "2025-09-30"
    assert cell(r.statements, "Total Revenue", "TTM") == pytest.approx(1160)
    assert set(r.statements) == {"income", "balance", "cashflow"}


def test_t1_fields_setting_holds_the_twelve_labels():
    assert set(rd.FIELDS) == set(TWELVE)


# ---------- T2 ratio arithmetic ----------
def test_t2_nine_ratios_exact_on_one_period():
    assert list(rd.RATIOS) == RATIO_NAMES
    r = rd.analyse(simple_raw())
    p = "2026-12-31"
    expect = {DE: 0.6, ND: 2.0, IC: 4.0, CR: 1.5, OCF: 0.25, FCF: -0.05, NM: 0.10, ROE: 0.10, GR: 0.25}
    labels = {DE: "0.60", ND: "2.0x", IC: "4.0x", CR: "1.50", OCF: "0.25", FCF: "-5.0%", NM: "10.0%",
              ROE: "10.0%", GR: "25.0%"}
    assert list(r.ratios.index) == RATIO_NAMES
    for name, v in expect.items():
        assert r.ratios.loc[name, p] == pytest.approx(v), name
        assert r.labels.loc[name, p] == labels[name], name


def test_t2_interest_expense_sign_ignored():
    r = rd.analyse(sim(Interest_Expense=-40))
    assert r.ratios.loc[IC, "2026-12-31"] == pytest.approx(4.0)


def test_t2_growth_na_on_oldest_and_ttm():
    r = rd.analyse(simple_raw())
    assert pd.isna(r.ratios.loc[GR, "2023-12-31"]) and r.labels.loc[GR, "2023-12-31"] == "n/a"
    g = rd.analyse(gamuda_like())
    assert pd.isna(g.ratios.loc[GR, "TTM"]) and g.labels.loc[GR, "TTM"] == "n/a"
    assert g.ratios.loc[GR, "2026-07-31"] == pytest.approx(0.25)


# ---------- T3 n/a rules ----------
def test_t3_zero_denominator_is_na():
    r = rd.analyse(sim(Current_Liabilities=0, Total_Revenue=0))
    p = "2026-12-31"
    for name in (CR, NM, FCF):
        assert pd.isna(r.ratios.loc[name, p]), name
        assert r.labels.loc[name, p] == "n/a", name
    assert not any(isinstance(v, float) and math.isinf(v) for v in r.ratios.to_numpy().ravel())


def test_t3_nan_interest_expense_grey():
    r = rd.analyse(sim(Interest_Expense=NAN))
    assert pd.isna(r.ratios.loc[IC, "2026-12-31"])
    assert r.labels.loc[IC, "2026-12-31"] == "n/a"
    assert r.lights[IC].colour == "grey"
    assert "interest expense not reported" in r.lights[IC].reason


def test_t3_apple_interest_cover_not_reported():
    r = rd.analyse(apple_like())
    assert r.lights[IC].colour == "grey"
    assert "interest expense not reported" in r.lights[IC].reason


def test_t3_net_cash_green():
    r = rd.analyse(sim(Cash_And_Cash_Equivalents=700))
    p = "2026-12-31"
    assert pd.isna(r.ratios.loc[ND, p])
    assert r.labels.loc[ND, p] == "net cash"
    assert r.lights[ND].colour == "green"
    assert "cash exceeds debt" in r.lights[ND].reason


def test_t3_ebitda_not_positive_with_debt_red():
    r = rd.analyse(sim(EBITDA=-10))
    p = "2026-12-31"
    assert pd.isna(r.ratios.loc[ND, p]) and r.labels.loc[ND, p] == "n/a"
    assert r.lights[ND].colour == "red"
    assert "EBITDA zero or negative; debt cannot be serviced from earnings" in r.lights[ND].reason


def test_t3_negative_equity_de_red_roe_grey():
    r = rd.analyse(sim(Stockholders_Equity=-100))
    p = "2026-12-31"
    assert pd.isna(r.ratios.loc[DE, p]) and pd.isna(r.ratios.loc[ROE, p])
    assert r.lights[DE].colour == "red" and "negative equity" in r.lights[DE].reason
    assert r.lights[ROE].colour == "grey" and "negative equity" in r.lights[ROE].reason


def test_t3_negative_ebit_interest_cover_red():
    r = rd.analyse(sim(EBIT=-80))
    assert r.ratios.loc[IC, "2026-12-31"] == pytest.approx(-2.0)
    assert r.lights[IC].colour == "red"
    assert "EBIT negative; interest not covered" in r.lights[IC].reason


# ---------- T4 thresholds ----------
def bounds(name):
    """(green bound, red bound). Accepts a 2-sequence or a dict with "green"/"red" keys."""
    t = rd.THRESHOLDS[name]
    if isinstance(t, dict):
        return float(t["green"]), float(t["red"])
    g, r = t
    return float(g), float(r)


def fmt(name, v):
    if name in MULT:
        return f"{v:.1f}x"
    if name in PLAIN:
        return f"{v:.2f}"
    return f"{v * 100:.1f}%"


def expected_colour(name, v):
    g, r = bounds(name)
    if g < r:  # lower is better
        return "green" if v < g else ("red" if v > r else "amber")
    return "green" if v > g else ("red" if v < r else "amber")


def samples(name):
    g, r = bounds(name)
    lo, hi = min(g, r), max(g, r)
    span = hi - lo
    return [lo - span, lo, (lo + hi) / 2, hi, hi + span]


@pytest.mark.parametrize("name", RATIO_NAMES)
def test_t4_threshold_bands_and_reasons(name):
    assert set(rd.THRESHOLDS) == set(RATIO_NAMES)
    seen = set()
    for v in samples(name):
        colour = expected_colour(name, v)
        seen.add(colour)
        light = rd.light_for(name, v, "2026-07-31")
        assert light.colour == colour, (name, v)
        assert light.reason.startswith(f"{name} {fmt(name, v)} (2026-07-31):"), light.reason
        assert light.reason.endswith(rd.REASONS[name][colour]), light.reason
    assert seen == {"green", "amber", "red"}


def test_t4_owner_ruled_lender_numbers():
    assert bounds(DE) == (0.5, 1.0)
    assert bounds(ND) == (2.0, 3.5)
    assert bounds(IC) == (5.0, 2.0)
    assert bounds(CR) == (1.5, 1.0)
    cases = [(DE, 0.49, "green"), (DE, 0.5, "amber"), (DE, 1.0, "amber"), (DE, 1.01, "red"),
             (ND, 1.99, "green"), (ND, 2.0, "amber"), (ND, 3.5, "amber"), (ND, 3.51, "red"),
             (IC, 5.01, "green"), (IC, 5.0, "amber"), (IC, 2.0, "amber"), (IC, 1.99, "red"),
             (CR, 1.51, "green"), (CR, 1.5, "amber"), (CR, 1.0, "amber"), (CR, 0.99, "red")]
    for name, v, colour in cases:
        assert rd.light_for(name, v, "TTM").colour == colour, (name, v)


def test_t4_none_value_is_grey():
    assert rd.light_for(NM, None, "TTM").colour == "grey"


# ---------- T5 light period ----------
def test_t5_ttm_used_when_valued_else_newest_annual():
    r = rd.analyse(gamuda_like())
    assert "(TTM)" in r.lights[DE].reason
    assert "(TTM)" in r.lights[NM].reason
    assert "(2026-07-31)" in r.lights[GR].reason
    a = rd.analyse(apple_like())
    assert "(TTM)" in a.lights[DE].reason
    assert "(2025-09-30)" in a.lights[GR].reason


# ---------- T6 overall light ----------
def test_t6_overall_is_worst_lender_ratio():
    r = rd.analyse(sim(Stockholders_Equity=500))  # D/E 1.2 red; ND 2.0, IC 4.0, CR 1.5 amber
    assert r.lights[DE].colour == "red"
    assert r.overall.colour == "red"
    assert r.overall.reason == "worst: " + r.lights[DE].reason


def test_t6_overall_ignores_non_lender_ratios():
    # lender ratios all green; FCF margin red and growth red do not drive the headline
    r = rd.analyse(sim(Total_Debt=200, Cash_And_Cash_Equivalents=100, Current_Liabilities=300,
                       Interest_Expense=10, Free_Cash_Flow=-50, Total_Revenue=500))
    assert r.lights[FCF].colour == "red" and r.lights[GR].colour == "red"
    assert r.overall.colour == "green"


def test_t6_overall_ignores_grey():
    r = rd.analyse(sim(Total_Debt=200, Cash_And_Cash_Equivalents=100, Current_Liabilities=300,
                       Interest_Expense=NAN))
    assert r.lights[IC].colour == "grey"
    assert r.overall.colour == "green"
    assert r.overall.reason.startswith("worst: ")


def test_t6_all_grey_not_enough_data():
    r = rd.analyse(sim(Total_Debt=ABSENT, Interest_Expense=ABSENT, Current_Liabilities=ABSENT))
    for name in LENDER:
        assert r.lights[name].colour == "grey", name
    assert r.overall.colour == "grey"
    assert r.overall.reason == "not enough data for a credit view"


def test_t6_overall_light_function_direct():
    lights = {n: rd.Light("green", f"{n} ok") for n in RATIO_NAMES}
    lights[DE] = rd.Light("amber", "D/E amber")
    lights[IC] = rd.Light("grey", "IC grey")
    lights[CR] = rd.Light("red", "CR red")
    lights[NM] = rd.Light("red", "NM red")  # not a lender ratio
    o = rd.overall_light(lights, False)
    assert o.colour == "red" and o.reason == "worst: CR red"
    b = rd.overall_light(lights, True)
    assert b.colour == "grey" and b.reason == BANK_LINE


def test_t6_bank_grey_with_o3_line():
    r = rd.analyse(bank_like())
    assert r.is_financial is True
    assert r.overall.colour == "grey"
    assert r.overall.reason == BANK_LINE
    for name in (IC, CR, ND):
        assert pd.isna(r.ratios.loc[name, "2026-12-31"]), name
        assert r.labels.loc[name, "2026-12-31"] == "n/a", name
        assert r.lights[name].colour == "grey", name
        assert "not meaningful for a financial company" in r.lights[name].reason
    for name in (DE, OCF, FCF, NM, ROE, GR):
        assert r.lights[name].colour in {"green", "amber", "red"}, name


def test_t6_financial_sector_setting():
    assert rd.FINANCIAL_SECTOR == "Financial Services"


# ---------- T7 valuation ----------
def test_t7_valuation_picks_and_upside():
    info = {"trailingPE": 20.0, "forwardPE": 15.0, "priceToBook": 2.0, "dividendYield": 2.0,
            "trailingAnnualDividendYield": 0.02, "enterpriseToEbitda": 10.0, "marketCap": 5000.0,
            "currentPrice": 10.0, "targetMeanPrice": 12.0, "numberOfAnalystOpinions": 11}
    v = rd.valuation_of(info, recs_frame())
    assert v["dividend_yield"] == pytest.approx(0.02)
    assert v["pe"] == 20.0 and v["forward_pe"] == 15.0 and v["pb"] == 2.0
    assert v["ev_ebitda"] == 10.0 and v["market_cap"] == 5000.0
    assert v["price"] == 10.0 and v["target_mean"] == 12.0
    assert v["upside"] == pytest.approx(0.2)
    assert v["analysts"] == 11
    assert (v["buy"], v["hold"], v["sell"]) == (5, 4, 2)


def test_t7_never_dividend_yield_percent():
    v = rd.valuation_of({"dividendYield": 2.0, "currentPrice": 10.0}, pd.DataFrame())
    assert v["dividend_yield"] is None


def test_t7_price_fallback_and_missing():
    v = rd.valuation_of({"regularMarketPrice": 8.0, "targetMeanPrice": 10.0}, pd.DataFrame())
    assert v["price"] == 8.0 and v["upside"] == pytest.approx(0.25)
    assert v["pe"] is None and v["market_cap"] is None and v["analysts"] is None
    assert v["buy"] is None and v["hold"] is None and v["sell"] is None
    assert rd.valuation_of({"currentPrice": 8.0}, pd.DataFrame())["upside"] is None
    assert rd.valuation_of({"targetMeanPrice": 8.0}, pd.DataFrame())["upside"] is None
    assert rd.valuation_of({"currentPrice": 0.0, "targetMeanPrice": 8.0}, pd.DataFrame())["upside"] is None


# ---------- T8 cache ----------
class FakeFetcher:
    def __init__(self, raw_fn=gamuda_like, fail=False):
        self.calls, self.raw_fn, self.fail, self.fetched_at = 0, raw_fn, fail, T0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.fail:
            raise ConnectionError("Yahoo down (fake)")
        raw = self.raw_fn()
        raw.fetched_at = self.fetched_at
        return raw


def test_t8_fresh_cache_no_fetch(tmp_path):
    f = FakeFetcher()
    r1 = rd.research("5398.KL", now=T0, fetcher=f, cache_dir=tmp_path, ttl=3600)
    assert f.calls == 1 and (tmp_path / "5398.KL.json").exists()
    r2 = rd.research("5398.KL", now=T0 + timedelta(minutes=10), fetcher=f, cache_dir=tmp_path, ttl=3600)
    assert f.calls == 1
    assert r2.stale is False and r2.periods == r1.periods


def test_t8_old_cache_refetched_and_overwritten(tmp_path):
    f = FakeFetcher()
    rd.research("5398.KL", now=T0, fetcher=f, cache_dir=tmp_path, ttl=3600)
    later = T0 + timedelta(hours=2)
    f.fetched_at = later
    rd.research("5398.KL", now=later, fetcher=f, cache_dir=tmp_path, ttl=3600)
    assert f.calls == 2
    saved = json.loads((tmp_path / "5398.KL.json").read_text(encoding="utf-8"))
    assert saved["fetched_at"].startswith(later.isoformat()[:16])


def test_t8_outage_serves_stale_copy(tmp_path):
    rd.research("5398.KL", now=T0, fetcher=FakeFetcher(), cache_dir=tmp_path, ttl=3600)
    down = FakeFetcher(fail=True)
    r = rd.research("5398.KL", now=T0 + timedelta(hours=2), fetcher=down, cache_dir=tmp_path, ttl=3600)
    assert down.calls == 1
    assert r.stale is True
    assert any(w.startswith("Yahoo unreachable; showing figures fetched") for w in r.warnings)
    assert r.periods[0] == "TTM"


def test_t8_outage_without_cache_raises(tmp_path):
    with pytest.raises(rd.ResearchError, match="Yahoo down"):
        rd.research("5398.KL", now=T0, fetcher=FakeFetcher(fail=True), cache_dir=tmp_path, ttl=3600)


def test_t8_cache_round_trip(tmp_path):
    assert rd.load_cache("5398.KL", cache_dir=tmp_path) is None
    raw = gamuda_like()
    rd.save_cache(raw, cache_dir=tmp_path)
    back = rd.load_cache("5398.KL", cache_dir=tmp_path)
    assert back is not None and back.code == "5398.KL"
    a, b = rd.analyse(raw), rd.analyse(back)
    assert a.periods == b.periods
    pd.testing.assert_frame_equal(a.ratios, b.ratios, check_dtype=False)
    assert a.overall == b.overall


def test_t8_cache_settings():
    assert rd.CACHE_TTL == 3600
    assert Path(rd.CACHE_DIR).parts[-2:] == ("output", "research_cache")


# ---------- T9 not found, ETF ----------
def test_t9_not_found_raises():
    with pytest.raises(rd.ResearchError, match="Yahoo has no data for ZZZZNOPE.KL"):
        rd.analyse(nothing_like())


def test_t9_not_found_via_research(tmp_path):
    with pytest.raises(rd.ResearchError):
        rd.research("ZZZZNOPE.KL", now=T0, fetcher=FakeFetcher(raw_fn=nothing_like), cache_dir=tmp_path)


def test_t9_etf_empty_periods_grey():
    # amended WP-3.3 (supervisor ruling 2026-11-01, spec v1.2 rule 5): an ETF with no statements gets the
    # ETF overall light, not the credit one, and no credit / fiscal-year warnings
    raw = etf_like()
    r = rd.analyse(raw)
    assert r.kind == "ETF"
    assert r.periods == []
    assert all(lt.colour == "grey" for lt in r.lights.values())  # credit lights stay grey
    assert r.overall == rd.etf_overall(rd.etf_lights(rd.etf_stats(raw)))
    assert "no financial statements from Yahoo" not in r.overall.reason
    assert not any("no full fiscal year" in w for w in r.warnings)
    assert not any("annual periods from Yahoo" in w for w in r.warnings)


# ---------- T10 warnings ----------
def test_t10_no_depreciation_warning():
    w = "Yahoo shows no depreciation for this company; EBITDA may equal EBIT"
    assert w in rd.analyse(gamuda_like()).warnings
    assert w not in rd.analyse(apple_like()).warnings


def test_t10_currency_mismatch_warning():
    r = rd.analyse(simple_raw(info=info_eq(currency="MYR", financialCurrency="USD")))
    assert "statements in USD, price in MYR; not converted" in r.warnings
    assert not any("not converted" in w for w in rd.analyse(simple_raw()).warnings)


def test_t10_fewer_than_four_years_warning():
    assert "only 3 annual periods from Yahoo" in rd.analyse(simple_raw(n_years=3)).warnings
    assert not any(w.startswith("only ") for w in rd.analyse(gamuda_like()).warnings)


# ---------- T11 links, code mapping ----------
def test_t11_links():
    assert rd.links_for("5398.KL") == {
        "yahoo": "https://finance.yahoo.com/quote/5398.KL",
        "filings": "https://www.bursamalaysia.com/market_information/announcements/company_announcement"
                   "?company=5398"}
    assert rd.links_for("AAPL") == {
        "yahoo": "https://finance.yahoo.com/quote/AAPL",
        "filings": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=AAPL&type=10-K"}


def test_t11_yahoo_code():
    assert rd.yahoo_code("MY.5398") == "5398.KL"
    assert rd.yahoo_code("US.AAPL") == "AAPL"
    assert rd.yahoo_code("HK.00700") is None


# ---------- T12 purity ----------
def test_t12_no_streamlit_import():
    out = subprocess.run([sys.executable, "-c", "import research_data, sys; print('streamlit' in sys.modules)"],
                         cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


def test_t12_analyse_never_fetches(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("fetcher called")
    monkeypatch.setattr(rd, "fetch_raw", boom)
    if "yfinance" in sys.modules:
        monkeypatch.setattr(sys.modules["yfinance"], "Ticker", boom)
    r = rd.analyse(gamuda_like())
    assert r.periods[0] == "TTM"


# ---------- M1 mutation-round-1 gaps (supervisor ruling 2026-10-31) ----------
def test_m1_non_lender_threshold_numbers():
    # spec s.5 verbatim; T4 reads THRESHOLDS, so the numbers themselves need a pin
    assert bounds(OCF) == (0.30, 0.15)
    assert bounds(FCF) == (0.10, 0.0)
    assert bounds(NM) == (0.10, 0.03)
    assert bounds(ROE) == (0.12, 0.06)
    assert bounds(GR) == (0.05, 0.0)


def test_m1_net_debt_exactly_zero_is_net_cash():
    r = rd.analyse(sim(Cash_And_Cash_Equivalents=600))  # debt 600
    assert r.labels.loc[ND, "2026-12-31"] == "net cash"
    assert r.lights[ND].colour == "green"


def test_m1_ebitda_exactly_zero_with_debt_red():
    r = rd.analyse(sim(EBITDA=0))
    assert r.lights[ND].colour == "red"
    assert "EBITDA zero or negative" in r.lights[ND].reason


def test_m1_equity_exactly_zero_de_red_roe_grey():
    r = rd.analyse(sim(Stockholders_Equity=0))
    assert r.lights[DE].colour == "red" and "negative equity" in r.lights[DE].reason
    assert r.lights[ROE].colour == "grey" and "negative equity" in r.lights[ROE].reason


def test_m1_ttm_needs_four_cashflow_quarters_too():
    raw = gamuda_like()
    raw.q_cashflow = raw.q_cashflow.iloc[:, :3]  # income still has 5 valued quarters
    assert rd.periods_of(raw)[1] is False
    assert "TTM" not in rd.analyse(raw).periods


def test_m1_all_nan_annual_column_dropped_when_not_cut():
    raw = make_raw("X.KL", info_eq(), dates(*SIMPLE_COLS), [dict(BASE)] * 3 + [{}])
    assert rd.periods_of(raw)[0] == SIMPLE_COLS[:3]
    assert "only 3 annual periods from Yahoo" in rd.analyse(raw).warnings


def test_m1_newest_four_of_five_annual_columns():
    raw = make_raw("X.KL", info_eq(), dates(*SIMPLE_COLS, "2022-12-31"), [dict(BASE)] * 5)
    assert rd.periods_of(raw)[0] == SIMPLE_COLS


def test_m1_no_quote_type_but_statements_is_not_an_error():
    r = rd.analyse(simple_raw(info={"sector": "Industrials"}))
    assert r.periods == SIMPLE_COLS


def test_m1_cache_exactly_ttl_old_is_stale(tmp_path):
    f = FakeFetcher()
    rd.research("5398.KL", now=T0, fetcher=f, cache_dir=tmp_path, ttl=3600)
    rd.research("5398.KL", now=T0 + timedelta(seconds=3600), fetcher=f, cache_dir=tmp_path, ttl=3600)
    assert f.calls == 2


def test_m1_net_cash_at_ttm_lights_ttm():
    raw = gamuda_like()
    raw.q_balance.loc["Cash And Cash Equivalents", raw.q_balance.columns[0]] = 700.0  # TTM net cash only
    r = rd.analyse(raw)
    assert r.labels.loc[ND, "TTM"] == "net cash"
    assert r.labels.loc[ND, "2026-07-31"] != "net cash"
    assert r.lights[ND].colour == "green"
    assert "(TTM)" in r.lights[ND].reason


# ---------- F review-round-1 findings (supervisor ruling 2026-10-31, spec v1.2) ----------
def quarterly_only():
    qd = dates("2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31")
    return make_raw("NEW.KL", info_eq(), dates(), [], qd, [dict(BASE)] * 4)


def test_f1_quarterly_only_gives_ttm_period_no_crash():
    r = rd.analyse(quarterly_only())
    assert r.periods == ["TTM"]
    assert "(TTM)" in r.lights[GR].reason
    assert "no financial statements from Yahoo" not in r.warnings


def with_code(fn, code="5398.KL"):
    def make():
        raw = fn()
        raw.code = code
        return raw
    return make


def good_info_empty_statements():
    raw = gamuda_like()
    e = pd.DataFrame()
    raw.income = raw.balance = raw.cashflow = raw.q_income = raw.q_balance = raw.q_cashflow = e
    return raw


def test_f2a_silent_not_found_serves_stale_copy(tmp_path):
    rd.research("5398.KL", now=T0, fetcher=FakeFetcher(), cache_dir=tmp_path, ttl=3600)
    silent = FakeFetcher(raw_fn=with_code(nothing_like))
    r = rd.research("5398.KL", now=T0 + timedelta(hours=2), fetcher=silent, cache_dir=tmp_path, ttl=3600)
    assert silent.calls == 1
    assert r.stale is True
    assert any(w.startswith("Yahoo unreachable; showing figures fetched") for w in r.warnings)
    assert r.periods[0] == "TTM"


def test_f2b_empty_statements_serve_stale_and_keep_cache(tmp_path):
    first = rd.research("5398.KL", now=T0, fetcher=FakeFetcher(), cache_dir=tmp_path, ttl=3600)
    silent = FakeFetcher(raw_fn=good_info_empty_statements)
    r = rd.research("5398.KL", now=T0 + timedelta(hours=2), fetcher=silent, cache_dir=tmp_path, ttl=3600)
    assert silent.calls == 1
    assert r.stale is True and r.periods == first.periods
    assert any(w.startswith("Yahoo unreachable; showing figures fetched") for w in r.warnings)
    back = rd.load_cache("5398.KL", cache_dir=tmp_path)
    assert back is not None and rd.analyse(back).periods == first.periods  # not overwritten


def test_f3_negative_equity_at_ttm_pins_roe_to_ttm():
    ann = [dict(BASE, **{"Net Income": 200, "Total Revenue": 1000 * 0.8 ** i}) for i in range(4)]
    qd = dates("2027-03-31", "2026-12-31", "2026-09-30", "2026-06-30")
    q = dict(BASE, **{"Total Revenue": 250, "Net Income": 50, "Operating Cash Flow": 40})
    qrows = [dict(q, **{"Stockholders Equity": -50})] + [dict(q)] * 3
    r = rd.analyse(make_raw("NEG.KL", info_eq(), dates(*SIMPLE_COLS), ann, qd, qrows))
    assert r.lights[DE].colour == "red" and "(TTM)" in r.lights[DE].reason
    assert r.lights[ROE].colour == "grey", r.lights[ROE].reason
    assert "(TTM)" in r.lights[ROE].reason and "negative equity" in r.lights[ROE].reason
    a = rd.analyse(apple_like())  # the one grey note that still falls back
    assert "(2025-09-30)" in a.lights[IC].reason
    assert a.lights[IC].colour == "grey" and "interest expense not reported" in a.lights[IC].reason


# ---------- M3 mutation-round-3 gaps and rule 11 wording (supervisor ruling 2026-10-31, spec v1.3) ----------
def test_m3_etf_refetch(tmp_path):
    f = FakeFetcher(raw_fn=etf_like)
    rd.research("VT", now=T0, fetcher=f, cache_dir=tmp_path, ttl=3600)
    later = T0 + timedelta(hours=2)
    f.fetched_at = later
    r = rd.research("VT", now=later, fetcher=f, cache_dir=tmp_path, ttl=3600)
    assert f.calls == 2
    assert r.stale is False
    assert not any("Yahoo unreachable" in w for w in r.warnings)
    saved = json.loads((tmp_path / "VT.json").read_text(encoding="utf-8"))
    assert saved["fetched_at"].startswith(later.isoformat()[:16])


def test_m3_dup_labels(monkeypatch):
    yf = pytest.importorskip("yfinance")
    g = gamuda_like()
    dup_income = pd.concat([g.income, g.income.loc[["EBIT"]]])  # EBIT row twice, as Yahoo sometimes sends

    class FakeTicker:
        def __init__(self, code):
            self.info = dict(g.info)
            self.income_stmt, self.balance_sheet, self.cashflow = dup_income, g.balance, g.cashflow
            self.quarterly_income_stmt, self.quarterly_balance_sheet = g.q_income, g.q_balance
            self.quarterly_cashflow, self.recommendations = g.q_cashflow, g.recs

    monkeypatch.setattr(yf, "Ticker", FakeTicker)
    raw = rd.fetch_raw("5398.KL", now=T0)
    assert raw.income.index.is_unique
    assert rd.analyse(raw).periods[0] == "TTM"


def test_m3_bad_cache_json(tmp_path):
    rd.save_cache(gamuda_like(), cache_dir=tmp_path)
    path = tmp_path / "5398.KL.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["fetched_at"] = 12345  # well-formed JSON, wrong shape
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert rd.load_cache("5398.KL", cache_dir=tmp_path) is None


def test_m3_nan_analyst_count():
    recs = recs_frame()
    recs.loc[0, "strongBuy"] = NAN
    v = rd.valuation_of({"currentPrice": 10.0}, recs)
    assert v["buy"] is None
    assert v["hold"] == 4 and v["sell"] == 2


def test_m3_ttm_only_warning():
    w = rd.analyse(quarterly_only()).warnings
    assert "no full fiscal year from Yahoo; TTM only" in w
    assert "only 0 annual periods from Yahoo" not in w


# ---------- WP-3.3 ETF view (spec v1.1, E1-E9). Made-up numbers only. ----------
import numpy as np  # noqa: E402

ETF_FIELDS = ("holdings", "sectors", "assets", "ops", "prices", "fx")


def etf_info(**kw):
    base = {"quoteType": "ETF", "currency": "USD", "longName": "Fake World ETF", "shortName": "FAKE WORLD",
            "exchange": "PCX", "netExpenseRatio": 0.05,  # a percent, as Yahoo sends it: 0.05% = 0.0005
            "totalAssets": 1.0e11, "yield": 0.02, "dividendYield": 2.0, "trailingAnnualDividendYield": 0.0,
            "category": "Fake Global Blend", "fundFamily": "FakeFunds", "regularMarketPrice": 175.0}
    base.update(kw)
    return base


def etf_holdings():
    """yfinance funds_data.top_holdings shape: index Symbol, columns Name, Holding Percent (fractions)."""
    syms = [f"FK{i}" for i in range(10)]
    df = pd.DataFrame({"Name": [f"Fake Holding {i}" for i in range(10)],
                       "Holding Percent": [0.050 - 0.004 * i for i in range(10)]}, index=syms)
    df.index.name = "Symbol"
    return df


# the 11 real yfinance sector keys (measure-1 s.6), made-up weights summing to 1.0
ETF_SECTORS = {"realestate": 0.03, "consumer_cyclical": 0.10, "basic_materials": 0.05,
               "consumer_defensive": 0.06, "technology": 0.25, "communication_services": 0.08,
               "financial_services": 0.15, "utilities": 0.035, "industrials": 0.11, "energy": 0.045,
               "healthcare": 0.09}
ETF_ASSETS = {"cashPosition": 0.01, "stockPosition": 0.98, "bondPosition": 0.0, "preferredPosition": 0.0,
              "convertiblePosition": 0.0, "otherPosition": 0.01}


def etf_ops():
    """funds_data.fund_operations shape: 3 rows x (fund column, Category Average)."""
    return pd.DataFrame({"VT": [0.0007, 0.03, 9.0e10], "Category Average": [0.0099, 0.40, 1.0e9]},
                        index=["Annual Report Expense Ratio", "Annual Holdings Turnover", "Total Net Assets"])


# Synthetic 5-year daily (calendar-day) Close, piecewise linear between these anchors. Each lookback
# date sits on a flat plateau of about +-2 weeks, so "n years back" lands on a known price whatever
# day-count the builder uses:
#   last date 2026-10-30, Close 175
#   1y back 2025-10-30 -> 150 (plateau 2025-10-15..2025-11-15)
#   3y back 2023-10-30 -> 125 (plateau 2023-10-15..2023-11-15)
#   5y back 2021-10-30 -> 100 (plateau from the first date 2021-10-01 to 2021-11-15)
# One dip: peak 150 on 2024-10-30, falls linearly to 120 on 2024-12-30, recovers to 150 (not above)
# by 2025-10-15. Before the peak the series never falls; after the dip it never falls again.
ANCHORS = [("2021-10-01", 100), ("2021-11-15", 100), ("2023-10-15", 125), ("2023-11-15", 125),
           ("2024-10-30", 150), ("2024-12-30", 120), ("2025-10-15", 150), ("2025-11-15", 150),
           ("2026-10-15", 175), ("2026-10-30", 175)]
# Hand values:
#   1y cumulative = 175/150 - 1 = 1/6 = 0.1667   annualised = the same
#   3y cumulative = 175/125 - 1 = 0.40           annualised = 1.40 ** (1/3) - 1 = 0.1187
#   5y cumulative = 175/100 - 1 = 0.75           annualised = 1.75 ** (1/5) - 1 = 0.1184
#   max drawdown (last 3 years, i.e. dates after 2023-10-30): running max reaches 150 at the peak,
#                 the low after it is 120 -> 120/150 - 1 = -0.20
RET = {"1y": 175 / 150 - 1, "3y": 0.40, "5y": 0.75}
ANN = {"1y": 175 / 150 - 1, "3y": 1.40 ** (1 / 3) - 1, "5y": 1.75 ** (1 / 5) - 1}
YEARS = {"1y": 1, "3y": 3, "5y": 5}


def five_year_close(anchors=ANCHORS):
    idx = pd.date_range(anchors[0][0], anchors[-1][0], freq="D")
    day0 = pd.Timestamp(anchors[0][0])
    xs = [(pd.Timestamp(d) - day0).days for d, _ in anchors]  # whole days, so no time-unit surprises
    ys = [float(v) for _, v in anchors]
    return pd.Series(np.interp((idx - day0).days, xs, ys), index=idx, name="Close")


def series(values, start="2026-10-01", freq="D"):
    return pd.Series([float(v) for v in values], index=pd.date_range(start, periods=len(values), freq=freq),
                     name="Close")


def empty_close():
    return pd.Series([], index=pd.DatetimeIndex([]), dtype="float64", name="Close")


def etf_with(**info):
    raw = etf_like()
    raw.info = etf_info(**info)
    return raw


def stats_with(**over):
    """etf_stats of the fixture with some values replaced; keeps whatever currency key the builder uses."""
    s = rd.etf_stats(etf_like())
    s.update(over)
    return s


# ---------- E1 etf_stats: cost, size, yield ----------
def test_e1_expense_ratio_from_net_expense_ratio_percent():
    assert rd.etf_stats(etf_like())["expense_ratio"] == pytest.approx(0.0005)  # 0.05 (percent) / 100


def test_e1_expense_ratio_falls_back_to_ops_then_none():
    raw = etf_like()
    del raw.info["netExpenseRatio"]
    assert rd.etf_stats(raw)["expense_ratio"] == pytest.approx(0.0007)  # the fund column, not Category Average
    raw.ops = pd.DataFrame()
    assert rd.etf_stats(raw)["expense_ratio"] is None


def test_e1_fund_size_and_ringgit_figure():
    s = rd.etf_stats(etf_like())
    assert s["fund_size"] == pytest.approx(1.0e11)
    assert s["fx"] == pytest.approx(4.25)
    assert s["fund_size_myr"] == pytest.approx(1.0e11 * 4.25)
    raw = etf_like()
    raw.fx = None
    assert rd.etf_stats(raw)["fund_size_myr"] is None
    my = etf_with(currency="MYR", totalAssets=5.0e8)
    my.fx = 1.0
    sm = rd.etf_stats(my)
    assert sm["fund_size_myr"] == pytest.approx(sm["fund_size"])
    assert sm["fund_size"] == pytest.approx(5.0e8)
    gone = etf_like()
    del gone.info["totalAssets"]
    s = rd.etf_stats(gone)
    assert s["fund_size"] is None and s["fund_size_myr"] is None


def test_e1_yield_from_yield_key_only():
    assert rd.etf_stats(etf_like())["distribution_yield"] == pytest.approx(0.02)
    raw = etf_like()
    del raw.info["yield"]  # dividendYield 2.0 (percent) and trailingAnnualDividendYield 0.0 remain
    assert rd.etf_stats(raw)["distribution_yield"] is None


def test_e1_category_and_family():
    s = rd.etf_stats(etf_like())
    assert s["category"] == "Fake Global Blend"
    assert s["fund_family"] == "FakeFunds"
    assert "legal_type" in s


# ---------- E2 holdings, sectors, assets, country ----------
def test_e2_top_holdings_ten_rows_fractions_in_order():
    th = rd.etf_stats(etf_like())["top_holdings"]
    assert list(th.columns) == ["Symbol", "Name", "Weight"]
    assert len(th) == 10
    assert list(th["Symbol"]) == [f"FK{i}" for i in range(10)]
    assert list(th["Name"]) == [f"Fake Holding {i}" for i in range(10)]
    assert th["Weight"].tolist() == pytest.approx([0.050 - 0.004 * i for i in range(10)])


def test_e2_top_holdings_at_most_ten():
    raw = etf_like()
    big = pd.concat([etf_holdings(), etf_holdings().rename(index=lambda s: s + "X")])
    big.index.name = "Symbol"
    raw.holdings = big
    assert len(rd.etf_stats(raw)["top_holdings"]) == 10


def test_e2_top_holdings_empty_when_absent():
    raw = etf_like()
    raw.holdings = pd.DataFrame()
    th = rd.etf_stats(raw)["top_holdings"]
    assert isinstance(th, pd.DataFrame) and th.empty


def test_e2_sector_mix_sorted_and_worded():
    sm = rd.etf_stats(etf_like())["sector_mix"]
    assert list(sm.columns) == ["Sector", "Weight"]
    assert len(sm) == 11
    w = sm["Weight"].tolist()
    assert w == sorted(w, reverse=True)
    assert sm["Sector"].iloc[0] == "Technology" and w[0] == pytest.approx(0.25)
    assert sm["Sector"].iloc[-1] == "Real estate" and w[-1] == pytest.approx(0.03)
    assert "Consumer cyclical" in set(sm["Sector"])
    assert not any("_" in x for x in sm["Sector"])


def test_e2_sector_label():
    assert rd.sector_label("realestate") == "Real estate"
    assert rd.sector_label("consumer_cyclical") == "Consumer cyclical"
    assert rd.sector_label("technology") == "Technology"
    assert rd.sector_label("healthcare") == "Healthcare"


def test_e2_asset_mix_drops_zero_rows():
    am = rd.etf_stats(etf_like())["asset_mix"]
    assert list(am.columns) == ["Class", "Weight"]
    assert len(am) == 3  # stock, cash, other; bond / preferred / convertible are 0.0
    assert (am["Weight"] > 0).all()
    assert sorted(am["Weight"].tolist()) == pytest.approx([0.01, 0.01, 0.98])


def test_e2_country_mix_is_none():
    assert rd.etf_stats(etf_like())["country_mix"] is None


# ---------- E3 returns ----------
@pytest.mark.parametrize("key", ["1y", "3y", "5y"])
def test_e3_cumulative_return_hand_values(key):
    assert rd.cumulative_return(five_year_close(), YEARS[key]) == pytest.approx(RET[key], abs=1e-9)


def test_e3_cumulative_return_too_short_or_empty():
    full = five_year_close()
    two_years = full[full.index > "2024-10-30"]
    assert rd.cumulative_return(two_years, 3) is None
    assert rd.cumulative_return(two_years, 5) is None
    assert rd.cumulative_return(empty_close(), 1) is None


def test_e3_lookback_uses_last_price_on_or_before():
    # business days; last date Mon 2026-11-02, so 1y back is Sun 2025-11-02 (no row).
    # Fri 2025-10-31 = 80 (on or before), Mon 2025-11-03 = 90 (after). Expected 100/80 - 1 = 0.25.
    idx = pd.bdate_range("2025-06-02", "2026-11-02")
    s = pd.Series(90.0, index=idx, name="Close")
    s[s.index <= "2025-10-31"] = 80.0
    s.iloc[-1] = 100.0
    assert "2025-11-02" not in set(s.index.strftime("%Y-%m-%d"))
    assert rd.cumulative_return(s, 1) == pytest.approx(0.25)


def test_e3_annualised():
    assert rd.annualised(0.21, 2) == pytest.approx(0.10, abs=1e-9)  # 1.21 ** 0.5 = 1.1
    assert rd.annualised(0.37, 1) == pytest.approx(0.37)
    assert rd.annualised(None, 3) is None


def test_e3_stats_returns_and_annual_returns():
    s = rd.etf_stats(etf_like())
    assert set(s["returns"]) == {"1y", "3y", "5y"}
    assert set(s["annual_returns"]) == {"1y", "3y", "5y"}
    for k in ("1y", "3y", "5y"):
        assert s["returns"][k] == pytest.approx(RET[k], abs=1e-9), k
        assert s["annual_returns"][k] == pytest.approx(ANN[k], abs=1e-9), k
        assert s["annual_returns"][k] == pytest.approx(rd.annualised(s["returns"][k], YEARS[k])), k
    assert s["annual_returns"]["1y"] == pytest.approx(s["returns"]["1y"])


def test_e3_stats_returns_none_when_short():
    raw = etf_like()
    full = five_year_close()
    raw.prices = pd.DataFrame({"Close": full[full.index > "2024-10-30"]})
    s = rd.etf_stats(raw)
    assert s["returns"]["1y"] is not None
    assert s["returns"]["3y"] is None and s["returns"]["5y"] is None
    assert s["annual_returns"]["3y"] is None and s["annual_returns"]["5y"] is None
    raw.prices = pd.DataFrame()
    s = rd.etf_stats(raw)
    assert all(s["returns"][k] is None for k in ("1y", "3y", "5y"))


# ---------- E4 volatility, drawdown, history note ----------
def test_e4_volatility_constant_is_zero():
    assert rd.volatility(series([50] * 30)) == pytest.approx(0.0)


def test_e4_volatility_two_steps_hand_value():
    # 100 -> 200 -> 100: log returns +ln2, -ln2; mean 0; sample std (ddof=1) = sqrt(2 * ln2^2 / 1) = ln2 * sqrt(2)
    # annualised: ln2 * sqrt(2) * sqrt(252) = 0.6931 * 1.4142 * 15.875 = 15.56
    assert rd.volatility(series([100, 200, 100])) == pytest.approx(math.log(2) * math.sqrt(2) * math.sqrt(252))


def test_e4_volatility_fewer_than_two_returns_none():
    assert rd.volatility(series([100, 110])) is None  # one return
    assert rd.volatility(series([100])) is None
    assert rd.volatility(empty_close()) is None


def test_e4_volatility_and_drawdown_last_three_years_only():
    # wild swings and a crash until 2022-06-30, then flat 100 for over 4 years: the 3-year window sees only flat
    old = pd.Series([100.0, 300.0, 30.0, 250.0, 100.0],
                    index=pd.to_datetime(["2022-06-26", "2022-06-27", "2022-06-28", "2022-06-29", "2022-06-30"]))
    flat = pd.Series(100.0, index=pd.date_range("2022-07-01", "2026-10-30", freq="D"))
    s = pd.concat([old, flat]).rename("Close")
    assert rd.volatility(s) == pytest.approx(0.0)
    assert rd.max_drawdown(s) == pytest.approx(0.0)


def test_e4_max_drawdown_dip_is_minus_twenty_percent():
    assert rd.max_drawdown(five_year_close()) == pytest.approx(-0.20)


def test_e4_max_drawdown_rising_and_empty():
    assert rd.max_drawdown(series(range(100, 140))) == 0.0
    assert rd.max_drawdown(empty_close()) is None


def test_e4_stats_carry_vol_and_drawdown():
    s = rd.etf_stats(etf_like())
    assert s["max_drawdown_3y"] == pytest.approx(-0.20)
    assert s["volatility_3y"] == pytest.approx(rd.volatility(five_year_close()))
    assert s["volatility_3y"] > 0
    assert not s.get("history_note")


def test_e4_history_note_when_under_three_years():
    raw = etf_like()
    full = five_year_close()
    raw.prices = pd.DataFrame({"Close": full[full.index > "2024-10-30"]})
    note = rd.etf_stats(raw).get("history_note")
    assert note and note.startswith("only ") and note.endswith(" years of prices")
    assert note in rd.analyse(raw).warnings


# ---------- E5 ETF lights ----------
EXP, SIZE = "expense_ratio", "fund_size"
ETF_PHRASES = {
    EXP: {"green": "cheap to hold", "amber": "fair cost", "red": "expensive for an index fund",
          "grey": "expense ratio not reported"},
    SIZE: {"green": "large and liquid", "amber": "mid-sized", "red": "small, closure risk",
           "grey": "fund size not reported"},
}


def test_e5_thresholds_and_reasons_settings():
    assert rd.ETF_THRESHOLDS == {"expense_ratio": (0.002, 0.006), "fund_size": (1e9, 1e8)}
    for item, phrases in ETF_PHRASES.items():
        for colour, phrase in phrases.items():
            assert rd.ETF_REASONS[item][colour] == phrase, (item, colour)


def etf_expected(item, v):
    g, r = rd.ETF_THRESHOLDS[item]
    if g < r:  # lower is better
        return "green" if v < g else ("red" if v > r else "amber")
    return "green" if v > g else ("red" if v < r else "amber")


@pytest.mark.parametrize("item", [EXP, SIZE])
def test_e5_bands_from_thresholds(item):
    g, r = rd.ETF_THRESHOLDS[item]
    lo, hi = min(g, r), max(g, r)
    seen = set()
    for v in (lo / 2, lo, (lo + hi) / 2, hi, hi * 2):
        colour = etf_expected(item, v)
        seen.add(colour)
        light = rd.etf_lights(stats_with(**{item: v}))[item]
        assert light.colour == colour, (item, v)
        assert light.reason.endswith(rd.ETF_REASONS[item][colour]), light.reason
    assert seen == {"green", "amber", "red"}
    assert rd.etf_lights(stats_with(**{item: lo}))[item].colour == "amber"   # boundary
    assert rd.etf_lights(stats_with(**{item: hi}))[item].colour == "amber"   # boundary


@pytest.mark.parametrize("v,colour,shown", [(0.0006, "green", "0.06%"), (0.002, "amber", "0.20%"),
                                            (0.004, "amber", "0.40%"), (0.006, "amber", "0.60%"),
                                            (0.0072, "red", "0.72%")])
def test_e5_expense_cases(v, colour, shown):
    light = rd.etf_lights(stats_with(expense_ratio=v))[EXP]
    assert light.colour == colour
    assert light.reason.startswith(f"Expense ratio {shown}:"), light.reason
    assert light.reason.endswith(ETF_PHRASES[EXP][colour]), light.reason


@pytest.mark.parametrize("v,colour,shown", [(1.01e11, "green", "101.0 bn"), (1e9, "amber", "1.0 bn"),
                                            (5e8, "amber", "500.0 m"), (1e8, "amber", "100.0 m"),
                                            (5e7, "red", "50.0 m")])
def test_e5_size_cases(v, colour, shown):
    light = rd.etf_lights(stats_with(fund_size=v, fund_size_myr=v * 4.25))[SIZE]
    assert light.colour == colour
    assert light.reason.startswith(f"Fund size USD {shown}"), light.reason
    assert light.reason.endswith(ETF_PHRASES[SIZE][colour]), light.reason


def test_e5_grey_when_none():
    lights = rd.etf_lights(stats_with(expense_ratio=None, fund_size=None, fund_size_myr=None))
    assert lights[EXP].colour == "grey" and "expense ratio not reported" in lights[EXP].reason
    assert lights[SIZE].colour == "grey" and "fund size not reported" in lights[SIZE].reason
    assert set(lights) == {EXP, SIZE}


# ---------- E6 ETF overall ----------
def test_e6_overall_is_worst():
    L = rd.Light
    o = rd.etf_overall({EXP: L("green", "cost ok"), SIZE: L("red", "size bad")})
    assert o.colour == "red" and o.reason == "worst: size bad"
    o = rd.etf_overall({EXP: L("amber", "cost meh"), SIZE: L("green", "size ok")})
    assert o.colour == "amber" and o.reason == "worst: cost meh"


def test_e6_one_grey_ignored():
    L = rd.Light
    o = rd.etf_overall({EXP: L("grey", "expense ratio not reported"), SIZE: L("green", "size ok")})
    assert o.colour == "green" and o.reason == "worst: size ok"


def test_e6_both_grey():
    L = rd.Light
    o = rd.etf_overall({EXP: L("grey", "a"), SIZE: L("grey", "b")})
    assert o.colour == "grey" and o.reason == "no cost or size data"


# ---------- E7 analyse ----------
def test_e7_analyse_etf():
    raw = etf_like()
    r = rd.analyse(raw)
    assert r.kind == "ETF"
    assert isinstance(r.etf, dict) and r.etf
    expected = rd.etf_overall(rd.etf_lights(rd.etf_stats(raw)))
    assert r.overall == expected
    assert r.overall.colour == "green"  # 0.05 % cost, 100 bn size
    assert not any("no full fiscal year" in w for w in r.warnings)
    assert not any("Yahoo unreachable" in w for w in r.warnings)


def test_e7_analyse_stock_unchanged():
    r = rd.analyse(gamuda_like())
    assert r.etf is None
    assert r.overall == rd.Light("amber", "worst: Debt / Equity 0.60 (TTM): moderate borrowing against equity")


# ---------- E8 cache ----------
def assert_stats_equal(a, b):
    assert set(a) == set(b)
    for k in a:
        x, y = a[k], b[k]
        if isinstance(x, pd.DataFrame):
            pd.testing.assert_frame_equal(x.reset_index(drop=True), y.reset_index(drop=True), check_dtype=False)
        elif isinstance(x, dict):
            assert set(x) == set(y), k
            for kk in x:
                assert (x[kk] is None and y[kk] is None) or x[kk] == pytest.approx(y[kk]), (k, kk)
        elif isinstance(x, float):
            assert x == pytest.approx(y), k
        else:
            assert x == y, k


def test_e8_cache_round_trip_etf_fields(tmp_path):
    raw = etf_like()
    rd.save_cache(raw, cache_dir=tmp_path)
    back = rd.load_cache("VT", cache_dir=tmp_path)
    assert back is not None
    assert back.fx == pytest.approx(4.25)
    assert not back.holdings.empty and back.sectors and back.assets and not back.prices.empty
    assert_stats_equal(rd.etf_stats(raw), rd.etf_stats(back))


def test_e8_old_cache_without_etf_keys_loads_empty(tmp_path):
    rd.save_cache(etf_like(), cache_dir=tmp_path)
    path = tmp_path / "VT.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    for k in ETF_FIELDS:
        doc.pop(k, None)  # the WP-3.1 file format
    path.write_text(json.dumps(doc), encoding="utf-8")
    back = rd.load_cache("VT", cache_dir=tmp_path)
    assert back is not None
    assert isinstance(back.holdings, pd.DataFrame) and back.holdings.empty
    assert back.sectors == {} and back.assets == {}
    assert isinstance(back.ops, pd.DataFrame) and back.ops.empty
    assert isinstance(back.prices, pd.DataFrame) and back.prices.empty
    assert back.fx is None
    rd.analyse(back)  # does not raise


# ---------- E9 fetch_raw and fetch_fx with a fake yfinance ----------
def tz_history(close, tz="America/New_York"):
    idx = close.index.tz_localize(tz)
    n = len(close)
    return pd.DataFrame({"Open": close.values, "High": close.values, "Low": close.values, "Close": close.values,
                         "Volume": [1000] * n, "Dividends": [0.0] * n, "Stock Splits": [0.0] * n,
                         "Capital Gains": [0.0] * n}, index=idx)


class FakeFunds:
    def __init__(self, none=False):
        self.top_holdings = None if none else etf_holdings()
        self.sector_weightings = None if none else dict(ETF_SECTORS)
        self.asset_classes = None if none else dict(ETF_ASSETS)
        self.fund_operations = None if none else etf_ops()
        self.fund_overview = None if none else {"categoryName": "Fake Global Blend", "family": "FakeFunds",
                                                "legalType": "Exchange Traded Fund"}


def fake_yf(info, funds="ok", fx_close=(4.10, 4.20, 4.25)):
    """A Ticker class that records every code built, every history call and every funds_data access."""
    log = {"codes": [], "funds_touched": 0, "history": []}
    e = pd.DataFrame()

    class FakeTicker:
        def __init__(self, code):
            log["codes"].append(code)
            self.code = code
            self.info = dict(info)
            self.income_stmt = self.balance_sheet = self.cashflow = e
            self.quarterly_income_stmt = self.quarterly_balance_sheet = self.quarterly_cashflow = e
            self.recommendations = e

        @property
        def funds_data(self):
            log["funds_touched"] += 1
            if funds == "raise":
                raise RuntimeError("funds_data broke (fake)")
            return FakeFunds(none=(funds == "none"))

        def history(self, period=None, **kw):
            log["history"].append((self.code, period))
            if self.code.endswith("MYR=X"):
                return tz_history(series(fx_close), tz="Europe/London")
            return tz_history(five_year_close())

    return FakeTicker, log


def test_e9_fetch_raw_etf_fills_fields(monkeypatch):
    yf = pytest.importorskip("yfinance")
    cls, log = fake_yf(etf_info())
    monkeypatch.setattr(yf, "Ticker", cls)
    raw = rd.fetch_raw("VT", now=T0)
    assert list(raw.holdings.columns) == ["Name", "Holding Percent"] and len(raw.holdings) == 10
    assert raw.sectors == ETF_SECTORS and raw.assets == ETF_ASSETS
    assert not raw.ops.empty
    assert list(raw.prices.columns) == ["Close"]
    assert raw.prices.index.tz is None
    assert len(raw.prices) == len(five_year_close())
    assert ("VT", "6y") in log["history"]  # spec v1.2: six years so the 5y lookback has a price before it
    assert raw.fx == pytest.approx(4.25)
    assert "USDMYR=X" in log["codes"]
    assert rd.etf_stats(raw)["max_drawdown_3y"] == pytest.approx(-0.20)


def test_e9_fetch_raw_funds_data_raises_gives_empties(monkeypatch):
    yf = pytest.importorskip("yfinance")
    cls, log = fake_yf(etf_info(), funds="raise")
    monkeypatch.setattr(yf, "Ticker", cls)
    raw = rd.fetch_raw("VT", now=T0)
    assert log["funds_touched"] >= 1
    assert raw.holdings.empty and raw.ops.empty
    assert raw.sectors == {} and raw.assets == {}


def test_e9_fetch_raw_non_frames_give_empties(monkeypatch):
    yf = pytest.importorskip("yfinance")
    cls, _ = fake_yf(etf_info(), funds="none")
    monkeypatch.setattr(yf, "Ticker", cls)
    raw = rd.fetch_raw("VT", now=T0)
    assert isinstance(raw.holdings, pd.DataFrame) and raw.holdings.empty
    assert isinstance(raw.ops, pd.DataFrame) and raw.ops.empty
    assert raw.sectors == {} and raw.assets == {}


def test_e9_fetch_raw_stock_never_touches_funds_data(monkeypatch):
    yf = pytest.importorskip("yfinance")
    cls, log = fake_yf(dict(gamuda_like().info))
    monkeypatch.setattr(yf, "Ticker", cls)
    raw = rd.fetch_raw("1234.KL", now=T0)
    assert log["funds_touched"] == 0
    assert raw.holdings.empty and raw.ops.empty
    # WP-3.2 spec v1.1 S10 amends this test: a stock now gets prices and fx too (rule 2)
    assert not raw.prices.empty and list(raw.prices.columns) == ["Close"]
    assert raw.sectors == {} and raw.assets == {}
    assert raw.fx == 1.0  # MYR stock: fetch_fx("MYR") is 1.0 without a Yahoo call


def test_e9_fetch_fx_myr_no_ticker(monkeypatch):
    yf = pytest.importorskip("yfinance")

    def boom(*a, **k):
        raise AssertionError("ticker built for MYR")
    monkeypatch.setattr(yf, "Ticker", boom)
    assert rd.fetch_fx("MYR") == 1.0
    assert rd.fetch_fx("MYR", ticker_cls=boom) == 1.0


def test_e9_fetch_fx_usd_last_close():
    cls, log = fake_yf({})
    assert rd.fetch_fx("USD", ticker_cls=cls) == pytest.approx(4.25)
    assert log["codes"] == ["USDMYR=X"]
    assert log["history"] == [("USDMYR=X", "5d")]


def test_e9_fetch_fx_default_uses_yfinance_ticker(monkeypatch):
    yf = pytest.importorskip("yfinance")
    cls, log = fake_yf({}, fx_close=(4.30, 4.40))
    monkeypatch.setattr(yf, "Ticker", cls)
    assert rd.fetch_fx("USD") == pytest.approx(4.40)
    assert log["codes"] == ["USDMYR=X"]


def test_e9_fetch_fx_failures_none():
    class Raising:
        def __init__(self, code):
            raise ConnectionError("Yahoo down (fake)")
    assert rd.fetch_fx("USD", ticker_cls=Raising) is None

    class Empty:
        def __init__(self, code):
            pass

        def history(self, **kw):
            return pd.DataFrame()
    assert rd.fetch_fx("USD", ticker_cls=Empty) is None


def test_e9_size_light_uses_own_currency_not_ringgit():
    raw = etf_with(totalAssets=5.0e7)
    raw.fx = 4.25
    s = rd.etf_stats(raw)
    assert s["fund_size_myr"] == pytest.approx(2.125e8)  # would be amber if judged in Ringgit
    light = rd.etf_lights(s)[SIZE]
    assert light.colour == "red"
    assert light.reason.startswith("Fund size USD 50.0 m"), light.reason


# ---------- Round 1b (spec v1.2): 7-day allowance on the lookback, 6y history ----------
def late_start_series(days_late):
    """Business-day-free calendar series ending 2026-10-30. 1y lookback date = 2025-10-30.
    First date = lookback + days_late, first price 80, then 90 up to the last day, last 100."""
    first = pd.Timestamp("2025-10-30") + pd.Timedelta(days=days_late)
    s = pd.Series(90.0, index=pd.date_range(first, "2026-10-30", freq="D"), name="Close")
    s.iloc[0] = 80.0
    s.iloc[-1] = 100.0
    return s


def test_r1b_first_price_three_days_late_is_used():
    # first date 2025-11-02, 3 days after the lookback: allowed, uses the first price 80 -> 100/80 - 1 = 0.25
    assert rd.cumulative_return(late_start_series(3), 1) == pytest.approx(0.25)


def test_r1b_first_price_seven_days_late_still_allowed():
    assert rd.cumulative_return(late_start_series(7), 1) == pytest.approx(0.25)  # boundary: up to 7 days


def test_r1b_first_price_ten_days_late_is_none():
    assert rd.cumulative_return(late_start_series(10), 1) is None


def test_r1b_stats_5y_from_six_year_style_start():
    # real yfinance shape: 5y back from 2026-10-30 is Sat 2021-10-30, first row Mon 2021-11-01 (2 days late)
    raw = etf_like()
    full = five_year_close()
    raw.prices = pd.DataFrame({"Close": full[full.index >= "2021-11-01"]})
    assert rd.etf_stats(raw)["returns"]["5y"] == pytest.approx(0.75)  # first price 100 (plateau) -> 175/100 - 1


# ---------- Mutation r1b: tests for the r1 survivors (made-up numbers, no network) ----------
def test_r1c_lookback_price_exactly_on_the_date_is_used():
    # a different price every day; the 1y lookback date 2025-10-30 has its own price
    idx = pd.date_range("2025-10-01", "2026-10-30", freq="D")
    s = pd.Series([100.0 + i for i in range(len(idx))], index=idx)
    expected = s.iloc[-1] / s[pd.Timestamp("2025-10-30")] - 1  # not the 2025-10-29 price
    assert rd.cumulative_return(s, 1) == pytest.approx(expected)


def test_r1c_fetch_raw_wrong_types_give_empties(monkeypatch):
    yf = pytest.importorskip("yfinance")
    from types import SimpleNamespace
    base, _ = fake_yf(etf_info())

    class OddTicker(base):
        @property
        def funds_data(self):  # not None, but not a frame / dict either
            return SimpleNamespace(top_holdings=[1, 2], sector_weightings="x", asset_classes=[("a", 1)],
                                   fund_operations={"a": 1}, fund_overview=[])

    monkeypatch.setattr(yf, "Ticker", OddTicker)
    raw = rd.fetch_raw("VT", now=T0)
    assert isinstance(raw.holdings, pd.DataFrame) and raw.holdings.empty
    assert isinstance(raw.ops, pd.DataFrame) and raw.ops.empty
    assert raw.sectors == {} and raw.assets == {}


def test_r1c_cache_prices_index_stays_dates(tmp_path):
    raw = etf_like()
    rd.save_cache(raw, cache_dir=tmp_path)
    back = rd.load_cache("VT", cache_dir=tmp_path)
    assert isinstance(back.prices.index, pd.DatetimeIndex)
    assert back.prices.index[0] == raw.prices.index[0]


def test_r1c_cache_keeps_number_like_symbols_and_names(tmp_path):
    # Yahoo codes such as "005935" (and a name that is only the code) must not come back as numbers
    raw = etf_like()
    raw.holdings = pd.DataFrame({"Name": ["005935", "00939"], "Holding Percent": [0.05, 0.04]},
                                index=pd.Index(["005935", "00939"], name="Symbol"))
    rd.save_cache(raw, cache_dir=tmp_path)
    back = rd.load_cache("VT", cache_dir=tmp_path)
    top = rd.etf_stats(back)["top_holdings"]
    assert list(top["Symbol"]) == ["005935", "00939"]
    assert list(top["Name"]) == ["005935", "00939"]


def test_r1c_chip_codes_keep_sheet_order_not_sorted():
    holdings = pd.DataFrame({"Code": ["US.ZZZ", "MY.1234", "US.FAKE"]})
    assert rd.chip_codes(holdings) == ["ZZZ", "1234.KL", "FAKE"]


def test_r1c_short_money_rm_for_myr():
    assert rd.short_money("MYR", 4.3e11) == "RM 430.0 bn"
    assert rd.short_money("USD", 1.012e11) == "USD 101.2 bn"
    assert rd.short_money("USD", 5e8) == "USD 500.0 m"
    assert rd.short_money("USD", None) == "n/a"


def test_r1c_cli_prints_etf_block(capsys):
    rd._print(rd.analyse(etf_like()))
    out = capsys.readouterr().out
    assert "expense ratio 0.05%" in out
    assert "fund size USD 100.0 bn  = RM 425.0 bn" in out
    assert "country mix: not provided by Yahoo" in out


# ---------- Review r1 F1, F2 and the history_note nit (spec v1.3 rules 3 and 5) ----------
def rising_with_bad_price(bad):
    """5-year calendar-day rising series (100 -> ~282), one Close replaced by `bad` on 2025-06-02,
    inside the last 3 years. Returns (series with the bad price, the same series without that row)."""
    idx = pd.date_range("2021-10-01", "2026-10-30", freq="D")
    s = pd.Series(100.0 + 0.1 * np.arange(len(idx)), index=idx, name="Close")
    s.loc["2025-06-02"] = bad
    return s, s.drop(pd.Timestamp("2025-06-02"))


@pytest.mark.parametrize("bad", [0.0, -5.0])
def test_r2_f1_bad_price_dropped_from_volatility(bad):
    s, clean = rising_with_bad_price(bad)
    v = rd.volatility(s)  # today: math domain error on log(0) / log(negative)
    assert v is not None and math.isfinite(v)
    assert v == pytest.approx(rd.volatility(clean))


@pytest.mark.parametrize("bad", [0.0, -5.0])
def test_r2_f1_bad_price_not_a_false_drawdown(bad):
    s, _ = rising_with_bad_price(bad)
    assert rd.max_drawdown(s) == 0.0  # the series only rises once the bad row is dropped; not -1.0


def test_r2_f1_bad_price_in_stats_does_not_raise():
    raw = etf_like()
    s = five_year_close()
    s.loc["2025-06-02"] = 0.0
    raw.prices = pd.DataFrame({"Close": s})
    st = rd.etf_stats(raw)
    assert st["max_drawdown_3y"] == pytest.approx(-0.20)
    assert st["volatility_3y"] is not None and math.isfinite(st["volatility_3y"])


def test_r2_f1_repeated_dates_keep_the_last():
    # constant series with one repeated date: still 0.0
    idx = pd.DatetimeIndex(["2026-10-01", "2026-10-02", "2026-10-02", "2026-10-03", "2026-10-04"])
    assert rd.volatility(pd.Series(50.0, index=idx)) == pytest.approx(0.0)
    # 100, (150 then 200 on the same day), 400: keep-last gives 100, 200, 400 -> log returns ln2, ln2 -> 0.0.
    # Keeping both rows gives ln1.5, ln(4/3), ln2, which are not equal, so the vol would be above 0.
    dup = pd.DatetimeIndex(["2026-10-01", "2026-10-02", "2026-10-02", "2026-10-03"])
    assert rd.volatility(pd.Series([100.0, 150.0, 200.0, 400.0], index=dup)) == pytest.approx(0.0)
    # 100, (50 then 100 on the same day), 100: keep-last never falls -> 0.0, not -0.5
    assert rd.max_drawdown(pd.Series([100.0, 50.0, 100.0, 100.0], index=dup)) == 0.0


def etf_empty_prices():
    raw = etf_like()
    raw.prices = pd.DataFrame()  # Yahoo partial failure: info back, history empty
    raw.holdings, raw.sectors, raw.assets, raw.ops = pd.DataFrame(), {}, {}, pd.DataFrame()
    return raw


def test_r2_f2_etf_empty_prices_serve_stale_and_keep_cache(tmp_path):
    first = rd.research("VT", now=T0, fetcher=FakeFetcher(raw_fn=etf_like), cache_dir=tmp_path, ttl=3600)
    assert first.etf["returns"]["1y"] == pytest.approx(RET["1y"])
    silent = FakeFetcher(raw_fn=etf_empty_prices)
    r = rd.research("VT", now=T0 + timedelta(hours=2), fetcher=silent, cache_dir=tmp_path, ttl=3600)
    assert silent.calls == 1
    assert r.stale is True
    assert r.etf["returns"]["1y"] == pytest.approx(RET["1y"])
    assert r.etf["max_drawdown_3y"] == pytest.approx(-0.20)
    back = rd.load_cache("VT", cache_dir=tmp_path)
    assert back is not None and not back.prices.empty  # not overwritten
    assert len(back.prices) == len(five_year_close())


def test_r2_nit_history_note_uses_the_seven_day_allowance():
    # 3y lookback from 2026-10-30 is 2023-10-30; first price 2023-11-02 (3 days late): the 3y return is shown,
    # so there must be no "only ... years of prices" note
    raw = etf_like()
    full = five_year_close()
    raw.prices = pd.DataFrame({"Close": full[full.index >= "2023-11-02"]})
    st = rd.etf_stats(raw)
    assert st["returns"]["3y"] == pytest.approx(0.40)
    assert not st.get("history_note")


# ---------- Mutation r2b: tests for the r2 survivors (made-up numbers, no network) ----------
def daily_rising_with_dip():
    """Calendar days 2025-10-01 .. 2026-10-30, a different price each day, one fall in the middle."""
    idx = pd.date_range("2025-10-01", "2026-10-30", freq="D")
    s = pd.Series([100.0 + i for i in range(len(idx))], index=idx)
    s.iloc[200:210] = 150.0  # a dip below the running peak
    return s


def test_r2b_nan_rows_are_dropped():
    clean = daily_rising_with_dip()
    s = clean.copy()
    s.loc[pd.Timestamp("2026-10-31")] = NAN  # Yahoo's half-filled last row
    s.loc[pd.Timestamp("2026-03-01")] = NAN  # and one in the middle
    clean = clean.drop(pd.Timestamp("2026-03-01"))
    assert rd.cumulative_return(s, 1) == pytest.approx(rd.cumulative_return(clean, 1))
    assert rd.max_drawdown(s) == pytest.approx(rd.max_drawdown(clean))
    assert rd.volatility(s) == pytest.approx(rd.volatility(clean))


def test_r2b_unsorted_dates_give_the_same_figures():
    s = daily_rising_with_dip()
    shuffled = s.sample(frac=1.0, random_state=0)
    assert not shuffled.index.is_monotonic_increasing
    assert rd.cumulative_return(shuffled, 1) == pytest.approx(rd.cumulative_return(s, 1))
    assert rd.volatility(shuffled) == pytest.approx(rd.volatility(s))
    assert rd.max_drawdown(shuffled) == pytest.approx(rd.max_drawdown(s))


def test_r2b_etf_stale_branch_not_used_when_saved_copy_has_no_prices(tmp_path):
    # the saved copy already lacks prices: a new fetch (also without prices) is served fresh and saved
    first = FakeFetcher(raw_fn=etf_empty_prices)
    rd.research("VT", now=T0, fetcher=first, cache_dir=tmp_path, ttl=3600)
    later = T0 + timedelta(hours=2)
    again = FakeFetcher(raw_fn=etf_empty_prices)
    again.fetched_at = later
    r = rd.research("VT", now=later, fetcher=again, cache_dir=tmp_path, ttl=3600)
    assert again.calls == 1
    assert r.stale is False
    assert rd.load_cache("VT", cache_dir=tmp_path).fetched_at == later  # cache rewritten


# ---------- Round 3 (spec v1.4 rules 11, 13): P3 etf_verdict, P4 research(force=True) ----------
def test_r3_p3_verdict_on_fixture():
    r = rd.analyse(etf_like())  # 0.05 % cost green, 100 bn size green
    assert rd.etf_verdict(r.etf) == "Cheap to hold; large and liquid"


def test_r3_p3_verdict_one_grey_cost():
    raw = etf_like()
    del raw.info["netExpenseRatio"]
    raw.ops = pd.DataFrame()  # no fallback either -> expense light grey
    r = rd.analyse(raw)
    assert rd.etf_verdict(r.etf) == "Cost not reported; large and liquid"


def test_r3_p3_verdict_one_grey_size():
    raw = etf_like()
    del raw.info["totalAssets"]
    assert rd.etf_verdict(rd.analyse(raw).etf) == "Cheap to hold; size not reported"


def test_r3_p3_verdict_red_and_amber_tails_from_etf_reasons():
    raw = etf_with(netExpenseRatio=0.72, totalAssets=5.0e8)  # 0.72 % red, 500 m amber
    expect = rd.ETF_REASONS["expense_ratio"]["red"] + "; " + rd.ETF_REASONS["fund_size"]["amber"]
    assert rd.etf_verdict(rd.analyse(raw).etf) == expect[0].upper() + expect[1:]
    assert rd.etf_verdict(rd.analyse(raw).etf) == "Expensive for an index fund; mid-sized"


def test_r3_p4_force_skips_fresh_cache_and_saves(tmp_path):
    f = FakeFetcher()
    rd.research("5398.KL", now=T0, fetcher=f, cache_dir=tmp_path, ttl=3600)
    soon = T0 + timedelta(minutes=10)  # cache still fresh
    f.fetched_at = soon
    r = rd.research("5398.KL", now=soon, fetcher=f, cache_dir=tmp_path, ttl=3600, force=True)
    assert f.calls == 2
    assert r.stale is False
    saved = json.loads((tmp_path / "5398.KL.json").read_text(encoding="utf-8"))
    assert saved["fetched_at"].startswith(soon.isoformat()[:16])


def test_r3_p4_force_false_keeps_cache(tmp_path):
    f = FakeFetcher()
    rd.research("5398.KL", now=T0, fetcher=f, cache_dir=tmp_path, ttl=3600)
    rd.research("5398.KL", now=T0 + timedelta(minutes=10), fetcher=f, cache_dir=tmp_path, ttl=3600, force=False)
    assert f.calls == 1


def test_r3_p4_force_with_failing_fetcher_serves_stale(tmp_path):
    rd.research("5398.KL", now=T0, fetcher=FakeFetcher(), cache_dir=tmp_path, ttl=3600)
    down = FakeFetcher(fail=True)
    r = rd.research("5398.KL", now=T0 + timedelta(minutes=10), fetcher=down, cache_dir=tmp_path, ttl=3600,
                    force=True)
    assert down.calls == 1
    assert r.stale is True and r.periods[0] == "TTM"


def test_r3_p4_force_keeps_etf_stale_copy_protection(tmp_path):
    rd.research("VT", now=T0, fetcher=FakeFetcher(raw_fn=etf_like), cache_dir=tmp_path, ttl=3600)
    silent = FakeFetcher(raw_fn=etf_empty_prices)
    r = rd.research("VT", now=T0 + timedelta(minutes=10), fetcher=silent, cache_dir=tmp_path, ttl=3600,
                    force=True)
    assert silent.calls == 1
    assert r.stale is True and r.etf["returns"]["1y"] == pytest.approx(RET["1y"])
    assert not rd.load_cache("VT", cache_dir=tmp_path).prices.empty


def test_r3b_top_holdings_pct_is_weight_times_100():
    st = rd.etf_stats(etf_like())
    pct, top = st["top_holdings_pct"], st["top_holdings"]
    assert list(pct.columns) == ["Name", "Symbol", "Weight %"]
    assert list(pct["Symbol"]) == list(top["Symbol"]) and list(pct["Name"]) == list(top["Name"])
    assert list(pct["Weight %"]) == pytest.approx(list(top["Weight"] * 100))
    assert pct["Weight %"].iloc[0] == pytest.approx(5.0)  # 0.050 in the fixture


# ---------- Round 4 (spec v1.5 rule 14, review r3 F1 and verdict nit) ----------
def names_only_holdings():
    """Holdings with no weights: Name column only (Yahoo sometimes omits Holding Percent)."""
    df = pd.DataFrame({"Name": [f"Fake Holding {i}" for i in range(3)]}, index=["FK0", "FK1", "FK2"])
    df.index.name = "Symbol"
    return df


def test_r4_top_weight_max_pct_on_fixture():
    assert rd.etf_stats(etf_like())["top_weight_max_pct"] == pytest.approx(5.0)  # largest weight 0.050 x 100


def test_r4_top_weight_max_pct_none_without_weights():
    raw = etf_like()
    raw.holdings = names_only_holdings()
    assert rd.etf_stats(raw)["top_weight_max_pct"] is None


def test_r4_verdict_both_red_joined_with_semicolon():
    raw = etf_with(netExpenseRatio=0.72, totalAssets=5.0e7)  # 0.72 % red, 50 m red
    assert rd.etf_verdict(rd.analyse(raw).etf) == "Expensive for an index fund; small, closure risk"


# ---------- WP-3.2 stock view (spec v1.1, S1-S10). Made-up numbers only. ----------
# New names (rd.price_stats, rd.company_stats, ...) are reached through the module inside each test,
# never imported at module level, so collection never breaks before the build.
from datetime import date, timezone  # noqa: E402

PRICE_KEYS = ("returns", "annual_returns", "volatility_3y", "max_drawdown_3y", "history_note")

# Six years of daily Close for a stock: the ETF anchors divided by 40, plus one earlier anchor so the
# series starts in 2020 (first price year 2020, before the dividend window 2021..2026). It only rises
# from 2020-11-02 (2.0) to 2021-10-01 (2.5), so the 3-year figures equal the ETF ones:
#   last 2026-10-30 Close 175/40 = 4.375; 1y back 150/40; 3y back 125/40; 5y back 100/40 = 2.5
#   returns 1y 175/150-1, 3y 0.40, 5y 0.75 (ratios unchanged by the /40); drawdown 120/150-1 = -0.20
STOCK_ANCHORS = [("2020-11-02", 80)] + list(ANCHORS)
STOCK_ANCHORS = [(d, v / 40) for d, v in STOCK_ANCHORS]

# Dividends per share (MYR), ex-dates. Calendar-year sums for the window 2021..2026 (fetched 2026-10-31):
#   2020: 0.10 (outside the window, dropped)
#   2021: 0.03 + 0.04 (31 Dec)          = 0.07, 2 payments
#   2022: 0.05 (1 Jan) + 0.06           = 0.11, 2
#   2023: none                          = 0.00, 0   (skipped year stays visible)
#   2024: 0.02 + 0.03                   = 0.05, 2
#   2025: 0.04 + 0.04                   = 0.08, 2
#   2026 so far: 0.05                   = 0.05, 1
STOCK_DIVS = [("2020-12-01", 0.10), ("2021-06-15", 0.03), ("2021-12-31", 0.04), ("2022-01-01", 0.05),
              ("2022-07-15", 0.06), ("2024-03-10", 0.02), ("2024-09-10", 0.03), ("2025-03-10", 0.04),
              ("2025-09-10", 0.04), ("2026-03-10", 0.05)]
DIV_TABLE = [("2026 so far", 0.05, 1), ("2025", 0.08, 2), ("2024", 0.05, 2), ("2023", 0.0, 0),
             ("2022", 0.11, 2), ("2021", 0.07, 2)]

# Rule 4 info keys (5398.KL-like: fullTimeEmployees absent). currentPrice 5.0 comes from info_eq.
STOCK_EXTRA = {"longBusinessSummary": "Fake Co builds made-up roads and railways.",
               "website": "https://example.com", "fiftyTwoWeekLow": 4.0, "fiftyTwoWeekHigh": 6.0,
               "heldPercentInsiders": 0.10, "heldPercentInstitutions": 0.55, "payoutRatio": 0.40,
               "marketCap": 2.98e10, "exchangeTimezoneName": "Asia/Kuala_Lumpur",
               "nextEarningsDate": "2026-12-09"}


def stock_close():
    return five_year_close(STOCK_ANCHORS)


def divs_frame(rows=STOCK_DIVS):
    """Raw.dividends shape (rule 2): one column Dividends, non-zero rows only, timezone-free dates."""
    idx = pd.DatetimeIndex(pd.to_datetime([d for d, _ in rows]))
    return pd.DataFrame({"Dividends": [float(v) for _, v in rows]}, index=idx)


def no_divs():
    return pd.DataFrame({"Dividends": pd.Series([], dtype="float64")}, index=pd.DatetimeIndex([]))


def _extend(raw, info, prices, dividends, fx):
    raw.info.update(STOCK_EXTRA)
    for k, v in info.items():
        if v is ABSENT:
            raw.info.pop(k, None)
        else:
            raw.info[k] = v
    raw.prices = pd.DataFrame({"Close": stock_close()}) if prices else pd.DataFrame()
    raw.dividends = divs_frame() if dividends else no_divs()
    raw.fx = fx
    return raw


def gamuda_stock(prices=True, dividends=True, fx=1.0, **info):
    """gamuda_like() plus the WP-3.2 parts; info=ABSENT drops a key. Set after construction so the
    fixture builds before Raw has a dividends field."""
    return _extend(gamuda_like(), info, prices, dividends, fx)


def aapl_stock(prices=True, dividends=True, fx=4.25, **info):
    """apple_like() (currency USD) plus the WP-3.2 parts; market cap 5.03e12 USD, fx 4.25."""
    base = {"marketCap": 5.03e12, "exchangeTimezoneName": "America/New_York", "fullTimeEmployees": 1000}
    base.update(info)
    return _extend(apple_like(), base, prices, dividends, fx)


# ---------- S1 price_stats ----------
def test_s1_price_stats_equals_etf_stats_keys():
    raw = etf_like()
    ps = rd.price_stats(raw.prices["Close"])
    es = rd.etf_stats(raw)
    assert set(ps) == set(PRICE_KEYS)
    for k in PRICE_KEYS:
        if isinstance(es[k], dict):
            assert set(ps[k]) == set(es[k]), k
            for kk in es[k]:
                assert ps[k][kk] == pytest.approx(es[k][kk]), (k, kk)
        elif isinstance(es[k], float):
            assert ps[k] == pytest.approx(es[k]), k
        else:
            assert ps[k] == es[k], k
    assert ps["returns"]["5y"] == pytest.approx(0.75)  # 175 / 100 - 1
    assert ps["max_drawdown_3y"] == pytest.approx(-0.20)  # 120 / 150 - 1


def test_s1_price_stats_empty_close():
    ps = rd.price_stats(empty_close())
    assert ps["history_note"] == "no price history from Yahoo"
    assert ps["returns"] == {"1y": None, "3y": None, "5y": None}
    assert ps["volatility_3y"] is None and ps["max_drawdown_3y"] is None


# ---------- S2 range_position ----------
def test_s2_range_position_middle_and_clipped():
    assert rd.range_position(4.0, 3.0, 5.0) == pytest.approx(0.5)  # (4 - 3) / (5 - 3)
    assert rd.range_position(2.0, 3.0, 5.0) == 0.0  # below the low -> clipped to 0
    assert rd.range_position(6.0, 3.0, 5.0) == 1.0  # above the high -> clipped to 1


def test_s2_range_position_none_cases():
    assert rd.range_position(4.0, 5.0, 5.0) is None  # high == low
    assert rd.range_position(4.0, 6.0, 5.0) is None  # high < low
    assert rd.range_position(None, 3.0, 5.0) is None
    assert rd.range_position(4.0, None, 5.0) is None
    assert rd.range_position(4.0, 3.0, None) is None


# ---------- S3 company_stats ----------
def test_s3_company_passes_through_text_range_and_ownership():
    c = rd.company_stats(gamuda_stock())
    assert c["summary"] == "Fake Co builds made-up roads and railways."
    assert c["website"] == "https://example.com"
    assert c["employees"] is None  # key absent, as for 5398.KL (measure-2)
    assert c["range_low"] == 4.0 and c["range_high"] == 6.0
    assert c["insiders"] == pytest.approx(0.10)  # fractions, passed through, no / 100
    assert c["institutions"] == pytest.approx(0.55)
    assert c["payout_ratio"] == pytest.approx(0.40)


def test_s3_company_summary_website_none_when_absent():
    c = rd.company_stats(gamuda_stock(longBusinessSummary=ABSENT, website=ABSENT, payoutRatio=ABSENT))
    assert c["summary"] is None and c["website"] is None and c["payout_ratio"] is None
    assert rd.company_stats(aapl_stock())["employees"] == 1000


def test_s3_range_position_uses_info_price_not_last_close():
    c = rd.company_stats(gamuda_stock())
    # info currentPrice 5.0: (5.0 - 4.0) / (6.0 - 4.0) = 0.5; the last Close 4.375 would give 0.1875
    assert c["range_position"] == pytest.approx(0.5)
    c = rd.company_stats(gamuda_stock(currentPrice=ABSENT, regularMarketPrice=4.5))
    assert c["range_position"] == pytest.approx(0.25)  # (4.5 - 4.0) / 2.0
    c = rd.company_stats(gamuda_stock(currentPrice=ABSENT))
    assert c["range_position"] is None  # no info price; never falls back to the history Close


def test_s3_market_cap_in_ringgit():
    c = rd.company_stats(gamuda_stock())
    assert c["market_cap"] == pytest.approx(2.98e10) and c["fx"] == 1.0
    assert c["market_cap_myr"] == pytest.approx(2.98e10)  # 2.98e10 x 1.0
    c = rd.company_stats(aapl_stock())
    assert c["market_cap_myr"] == pytest.approx(2.13775e13)  # 5.03e12 x 4.25
    assert rd.company_stats(aapl_stock(fx=None))["market_cap_myr"] is None
    assert rd.company_stats(gamuda_stock(marketCap=ABSENT))["market_cap_myr"] is None


@pytest.mark.parametrize("value, expected", [
    ("2026-12-09", date(2026, 12, 9)),   # after fetched_at 2026-10-31
    ("2026-10-31", date(2026, 10, 31)),  # the fetch day itself is not "earlier"
    ("2026-10-01", None),                # before fetched_at: a past report, not "next"
    ("soon", None),                      # garbage
    (None, None),
    (ABSENT, None),
])
def test_s3_next_earnings(value, expected):
    c = rd.company_stats(gamuda_stock(nextEarningsDate=value))
    assert c["next_earnings"] == expected
    if expected is not None:
        assert type(c["next_earnings"]) is date


def test_s3_price_chart_last_five_years_sorted():
    c = rd.company_stats(gamuda_stock())
    pc = c["price_chart"]
    assert list(pc.columns) == ["Date", "Close"]
    # dates after 2026-10-30 minus 5 years = 2021-10-30, so 2021-10-31 .. 2026-10-30:
    # 2021-10-31 -> 2026-10-31 is 5 x 365 + 1 (29 Feb 2024) = 1826 days, so 1826 daily rows to 2026-10-30
    assert pd.Timestamp(pc["Date"].iloc[0]) == pd.Timestamp("2021-10-31")
    assert pd.Timestamp(pc["Date"].iloc[-1]) == pd.Timestamp("2026-10-30")
    assert len(pc) == 1826
    assert pd.Series(pd.to_datetime(pc["Date"])).is_monotonic_increasing
    assert pc["Close"].iloc[-1] == pytest.approx(4.375)  # 175 / 40


def test_s3_price_chart_cleaned_and_unsorted_input():
    s = stock_close()
    s.iloc[-10] = 0.0  # Yahoo's 0.0 for a thin day: dropped, as in _clean
    pc = rd.price_chart(s.iloc[::-1])
    assert len(pc) == 1825  # 1826 minus the zero row
    assert (pc["Close"] > 0).all()
    assert pd.Series(pd.to_datetime(pc["Date"])).is_monotonic_increasing
    one = rd.price_chart(stock_close(), years=1)
    assert pd.Timestamp(one["Date"].iloc[0]) == pd.Timestamp("2025-10-31")  # after 2025-10-30


def test_s3_price_chart_empty_without_prices():
    c = rd.company_stats(gamuda_stock(prices=False))
    assert isinstance(c["price_chart"], pd.DataFrame) and c["price_chart"].empty
    assert rd.price_chart(empty_close()).empty


def test_s3_company_carries_price_stats():
    raw = gamuda_stock()
    c = rd.company_stats(raw)
    ps = rd.price_stats(raw.prices["Close"])
    for k in PRICE_KEYS:
        assert k in c, k
    for k in YEARS:
        assert c["returns"][k] == pytest.approx(RET[k])  # same ratios as the ETF fixture (values / 40)
        assert c["annual_returns"][k] == pytest.approx(ANN[k])
    assert c["max_drawdown_3y"] == pytest.approx(-0.20)
    assert c["volatility_3y"] == pytest.approx(ps["volatility_3y"])
    assert c["history_note"] is None  # six years of prices


def test_s3_company_dividends_from_dividend_history():
    raw = gamuda_stock()
    c = rd.company_stats(raw)
    expected = rd.dividend_history(raw.dividends, 2026, 2020)  # fetched 2026; first price 2020-11-02
    pd.testing.assert_frame_equal(c["dividends"].reset_index(drop=True), expected.reset_index(drop=True))
    assert list(c["dividends"]["Year"]) == [y for y, _, _ in DIV_TABLE]


# ---------- S4 dividend_history ----------
def test_s4_dividend_history_sums_counts_newest_first():
    t = rd.dividend_history(divs_frame(), 2026)
    assert list(t.columns) == ["Year", "Per share", "Payments"]
    assert len(t) == 6  # 2021 .. 2026 (DIVIDEND_YEARS = 5 full years before the current one)
    assert rd.DIVIDEND_YEARS == 5
    assert list(t["Year"]) == [y for y, _, _ in DIV_TABLE]  # "2026 so far" first, 2020 left out
    assert list(t["Per share"]) == pytest.approx([p for _, p, _ in DIV_TABLE])  # see DIV_TABLE sums
    assert [int(n) for n in t["Payments"]] == [n for _, _, n in DIV_TABLE]
    assert all(isinstance(y, str) for y in t["Year"])


def test_s4_dividend_history_types():
    t = rd.dividend_history(divs_frame(), 2026)
    assert pd.api.types.is_float_dtype(t["Per share"])
    assert pd.api.types.is_integer_dtype(t["Payments"])


def test_s4_skipped_year_present_with_zero():
    t = rd.dividend_history(divs_frame(), 2026).set_index("Year")
    assert t.loc["2023", "Per share"] == 0.0
    assert t.loc["2023", "Payments"] == 0


def test_s4_31_dec_and_1_jan_in_different_years():
    t = rd.dividend_history(divs_frame([("2021-12-31", 0.04), ("2022-01-01", 0.05)]), 2026).set_index("Year")
    assert t.loc["2021", "Per share"] == pytest.approx(0.04) and t.loc["2021", "Payments"] == 1
    assert t.loc["2022", "Per share"] == pytest.approx(0.05) and t.loc["2022", "Payments"] == 1


def test_s4_years_before_first_year_dropped():
    t = rd.dividend_history(divs_frame(), 2026, first_year=2023)  # listed in 2023
    assert list(t["Year"]) == ["2026 so far", "2025", "2024", "2023"]
    assert list(t["Per share"]) == pytest.approx([0.05, 0.08, 0.05, 0.0])


def test_s4_first_year_before_window_keeps_six_rows():
    t = rd.dividend_history(divs_frame(), 2026, first_year=2020)
    assert len(t) == 6


def test_s4_empty_dividends_with_prices_six_zero_rows():
    t = rd.dividend_history(no_divs(), 2026, first_year=2020)
    assert list(t["Year"]) == ["2026 so far", "2025", "2024", "2023", "2022", "2021"]
    assert list(t["Per share"]) == [0.0] * 6
    assert [int(n) for n in t["Payments"]] == [0] * 6
    t2 = rd.dividend_history(pd.DataFrame(), 2026, first_year=2020)  # no Dividends column at all
    assert len(t2) == 6 and list(t2["Per share"]) == [0.0] * 6


def test_s4_company_no_prices_no_dividends_empty_frame():
    c = rd.company_stats(gamuda_stock(prices=False, dividends=False))
    assert isinstance(c["dividends"], pd.DataFrame) and c["dividends"].empty


def test_s4_company_prices_but_no_dividends_six_zero_rows():
    c = rd.company_stats(gamuda_stock(dividends=False))
    assert len(c["dividends"]) == 6 and list(c["dividends"]["Per share"]) == [0.0] * 6


# ---------- S5 credit_rows ----------
SPEC_GROUPS = {DE: "Leverage", ND: "Leverage", IC: "Coverage", CR: "Liquidity", OCF: "Cash", FCF: "Cash",
               NM: "Profitability", ROE: "Profitability", GR: "Growth"}


def test_s5_ratio_groups_setting():
    assert rd.RATIO_GROUPS == SPEC_GROUPS


def test_s5_credit_rows_nine_in_order_with_cells_and_lights():
    r = rd.analyse(gamuda_like())
    assert r.periods[0] == "TTM"
    rows = rd.credit_rows(r)
    assert [row["ratio"] for row in rows] == RATIO_NAMES
    for row in rows:
        name = row["ratio"]
        assert row["group"] == SPEC_GROUPS[name]
        assert row["cells"] == [r.labels.loc[name, p] for p in r.periods]  # TTM first, as r.periods
        assert row["light"] is r.lights[name]  # the same object, nothing recomputed
        assert row["drives_overall"] is (name in LENDER)
    assert sum(row["drives_overall"] for row in rows) == 4
    de = rows[0]
    assert de["cells"] == ["0.60"] * 5  # Debt / Equity 600 / 1000 in every period


# ---------- S6 statement_rows and statement_unit ----------
def big_raw():
    """simple_raw with large newest-year figures; Interest Expense NaN in the newest year."""
    return simple_raw(**F(Total_Revenue=2.5e9, Total_Debt=6.0e8, Operating_Cash_Flow=1.5e8, Interest_Expense=NAN))


def test_s6_statement_rows_fields_periods_and_millions():
    r = rd.analyse(big_raw())
    t = rd.statement_rows(r)
    assert set(t) == {"income", "balance", "cashflow"}
    for s in ("income", "balance", "cashflow"):
        assert list(t[s].index) == [f for f, st in rd.FIELDS.items() if st == s]
        assert list(t[s].columns) == r.periods
    newest = SIMPLE_COLS[0]
    assert t["income"].loc["Total Revenue", newest] == pytest.approx(2500.0)  # 2.5e9 / 1e6
    assert t["balance"].loc["Total Debt", newest] == pytest.approx(600.0)  # 6.0e8 / 1e6
    assert t["cashflow"].loc["Operating Cash Flow", newest] == pytest.approx(150.0)  # 1.5e8 / 1e6
    assert t["income"].loc["Total Revenue", SIMPLE_COLS[1]] == pytest.approx(0.0008)  # 800 / 1e6
    assert pd.isna(t["income"].loc["Interest Expense", newest])  # NaN stays NaN
    assert "Reconciled Depreciation" not in t["income"].index  # only the twelve FIELDS


def test_s6_statement_titles_and_unit():
    assert rd.STATEMENT_TITLES == {"income": "Income statement", "balance": "Balance sheet",
                                   "cashflow": "Cash flow"}
    r = rd.analyse(gamuda_like())
    assert rd.statement_unit(r) == "MYR millions"
    r.financial_currency = None
    assert rd.statement_unit(r) == "millions"


# ---------- S7 short_money tn ----------
def test_s7_short_money_trillions_and_existing_cases():
    # existing bn / m / k cases first (they pass today and must stay), then the new tn step
    assert rd.short_money("MYR", 4.3e11) == "RM 430.0 bn"
    assert rd.short_money("USD", 1.012e11) == "USD 101.2 bn"
    assert rd.short_money("USD", 9.0e11) == "USD 900.0 bn"
    assert rd.short_money("USD", 5e8) == "USD 500.0 m"
    assert rd.short_money("USD", 2500) == "USD 2.5 k"
    assert rd.short_money("USD", None) == "n/a"
    assert rd.short_money("USD", 5.03e12) == "USD 5.0 tn"
    assert rd.short_money("USD", 9.9996e11) == "USD 1.0 tn"  # rounds up to the next unit, as for bn
    assert rd.short_money("MYR", 2.13775e13) == "RM 21.4 tn"  # 5.03e12 x 4.25


# ---------- S8 analyse ----------
def test_s8_analyse_stock_has_company_and_same_credit():
    before = rd.analyse(gamuda_like())  # the WP-3.1 fixture, no WP-3.2 parts
    r = rd.analyse(gamuda_stock())
    assert r.etf is None
    assert isinstance(r.company, dict)
    assert r.company["range_position"] == pytest.approx(0.5)  # (5.0 - 4.0) / 2.0
    assert r.company["market_cap_myr"] == pytest.approx(2.98e10)
    assert r.overall == rd.Light("amber", "worst: Debt / Equity 0.60 (TTM): moderate borrowing against equity")
    assert r.overall == before.overall
    assert r.lights == before.lights
    assert r.periods == before.periods


def test_s8_analyse_etf_company_none_and_price_chart():
    r = rd.analyse(etf_like())
    assert r.company is None
    pc = r.etf["price_chart"]
    assert list(pc.columns) == ["Date", "Close"] and not pc.empty
    # ETF fixture last date 2026-10-30, so the chart starts 2021-10-31 (same helper as the stock view)
    assert pd.Timestamp(pc["Date"].iloc[0]) == pd.Timestamp("2021-10-31")
    pd.testing.assert_frame_equal(pc.reset_index(drop=True),
                                  rd.price_chart(etf_like().prices["Close"]).reset_index(drop=True))


def test_s8_stock_without_prices_warns_and_gives_na():
    r = rd.analyse(gamuda_stock(prices=False))
    assert "no price history from Yahoo" in r.warnings
    assert r.company["returns"] == {"1y": None, "3y": None, "5y": None}
    assert r.company["volatility_3y"] is None and r.company["max_drawdown_3y"] is None
    assert r.company["price_chart"].empty


def test_s8_stock_short_history_note_in_warnings():
    raw = gamuda_stock()
    raw.prices = pd.DataFrame({"Close": stock_close().loc["2025-01-01":]})  # under two years of prices
    r = rd.analyse(raw)
    note = r.company["history_note"]
    assert note and note.startswith("only ") and note in r.warnings


# ---------- S9 cache ----------
def test_s9_cache_round_trip_stock(tmp_path):
    raw = gamuda_stock()
    rd.save_cache(raw, cache_dir=tmp_path)
    back = rd.load_cache("5398.KL", cache_dir=tmp_path)
    assert back is not None
    assert back.info["nextEarningsDate"] == "2026-12-09"
    assert len(back.dividends) == len(STOCK_DIVS)
    assert list(back.dividends["Dividends"]) == pytest.approx([v for _, v in STOCK_DIVS])
    assert not back.prices.empty and back.fx == 1.0
    assert_stats_equal(rd.company_stats(raw), rd.company_stats(back))


def test_s9_wp33_cache_without_dividends_loads_empty(tmp_path):
    rd.save_cache(gamuda_stock(), cache_dir=tmp_path)
    path = tmp_path / "5398.KL.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.pop("dividends", None)  # the WP-3.3 file format
    path.write_text(json.dumps(doc), encoding="utf-8")
    back = rd.load_cache("5398.KL", cache_dir=tmp_path)
    assert back is not None
    assert isinstance(back.dividends, pd.DataFrame) and back.dividends.empty
    r = rd.analyse(back)  # does not raise
    assert r.company is not None


def test_s9_raw_default_dividends_empty():
    e = pd.DataFrame()
    raw = rd.Raw(code="X", info={}, income=e, balance=e, cashflow=e, q_income=e, q_balance=e, q_cashflow=e,
                 recs=e, fetched_at=T0)
    assert isinstance(raw.dividends, pd.DataFrame) and raw.dividends.empty
    assert hasattr(rd, "_EXTRA_FRAMES") and "dividends" in rd._EXTRA_FRAMES


# ---------- S10 fetch_raw for a stock with a fake yfinance ----------
def epoch(*args):
    """UTC wall time -> epoch seconds (int), as Yahoo sends earningsTimestamp*."""
    return int(datetime(*args, tzinfo=timezone.utc).timestamp())


# 2027-01-29 01:00 UTC = 2027-01-28 20:00 in New York (EST, UTC-5): one calendar day apart.
START_NY = epoch(2027, 1, 29, 1, 0)
PAST_REPORT = epoch(2026, 10, 2, 21, 0)  # earningsTimestamp: the last report, never used


def stock_history(tz="America/New_York", divs=STOCK_DIVS):
    """yfinance history(period="6y") shape for a stock: 7 columns, tz-aware index, Dividends on ex-dates."""
    h = tz_history(stock_close(), tz=tz).drop(columns=["Capital Gains"])
    for d, v in divs:
        h.loc[pd.Timestamp(d).tz_localize(tz), "Dividends"] = v
    return h


def fake_stock_yf(info, history="ok", calendar="ok", divs=STOCK_DIVS, fx_close=(4.10, 4.20, 4.25)):
    """A Ticker class for a stock: records codes, history calls, funds_data and calendar access."""
    cls, log = fake_yf(info, fx_close=fx_close)
    log["calendar"] = 0

    class StockTicker(cls):
        @property
        def calendar(self):
            log["calendar"] += 1
            if calendar == "raise":
                raise RuntimeError("calendar broke (fake)")
            if calendar == "empty":
                return {}
            return {"Earnings Date": [date(2027, 2, 15)], "Earnings Average": None}

        def history(self, period=None, **kw):
            if self.code.endswith("MYR=X"):
                return super().history(period=period, **kw)
            log["history"].append((self.code, period))
            if history == "raise":
                raise ConnectionError("history broke (fake)")
            return stock_history(divs=divs)

    return StockTicker, log


def us_info(**kw):
    base = info_eq(currency="USD", financialCurrency="USD", exchangeTimezoneName="America/New_York",
                   earningsTimestamp=PAST_REPORT, earningsTimestampStart=START_NY)
    for k, v in kw.items():
        if v is ABSENT:
            base.pop(k, None)
        else:
            base[k] = v
    return base


def fetch_with(monkeypatch, info, **fake):
    yf = pytest.importorskip("yfinance")
    cls, log = fake_stock_yf(info, **fake)
    monkeypatch.setattr(yf, "Ticker", cls)
    return rd.fetch_raw("FAKE", now=T0), log


def test_s10_stock_prices_dividends_fx_from_one_history_call(monkeypatch):
    raw, log = fetch_with(monkeypatch, us_info())
    assert [h for h in log["history"] if h[0] == "FAKE"] == [("FAKE", "6y")]  # ONE call serves both
    assert list(raw.prices.columns) == ["Close"] and raw.prices.index.tz is None
    assert len(raw.prices) == len(stock_close())
    assert list(raw.dividends.columns) == ["Dividends"]
    assert raw.dividends.index.tz is None
    assert len(raw.dividends) == len(STOCK_DIVS)  # non-zero rows only
    assert list(raw.dividends["Dividends"]) == pytest.approx([v for _, v in STOCK_DIVS])
    assert pd.Timestamp(raw.dividends.index[0]) == pd.Timestamp("2020-12-01")
    assert raw.fx == pytest.approx(4.25)  # last USDMYR=X Close
    assert "USDMYR=X" in log["codes"]
    assert log["funds_touched"] == 0


def test_s10_earnings_from_start_in_exchange_zone(monkeypatch):
    raw, _ = fetch_with(monkeypatch, us_info())
    # START_NY is 2027-01-29 in UTC but 2027-01-28 in New York; the exchange's zone wins.
    # The calendar (2027-02-15) and earningsTimestamp (2026-10-02) are not used.
    assert raw.info["nextEarningsDate"] == "2027-01-28"


def test_s10_earnings_start_in_utc_when_zone_absent(monkeypatch):
    raw, _ = fetch_with(monkeypatch, us_info(exchangeTimezoneName=ABSENT))
    assert raw.info["nextEarningsDate"] == "2027-01-29"  # 01:00 UTC on 29 Jan


def test_s10_earnings_from_calendar_only_without_start(monkeypatch):
    raw, _ = fetch_with(monkeypatch, us_info(earningsTimestampStart=ABSENT))
    assert raw.info["nextEarningsDate"] == "2027-02-15"  # calendar["Earnings Date"][0]
    # no Start and an empty calendar: absent, even though earningsTimestamp (2026-10-02) is present
    raw, _ = fetch_with(monkeypatch, us_info(earningsTimestampStart=ABSENT), calendar="empty")
    assert "nextEarningsDate" not in raw.info


def test_s10_calendar_raising_gives_no_date_no_exception(monkeypatch):
    raw, log = fetch_with(monkeypatch, us_info(earningsTimestampStart=ABSENT), calendar="raise")
    assert log["calendar"] >= 1  # the calendar was asked (and raised)
    assert "nextEarningsDate" not in raw.info
    assert not raw.prices.empty  # the rest of the fetch is unharmed


def test_s10_all_zero_dividends_give_empty_frame(monkeypatch):
    raw, _ = fetch_with(monkeypatch, us_info(), divs=[])  # Dividends column present, all 0.0 (BRK-B-like)
    assert isinstance(raw.dividends, pd.DataFrame) and raw.dividends.empty
    assert not raw.prices.empty


def test_s10_history_raising_gives_empty_prices_and_dividends(monkeypatch):
    raw, log = fetch_with(monkeypatch, us_info(), history="raise")
    assert isinstance(raw.prices, pd.DataFrame) and raw.prices.empty
    assert isinstance(raw.dividends, pd.DataFrame) and raw.dividends.empty
    assert raw.info["nextEarningsDate"] == "2027-01-28"  # other parts still filled
    assert log["funds_touched"] == 0


# ---------- added by the mutation checker (WP-3.2 round 1) ----------
def test_m1_price_figures_use_every_price_up_to_the_last():
    # The main fixtures end on a flat stretch, so dropping or shifting the last prices changed nothing.
    # Here the series ends on a rising slope: every figure depends on the very last price.
    close = five_year_close(ANCHORS[:-1])  # ends 2026-10-15 at 175, still rising
    expected = {"returns": {k: rd.cumulative_return(close, n) for k, n in YEARS.items()},
                "volatility_3y": rd.volatility(close), "max_drawdown_3y": rd.max_drawdown(close)}
    assert expected["returns"]["1y"] == pytest.approx(175 / 150 - 1)
    etf = etf_like()
    etf.prices = pd.DataFrame({"Close": close})
    stock = gamuda_stock()
    stock.prices = pd.DataFrame({"Close": close})
    for got in (rd.price_stats(close), rd.etf_stats(etf), rd.company_stats(stock)):
        for k in YEARS:
            assert got["returns"][k] == pytest.approx(expected["returns"][k], rel=1e-12), k
        assert got["volatility_3y"] == pytest.approx(expected["volatility_3y"], rel=1e-12)
        assert got["max_drawdown_3y"] == pytest.approx(expected["max_drawdown_3y"], rel=1e-12)


def test_m1_cache_dividends_index_stays_dates(tmp_path):
    raw = gamuda_stock()
    rd.save_cache(raw, cache_dir=tmp_path)
    back = rd.load_cache("5398.KL", cache_dir=tmp_path)
    assert isinstance(back.dividends.index, pd.DatetimeIndex)  # timezone-free dates, as fetched
    assert list(back.dividends.index) == list(pd.DatetimeIndex(raw.dividends.index))


# ---------- WP-3.2 round 2, Part B (spec v1.2 rules 14-15). Made-up numbers only. ----------
# R2 (rule 14): no earnings lookup for an ETF; Ticker.calendar must never be touched for one.
def no_calendar_yf(info):
    """fake_stock_yf whose calendar raises AssertionError the moment it is read (and counts the reads)."""
    cls, log = fake_stock_yf(info)

    class NoCalendarTicker(cls):
        @property
        def calendar(self):
            log["calendar"] += 1
            raise AssertionError("calendar touched (fake)")

    return NoCalendarTicker, log


def fetch_no_calendar(monkeypatch, code, info):
    yf = pytest.importorskip("yfinance")
    cls, log = no_calendar_yf(info)
    monkeypatch.setattr(yf, "Ticker", cls)
    return rd.fetch_raw(code, now=T0), log


def test_r2b_etf_fetch_has_no_next_earnings_even_with_start(monkeypatch):
    info = etf_info(exchangeTimezoneName="America/New_York", earningsTimestampStart=START_NY)
    raw, log = fetch_no_calendar(monkeypatch, "VT", info)
    assert "nextEarningsDate" not in raw.info  # START_NY would give 2027-01-28 for a stock
    assert log["calendar"] == 0
    assert not raw.prices.empty  # the rest of the ETF fetch still works


def test_r2b_etf_fetch_never_touches_calendar(monkeypatch):
    raw, log = fetch_no_calendar(monkeypatch, "VT", etf_info())  # no Start key: today the calendar is asked
    assert log["calendar"] == 0
    assert "nextEarningsDate" not in raw.info
    assert raw.holdings is not None and len(raw.holdings) == 10


def test_r2b_stock_fetch_still_gets_next_earnings(monkeypatch):
    raw, log = fetch_no_calendar(monkeypatch, "FAKE", us_info())
    assert raw.info["nextEarningsDate"] == "2027-01-28"  # START_NY in New York, as S10
    assert log["calendar"] == 0  # Start present: the calendar is not needed


# R3 (rule 15): every Yahoo number through one safe converter. Text that is not a number, NaN and
# infinities -> None; numeric text "12.5" -> 12.5.
BAD_OR_TEXT = [("Infinity", None), ("abc", None), (float("nan"), None), (float("inf"), None), ("12.5", 12.5)]
VALUATION_KEYS = {"trailingPE": "pe", "forwardPE": "forward_pe", "priceToBook": "pb",
                  "trailingAnnualDividendYield": "dividend_yield", "enterpriseToEbitda": "ev_ebitda",
                  "marketCap": "market_cap", "currentPrice": "price", "targetMeanPrice": "target_mean",
                  "numberOfAnalystOpinions": "analysts"}
GOOD_VALUATION = {"trailingPE": 14.2, "forwardPE": 11.6, "priceToBook": 1.3, "trailingAnnualDividendYield": 0.02,
                  "enterpriseToEbitda": 9.8, "marketCap": 5000.0, "currentPrice": 5.0, "targetMeanPrice": 6.0,
                  "numberOfAnalystOpinions": 20}


@pytest.mark.parametrize("value,expected", BAD_OR_TEXT, ids=["Infinity", "abc", "nan", "inf", "text-12.5"])
def test_r3_valuation_of_safe_numbers(value, expected):
    for key, field in VALUATION_KEYS.items():
        v = rd.valuation_of(info_eq(**dict(GOOD_VALUATION, **{key: value})), recs_frame())
        assert v[field] == expected if expected is not None else v[field] is None, (key, v[field])
        for other_key, other in VALUATION_KEYS.items():  # the other keys keep their good values
            if other_key != key:
                assert v[other] == GOOD_VALUATION[other_key], (key, other)


@pytest.mark.parametrize("value", ["Infinity", "abc", float("nan"), float("inf")], ids=["Infinity", "abc", "nan", "inf"])
@pytest.mark.parametrize("key", ["currentPrice", "targetMeanPrice"])
def test_r3_upside_none_when_price_or_target_unusable(key, value):
    v = rd.valuation_of(info_eq(**dict(GOOD_VALUATION, **{key: value})), recs_frame())
    assert v["upside"] is None


def test_r3_upside_from_numeric_text():
    v = rd.valuation_of(info_eq(**dict(GOOD_VALUATION, currentPrice="5.0", targetMeanPrice="6.0")), recs_frame())
    assert v["upside"] == pytest.approx(0.2)  # 6.0 / 5.0 - 1


COMPANY_NUMBER_KEYS = {"fiftyTwoWeekLow": "range_low", "fiftyTwoWeekHigh": "range_high",
                       "heldPercentInsiders": "insiders", "heldPercentInstitutions": "institutions",
                       "payoutRatio": "payout_ratio", "marketCap": "market_cap"}


@pytest.mark.parametrize("value,expected", BAD_OR_TEXT, ids=["Infinity", "abc", "nan", "inf", "text-12.5"])
def test_r3_company_stats_safe_numbers(value, expected):
    for key, field in COMPANY_NUMBER_KEYS.items():
        co = rd.company_stats(gamuda_stock(**{key: value}))
        assert co[field] == expected if expected is not None else co[field] is None, (key, co[field])
    co = rd.company_stats(gamuda_stock(marketCap=value))  # fx 1.0
    assert co["market_cap_myr"] == expected if expected is not None else co["market_cap_myr"] is None


@pytest.mark.parametrize("value", ["Infinity", "abc", float("inf")], ids=["Infinity", "abc", "inf"])
def test_r3_company_range_position_none_for_unusable_range(value):
    assert rd.company_stats(gamuda_stock(fiftyTwoWeekHigh=value))["range_position"] is None
