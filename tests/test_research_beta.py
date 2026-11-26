"""WP-3.8 Beta against the home market index, data layer (spec v1, rules B1-B6, B9, B10). Fakes only: made-up
price paths whose daily returns are set by hand, so every beta below is worked out by hand. No network, no
workbook. New names (rd.beta, rd.beta_index, rd.beta_text, rd.BETA_INDEX, ...) are reached through the module
inside each test, so the file collects before the build and each test fails on its own."""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import research_data as rd  # noqa: E402
from test_research_data import (T0, empty_close, etf_info, etf_like, fake_stock_yf, fake_yf,  # noqa: E402
                                gamuda_stock, info_eq, stock_close, us_info)

NAN = float("nan")
KLCI = ("^KLSE", "FBM KLCI")
SPX = ("^GSPC", "S&P 500")
KLCI_WARNING = "Beta not available: no FBM KLCI prices from Yahoo."
SPX_WARNING = "Beta not available: no S&P 500 prices from Yahoo."
END = "2026-10-30"


# ---------- made-up price paths ----------
# The index's daily simple return on date k (k = 1, 2, ...) is CYCLE[k % 6]: +1.0%, -0.5%, 0, 0, +0.8%, -1.2%.
# A "stock" with multiplier m has daily return m x the index return on every date, so by hand
#   beta = cov(m r, r) / var(r) = m var(r) / var(r) = m      (var(r) > 0: the cycle is not constant).
# Dates k with k % 6 == 2 have a zero return INTO them and OUT of them (k % 6 == 3 is also zero), so the price
# there equals both neighbours: dropping such a date (a bad price) leaves every remaining return unchanged.
CYCLE = [-0.012, 0.010, 0.0, 0.0, 0.008, -0.005]  # CYCLE[k % 6]: k%6==1 -> +1.0%, 2 -> 0, 3 -> 0, ...


def bdays(n, end=END):
    return pd.bdate_range(end=end, periods=n)


def path(n, mult=1.0, end=END, start_price=100.0):
    """Close on n business days ending `end`; return into date k = mult(k) x CYCLE[k % 6].
    mult is a number or a function of the date."""
    idx = bdays(n, end)
    p, out = start_price, [start_price]
    for k in range(1, n):
        m = mult(idx[k]) if callable(mult) else mult
        p = p * (1 + m * CYCLE[k % 6])
        out.append(p)
    return pd.Series(out, index=idx, name="Close")


def beta(*a, **k):
    return rd.beta(*a, **k)  # AttributeError until WP-3.8 is built: the test fails, the file collects


# ---------- B1 which index ----------
def test_b1_settings_at_the_top():
    assert rd.BETA_INDEX == {"MY": KLCI, "US": SPX}
    assert rd.BETA_MIN_RETURNS == 250


@pytest.mark.parametrize("code,info", [
    ("5398.KL", {"quoteType": "EQUITY", "currency": "MYR"}),
    ("5398.KL", {}),
    ("5398.KL", None),  # the suffix alone decides
    ("0820EA.KL", {"quoteType": "ETF", "currency": "MYR"}),
], ids=["kl_equity", "kl_empty_info", "kl_none_info", "kl_etf"])
def test_b1_kl_code_is_klci(code, info):
    assert rd.beta_index(code, info) == KLCI
    assert rd.beta_index(code, info) == rd.BETA_INDEX["MY"]


@pytest.mark.parametrize("code,info", [
    ("AAPL", {"quoteType": "EQUITY", "currency": "USD"}),
    ("VT", {"quoteType": "ETF", "currency": "USD"}),
    ("BRK-B", {"quoteType": "EQUITY", "currency": "USD"}),  # a dash is not a dot: still a plain US code
], ids=["us_equity", "us_etf", "brk_b"])
def test_b1_plain_us_code_is_sp500(code, info):
    assert rd.beta_index(code, info) == SPX
    assert rd.beta_index(code, info) == rd.BETA_INDEX["US"]


