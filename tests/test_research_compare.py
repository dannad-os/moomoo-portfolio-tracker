"""WP-3.4.1 "Compare with today", data layer (spec v1, research_data.compare / Moved / Comparison). Fakes only: the
made-up Research results of test_research_data (rd.analyse of gamuda_stock / etf_like) with their headline
figures set by hand to round numbers, so every expected text below is worked out by hand. No network, no cache
folder, no workbook. rd.compare is looked up inside each test, so the file collects before it exists."""
import ast
import builtins
import copy
import dataclasses
import inspect
import json
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import research_data as rd  # noqa: E402
from test_research_data import etf_like, gamuda_stock  # noqa: E402

NAN = float("nan")
SAVED_AT = datetime(2026, 10, 31, 9, 0)
TODAY_AT = datetime(2026, 11, 16, 10, 30)
DE, ND, IC, CR = "Debt / Equity", "Net debt / EBITDA", "Interest cover", "Current ratio"
OCF, FCF, NM, ROE, GR = "OCF / Total debt", "FCF margin", "Net margin", "ROE", "Revenue growth"

# Section names (spec "Rows")
PS, VAL, RR, CH, LT, COSTS = "Price and size", "Valuation", "Returns and risk", "Credit health", "Lights", "Costs"
# Figure labels: "reuse the wording the Research layout already uses" (research_view.draw_returns metric labels).
# The spec's own list says "Return 1y, 3y, 5y", "Volatility 3y", "Max drawdown 3y": see checks.md "needs a ruling".
R1, R3, R5, VOL, MDD = "1y return", "3y return", "5y return", "Volatility", "Max drawdown"

KINDS_NOTE = "The saved copy and today's result are different kinds (stock / ETF); nothing to compare."
SAME_FETCH_NOTE = "Today's figures are the same fetch as the saved ones (the hourly copy has not renewed yet)."


def compare(saved, fresh):
    return rd.compare(saved, fresh)  # AttributeError until WP-3.4.1 is built: the test fails, the file collects


# ---------- made-up results ----------
def set_credit(r, periods, newest, older=None):
    """periods newest first; newest {ratio: (float or NaN, label)} fills the first column. Older columns hold
    99.0 / "99.00" so a comparison that reads the wrong column shows it. older {ratio: (v, label)} fills the
    second column for those ratios (v3.1: an empty newest cell falls back to it)."""
    r.periods = list(periods)
    r.ratios = pd.DataFrame(99.0, index=rd.RATIOS, columns=r.periods)
    r.labels = pd.DataFrame("99.00", index=rd.RATIOS, columns=r.periods)
    if r.periods:
        for name, (v, label) in newest.items():
            r.ratios.loc[name, r.periods[0]] = v
            r.labels.loc[name, r.periods[0]] = label
    for name, (v, label) in (older or {}).items():
        r.ratios.loc[name, r.periods[1]] = v
        r.labels.loc[name, r.periods[1]] = label


SAVED_CREDIT = {DE: (0.60, "0.60"), ND: (1.5, "1.5x"), IC: (5.0, "5.0x"), CR: (1.50, "1.50"), OCF: (0.25, "0.25"),
                FCF: (-0.05, "-5.0%"), NM: (0.10, "10.0%"), ROE: (0.10, "10.0%"), GR: (NAN, "n/a")}
FRESH_CREDIT = {DE: (0.85, "0.85"), ND: (NAN, "net cash"), IC: (6.4, "6.4x"), CR: (1.50, "1.50"),
                OCF: (0.20, "0.20"), FCF: (0.02, "2.0%"), NM: (0.1449, "14.5%"), ROE: (0.10, "10.0%"),
                GR: (NAN, "n/a")}
# v3.1: as compute_ratios does, Revenue growth has no TTM figure; the year column holds it.
SAVED_OLDER = {GR: (0.08, "8.0%")}
FRESH_OLDER = {GR: (0.05, "5.0%")}
YEAR = "2026-07-31"
SAVED_LIGHTS = {DE: ("green", "Debt / Equity 0.60 (TTM): low borrowing against equity"),
                ND: ("green", "Net debt / EBITDA 1.5x (TTM): debt repayable from under two years of earnings"),
                IC: ("amber", "Interest cover 5.0x (TTM): EBIT covers interest, thin margin"),
                CR: ("green", "Current ratio 1.50 (TTM): short-term assets well above short-term bills"),
                OCF: ("amber", "OCF / Total debt 0.25 (TTM): operating cash pays down debt slowly"),
                FCF: ("red", "FCF margin -5.0% (TTM): spends more cash than it brings in"),
                NM: ("green", "Net margin 10.0% (TTM): keeps a healthy share of revenue as profit"),
                ROE: ("amber", "ROE 10.0% (TTM): modest return on shareholders' money"),
                GR: ("grey", "Revenue growth 8.0% (2026-07-31): growth not judged")}
FRESH_LIGHTS = {DE: ("amber", "Debt / Equity 0.85 (TTM): moderate borrowing against equity"),
                ND: ("green", "Net debt / EBITDA net cash (TTM): cash exceeds debt"),
                IC: ("green", "Interest cover 6.4x (TTM): EBIT covers interest comfortably"),
                CR: ("green", "Current ratio 1.50 (TTM): short-term assets well above short-term bills"),
                OCF: ("amber", "OCF / Total debt 0.20 (TTM): operating cash pays down debt slowly"),
                FCF: ("amber", "FCF margin 2.0% (TTM): some free cash after investment"),
                NM: ("green", "Net margin 14.5% (TTM): keeps a healthy share of revenue as profit"),
                ROE: ("amber", "ROE 10.0% (TTM): modest return on shareholders' money"),
                GR: ("grey", "Revenue growth 5.0% (2026-07-31): growth not judged")}


def light_on(r, name, period, value="x"):
    """Move one side's light for a ratio onto a period (v4.1a: the light's reason names its period)."""
    r.lights[name] = rd.Light(r.lights[name].colour, f"{name} {value} ({period}): made-up phrase")


_BASE = {}


def base(kind):
    """rd.analyse of the shared fixture, worked out once; each test gets its own deep copy."""
    if kind not in _BASE:
        _BASE[kind] = rd.analyse(gamuda_stock() if kind == "stock" else etf_like())
    return copy.deepcopy(_BASE[kind])


def stock(when, price, cap, val, returns, vol, mdd, credit, lights, overall, periods=("TTM", "2026-07-31"),
          older=None):
    r = base("stock")
    r.fetched_at, r.stale, r.currency, r.is_financial = when, False, "MYR", False
    r.price, r.market_cap = price, cap
    r.valuation.update(val, price=price, market_cap=cap)
    co = r.company
    co["market_cap"] = cap
    co["returns"], co["volatility_3y"], co["max_drawdown_3y"] = dict(returns), vol, mdd
    set_credit(r, periods, credit, older)
    r.lights = {k: rd.Light(*v) for k, v in lights.items()}
    r.overall = rd.Light(*overall)
    return r


def saved_stock():
    return stock(SAVED_AT, 5.0, 2.0e10,
                 dict(pe=12.0, forward_pe=11.0, pb=1.3, ev_ebitda=9.8, dividend_yield=0.045, target_mean=None),
                 {"1y": 0.123, "3y": 0.40, "5y": None}, 0.184, -0.221, SAVED_CREDIT, SAVED_LIGHTS,
                 ("amber", "worst: Interest cover 5.0x (TTM): EBIT covers interest, thin margin"),
                 older=SAVED_OLDER)


def fresh_stock():
    return stock(TODAY_AT, 5.4, 1.936e10,
                 dict(pe=13.4, forward_pe=10.8, pb=1.3, ev_ebitda=None, dividend_yield=0.0432, target_mean=6.0),
                 {"1y": 0.155, "3y": 0.40, "5y": None}, 0.172, -0.25, FRESH_CREDIT, FRESH_LIGHTS,
                 ("amber", "worst: Debt / Equity 0.85 (TTM): moderate borrowing against equity"),
                 older=FRESH_OLDER)


