"""WP-2 loader tests (spec T1-T8). Fakes only: the workbook is written into tmp_path
by the tracker's own pt.save with fake frames, pt.OUT_FILE monkeypatched."""
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import portfolio_tracker as pt  # noqa: E402
import portfolio_data as pdata  # noqa: E402

AS_OF = date(2026, 10, 25)
ANCHOR = date(2026, 10, 21)
BLEND = "Blended benchmark (40/20/40) %"
LOG_COLS = ["Date", "Moomoo total (RM)", "Cash (RM)", "Local (RM)", "Regional (RM)", "Global (RM)",
            "Net deposits (RM)", "Moomoo return %", "Moomoo XIRR %", "FBM KLCI %",
            "Asia ex-Japan (AAXJ) %", "World (VT) %", BLEND, "Savings pot (RM)",
            "All-in total (RM)", "All-in return %"]
MEASURES = ["My Moomoo portfolio", "My Moomoo portfolio (simple)", "FBM KLCI", "Asia ex-Japan (AAXJ)",
            "World (VT)", "Blended benchmark (40/20/40)", "Savings pot 4%"]


# ---------- fake frames (made-up figures) ----------
def fake_summary(unassigned):
    rows = [
        {"Bucket": "local", "Value (RM)": 400.0, "Weight": 0.4, "Target": 0.4, "Drift": 0.0, "Rebalance?": ""},
        {"Bucket": "regional", "Value (RM)": 250.0, "Weight": 0.25, "Target": 0.2, "Drift": 0.05,
         "Rebalance?": "SELL ~RM50"},
        {"Bucket": "global", "Value (RM)": 350.0, "Weight": 0.35, "Target": 0.4, "Drift": -0.05,
         "Rebalance?": "BUY ~RM50"},
    ]
    if unassigned:
        rows.append({"Bucket": "unassigned", "Value (RM)": 11.0, "Weight": None, "Target": None,
                     "Drift": None, "Rebalance?": "Add these codes to BUCKETS in the script"})
    return pd.DataFrame(rows)


def fake_perf(xirr=None, simple=0.0123):
    vals = [xirr, simple, 0.01, 0.02, 0.03, 0.021, 0.004]
    return pd.DataFrame({"Measure": MEASURES, "Return %": vals})


def log_row(d, total, ret, blend):
    row = dict.fromkeys(LOG_COLS)
    row.update({"Date": d, "Moomoo total (RM)": total, "Cash (RM)": 10.0, "Moomoo return %": ret, BLEND: blend})
    return row


def fake_holdings():
    return pd.DataFrame([{"Code": "MY.0001", "Name": "Fake Co", "Bucket": "local", "Qty": 100,
                          "Currency": "MYR", "Avg cost": 4.0, "Price": 4.0, "Cost (RM)": 400.0, "Value (RM)": 400.0,
                          "Unrealised P/L (RM)": 0.0, "P/L %": 0.0}])


def build(monkeypatch, tmp_path, unassigned=False, prior=None, today=None, perf=None, holdings=None):
    """Write a fake workbook with pt.save. prior: earlier Daily_Log rows; today: this run's log row."""
    out = tmp_path / "Fake_Tracker.xlsx"
    monkeypatch.setattr(pt, "OUT_FILE", out)
    prior_df = pd.DataFrame(prior if prior is not None else [
        log_row(date(2026, 10, 21), 1000.0, 0.0, 0.002),
        log_row(date(2026, 10, 22), 1005.0, None, None),
    ], columns=LOG_COLS + sorted({k for r in (prior or []) for k in r} - set(LOG_COLS)))
    monkeypatch.setattr(pt, "read_sheet",
                        lambda name: prior_df.copy() if name == "Daily_Log" else pd.DataFrame())
    row = today or log_row(AS_OF, 1021.0, 0.021, 0.015)
    pt.save(fake_summary(unassigned), perf if perf is not None else fake_perf(), row,
            fake_holdings() if holdings is None else holdings,
            pd.DataFrame(), pd.DataFrame(columns=pt.CASHFLOW_COLS), ANCHOR)
    return out