@pytest.mark.parametrize("code,info", [
    ("0700.HK", {"quoteType": "EQUITY", "currency": "HKD"}),
    ("0700.HK", {"quoteType": "EQUITY", "currency": "USD"}),  # has a dot: not plain US whatever the currency
    ("D05.SI", {"quoteType": "EQUITY", "currency": "SGD"}),
    ("BTC-USD", {"quoteType": "CRYPTOCURRENCY", "currency": "USD"}),
    ("^KLSE", {"quoteType": "INDEX", "currency": "MYR"}),
    ("^GSPC", {"quoteType": "INDEX", "currency": "USD"}),
    ("MYR=X", {"quoteType": "CURRENCY", "currency": "MYR"}),
    ("AAPL", {"quoteType": "EQUITY", "currency": "EUR"}),
    ("AAPL", {"quoteType": "EQUITY"}),
    ("AAPL", {"currency": "USD"}),
    ("AAPL", {}),
    ("AAPL", None),
], ids=["hk", "hk_usd", "si", "crypto", "klse_itself", "gspc_itself", "fx", "eur", "no_ccy", "no_type",
        "empty_info", "none_info"])
def test_b1_anything_else_is_none(code, info):
    assert rd.beta_index(code, info) is None


# ---------- B2 the figure: hand values ----------
def test_b2_identical_is_one():
    i = path(400)
    assert beta(i, i.copy()) == pytest.approx(1.0, abs=1e-9)  # cov(r, r) / var(r) = 1


def test_b2_twice_the_index_is_two():
    assert beta(path(400, 2.0), path(400)) == pytest.approx(2.0, abs=1e-9)  # cov(2r, r) / var(r) = 2


def test_b2_negative_of_the_index_is_minus_one():
    assert beta(path(400, -1.0), path(400)) == pytest.approx(-1.0, abs=1e-9)  # cov(-r, r) / var(r) = -1


def test_b2_flat_stock_against_moving_index_is_zero():
    flat = pd.Series(50.0, index=bdays(400), name="Close")  # every return 0 -> cov 0 -> 0 / var(r) = 0
    b = beta(flat, path(400))
    assert b is not None and b == pytest.approx(0.0, abs=1e-12)


def test_b2_flat_index_is_none():
    flat = pd.Series(50.0, index=bdays(400), name="Close")  # var(index) = 0: no beta
    assert beta(path(400), flat) is None


def test_b2_returns_a_plain_float():
    b = beta(path(400, 2.0), path(400))
    assert type(b) is float


# ---------- B2 minimum: BETA_MIN_RETURNS = 250 ----------
def test_b2_249_returns_is_none():
    assert beta(path(250, 2.0), path(250)) is None  # 250 common dates -> 249 returns < 250


def test_b2_250_returns_gives_a_value():
    assert beta(path(251, 2.0), path(251)) == pytest.approx(2.0, abs=1e-9)  # 251 dates -> 250 returns


# ---------- B2 inner join on common dates ----------
def test_b2_only_dates_in_both_series_count():
    """Stock-only dates (Saturdays at 999) and index-only dates (Sundays at 1.0) are dropped by the inner join;
    on the common business days the stock is exactly 2x the index -> 2.0. Filling or own-day returns would
    pull in the 999 / 1.0 prices and move the figure far from 2."""
    s, i = path(400, 2.0), path(400)
    sats = pd.date_range(s.index[10], s.index[-10], freq="W-SAT")[:30]
    suns = pd.date_range(s.index[10], s.index[-10], freq="W-SUN")[:30]
    s2 = pd.concat([s, pd.Series(999.0, index=sats)]).sort_index()
    i2 = pd.concat([i, pd.Series(1.0, index=suns)]).sort_index()
    assert beta(s2, i2) == pytest.approx(2.0, abs=1e-9)


def test_b2_no_common_dates_is_none():
    s = path(400, 2.0)
    i = pd.Series(path(400).values, index=pd.bdate_range("2010-01-01", periods=400))  # no date in common
    assert beta(s, i) is None


# ---------- B2 the 3-year window ----------
def test_b2_last_three_years_only():
    """Five years of business days. Up to 2023-09-15 the stock moves -1x the index; after it, 2x. The window is
    the dates after 2026-10-30 - 3 years = 2023-10-30, all in the 2x stretch -> 2.0. The whole five years
    would mix -1 and 2 and give well under 2."""
    switch = pd.Timestamp("2023-09-15")
    n = len(pd.bdate_range("2021-10-01", END))
    s = path(n, lambda d: -1.0 if d <= switch else 2.0)
    i = path(n)
    assert beta(s, i) == pytest.approx(2.0, abs=1e-9)
    assert beta(s, i, years=rd.RISK_YEARS) == pytest.approx(2.0, abs=1e-9)
    assert beta(s, i, years=6) < 1.9  # the years argument is the window