def etf(when, price, size, expense, dist, returns, vol, mdd, size_light, er_light):
    r = base("etf")
    r.fetched_at, r.stale, r.currency, r.price = when, False, "USD", price
    e = r.etf
    e["currency"], e["fund_size"], e["fund_size_myr"] = "USD", size, size * 4.25
    e["expense_ratio"], e["distribution_yield"] = expense, dist
    e["returns"], e["volatility_3y"], e["max_drawdown_3y"] = dict(returns), vol, mdd
    e["lights"] = {"expense_ratio": rd.Light(*er_light), "fund_size": rd.Light(*size_light)}
    e["overall"] = rd.etf_overall(e["lights"])
    r.overall = e["overall"]
    return r


def saved_etf():
    return etf(SAVED_AT, 100.0, 5.0e8, 0.0007, 0.018, {"1y": 0.20, "3y": 0.30, "5y": 0.50}, 0.15, -0.30,
               ("amber", "Fund size USD 500.0 m: mid-sized"), ("green", "Expense ratio 0.07%: cheap to hold"))


def fresh_etf():
    return etf(TODAY_AT, 92.0, 2.5e9, 0.0006, 0.020, {"1y": 0.15, "3y": 0.30, "5y": None}, 0.15, -0.30,
               ("green", "Fund size USD 2.5 bn: large and liquid"), ("green", "Expense ratio 0.06%: cheap to hold"))


def row(c, section, figure):
    hits = [m for m in c.rows if m.section == section and m.figure == figure]
    assert len(hits) == 1, f"want one row {section} / {figure}, got {len(hits)}: " + \
        "; ".join(f"{m.section} / {m.figure}" for m in c.rows)
    return hits[0]


def texts_of(m):
    return (m.saved, m.today, m.change)


def stock_c():
    return compare(saved_stock(), fresh_stock())


def etf_c():
    return compare(saved_etf(), fresh_etf())


# ---------- interface ----------
def test_moved_fields_in_spec_order():
    assert [f.name for f in dataclasses.fields(rd.Moved)] == ["section", "figure", "saved", "today", "change", "note"]


def test_comparison_fields_in_spec_order():
    assert [f.name for f in dataclasses.fields(rd.Comparison)] == ["code", "saved_on", "today_on", "rows", "notes"]


def test_compare_takes_saved_then_fresh():
    assert list(inspect.signature(rd.compare).parameters) == ["saved", "fresh"]


def test_comparison_code_and_dates_from_fetched_at():
    c = stock_c()
    assert isinstance(c, rd.Comparison)
    assert c.code == "5398.KL"
    assert c.saved_on == date(2026, 10, 31) and type(c.saved_on) is date
    assert c.today_on == date(2026, 11, 16) and type(c.today_on) is date
    assert all(isinstance(m, rd.Moved) for m in c.rows)
    assert c.notes == []


# ---------- rows and order ----------
STOCK_ORDER = [(PS, "Price"), (PS, "Market cap"),
               (VAL, "P/E"), (VAL, "Forward P/E"), (VAL, "P/B"), (VAL, "EV/EBITDA"), (VAL, "Dividend yield"),
               (VAL, "Analyst target"),
               (RR, R1), (RR, R3), (RR, VOL), (RR, MDD),  # 5y missing on both sides: left out
               *[(CH, n) for n in rd.RATIOS],  # v3.1: Revenue growth from the year column on both sides
               *[(LT, n) for n in rd.RATIOS], (LT, "Overall")]
ETF_ORDER = [(PS, "Price"), (PS, "Fund size"), (COSTS, "Expense ratio"), (COSTS, "Distribution yield"),
             (RR, R1), (RR, R3), (RR, R5), (RR, VOL), (RR, MDD),
             (LT, "Expense ratio"), (LT, "Fund size"), (LT, "Overall")]


def test_stock_rows_sections_and_order():
    assert [(m.section, m.figure) for m in stock_c().rows] == STOCK_ORDER


def test_etf_rows_sections_and_order():
    assert [(m.section, m.figure) for m in etf_c().rows] == ETF_ORDER


def test_etf_has_no_valuation_or_credit_rows():
    sections = {m.section for m in etf_c().rows}
    assert VAL not in sections and CH not in sections


def test_left_out_figures_do_not_move_anything():
    """Ringgit sizes, FX, annualised returns, upside, 52-week range, analyst counts, dividends: changing only
    them leaves every row at "no change"."""
    s, f = saved_stock(), saved_stock()
    f.fetched_at = TODAY_AT
    co = f.company
    co["market_cap_myr"], co["fx"] = 9.9e10, 4.9
    co["annual_returns"] = {"1y": 0.9, "3y": 0.9, "5y": 0.9}
    co["range_low"], co["range_high"], co["range_position"] = 1.0, 9.0, 0.5
    co["payout_ratio"], co["insiders"] = 0.99, 0.99
    f.valuation.update(upside=0.5, buy=9, hold=0, sell=0, analysts=9)
    changes = {m.figure: m.change for m in compare(s, f).rows}
    assert changes and set(changes.values()) == {"no change"}, changes


def test_etf_left_out_ringgit_size_does_not_move_anything():
    s, f = saved_etf(), saved_etf()
    f.fetched_at = TODAY_AT
    f.etf["fx"], f.etf["fund_size_myr"] = 4.9, 9.9e10
    f.etf["annual_returns"] = {"1y": 0.9, "3y": 0.9, "5y": 0.9}
    changes = {m.figure: m.change for m in compare(s, f).rows}
    assert changes and set(changes.values()) == {"no change"}, changes


# ---------- amounts: relative change, one decimal ----------
def test_amount_up_price():
    assert texts_of(row(stock_c(), PS, "Price")) == ("5.00 MYR", "5.40 MYR", "▲ +8.0%")


def test_amount_down_market_cap_own_currency():
    assert texts_of(row(stock_c(), PS, "Market cap")) == ("RM 20.0 bn", "RM 19.4 bn", "▼ -3.2%")


def test_market_cap_in_listing_currency_not_ringgit():
    s, f = saved_stock(), fresh_stock()
    for r, cap in ((s, 5.0e12), (f, 5.5e12)):
        r.currency, r.market_cap = "USD", cap
        r.company["market_cap"], r.company["market_cap_myr"] = cap, cap * 4.25
        r.valuation["market_cap"] = cap
    assert texts_of(row(compare(s, f), PS, "Market cap")) == ("USD 5.0 tn", "USD 5.5 tn", "▲ +10.0%")


def test_amount_one_sided_analyst_target():
    assert texts_of(row(stock_c(), VAL, "Analyst target")) == ("n/a", "6.00 MYR", "n/a")


def test_amount_down_etf_price():
    assert texts_of(row(etf_c(), PS, "Price")) == ("100.00 USD", "92.00 USD", "▼ -8.0%")


def test_amount_up_etf_fund_size_own_currency():
    assert texts_of(row(etf_c(), PS, "Fund size")) == ("USD 500.0 m", "USD 2.5 bn", "▲ +400.0%")


@pytest.mark.parametrize("today", [100.04, 99.97], ids=["tiny_up", "tiny_down"])
def test_amount_zero_at_one_decimal_is_no_change(today):
    s, f = saved_etf(), saved_etf()
    f.fetched_at, f.price = TODAY_AT, today
    assert row(compare(s, f), PS, "Price").change == "no change"