# ---------- T1 ----------
def test_t1_load_workbook_fields(monkeypatch, tmp_path):
    p = pdata.load_workbook(build(monkeypatch, tmp_path))
    assert isinstance(p, pdata.Portfolio)
    for f in ("allocation", "performance", "holdings", "daily_log"):
        assert isinstance(getattr(p, f), pd.DataFrame) and len(getattr(p, f)) > 0, f
    assert isinstance(p.monthly, pd.DataFrame)  # WP-2.1: save writes Monthly
    assert list(p.monthly.columns) == ["Month", "End value (RM)", "Deposits (RM)", "Withdrawals (RM)",
                                       "Trades", "Month return %", "Note"]
    assert p.as_of == AS_OF and p.anchor == ANCHOR
    assert list(p.allocation.columns) == ["Bucket", "Value (RM)", "Weight", "Target", "Drift", "Rebalance?"]
    assert list(p.performance.columns) == ["Measure", "Return %"]
    assert pd.api.types.is_datetime64_any_dtype(p.daily_log["Date"])
    assert len(p.daily_log) == 3


# ---------- T2 ----------
@pytest.mark.parametrize("unassigned,n", [(False, 3), (True, 4)])
def test_t2_summary_found_by_table_not_offset(monkeypatch, tmp_path, unassigned, n):
    p = pdata.load_workbook(build(monkeypatch, tmp_path, unassigned=unassigned))
    assert len(p.allocation) == n
    assert list(p.allocation["Bucket"])[:3] == ["local", "regional", "global"]
    assert list(p.performance["Measure"]) == MEASURES
    assert p.performance["Return %"].iloc[1] == pytest.approx(0.0123)
    assert p.anchor == ANCHOR


# ---------- T3 ----------
def test_t3_tile_values_picked(monkeypatch, tmp_path):
    p = pdata.load_workbook(build(monkeypatch, tmp_path, perf=fake_perf(xirr=None, simple=0.0456)))
    t = pdata.tile_values(p)
    assert t["total"] == pytest.approx(1021.0)  # last Daily_Log row
    assert t["xirr"] is None  # blank Return % cell
    assert t["simple"] == pytest.approx(0.0456)
    assert t["anchor"] == ANCHOR and t["as_of"] == AS_OF


def test_t3_tile_xirr_present(monkeypatch, tmp_path):
    p = pdata.load_workbook(build(monkeypatch, tmp_path, perf=fake_perf(xirr=0.0789)))
    assert pdata.tile_values(p)["xirr"] == pytest.approx(0.0789)


# ---------- T4 ----------
def test_t4_chart_frame_two_series_unchanged(monkeypatch, tmp_path):
    p = pdata.load_workbook(build(monkeypatch, tmp_path))
    cf = pdata.chart_frame(p)
    assert list(cf.columns) == ["Date", "My Moomoo portfolio", "Blended benchmark (40/20/40)"]
    assert len(cf) == 2  # 2026-10-22 has both NaN -> dropped
    assert cf["My Moomoo portfolio"].tolist() == pytest.approx([0.0, 0.021])
    assert cf["Blended benchmark (40/20/40)"].tolist() == pytest.approx([0.002, 0.015])


def test_t4_chart_frame_blend_absent_is_nan(monkeypatch, tmp_path):
    prior = [log_row(date(2026, 10, 21), 1000.0, 0.0, None), log_row(date(2026, 10, 22), 1005.0, None, None)]
    out = build(monkeypatch, tmp_path, prior=prior, today=log_row(AS_OF, 1021.0, 0.021, None))
    p = pdata.load_workbook(out)
    assert BLEND not in p.daily_log.columns  # tracker dropped the all-empty column
    cf = pdata.chart_frame(p)
    assert cf["Blended benchmark (40/20/40)"].isna().all()
    assert cf["My Moomoo portfolio"].tolist() == pytest.approx([0.0, 0.021])


# ---------- T5 ----------
def test_t5_missing_workbook(tmp_path):
    with pytest.raises(FileNotFoundError):
        pdata.load_workbook(tmp_path / "nope.xlsx")


# ---------- T6 ----------
def test_t6_monthly_sheet_returned(monkeypatch, tmp_path):
    out = build(monkeypatch, tmp_path)
    monthly = pd.DataFrame({"Month": ["2026-10"], "End value (RM)": [1021.0], "Month return %": [0.021]})
    with pd.ExcelWriter(out, engine="openpyxl", mode="a", if_sheet_exists="replace") as xw:  # WP-2.1: save writes Monthly
        monthly.to_excel(xw, sheet_name="Monthly", index=False)
    p = pdata.load_workbook(out)
    assert isinstance(p.monthly, pd.DataFrame)
    assert list(p.monthly.columns) == list(monthly.columns)
    assert p.monthly["End value (RM)"].iloc[0] == pytest.approx(1021.0)