def test_b2_window_on_the_joined_set_then_the_minimum():
    """An old common stretch (600 business days ending 2022-06-30, stock -1x) and a recent one ending 2026-10-30
    (stock 2x). Only the recent stretch is inside the 3-year window: with 251 dates there it is 250 returns ->
    2.0; with 250 dates it is 249 returns -> None, although the series hold far more than 250 returns."""
    old_s, old_i = path(600, -1.0, end="2022-06-30"), path(600, end="2022-06-30")
    for recent, want in ((251, 2.0), (250, None)):
        s = pd.concat([old_s, path(recent, 2.0)])
        i = pd.concat([old_i, path(recent)])
        got = beta(s, i)
        if want is None:
            assert got is None, recent
        else:
            assert got == pytest.approx(want, abs=1e-9), recent


# ---------- B2 bad inputs ----------
def test_b2_bad_prices_dropped_like_volatility():
    """Zero, NaN, negative and text prices sit on dates k % 6 == 2, where the price equals both neighbours, so
    dropping them leaves every return unchanged -> still exactly 2.0."""
    s = path(400, 2.0).astype(object)
    i = path(400)
    s.iloc[8], s.iloc[14], s.iloc[20], s.iloc[32] = 0.0, NAN, -5.0, "x"
    i.iloc[26] = NAN
    i.iloc[38] = 0.0
    assert beta(s, i) == pytest.approx(2.0, abs=1e-9)


def test_b2_shuffled_dates():
    s, i = path(400, 2.0), path(400)
    assert beta(s.sample(frac=1, random_state=1), i.sample(frac=1, random_state=2)) == pytest.approx(2.0, abs=1e-9)


def test_b2_duplicated_dates_keep_the_last():
    """As _clean does: a repeated date keeps the last value. The junk 1e6 / 1e-6 rows come first."""
    s, i = path(400, 2.0), path(400)
    s2 = pd.concat([pd.Series(1e6, index=s.index[[50, 120]]), s])
    i2 = pd.concat([pd.Series(1e-6, index=i.index[[60, 130]]), i])
    assert beta(s2, i2) == pytest.approx(2.0, abs=1e-9)


@pytest.mark.parametrize("which", ["stock", "index"])
@pytest.mark.parametrize("bad", ["none", "empty", "all_nan", "all_zero"])
def test_b2_none_or_empty_input_is_none(which, bad):
    good = path(400)
    made = {"none": None, "empty": empty_close(),
            "all_nan": pd.Series(NAN, index=bdays(400)), "all_zero": pd.Series(0.0, index=bdays(400))}[bad]
    args = (made, good) if which == "stock" else (good, made)
    assert beta(*args) is None


def test_b2_both_none_is_none():
    assert beta(None, None) is None


# ---------- B3 fetch ----------
def _hist_for(log, code):
    return [h for h in log["history"] if h[0] == code]


def test_b3_kl_stock_fetches_klse_once_after_its_own_prices(monkeypatch):
    yf = pytest.importorskip("yfinance")
    cls, log = fake_stock_yf(info_eq())
    monkeypatch.setattr(yf, "Ticker", cls)
    raw = rd.fetch_raw("5398.KL", now=T0)
    assert _hist_for(log, "^KLSE") == [("^KLSE", rd.PRICE_PERIOD)]  # exactly once, same 6y period
    assert log["history"].index(("5398.KL", "6y")) < log["history"].index(("^KLSE", "6y"))
    assert "^GSPC" not in log["codes"]
    ip = raw.index_prices
    assert isinstance(ip, pd.DataFrame) and list(ip.columns) == ["Close"]
    assert ip.index.tz is None and len(ip) == len(stock_close())  # a frame like prices: tz dropped


def test_b3_us_stock_fetches_gspc_once(monkeypatch):
    yf = pytest.importorskip("yfinance")
    cls, log = fake_stock_yf(us_info())
    monkeypatch.setattr(yf, "Ticker", cls)
    raw = rd.fetch_raw("FAKE", now=T0)
    assert _hist_for(log, "^GSPC") == [("^GSPC", "6y")]
    assert "^KLSE" not in log["codes"]
    assert not raw.index_prices.empty