@pytest.mark.parametrize("saved_price", [0.0, -1.0], ids=["zero", "negative"])
def test_amount_saved_zero_or_negative_is_na(saved_price):
    s, f = saved_stock(), fresh_stock()
    s.price = saved_price
    s.valuation["price"] = saved_price
    assert row(compare(s, f), PS, "Price").change == "n/a"


@pytest.mark.parametrize("saved_cap", [0.0, -5.0e9], ids=["zero", "negative"])
def test_amount_saved_zero_or_negative_market_cap_is_na(saved_cap):
    s, f = saved_stock(), fresh_stock()
    s.market_cap = s.company["market_cap"] = s.valuation["market_cap"] = saved_cap
    assert row(compare(s, f), PS, "Market cap").change == "n/a"


def test_amount_penny_price_three_decimals():
    s, f = saved_stock(), fresh_stock()
    s.price, f.price = 0.250, 0.285
    s.valuation["price"], f.valuation["price"] = 0.250, 0.285
    assert texts_of(row(compare(s, f), PS, "Price")) == ("0.250 MYR", "0.285 MYR", "▲ +14.0%")


# ---------- multiples: difference, two decimals ----------
def test_multiple_up_pe():
    assert texts_of(row(stock_c(), VAL, "P/E")) == ("12.0", "13.4", "▲ +1.40")


def test_multiple_down_forward_pe():
    assert texts_of(row(stock_c(), VAL, "Forward P/E")) == ("11.0", "10.8", "▼ -0.20")


def test_multiple_equal_pb_no_change():
    assert texts_of(row(stock_c(), VAL, "P/B")) == ("1.3", "1.3", "no change")


def test_multiple_one_sided_ev_ebitda_today_missing():
    assert texts_of(row(stock_c(), VAL, "EV/EBITDA")) == ("9.8x", "n/a", "n/a")


def test_multiple_zero_at_two_decimals_is_no_change():
    s, f = saved_stock(), fresh_stock()
    s.valuation["pe"], f.valuation["pe"] = 12.0, 12.004
    assert row(compare(s, f), VAL, "P/E").change == "no change"


def test_multiple_saved_missing_today_present():
    s, f = saved_stock(), fresh_stock()
    s.valuation["pe"] = None
    assert texts_of(row(compare(s, f), VAL, "P/E")) == ("n/a", "13.4", "n/a")


def test_multiple_missing_on_both_sides_row_left_out():
    s, f = saved_stock(), fresh_stock()
    s.valuation["pe"] = f.valuation["pe"] = None
    assert "P/E" not in [m.figure for m in compare(s, f).rows]


# ---------- percents: points between the displayed percentages ----------
def test_percent_down_dividend_yield_points():
    assert texts_of(row(stock_c(), VAL, "Dividend yield")) == ("4.50%", "4.32%", "▼ -0.18 points")


def test_percent_points_from_displayed_not_raw_values():
    """4.504% shows as 4.50%, 5.696% as 5.70%: the change is 5.70 - 4.50 = +1.20 points (raw would say +1.19)."""
    s, f = saved_stock(), fresh_stock()
    s.valuation["dividend_yield"], f.valuation["dividend_yield"] = 0.04504, 0.05696
    assert texts_of(row(compare(s, f), VAL, "Dividend yield")) == ("4.50%", "5.70%", "▲ +1.20 points")


def test_percent_zero_at_display_is_no_change():
    s, f = saved_stock(), fresh_stock()
    s.valuation["dividend_yield"], f.valuation["dividend_yield"] = 0.0450, 0.04501
    assert row(compare(s, f), VAL, "Dividend yield").change == "no change"


def test_percent_up_return_signed_display():
    assert texts_of(row(stock_c(), RR, R1)) == ("+12.3%", "+15.5%", "▲ +3.20 points")


def test_percent_equal_return_no_change():
    assert texts_of(row(stock_c(), RR, R3)) == ("+40.0%", "+40.0%", "no change")


def test_percent_down_volatility():
    assert texts_of(row(stock_c(), RR, VOL)) == ("18.4%", "17.2%", "▼ -1.20 points")


def test_percent_down_max_drawdown():
    assert texts_of(row(stock_c(), RR, MDD)) == ("-22.1%", "-25.0%", "▼ -2.90 points")


def test_percent_return_missing_on_both_sides_row_left_out():
    assert R5 not in [m.figure for m in stock_c().rows]


def test_percent_one_sided_etf_5y_return():
    assert texts_of(row(etf_c(), RR, R5)) == ("+50.0%", "n/a", "n/a")


def test_percent_down_etf_return_points():
    assert texts_of(row(etf_c(), RR, R1)) == ("+20.0%", "+15.0%", "▼ -5.00 points")


def test_percent_down_expense_ratio_points():
    assert texts_of(row(etf_c(), COSTS, "Expense ratio")) == ("0.07%", "0.06%", "▼ -0.01 points")


def test_percent_up_distribution_yield_points():
    assert texts_of(row(etf_c(), COSTS, "Distribution yield")) == ("1.80%", "2.00%", "▲ +0.20 points")


def test_figure_rows_have_empty_note():
    for m in stock_c().rows + etf_c().rows:
        if m.section in (PS, VAL, RR, COSTS):
            assert m.note == "", (m.figure, m.note)


def test_change_texts_say_direction_only():
    """No good / bad word anywhere in the result; the arrow is the only mark of direction."""
    words = ("good", "bad", "better", "worse", "improv", "deteriorat")
    for m in stock_c().rows + etf_c().rows:
        if m.section != LT:
            assert not any(w in m.change.lower() for w in words), m.change
            assert m.change in ("no change", "n/a") or m.change[:2] in ("▲ ", "▼ "), m.change


# ---------- credit health: newest column, labels shown, change from the floats ----------
CREDIT_WANT = {DE: ("0.60", "0.85", "▲ +0.25"), ND: ("1.5x", "net cash", "n/a"), IC: ("5.0x", "6.4x", "▲ +1.40"),
               CR: ("1.50", "1.50", "no change"), OCF: ("0.25", "0.20", "▼ -0.05"),
               FCF: ("-5.0%", "2.0%", "▲ +7.00 points"), NM: ("10.0%", "14.5%", "▲ +4.50 points"),
               ROE: ("10.0%", "10.0%", "no change"), GR: ("8.0%", "5.0%", "▼ -3.00 points")}


@pytest.mark.parametrize("name", list(CREDIT_WANT))
def test_credit_row_texts_and_change(name):
    assert texts_of(row(stock_c(), CH, name)) == CREDIT_WANT[name]


def test_credit_both_sides_na_row_left_out():
    """v3.1: Revenue growth empty ("n/a", NaN) in every period on both sides: the row is still left out."""
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["TTM", YEAR], SAVED_CREDIT, {GR: (NAN, "n/a")})
    set_credit(f, ["TTM", YEAR], FRESH_CREDIT, {GR: (NAN, "n/a")})
    del s.lights[GR], f.lights[GR]  # v4.2: a light on either side keeps the row
    assert GR not in [m.figure for m in compare(s, f).rows if m.section == CH]


def test_credit_same_newest_period_note_empty():
    """v3.1: every ratio read from TTM on both sides has note ""; Revenue growth (read from the year on both
    sides, which is not either side's newest period) carries the period note."""
    notes = {m.figure: m.note for m in stock_c().rows if m.section == CH}
    assert notes.pop(GR) == f"saved: {YEAR}, today: {YEAR}"
    assert set(notes.values()) == {""}, notes


def test_credit_different_newest_periods_note_and_change_still_shown():
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["2026-07-31", "2025-07-31"], SAVED_CREDIT)
    m = row(compare(s, f), CH, DE)
    assert m.note == "saved: 2026-07-31, today: TTM"
    assert texts_of(m) == ("0.60", "0.85", "▲ +0.25")