# ---------- T7 ----------
def test_t7_read_named_table_unknown(monkeypatch, tmp_path):
    from openpyxl import load_workbook as ox_load
    ws = ox_load(build(monkeypatch, tmp_path))["Summary"]
    assert list(pdata.read_named_table(ws, "Performance")["Measure"]) == MEASURES
    with pytest.raises(KeyError, match="NoSuchTable"):
        pdata.read_named_table(ws, "NoSuchTable")


# ---------- T8 ----------
def test_t8_no_streamlit():
    assert "streamlit" not in sys.modules
    src = Path(pdata.__file__).read_text(encoding="utf-8")
    assert "import streamlit" not in src and "from streamlit" not in src
    assert "import streamlit" not in Path(__file__).read_text(encoding="utf-8").replace(
        '"import streamlit"', "")


# ---------- T11 (WP-2.1): days since anchor tile ----------
def test_t11_tile_days_last_row(monkeypatch, tmp_path):
    prior = [dict(log_row(date(2026, 10, 21), 1000.0, 0.0, 0.002), **{"Days since anchor": 0}),
             dict(log_row(date(2026, 10, 22), 1005.0, None, None), **{"Days since anchor": 1})]
    today = dict(log_row(AS_OF, 1021.0, 0.021, 0.015), **{"Days since anchor": 4})
    p = pdata.load_workbook(build(monkeypatch, tmp_path, prior=prior, today=today))
    assert pdata.tile_values(p)["days"] == 4


def test_t11_tile_days_absent_is_none(monkeypatch, tmp_path):
    p = pdata.load_workbook(build(monkeypatch, tmp_path))
    assert "Days since anchor" not in p.daily_log.columns
    t = pdata.tile_values(p)
    assert "days" in t and t["days"] is None


# ---------- R3 (WP-2.1 round 2): page guards optional Monthly columns ----------
def test_r3_page_guards_monthly_columns():
    """Source-level guard (like T8): the page checks the columns exist before formatting them,
    so a Monthly sheet without them cannot raise KeyError."""
    src = (ROOT / "pages" / "portfolio.py").read_text(encoding="utf-8")
    assert '"Month return %" in' in src
    assert '"Note" in' in src


# ---------- WP-1.3: Cost (RM) passes through the loader ----------
class OnePositionCtx:
    """Fake OpenD context: one REAL account, one USD row at 4.0 MYR per USD (400 / 100 totals)."""
    def __init__(self, **kw):
        pass

    def get_acc_list(self):
        return pt.RET_OK, pd.DataFrame({"acc_id": [1], "trd_env": [pt.TrdEnv.REAL]})

    def accinfo_query(self, currency=None, **kw):
        return pt.RET_OK, pd.DataFrame([{"total_assets": 400.0 if currency == pt.Currency.MYR else 100.0,
                                         "cash": 0.0}])

    def position_list_query(self, **kw):
        return pt.RET_OK, pd.DataFrame([{"code": "US.FAKE", "stock_name": "Fake USD", "qty": 10.0,
                                         "currency": "USD", "average_cost": 2.5, "nominal_price": 3.0,
                                         "market_val": 30.0, "unrealized_pl": 5.0, "pl_ratio_avg_cost": 20.0}])

    def history_deal_list_query(self, **kw):
        return pt.RET_OK, pd.DataFrame()

    deal_list_query = history_deal_list_query

    def get_acc_cash_flow(self, **kw):
        return pt.RET_OK, pd.DataFrame(columns=pt.CASHFLOW_COLS)

    def close(self):
        pass


def test_wp13_loader_passes_cost_through(monkeypatch, tmp_path):
    monkeypatch.setattr(pt, "OpenSecTradeContext", OnePositionCtx)
    holdings, _, _, _ = pt.fetch([])
    p = pdata.load_workbook(build(monkeypatch, tmp_path, holdings=holdings))
    assert "Cost (RM)" in p.holdings.columns
    assert p.holdings["Cost (RM)"].iloc[0] == pytest.approx(100.0)  # 10 x 2.5 x 4.0
    cols = list(p.holdings.columns)
    assert cols.index("Cost (RM)") == cols.index("Value (RM)") - 1