def test_b3_us_etf_fetches_gspc_once(monkeypatch):
    yf = pytest.importorskip("yfinance")
    cls, log = fake_yf(etf_info())
    monkeypatch.setattr(yf, "Ticker", cls)
    raw = rd.fetch_raw("VT", now=T0)
    assert _hist_for(log, "^GSPC") == [("^GSPC", "6y")]
    assert list(raw.index_prices.columns) == ["Close"]


@pytest.mark.parametrize("code,info", [
    ("0700.HK", info_eq(currency="HKD", financialCurrency="HKD")),
    ("BTC-USD", {"quoteType": "CRYPTOCURRENCY", "currency": "USD", "shortName": "Bitcoin"}),
], ids=["hk", "crypto"])
def test_b3_no_index_fetch_when_no_home_index(monkeypatch, code, info):
    yf = pytest.importorskip("yfinance")
    cls, log = fake_stock_yf(info)
    monkeypatch.setattr(yf, "Ticker", cls)
    raw = rd.fetch_raw(code, now=T0)
    assert not [c for c in log["codes"] if c.startswith("^")], log["codes"]
    assert not [h for h in log["history"] if h[0].startswith("^")]
    assert isinstance(raw.index_prices, pd.DataFrame) and raw.index_prices.empty


@pytest.mark.parametrize("failure", ["history_raises", "ticker_raises", "empty_history", "no_close"])
def test_b3_index_failure_gives_empty_frame_no_exception(monkeypatch, failure):
    yf = pytest.importorskip("yfinance")
    base, log = fake_stock_yf(info_eq())

    class Broken(base):
        def __init__(self, code):
            if code.startswith("^") and failure == "ticker_raises":
                raise ConnectionError("index ticker broke (fake)")
            super().__init__(code)

        def history(self, period=None, **kw):
            if self.code.startswith("^"):
                log["history"].append((self.code, period))
                if failure == "history_raises":
                    raise ConnectionError("index history broke (fake)")
                if failure == "no_close":
                    return pd.DataFrame({"Open": [1.0]}, index=pd.DatetimeIndex(["2026-10-30"]))
                return pd.DataFrame()
            return super().history(period=period, **kw)

    monkeypatch.setattr(yf, "Ticker", Broken)
    raw = rd.fetch_raw("5398.KL", now=T0)
    assert isinstance(raw.index_prices, pd.DataFrame) and raw.index_prices.empty
    assert not raw.prices.empty  # the code's own prices are untouched
    r = rd.analyse(raw)
    assert r.company["beta_3y"] is None
    assert KLCI_WARNING in r.warnings


def test_b3_raw_default_index_prices_empty():
    raw = rd.Raw(code="X", info={}, income=pd.DataFrame(), balance=pd.DataFrame(), cashflow=pd.DataFrame(),
                 q_income=pd.DataFrame(), q_balance=pd.DataFrame(), q_cashflow=pd.DataFrame(),
                 recs=pd.DataFrame(), fetched_at=T0)
    assert isinstance(raw.index_prices, pd.DataFrame) and raw.index_prices.empty


# ---------- B3 cache ----------
def stock_with_index():
    raw = gamuda_stock()
    raw.index_prices = pd.DataFrame({"Close": stock_close()})  # identical to the stock -> beta 1.0
    return raw


def test_b3_cache_round_trip_keeps_index_prices(tmp_path):
    raw = stock_with_index()
    rd.save_cache(raw, tmp_path)
    doc = json.loads((tmp_path / "5398.KL.json").read_text(encoding="utf-8"))
    assert "index_prices" in doc  # in the code's own cache file
    back = rd.load_cache("5398.KL", tmp_path)
    assert isinstance(back.index_prices.index, pd.DatetimeIndex)
    pd.testing.assert_series_equal(back.index_prices["Close"], raw.index_prices["Close"], check_freq=False,
                                   check_names=False, check_index_type=False)
    assert rd.analyse(back).company["beta_3y"] == pytest.approx(1.0, abs=1e-9)