def test_credit_two_year_ends_note():
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["2025-07-31", "2024-07-31"], SAVED_CREDIT)
    set_credit(f, ["2026-07-31", "2025-07-31"], FRESH_CREDIT)
    assert row(compare(s, f), CH, IC).note == "saved: 2025-07-31, today: 2026-07-31"


def test_credit_reads_the_newest_column_only():
    """Older columns hold 99.0 / "99.00" in these fixtures; none of them may show."""
    for m in stock_c().rows:
        if m.section == CH:
            assert "99" not in m.saved + m.today + m.change, m


def test_credit_today_without_periods_is_na():
    s, f = saved_stock(), fresh_stock()
    set_credit(f, [], {})
    m = row(compare(s, f), CH, DE)
    assert (m.saved, m.today, m.change) == ("0.60", "n/a", "n/a")


# ---------- lights ----------
def light_row(c, name):
    m = row(c, LT, name)
    return (m.saved, m.today, m.change, m.note)


def test_light_changed_green_to_amber_with_today_reason():
    assert light_row(stock_c(), DE) == ("green", "amber", "green → amber", FRESH_LIGHTS[DE][1])


def test_light_changed_amber_to_green():
    assert light_row(stock_c(), IC) == ("amber", "green", "amber → green", FRESH_LIGHTS[IC][1])


def test_light_equal_no_change_with_today_reason():
    assert light_row(stock_c(), ND) == ("green", "green", "no change", FRESH_LIGHTS[ND][1])


def test_light_grey_is_a_colour_word():
    assert light_row(stock_c(), GR) == ("grey", "grey", "no change", FRESH_LIGHTS[GR][1])


def test_overall_light_row_last():
    c = stock_c()
    assert (c.rows[-1].section, c.rows[-1].figure) == (LT, "Overall")
    assert light_row(c, "Overall") == ("amber", "amber", "no change",
                                       "worst: Debt / Equity 0.85 (TTM): moderate borrowing against equity")


def test_light_only_saved_keeps_row_with_saved_reason():
    s, f = saved_stock(), fresh_stock()
    del f.lights[ROE]
    assert light_row(compare(s, f), ROE) == ("amber", "n/a", "n/a", SAVED_LIGHTS[ROE][1])


def test_light_only_today_keeps_row_with_today_reason():
    s, f = saved_stock(), fresh_stock()
    del s.lights[FCF]
    assert light_row(compare(s, f), FCF) == ("n/a", "amber", "n/a", FRESH_LIGHTS[FCF][1])


def test_light_on_neither_side_row_left_out():
    s, f = saved_stock(), fresh_stock()
    del s.lights[GR], f.lights[GR]
    assert GR not in [m.figure for m in compare(s, f).rows if m.section == LT]


def test_etf_lights_and_overall():
    c = etf_c()
    assert light_row(c, "Expense ratio") == ("green", "green", "no change", "Expense ratio 0.06%: cheap to hold")
    assert light_row(c, "Fund size") == ("amber", "green", "amber → green", "Fund size USD 2.5 bn: large and liquid")
    assert light_row(c, "Overall")[:3] == ("amber", "green", "amber → green")


def test_financial_grey_lights_flow_through():
    s, f = saved_stock(), fresh_stock()
    for r in (s, f):
        r.is_financial = True
        r.overall = rd.Light("grey", rd.BANK_LINE)
    assert light_row(compare(s, f), "Overall") == ("grey", "grey", "no change", rd.BANK_LINE)


# ---------- None, NaN, numpy, missing keys ----------
def test_nan_saved_counts_as_no_value():
    s, f = saved_stock(), fresh_stock()
    s.valuation["pe"] = NAN
    assert texts_of(row(compare(s, f), VAL, "P/E")) == ("n/a", "13.4", "n/a")


def test_nan_on_both_sides_row_left_out():
    s, f = saved_stock(), fresh_stock()
    s.valuation["pb"] = NAN
    f.valuation["pb"] = np.float64("nan")
    assert "P/B" not in [m.figure for m in compare(s, f).rows]


def test_numpy_scalars_are_values():
    s, f = saved_stock(), fresh_stock()
    s.price, f.price = np.float64(5.0), np.float64(5.4)
    s.valuation["pe"], f.valuation["pe"] = np.float64(12.0), np.float64(13.4)
    s.market_cap, f.market_cap = np.int64(20_000_000_000), np.int64(19_360_000_000)
    s.company["market_cap"], f.company["market_cap"] = s.market_cap, f.market_cap
    c = compare(s, f)
    assert texts_of(row(c, PS, "Price")) == ("5.00 MYR", "5.40 MYR", "▲ +8.0%")
    assert texts_of(row(c, VAL, "P/E")) == ("12.0", "13.4", "▲ +1.40")
    assert texts_of(row(c, PS, "Market cap")) == ("RM 20.0 bn", "RM 19.4 bn", "▼ -3.2%")


def test_nan_in_returns_and_numpy_nan_volatility():
    s, f = saved_stock(), fresh_stock()
    s.company["returns"]["1y"] = NAN
    f.company["volatility_3y"] = np.float64("nan")
    c = compare(s, f)
    assert texts_of(row(c, RR, R1)) == ("n/a", "+15.5%", "n/a")
    assert texts_of(row(c, RR, VOL)) == ("18.4%", "n/a", "n/a")


def test_missing_keys_do_not_raise():
    s, f = saved_stock(), fresh_stock()
    del s.valuation["forward_pe"]
    del f.company["returns"]["3y"]
    c = compare(s, f)
    assert texts_of(row(c, VAL, "Forward P/E")) == ("n/a", "10.8", "n/a")
    assert texts_of(row(c, RR, R3)) == ("+40.0%", "n/a", "n/a")


def test_etf_none_figures_do_not_raise():
    s, f = saved_etf(), fresh_etf()
    s.etf["expense_ratio"] = None
    f.etf["fund_size"] = None
    f.etf["fund_size_myr"] = None
    c = compare(s, f)
    assert texts_of(row(c, COSTS, "Expense ratio")) == ("n/a", "0.06%", "n/a")
    assert texts_of(row(c, PS, "Fund size")) == ("USD 500.0 m", "n/a", "n/a")


# ---------- notes ----------
def test_kind_mismatch_stock_then_etf():
    c = compare(saved_stock(), fresh_etf())
    assert c.rows == [] and c.notes == [KINDS_NOTE]


def test_kind_mismatch_etf_then_stock():
    c = compare(saved_etf(), fresh_stock())
    assert c.rows == [] and c.notes == [KINDS_NOTE]


def test_kind_mismatch_company_missing_on_one_side():
    f = fresh_stock()
    f.company = None
    c = compare(saved_stock(), f)
    assert c.rows == [] and c.notes == [KINDS_NOTE]


def test_same_fetch_note():
    s, f = saved_stock(), saved_stock()
    c = compare(s, f)
    assert SAME_FETCH_NOTE in c.notes
    assert c.rows and {m.change for m in c.rows} == {"no change"}


def test_no_same_fetch_note_when_times_differ():
    assert SAME_FETCH_NOTE not in stock_c().notes


def test_stale_today_note():
    f = fresh_stock()
    f.stale, f.fetched_at = True, datetime(2026, 11, 15, 8, 5)
    c = compare(saved_stock(), f)
    assert c.notes == ["Yahoo could not be reached; the Today column shows figures fetched 2026-11-15 08:05."]
    assert c.today_on == date(2026, 11, 15)


def test_saved_stale_alone_gives_no_note():
    s = saved_stock()
    s.stale = True
    assert compare(s, fresh_stock()).notes == []


# ---------- purity ----------
def state(r):
    import research_store
    return json.dumps(research_store.to_doc(r, "", date(2026, 11, 16)), sort_keys=True, default=str)


def test_inputs_not_mutated():
    s, f = saved_stock(), fresh_stock()
    before = state(s), state(f)
    compare(s, f)
    assert (state(s), state(f)) == before


def test_etf_inputs_not_mutated():
    s, f = saved_etf(), fresh_etf()
    before = state(s), state(f)
    compare(s, f)
    assert (state(s), state(f)) == before


def test_deterministic():
    assert stock_c() == stock_c()
    assert etf_c() == etf_c()


def test_no_yahoo_cache_file_or_clock(monkeypatch):
    s, f = saved_stock(), fresh_stock()
    fn = rd.compare

    def boom(*a, **k):
        raise AssertionError("compare reached Yahoo, the cache, a file or the clock")

    for name in ("research", "fetch_raw", "fetch_fx", "load_cache", "save_cache", "analyse"):
        monkeypatch.setattr(rd, name, boom)

    class NoClock(datetime):
        now = today = utcnow = classmethod(boom)

    monkeypatch.setattr(rd, "datetime", NoClock)
    monkeypatch.setattr(builtins, "open", boom)
    for name in ("open", "read_text", "write_text", "read_bytes", "write_bytes", "exists", "mkdir"):
        monkeypatch.setattr(Path, name, boom)
    c = fn(s, f)
    monkeypatch.undo()
    assert c.rows


def compare_source():
    tree = ast.parse((ROOT / "research_data.py").read_text(encoding="utf-8"))
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "compare"), None)
    assert fn is not None, "research_data.py has no compare()"
    return ast.unparse(fn)


def test_compare_source_uses_no_streamlit_or_io():
    src = compare_source()
    for bad in ("streamlit", "research(", "load_cache", "save_cache", "fetch_raw", "open(", ".now(", "CACHE_DIR"):
        assert bad not in src, bad



# ---------- round 1b: v2 rulings (2026-11-16) ----------
# v2.4: multiples and plain ratios change by the difference of the DISPLAYED values; amounts stay relative on raw.
def test_v2_multiple_change_from_displayed_values():
    """12.04 shows "12.0", 13.46 shows "13.5": the change is 13.5 - 12.0 = +1.50 (raw would say +1.42)."""
    s, f = saved_stock(), fresh_stock()
    s.valuation["pe"], f.valuation["pe"] = 12.04, 13.46
    assert texts_of(row(compare(s, f), VAL, "P/E")) == ("12.0", "13.5", "▲ +1.50")


def test_v2_multiple_same_display_is_no_change():
    """9.84 and 9.76 both show "9.8x": no change (raw would say -0.08)."""
    s, f = saved_stock(), fresh_stock()
    s.valuation["ev_ebitda"], f.valuation["ev_ebitda"] = 9.84, 9.76
    assert texts_of(row(compare(s, f), VAL, "EV/EBITDA")) == ("9.8x", "9.8x", "no change")


def test_v2_credit_plain_ratio_change_from_displayed_values():
    """Debt / Equity 0.604 shows "0.60", 0.856 shows "0.86": +0.26 (raw would say +0.25)."""
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["TTM", "2026-07-31"], dict(SAVED_CREDIT, **{DE: (0.604, "0.60")}))
    set_credit(f, ["TTM", "2026-07-31"], dict(FRESH_CREDIT, **{DE: (0.856, "0.86")}))
    assert texts_of(row(compare(s, f), CH, DE)) == ("0.60", "0.86", "▲ +0.26")


def test_v2_credit_multiple_change_from_displayed_values():
    """Interest cover 5.04x shows "5.0x", 6.46x shows "6.5x": +1.50 (raw would say +1.42)."""
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["TTM", "2026-07-31"], dict(SAVED_CREDIT, **{IC: (5.04, "5.0x")}))
    set_credit(f, ["TTM", "2026-07-31"], dict(FRESH_CREDIT, **{IC: (6.46, "6.5x")}))
    assert texts_of(row(compare(s, f), CH, IC)) == ("5.0x", "6.5x", "▲ +1.50")


def test_v2_percent_change_from_displayed_values_return():
    """+12.34% shows "+12.3%", +15.56% shows "+15.6%": +3.30 points (raw would say +3.22)."""
    s, f = saved_stock(), fresh_stock()
    s.company["returns"]["1y"], f.company["returns"]["1y"] = 0.1234, 0.1556
    assert texts_of(row(compare(s, f), RR, R1)) == ("+12.3%", "+15.6%", "▲ +3.30 points")


def test_v2_amount_change_stays_relative_on_raw_values():
    """0.2504 shows "0.250", 0.2846 shows "0.285": raw 0.2846 / 0.2504 - 1 = +13.7% (the displayed values would
    give +14.0%)."""
    s, f = saved_stock(), fresh_stock()
    s.price, f.price = 0.2504, 0.2846
    s.valuation["price"], f.valuation["price"] = 0.2504, 0.2846
    assert texts_of(row(compare(s, f), PS, "Price")) == ("0.250 MYR", "0.285 MYR", "▲ +13.7%")


# v2.5: a label but no number on either side: row kept, change n/a
def test_v2_credit_label_without_number_on_both_sides_row_kept():
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["TTM", "2026-07-31"], dict(SAVED_CREDIT, **{ND: (NAN, "net cash")}))
    m = row(compare(s, f), CH, ND)
    assert texts_of(m) == ("net cash", "net cash", "n/a")


# v2.6: one side without periods: note ""
def test_v2_credit_note_empty_when_today_has_no_periods():
    s, f = saved_stock(), fresh_stock()
    set_credit(f, [], {})
    assert row(compare(s, f), CH, DE).note == ""


def test_v2_credit_note_empty_when_saved_has_no_periods():
    s, f = saved_stock(), fresh_stock()
    set_credit(s, [], {})
    m = row(compare(s, f), CH, DE)
    assert (m.saved, m.today, m.change, m.note) == ("n/a", "0.85", "n/a", "")


# v2.7: neither company nor etf on both sides: different kinds
def test_v2_no_company_and_no_etf_on_both_sides_is_different_kinds():
    s, f = saved_stock(), fresh_stock()
    s.company = f.company = None
    c = compare(s, f)
    assert c.rows == [] and c.notes == [KINDS_NOTE]


# ---------- round 1c: mutation survivors (ruling 2026-11-16) ----------
# M2 (v2.1): the shared pct keeps its blank argument, as the layout's pct did before the move.
def test_r1c_shared_pct_blank_argument():
    assert rd.pct(None, blank="") == ""
    assert rd.pct(NAN, blank="-") == "-"
    assert rd.pct(np.float64("nan"), places=2, sign=True, blank="--") == "--"
    assert rd.pct(None) == "n/a"
    assert rd.pct(0.123, blank="") == "12.3%"


# M6 (v2.1): a missing currency reads "n/a" after the price, as the layout's priced (through shown) did.
def test_r1c_shared_priced_without_currency():
    assert rd.priced(5.0, None) == "5.00 n/a"
    assert rd.priced(0.285, None) == "0.285 n/a"
    assert rd.priced(None, None) == "n/a"
    assert rd.priced(5.0, "MYR") == "5.00 MYR"


def test_r1c_compare_price_without_currency():
    s, f = saved_stock(), fresh_stock()
    s.currency = None
    c = compare(s, f)
    # Round 2b (ruled 2026-11-16): a missing currency is not "different"; the change is worked out as usual.
    assert texts_of(row(c, PS, "Price")) == ("5.00 n/a", "5.40 MYR", "▲ +8.0%")


# M45: the same-fetch note needs the full fetched_at to match, not just the date.
def test_r1c_no_same_fetch_note_same_day_different_time():
    s, f = saved_stock(), fresh_stock()
    s.fetched_at, f.fetched_at = datetime(2026, 11, 16, 9, 0), datetime(2026, 11, 16, 15, 0)
    c = compare(s, f)
    assert SAME_FETCH_NOTE not in c.notes
    assert c.notes == []