def test_b3_old_cache_file_without_index_prices_loads_empty(tmp_path):
    rd.save_cache(stock_with_index(), tmp_path)
    p = tmp_path / "5398.KL.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc.pop("index_prices", None)  # a file written before WP-3.8
    p.write_text(json.dumps(doc), encoding="utf-8")
    back = rd.load_cache("5398.KL", tmp_path)
    assert back is not None
    assert isinstance(back.index_prices, pd.DataFrame) and back.index_prices.empty
    assert rd.analyse(back).company["beta_3y"] is None


# ---------- B4 stats ----------
def test_b4_company_stats_carries_beta_against_klci():
    c = rd.company_stats(stock_with_index())
    assert c["beta_3y"] == pytest.approx(1.0, abs=1e-9)  # index identical to the stock
    assert c["beta_index"] == "FBM KLCI"


def test_b4_company_stats_twice_the_index():
    raw = gamuda_stock()
    raw.prices = pd.DataFrame({"Close": path(400, 2.0)})
    raw.index_prices = pd.DataFrame({"Close": path(400)})
    assert rd.company_stats(raw)["beta_3y"] == pytest.approx(2.0, abs=1e-9)


def test_b4_etf_stats_carries_beta_against_sp500():
    raw = etf_like()
    raw.index_prices = pd.DataFrame({"Close": raw.prices["Close"].copy()})
    e = rd.etf_stats(raw)
    assert e["beta_3y"] == pytest.approx(1.0, abs=1e-9)
    assert e["beta_index"] == "S&P 500"


def test_b4_no_index_prices_gives_none_but_keeps_the_name():
    raw = gamuda_stock()
    raw.index_prices = pd.DataFrame()
    c = rd.company_stats(raw)
    assert c["beta_3y"] is None and c["beta_index"] == "FBM KLCI"
    raw = etf_like()
    raw.index_prices = pd.DataFrame()
    e = rd.etf_stats(raw)
    assert e["beta_3y"] is None and e["beta_index"] == "S&P 500"


def test_b4_no_home_index_gives_none_name():
    raw = gamuda_stock()
    raw.code = "0700.HK"
    raw.index_prices = pd.DataFrame()
    c = rd.company_stats(raw)
    assert "beta_3y" in c and "beta_index" in c
    assert c["beta_3y"] is None and c["beta_index"] is None


def test_b4_price_stats_unchanged_beta_only_in_the_view_dicts():
    close = stock_close()
    assert set(rd.price_stats(close)) == {"returns", "annual_returns", "volatility_3y", "max_drawdown_3y",
                                          "history_note"}
    import inspect
    assert list(inspect.signature(rd.price_stats).parameters) == ["close"]
    assert {"beta_3y", "beta_index"} <= set(rd.company_stats(stock_with_index()))
    assert {"beta_3y", "beta_index"} <= set(rd.etf_stats(etf_like()))


# ---------- B5 warning ----------
def test_b5_stock_warning_when_index_frame_empty():
    raw = gamuda_stock()
    raw.index_prices = pd.DataFrame()
    w = rd.analyse(raw).warnings
    assert w.count(KLCI_WARNING) == 1, w


def test_b5_etf_warning_when_index_frame_empty():
    raw = etf_like()
    raw.index_prices = pd.DataFrame()
    w = rd.analyse(raw).warnings
    assert w.count(SPX_WARNING) == 1, w


def test_b5_no_warning_when_no_home_index():
    raw = gamuda_stock()
    raw.code = "0700.HK"
    raw.index_prices = pd.DataFrame()
    r = rd.analyse(raw)
    assert r.company["beta_index"] is None
    assert not [x for x in r.warnings if x.startswith("Beta")], r.warnings


def test_b5_no_warning_when_index_history_too_short():
    raw = gamuda_stock()
    raw.index_prices = pd.DataFrame({"Close": stock_close().iloc[-100:]})  # 99 common returns < 250
    r = rd.analyse(raw)
    assert r.company["beta_3y"] is None and r.company["beta_index"] == "FBM KLCI"
    assert not [x for x in r.warnings if x.startswith("Beta")], r.warnings


def test_b5_no_warning_when_beta_shown():
    r = rd.analyse(stock_with_index())
    assert r.company["beta_3y"] == pytest.approx(1.0, abs=1e-9)
    assert not [x for x in r.warnings if x.startswith("Beta")], r.warnings