def test_r1c_no_same_fetch_note_one_second_apart():
    s, f = saved_stock(), saved_stock()
    s.fetched_at, f.fetched_at = datetime(2026, 11, 16, 9, 0, 0), datetime(2026, 11, 16, 9, 0, 1)
    assert compare(s, f).notes == []


def test_r1c_same_fetch_note_on_exact_same_time_same_day():
    s, f = saved_stock(), fresh_stock()
    s.fetched_at = f.fetched_at = datetime(2026, 11, 16, 9, 0)
    assert compare(s, f).notes == [SAME_FETCH_NOTE]


# M64: an ETF comparison has no Credit health rows, even when its result carries statement periods.
def test_r1c_etf_with_statement_periods_still_has_no_credit_rows():
    s, f = saved_etf(), fresh_etf()
    set_credit(s, ["TTM"], SAVED_CREDIT)
    set_credit(f, ["TTM"], FRESH_CREDIT)
    s.lights = {k: rd.Light(*v) for k, v in SAVED_LIGHTS.items()}
    f.lights = {k: rd.Light(*v) for k, v in FRESH_LIGHTS.items()}
    c = compare(s, f)
    assert CH not in {m.section for m in c.rows}
    assert [(m.section, m.figure) for m in c.rows] == ETF_ORDER
    assert not any(m.figure in rd.RATIOS for m in c.rows)


# ---------- round 2: v3 rulings (2026-11-16) ----------
# v3.1: per ratio and per side, the newest period with a number or a label other than "n/a" (else that side's
# newest); note whenever the two periods used differ or either is not its side's newest period.
def test_v3_revenue_growth_empty_ttm_both_sides_uses_the_year():
    m = row(stock_c(), CH, GR)
    assert (m.saved, m.today, m.change, m.note) == ("8.0%", "5.0%", "▼ -3.00 points", f"saved: {YEAR}, today: {YEAR}")


def test_v3_revenue_growth_row_sits_with_the_credit_rows():
    ch = [m.figure for m in stock_c().rows if m.section == CH]
    assert ch == rd.RATIOS


def test_v3_empty_ttm_on_saved_side_only():
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["TTM", YEAR], dict(SAVED_CREDIT, **{IC: (NAN, "n/a")}), dict(SAVED_OLDER, **{IC: (4.0, "4.0x")}))
    light_on(s, IC, YEAR, "4.0x")  # v4: the light was judged on the year, so the figure is read there
    m = row(compare(s, f), CH, IC)
    assert (m.saved, m.today, m.change, m.note) == ("4.0x", "6.4x", "▲ +2.40", f"saved: {YEAR}, today: TTM")


def test_v3_empty_ttm_on_today_side_only():
    s, f = saved_stock(), fresh_stock()
    set_credit(f, ["TTM", YEAR], dict(FRESH_CREDIT, **{DE: (NAN, "n/a")}), dict(FRESH_OLDER, **{DE: (0.70, "0.70")}))
    light_on(f, DE, YEAR, "0.70")  # v4: the light was judged on the year
    m = row(compare(s, f), CH, DE)
    assert (m.saved, m.today, m.change, m.note) == ("0.60", "0.70", "▲ +0.10", f"saved: TTM, today: {YEAR}")


def test_v3_label_only_newest_cell_counts_as_filled():
    """"net cash" with no number is a label other than "n/a": TTM is used, the 99 sentinel year is not."""
    m = row(stock_c(), CH, ND)
    assert (m.saved, m.today, m.change, m.note) == ("1.5x", "net cash", "n/a", "")


def test_v3_one_side_empty_in_every_period_falls_back_to_its_newest():
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["TTM", YEAR], SAVED_CREDIT, {GR: (NAN, "n/a")})
    m = row(compare(s, f), CH, GR)
    # v4 (round 3): the saved light names the year, so the saved cell is that year's "n/a", not the newest TTM.
    assert (m.saved, m.today, m.change, m.note) == ("n/a", "5.0%", "n/a", f"saved: {YEAR}, today: {YEAR}")


def test_v3_all_periods_empty_both_sides_row_absent():
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["TTM", YEAR], dict(SAVED_CREDIT, **{IC: (NAN, "n/a")}), dict(SAVED_OLDER, **{IC: (NAN, "n/a")}))
    set_credit(f, ["TTM", YEAR], dict(FRESH_CREDIT, **{IC: (NAN, "n/a")}), dict(FRESH_OLDER, **{IC: (NAN, "n/a")}))
    del s.lights[IC], f.lights[IC]  # v4.2: a light on either side keeps the row
    assert IC not in [m.figure for m in compare(s, f).rows if m.section == CH]


def test_v3_ttm_against_ttm_note_empty():
    m = row(stock_c(), CH, DE)
    assert (m.saved, m.today, m.change, m.note) == ("0.60", "0.85", "▲ +0.25", "")


def test_v3_used_year_differs_from_newest_year_on_both_sides():
    """Both sides' newest column is TTM, both fall back to the same year: the note still names the year."""
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["TTM", YEAR], dict(SAVED_CREDIT, **{CR: (NAN, "n/a")}), dict(SAVED_OLDER, **{CR: (1.20, "1.20")}))
    set_credit(f, ["TTM", YEAR], dict(FRESH_CREDIT, **{CR: (NAN, "n/a")}), dict(FRESH_OLDER, **{CR: (1.35, "1.35")}))
    light_on(s, CR, YEAR, "1.20")
    light_on(f, CR, YEAR, "1.35")
    m = row(compare(s, f), CH, CR)
    assert (m.saved, m.today, m.change, m.note) == ("1.20", "1.35", "▲ +0.15", f"saved: {YEAR}, today: {YEAR}")


# v3.2: amount rows whose two sides are in different currencies: change "n/a", cells unchanged.
def test_v3_stock_price_different_currencies_change_na():
    s, f = saved_stock(), fresh_stock()
    f.currency = "USD"
    assert texts_of(row(compare(s, f), PS, "Price")) == ("5.00 MYR", "5.40 USD", "n/a")


def test_v3_stock_market_cap_different_currencies_change_na():
    s, f = saved_stock(), fresh_stock()
    f.currency = "USD"
    assert texts_of(row(compare(s, f), PS, "Market cap")) == ("RM 20.0 bn", "USD 19.4 bn", "n/a")


def test_v3_analyst_target_different_currencies_change_na():
    s, f = saved_stock(), fresh_stock()
    s.valuation["target_mean"] = 5.5
    f.currency = "USD"
    assert texts_of(row(compare(s, f), VAL, "Analyst target")) == ("5.50 MYR", "6.00 USD", "n/a")


def test_v3_analyst_target_same_currency_still_relative():
    s, f = saved_stock(), fresh_stock()
    s.valuation["target_mean"] = 5.5
    assert texts_of(row(compare(s, f), VAL, "Analyst target")) == ("5.50 MYR", "6.00 MYR", "▲ +9.1%")


def test_v3_currency_rule_leaves_multiples_and_percents_alone():
    s, f = saved_stock(), fresh_stock()
    f.currency = "USD"
    c = compare(s, f)
    assert row(c, VAL, "P/E").change == "▲ +1.40"
    assert row(c, VAL, "Dividend yield").change == "▼ -0.18 points"


def test_v3_etf_fund_size_different_fund_currencies_change_na():
    s, f = saved_etf(), fresh_etf()
    f.etf["currency"] = "EUR"
    c = compare(s, f)
    assert texts_of(row(c, PS, "Fund size")) == ("USD 500.0 m", "EUR 2.5 bn", "n/a")
    assert texts_of(row(c, PS, "Price")) == ("100.00 USD", "92.00 USD", "▼ -8.0%")


def test_v3_etf_price_different_quote_currencies_change_na():
    s, f = saved_etf(), fresh_etf()
    f.currency = "EUR"
    c = compare(s, f)
    assert texts_of(row(c, PS, "Price")) == ("100.00 USD", "92.00 EUR", "n/a")
    assert texts_of(row(c, PS, "Fund size")) == ("USD 500.0 m", "USD 2.5 bn", "▲ +400.0%")


# ---------- round 2b: mutation-r2 survivors (ruling 2026-11-16) ----------
# v3.1 note: either used period not its own side's newest -> note, even when the two used periods are equal.
def test_r2b_saved_falls_back_to_the_year_today_newest_is_that_year():
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["TTM", YEAR], dict(SAVED_CREDIT, **{IC: (NAN, "n/a")}), dict(SAVED_OLDER, **{IC: (4.0, "4.0x")}))
    set_credit(f, [YEAR], FRESH_CREDIT)
    light_on(s, IC, YEAR, "4.0x")
    m = row(compare(s, f), CH, IC)
    assert (m.saved, m.today, m.change, m.note) == ("4.0x", "6.4x", "▲ +2.40", f"saved: {YEAR}, today: {YEAR}")


def test_r2b_today_falls_back_to_the_year_saved_newest_is_that_year():
    s, f = saved_stock(), fresh_stock()
    set_credit(s, [YEAR], SAVED_CREDIT)
    set_credit(f, ["TTM", YEAR], dict(FRESH_CREDIT, **{DE: (NAN, "n/a")}), dict(FRESH_OLDER, **{DE: (0.70, "0.70")}))
    light_on(f, DE, YEAR, "0.70")
    m = row(compare(s, f), CH, DE)
    assert (m.saved, m.today, m.change, m.note) == ("0.60", "0.70", "▲ +0.10", f"saved: {YEAR}, today: {YEAR}")


def test_r2b_both_use_their_own_equal_newest_year_note_empty():
    s, f = saved_stock(), fresh_stock()
    set_credit(s, [YEAR], SAVED_CREDIT)
    set_credit(f, [YEAR], FRESH_CREDIT)
    m = row(compare(s, f), CH, IC)
    assert (m.saved, m.today, m.change, m.note) == ("5.0x", "6.4x", "▲ +1.40", "")


# v3.2 as ruled: a currency that is None or "" on one side only is not "different".
def test_r2b_stock_price_today_currency_missing_still_changes():
    s, f = saved_stock(), fresh_stock()
    f.currency = None
    assert texts_of(row(compare(s, f), PS, "Price")) == ("5.00 MYR", "5.40 n/a", "▲ +8.0%")


@pytest.mark.parametrize("side", ["saved", "today"])
def test_r2b_stock_market_cap_empty_currency_one_side_still_changes(side):
    s, f = saved_stock(), fresh_stock()
    (s if side == "saved" else f).currency = ""
    assert row(compare(s, f), PS, "Market cap").change == "▼ -3.2%"


@pytest.mark.parametrize("side,ccy", [("saved", None), ("today", None), ("saved", ""), ("today", "")])
def test_r2b_etf_fund_size_missing_fund_currency_one_side_still_changes(side, ccy):
    s, f = saved_etf(), fresh_etf()
    (s if side == "saved" else f).etf["currency"] = ccy
    m = row(compare(s, f), PS, "Fund size")
    want = ("500.0 m", "USD 2.5 bn") if side == "saved" else ("USD 500.0 m", "2.5 bn")
    assert texts_of(m) == (*want, "▲ +400.0%")


# ---------- round 3: v4 rulings (2026-11-16) ----------
# v4.1: per ratio and per side the Credit health row uses the period its own light names ("(<period>)" in the
# reason, first match in that side's periods); else TTM when filled, else the newest fiscal year, else the newest
# period. The cell shows that period's label as it is; the search never walks on to an older year.
OLD = "2025-07-31"
NA = (NAN, "n/a")


def three(r, credit, cells):
    """periods TTM, YEAR, OLD; credit fills TTM; cells {ratio: (ttm, year, old)} override the three columns."""
    set_credit(r, ["TTM", YEAR, OLD], credit)
    for name, cols in cells.items():
        for p, (v, label) in zip(r.periods, cols):
            r.ratios.loc[name, p] = v
            r.labels.loc[name, p] = label


def credit_texts(c, name):
    m = row(c, CH, name)
    return (m.saved, m.today, m.change, m.note)


def test_v4_light_on_ttm_with_a_number():
    s, f = saved_stock(), fresh_stock()
    three(s, SAVED_CREDIT, {})
    three(f, FRESH_CREDIT, {})
    assert credit_texts(compare(s, f), DE) == ("0.60", "0.85", "▲ +0.25", "")


def test_v4_light_on_ttm_blank_on_purpose_never_shows_an_older_year():
    """The reviewer's case: Net debt / EBITDA "n/a" at TTM and at the newest year (EBITDA negative), "0.8x" two
    years back; the red light was judged on TTM. The cell stays "n/a"; the row stays because a light exists."""
    s, f = saved_stock(), fresh_stock()
    for r, credit in ((s, SAVED_CREDIT), (f, FRESH_CREDIT)):
        three(r, credit, {ND: (NA, NA, (0.8, "0.8x"))})
        r.lights[ND] = rd.Light("red", "Net debt / EBITDA n/a (TTM): EBITDA zero or negative")
    t = credit_texts(compare(s, f), ND)
    assert t == ("n/a", "n/a", "n/a", "")
    assert "0.8x" not in "".join(t)


def test_v4_lights_naming_different_periods_each_side_its_own():
    """Saved TTM holds a number (5.0x) but the saved light was judged on the year: the year's 4.0x is shown."""
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["TTM", YEAR], SAVED_CREDIT, dict(SAVED_OLDER, **{IC: (4.0, "4.0x")}))
    light_on(s, IC, YEAR, "4.0x")
    assert credit_texts(compare(s, f), IC) == ("4.0x", "6.4x", "▲ +2.40", f"saved: {YEAR}, today: TTM")


def test_v4_reason_naming_a_period_not_in_periods_falls_back_newest_year_not_older():
    s, f = saved_stock(), fresh_stock()
    three(s, SAVED_CREDIT, {DE: (NA, NA, (0.50, "0.50"))})
    s.lights[DE] = rd.Light("green", "Debt / Equity 0.50 (2023-07-31): low borrowing against equity")
    assert credit_texts(compare(s, f), DE) == ("n/a", "0.85", "n/a", f"saved: {YEAR}, today: TTM")


def test_v4_reason_naming_a_period_not_in_periods_ttm_filled_uses_ttm():
    s, f = saved_stock(), fresh_stock()
    s.lights[DE] = rd.Light("green", "Debt / Equity 0.50 (2023-07-31): low borrowing against equity")
    assert credit_texts(compare(s, f), DE) == ("0.60", "0.85", "▲ +0.25", "")


def test_v4_grey_light_without_a_period_falls_back_newest_year_not_older():
    s, f = saved_stock(), fresh_stock()
    three(s, SAVED_CREDIT, {GR: (NA, NA, (0.30, "30.0%"))})
    s.lights[GR] = rd.Light("grey", "Revenue growth n/a: no earlier year to compare")
    assert credit_texts(compare(s, f), GR) == ("n/a", "5.0%", "n/a", f"saved: {YEAR}, today: {YEAR}")


def test_v4_no_light_ttm_filled_uses_ttm():
    s, f = saved_stock(), fresh_stock()
    del s.lights[DE]
    assert credit_texts(compare(s, f), DE) == ("0.60", "0.85", "▲ +0.25", "")