# ---------- B6 beta_text ----------
@pytest.mark.parametrize("v,want", [
    (1.12, "1.12"), (-0.35, "-0.35"), (0.0, "0.00"), (2.0, "2.00"), (1.0, "1.00"), (0.954, "0.95"),
    (-0.0, "0.00"), (-0.001, "0.00"), (-0.004, "0.00"),  # never "-0.00"
    (np.float64(1.5), "1.50"), (None, "n/a"), (NAN, "n/a"), (np.float64("nan"), "n/a"),
], ids=["1.12", "-0.35", "zero", "two", "one", "round_down", "neg_zero", "tiny_neg", "small_neg", "numpy", "none",
        "nan", "numpy_nan"])
def test_b6_beta_text(v, want):
    assert rd.beta_text(v) == want


# ---------- B9 What moved ----------
from test_research_compare import (ETF_ORDER, MDD, RR, STOCK_ORDER, fresh_etf, fresh_stock, row,  # noqa: E402
                                   saved_etf, saved_stock, texts_of)


def with_beta(r, v, name):
    block = r.etf if r.etf is not None else r.company
    block["beta_3y"], block["beta_index"] = v, name
    return r


def after_mdd(order):
    i = order.index((RR, MDD))
    return order[:i + 1] + [(RR, "Beta")] + order[i + 1:]


def test_b9_stock_beta_row_after_max_drawdown():
    s, f = with_beta(saved_stock(), 1.12, "FBM KLCI"), with_beta(fresh_stock(), 0.95, "FBM KLCI")
    c = rd.compare(s, f)
    assert [(m.section, m.figure) for m in c.rows] == after_mdd(STOCK_ORDER)
    assert texts_of(row(c, RR, "Beta")) == ("1.12", "0.95", "▼ -0.17")  # 0.95 - 1.12 = -0.17 (diff of shown)


def test_b9_etf_beta_row_after_max_drawdown():
    s, f = with_beta(saved_etf(), 0.98, "S&P 500"), with_beta(fresh_etf(), 1.05, "S&P 500")
    c = rd.compare(s, f)
    assert [(m.section, m.figure) for m in c.rows] == after_mdd(ETF_ORDER)
    assert texts_of(row(c, RR, "Beta")) == ("0.98", "1.05", "▲ +0.07")  # 1.05 - 0.98 = +0.07


def test_b9_same_beta_no_change():
    c = rd.compare(with_beta(saved_stock(), 1.0, "FBM KLCI"), with_beta(fresh_stock(), 1.001, "FBM KLCI"))
    assert texts_of(row(c, RR, "Beta")) == ("1.00", "1.00", "no change")


def test_b9_both_none_skipped():
    c = rd.compare(with_beta(saved_stock(), None, "FBM KLCI"), with_beta(fresh_stock(), None, "FBM KLCI"))
    assert (RR, "Beta") not in [(m.section, m.figure) for m in c.rows]
    # and the row exists once a side has it (so this check cannot pass on a compare that never shows Beta)
    c = rd.compare(with_beta(saved_stock(), None, None), with_beta(fresh_stock(), 0.8, "FBM KLCI"))
    assert texts_of(row(c, RR, "Beta")) == ("n/a", "0.80", "n/a")


def test_b9_old_snapshot_without_keys_shows_saved_na():
    s, f = saved_etf(), with_beta(fresh_etf(), 1.05, "S&P 500")
    s.etf.pop("beta_3y", None)
    s.etf.pop("beta_index", None)  # saved before WP-3.8
    m = row(rd.compare(s, f), RR, "Beta")
    assert texts_of(m) == ("n/a", "1.05", "n/a")


# ---------- B10 console smoke ----------
def test_b10_print_company_beta_line(capsys):
    rd._print_company(rd.company_stats(stock_with_index()), "MYR")
    assert "beta 3y 1.00 against FBM KLCI" in capsys.readouterr().out


def test_b10_print_company_beta_na(capsys):
    raw = gamuda_stock()
    raw.index_prices = pd.DataFrame()
    rd._print_company(rd.company_stats(raw), "MYR")
    out = capsys.readouterr().out
    assert "beta 3y n/a" in out and "beta 3y n/a against" not in out


def test_b10_print_etf_beta_line(capsys):
    raw = etf_like()
    raw.index_prices = pd.DataFrame({"Close": raw.prices["Close"].copy()})
    e = rd.analyse(raw).etf
    rd._print_etf(e)
    assert "beta 3y 1.00 against S&P 500" in capsys.readouterr().out