def test_v4_no_light_ttm_empty_uses_the_newest_year():
    s, f = saved_stock(), fresh_stock()
    set_credit(f, ["TTM", YEAR], dict(FRESH_CREDIT, **{DE: NA}), dict(FRESH_OLDER, **{DE: (0.70, "0.70")}))
    del f.lights[DE]
    assert credit_texts(compare(s, f), DE) == ("0.60", "0.70", "▲ +0.10", f"saved: TTM, today: {YEAR}")


def test_v4_no_light_ttm_and_newest_year_empty_never_walks_to_an_older_year():
    s, f = saved_stock(), fresh_stock()
    three(s, SAVED_CREDIT, {DE: (NA, NA, (0.50, "0.50"))})
    del s.lights[DE]
    assert credit_texts(compare(s, f), DE) == ("n/a", "0.85", "n/a", f"saved: {YEAR}, today: TTM")


def test_v4_no_ttm_column_uses_the_newest_year_not_older():
    """The light names (TTM), which is not in this side's periods: fallback to the newest fiscal year."""
    s, f = saved_stock(), fresh_stock()
    set_credit(s, [YEAR, OLD], dict(SAVED_CREDIT, **{DE: NA}), {DE: (0.50, "0.50")})
    assert credit_texts(compare(s, f), DE) == ("n/a", "0.85", "n/a", f"saved: {YEAR}, today: TTM")


def test_v4_only_a_ttm_column_empty_uses_ttm():
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["TTM"], dict(SAVED_CREDIT, **{DE: NA}))
    del s.lights[DE]
    assert credit_texts(compare(s, f), DE) == ("n/a", "0.85", "n/a", "")


def test_v4_period_outside_brackets_is_not_matched():
    """The reason mentions "TTM" outside brackets and names "(2026-07-31)": the year is used, not TTM."""
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["TTM", YEAR], SAVED_CREDIT, dict(SAVED_OLDER, **{IC: (4.0, "4.0x")}))
    s.lights[IC] = rd.Light("amber", "Interest cover 4.0x (2026-07-31): TTM not yet filed")
    assert credit_texts(compare(s, f), IC) == ("4.0x", "6.4x", "▲ +2.40", f"saved: {YEAR}, today: TTM")


def test_v4_period_without_its_closing_bracket_is_not_matched():
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["TTM", YEAR], SAVED_CREDIT, dict(SAVED_OLDER, **{IC: (4.0, "4.0x")}))
    s.lights[IC] = rd.Light("amber", "Interest cover 4.0x (2026-07-31 restated): thin margin")
    assert credit_texts(compare(s, f), IC) == ("5.0x", "6.4x", "▲ +1.40", "")


# v4.2: row kept when either side has a number or a non-"n/a" label at its used period, or a light.
def test_v4_no_number_at_used_period_and_no_light_row_absent_even_with_older_numbers():
    s, f = saved_stock(), fresh_stock()
    three(s, SAVED_CREDIT, {CR: (NA, NA, (1.10, "1.10"))})
    three(f, FRESH_CREDIT, {CR: (NA, NA, (1.20, "1.20"))})
    del s.lights[CR], f.lights[CR]
    assert CR not in [m.figure for m in compare(s, f).rows if m.section == CH]


def test_v4_no_number_on_either_side_but_a_light_on_one_keeps_the_row():
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["TTM", YEAR], dict(SAVED_CREDIT, **{CR: NA}), dict(SAVED_OLDER, **{CR: NA}))
    set_credit(f, ["TTM", YEAR], dict(FRESH_CREDIT, **{CR: NA}), dict(FRESH_OLDER, **{CR: NA}))
    del f.lights[CR]  # saved light names (TTM); today falls back TTM "n/a" -> newest year
    assert credit_texts(compare(s, f), CR) == ("n/a", "n/a", "n/a", f"saved: TTM, today: {YEAR}")


# ---------- round 3b: the four accepted round-3 survivors (2026-11-16) ----------
def test_r3b_reason_naming_two_periods_uses_the_first_in_periods():
    """v4.1a: first entry of periods [TTM, YEAR, OLD] found in the reason, not the last, not the first in the text."""
    s, f = saved_stock(), fresh_stock()
    three(s, SAVED_CREDIT, {IC: ((5.0, "5.0x"), (4.0, "4.0x"), (3.0, "3.0x"))})
    s.lights[IC] = rd.Light("amber", f"Interest cover 3.0x ({OLD}) then 4.0x ({YEAR}): thin margin")
    assert credit_texts(compare(s, f), IC) == ("4.0x", "6.4x", "▲ +2.40", f"saved: {YEAR}, today: TTM")


def test_r3b_reason_naming_ttm_and_a_year_uses_ttm():
    s, f = saved_stock(), fresh_stock()
    three(s, SAVED_CREDIT, {IC: ((5.0, "5.0x"), (4.0, "4.0x"), (3.0, "3.0x"))})
    s.lights[IC] = rd.Light("amber", f"Interest cover 4.0x ({YEAR}), 5.0x (TTM): thin margin")
    assert credit_texts(compare(s, f), IC) == ("5.0x", "6.4x", "▲ +1.40", "")


def test_r3b_grey_light_naming_a_period_is_followed():
    """v4.1a: a grey light's period counts too; TTM is filled (0.60) but the grey light was judged on the year."""
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["TTM", YEAR], SAVED_CREDIT, dict(SAVED_OLDER, **{DE: (0.55, "0.55")}))
    s.lights[DE] = rd.Light("grey", f"Debt / Equity 0.55 ({YEAR}): not judged for a bank")
    assert credit_texts(compare(s, f), DE) == ("0.55", "0.85", "▲ +0.30", f"saved: {YEAR}, today: TTM")


def test_r3b_grey_light_on_today_side_naming_a_period_is_followed():
    s, f = saved_stock(), fresh_stock()
    set_credit(f, ["TTM", YEAR], FRESH_CREDIT, dict(FRESH_OLDER, **{DE: (0.70, "0.70")}))
    f.lights[DE] = rd.Light("grey", f"Debt / Equity 0.70 ({YEAR}): not judged for a bank")
    assert credit_texts(compare(s, f), DE) == ("0.60", "0.70", "▲ +0.10", f"saved: TTM, today: {YEAR}")


def test_r3b_no_light_ttm_label_only_uses_ttm():
    """v4.1b: TTM "net cash" (no number, label not "n/a") is filled, so the year's 1.2x is not used."""
    s, f = saved_stock(), fresh_stock()
    set_credit(f, ["TTM", YEAR], FRESH_CREDIT, dict(FRESH_OLDER, **{ND: (1.2, "1.2x")}))
    del f.lights[ND]
    assert credit_texts(compare(s, f), ND) == ("1.5x", "net cash", "n/a", "")


def test_r3b_light_naming_no_period_ttm_label_only_uses_ttm():
    s, f = saved_stock(), fresh_stock()
    set_credit(f, ["TTM", YEAR], FRESH_CREDIT, dict(FRESH_OLDER, **{ND: (1.2, "1.2x")}))
    f.lights[ND] = rd.Light("green", "Net debt / EBITDA net cash: cash exceeds debt")
    assert credit_texts(compare(s, f), ND) == ("1.5x", "net cash", "n/a", "")


def test_r3b_no_number_on_either_side_light_only_today_keeps_the_row():
    """v4.2: mirror of the saved-only case; a light on today's side alone keeps the row."""
    s, f = saved_stock(), fresh_stock()
    set_credit(s, ["TTM", YEAR], dict(SAVED_CREDIT, **{CR: NA}), dict(SAVED_OLDER, **{CR: NA}))
    set_credit(f, ["TTM", YEAR], dict(FRESH_CREDIT, **{CR: NA}), dict(FRESH_OLDER, **{CR: NA}))
    del s.lights[CR]  # today's light names (TTM); saved falls back TTM "n/a" -> newest year
    assert credit_texts(compare(s, f), CR) == ("n/a", "n/a", "n/a", f"saved: {YEAR}, today: TTM")