def test_b10_print_etf_beta_na(capsys):
    raw = etf_like()
    raw.index_prices = pd.DataFrame()
    rd._print_etf(rd.analyse(raw).etf)
    assert "beta 3y n/a" in capsys.readouterr().out


# ---------- added by the mutation pass (WP-3.8 mutation-r1): rulings of decision.md point 4 ----------
def test_m_no_home_index_ignores_filled_index_prices():
    """Ruling 4a: beta_index None -> beta_3y and beta_index None even when index_prices holds prices."""
    raw = stock_with_index()
    raw.code = "0700.HK"
    c = rd.company_stats(raw)
    assert c["beta_3y"] is None and c["beta_index"] is None
    raw = etf_like()
    raw.code = "VT.L"  # a dot: no home index
    raw.index_prices = pd.DataFrame({"Close": raw.prices["Close"].copy()})
    e = rd.etf_stats(raw)
    assert e["beta_3y"] is None and e["beta_index"] is None
    assert not [x for x in rd.analyse(raw).warnings if x.startswith("Beta")]


@pytest.mark.parametrize("bad", [NAN, 0.0, -1.0], ids=["nan", "zero", "negative"])
def test_m_index_frame_with_no_usable_price_warns(bad):
    """Ruling 4b: a non-empty index frame with no usable price after cleaning counts as no index prices."""
    raw = gamuda_stock()
    raw.index_prices = pd.DataFrame({"Close": [bad] * 400}, index=stock_close().index[-400:])
    r = rd.analyse(raw)
    assert r.company["beta_3y"] is None
    assert r.warnings.count(KLCI_WARNING) == 1, r.warnings


def test_m_no_quote_type_no_index_fetch(monkeypatch):
    """Ruling 4c: no quoteType -> no price fetch at all, so no index fetch either."""
    yf = pytest.importorskip("yfinance")
    cls, log = fake_stock_yf({})
    monkeypatch.setattr(yf, "Ticker", cls)
    raw = rd.fetch_raw("5398.KL", now=T0)
    assert not [c for c in log["codes"] if c.startswith("^")], log["codes"]
    assert raw.index_prices.empty


def test_m_index_fetch_failure_saves_the_new_copy(tmp_path):
    """Ruling 4d: an older cached copy WITH index prices is replaced by the new fetch whose index is empty."""
    from datetime import timedelta
    old = stock_with_index()
    rd.save_cache(old, tmp_path)

    def fetcher(code, now=None):
        raw = gamuda_stock()
        raw.index_prices = pd.DataFrame()
        raw.fetched_at = now
        return raw
    later = T0 + timedelta(hours=2)
    r = rd.research("5398.KL", now=later, fetcher=fetcher, cache_dir=tmp_path, ttl=3600)
    assert r.stale is False and r.company["beta_3y"] is None and KLCI_WARNING in r.warnings
    back = rd.load_cache("5398.KL", tmp_path)
    assert back.fetched_at == later and back.index_prices.empty


@pytest.mark.parametrize("v,want", [(-0.006, "-0.01"), (-0.0049, "0.00"), (0.996, "1.00"), (-1.004, "-1.00")],
                         ids=["neg_rounds_out", "neg_rounds_to_zero", "rounds_up", "neg_one"])
def test_m_beta_text_round_then_no_minus_zero(v, want):
    """Ruling 4e: round to two decimals, then a "-0.00" prints "0.00"; other negatives keep their sign."""
    assert rd.beta_text(v) == want


@pytest.mark.parametrize("which", ["company", "etf"])
def test_m_beta_line_directly_after_volatility_line(capsys, which):
    """Ruling 4f: the B10 line sits directly after the volatility / drawdown line."""
    if which == "company":
        rd._print_company(rd.company_stats(stock_with_index()), "MYR")
    else:
        raw = etf_like()
        raw.index_prices = pd.DataFrame({"Close": raw.prices["Close"].copy()})
        rd._print_etf(rd.analyse(raw).etf)
    lines = capsys.readouterr().out.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith("volatility 3y"))
    assert lines[i + 1] == f"beta 3y 1.00 against {'FBM KLCI' if which == 'company' else 'S&P 500'}"
