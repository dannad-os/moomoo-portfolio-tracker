"""
verify_tracker.py: data-only checks for portfolio_tracker.py.

Runs on a fresh clone: no Portfolio_Tracker.xlsx, no OpenD, no internet.
Calls the pure functions with fixed inputs and compares against known answers;
check 12 also drives fetch()/save() with a fake OpenD into a temp folder
(never the real workbook).
Prints one line per check, then RESULT: PASS or RESULT: FAIL (exit code 0 / 1).
Run:  python verify_tracker.py
What each check pins: docs/verify-suites.md
"""
import contextlib
import io
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_tracker as pt  # noqa: E402

S = pt.START_DATE
D0 = date(2025, 1, 1)
CF_COLS = ["cashflow_id", "clearing_date", "settlement_date", "currency", "cashflow_type",
           "cashflow_direction", "cashflow_amount", "cashflow_remark"]


def days(n):
    return timedelta(days=n)


def quiet(fn):
    """Run fn() with its prints swallowed (warnings are expected in some checks)."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn()


def close(a, b):
    return a is not None and abs(a - b) < 1e-6


# ---------- the checks: (name, got, expected, compare) ----------

def deal_window():
    today = S + days(200)
    return pt.deal_window(today), ((today - days(89)).isoformat(), today.isoformat())


def cashflow_dates():
    today = S + days(10)
    got = pt.cashflow_dates(today - days(5), today)
    return got, [today - days(i) for i in range(5, -1, -1)]


def xirr_doubling():
    return pt.xirr([(D0, -100.0), (D0 + days(365), 200.0)]), 1.0


def xirr_two_deposits():
    return pt.xirr([(D0, -100.0), (D0 + days(365), -100.0), (D0 + days(730), 231.0)]), 0.1


def xirr_withdrawal():
    return pt.xirr([(D0, -1000.0), (D0 + days(365), 100.0), (D0 + days(730), 1100.0)]), 0.1


def xirr_flows_anchor():
    today = S + days(30)
    log = pd.DataFrame([{"Date": d, "Moomoo total (RM)": t} for d, t in
                        [(S - days(2), 900.0), (S, 30_000.0), (S + days(1), 30_100.0)]])
    cf = pd.DataFrame([
        ("1", S.isoformat(), "", "MYR", "Bank Transfer Deposits", "IN", 999.0, ""),     # anchor day: left out
        ("2", (S + days(5)).isoformat(), "", "MYR", "Bank Transfer Deposits", "IN", 5000.0, ""),
        ("3", (S + days(6)).isoformat(), "", "MYR", "Fund Subscription", "OUT", -3.0, ""),  # fund buy: not a deposit
    ], columns=CF_COLS)
    got = quiet(lambda: pt.xirr_flows(log, cf, today, 36_000.0))
    return got, [(S, -30_000.0), (S + days(5), -5000.0), (today, 36_000.0)]


def unassigned_weight():
    holdings = pd.DataFrame([
        {"Code": "MY.0005", "Bucket": "local", "Value (RM)": 800.0},
        {"Code": "US.XYZ", "Bucket": "unassigned", "Value (RM)": 100.0},
    ])
    summary, _, _, _ = pt.build_summary(holdings, {"total": 900.0, "cash": 0.0}, {}, S - days(2))
    s = summary.set_index("Bucket")
    got = (round(float(s.loc["local", "Weight"]), 9), s.loc["unassigned", "Rebalance?"])
    return got, (1.0, "Add these codes to BUCKETS in the script")


def fund_cash_like():
    holdings = pd.DataFrame([
        {"Code": "MY.0005", "Bucket": "local", "Value (RM)": 400.0},
        {"Code": "SG.ES3", "Bucket": "regional", "Value (RM)": 300.0},
        {"Code": "US.VT", "Bucket": "global", "Value (RM)": 300.0},
    ])
    with_fund, _, _, _ = pt.build_summary(holdings, {"total": 1100.0, "cash": 0.0, "fund": 100.0}, {}, S - days(2))
    without, _, _, _ = pt.build_summary(holdings, {"total": 1000.0, "cash": 0.0, "fund": 0.0}, {}, S - days(2))
    w, b = with_fund.set_index("Bucket"), without.set_index("Bucket")
    f = w.loc[pt.FUND_LABEL]
    got = (float(f["Value (RM)"]), bool(pd.isna(f["Weight"])),
           [float(w.loc[k, "Weight"]) for k in pt.TARGETS], pt.FUND_LABEL in list(without["Bucket"]))
    return got, (100.0, True, [float(b.loc[k, "Weight"]) for k in pt.TARGETS], False)


def benchmark_failure():
    real = pt.yf.download

    def offline(*a, **k):
        raise OSError("offline")
    pt.yf.download = offline
    try:
        out = quiet(lambda: pt.benchmark_returns(S))
    finally:
        pt.yf.download = real
    got = (list(out), all(isinstance(v, float) and math.isnan(v) for v in out.values()))
    labels = ["FBM KLCI", "Asia ex-Japan (AAXJ)", "World (VT)", "Blended benchmark (40/20/40)"]
    return got, (labels, True)


def types_disjoint():
    return sorted(pt.DEPOSIT_TYPES & pt.IGNORED_TYPES), []


def monthly_boundary():
    """Flows sit in (previous end-row date, this end-row date]: a 31 Oct deposit stays in October when
    31 Oct is logged, and moves to November when it is not."""
    a = date(2026, 10, 20)
    flows = [(date(2026, 10, 31), 50.0), (date(2026, 11, 1), 150.0)]
    deals = pd.DataFrame(columns=["Deal ID", "Time", "Code", "Name", "Bucket", "Side", "Qty", "Price"])

    def deposits(rows):
        log = pd.DataFrame([{"Date": d, "Moomoo total (RM)": t} for d, t in rows])
        m = pt.monthly_table(log, flows, deals, a)
        return list(zip(m["Month"], m["Deposits (RM)"].astype(float)))
    both = deposits([(a, 1000.0), (date(2026, 10, 30), 1040.0), (date(2026, 10, 31), 1100.0),
                     (date(2026, 11, 1), 1300.0)])
    gap = deposits([(a, 1000.0), (date(2026, 10, 30), 1040.0), (date(2026, 11, 1), 1300.0)])
    return (both, gap), ([("2026-10", 50.0), ("2026-11", 150.0)], [("2026-10", 0.0), ("2026-11", 200.0)])


class _HoldingsCtx:
    """Fake OpenD: one account, a USD row (4.0 MYR per USD from 400 / 100 totals), a MYR row,
    and a row with no average cost (NaN), whose Cost (RM) must be blank."""
    def __init__(self, **kw):
        pass

    def get_acc_list(self):
        return pt.RET_OK, pd.DataFrame({"acc_id": [1], "trd_env": [pt.TrdEnv.REAL]})

    def accinfo_query(self, currency=None, **kw):
        return pt.RET_OK, pd.DataFrame([{"total_assets": 400.0 if currency == pt.Currency.MYR else 100.0,
                                         "cash": 0.0}])

    def position_list_query(self, **kw):
        keys = ["code", "stock_name", "qty", "currency", "average_cost", "nominal_price",
                "market_val", "unrealized_pl", "pl_ratio_avg_cost"]
        return pt.RET_OK, pd.DataFrame([
            ("US.FAKE", "Fake USD", 10.0, "USD", 2.5, 3.0, 30.0, 5.0, 20.0),
            ("MY.0001", "Fake MYR", 100.0, "MYR", 1.5, 1.6, 160.0, 10.0, 6.6667),
            ("MY.0003", "No cost", 5.0, "MYR", float("nan"), 2.0, 10.0, 0.0, 0.0),
        ], columns=keys)

    def history_deal_list_query(self, **kw):
        return pt.RET_OK, pd.DataFrame()

    deal_list_query = history_deal_list_query

    def get_acc_cash_flow(self, **kw):
        return pt.RET_OK, pd.DataFrame(columns=pt.CASHFLOW_COLS)

    def close(self):
        pass


def holdings_cost():
    """fetch() with a fake OpenD, save() into a temp workbook, then read its Holdings sheet:
    Cost (RM) exists, and Cost = Value - Unrealised P/L per row within max(RM 0.01, 0.01% of value);
    rows with a blank cost are skipped and counted."""
    import tempfile
    real = pt.OpenSecTradeContext, pt.OUT_FILE, pt.read_sheet
    with tempfile.TemporaryDirectory() as tmp:
        pt.OpenSecTradeContext = _HoldingsCtx
        pt.OUT_FILE = Path(tmp) / "Fake_Tracker.xlsx"
        pt.read_sheet = lambda name: pd.DataFrame()
        try:
            holdings, _, _, cashflow = quiet(lambda: pt.fetch([]))
            summary = pd.DataFrame([{"Bucket": "local", "Value (RM)": 1.0, "Weight": 1.0, "Target": 0.4,
                                     "Drift": 0.6, "Rebalance?": ""}])
            perf = pd.DataFrame({"Measure": ["My Moomoo portfolio"], "Return %": [None]})
            quiet(lambda: pt.save(summary, perf, {"Date": S, "Moomoo total (RM)": 1.0}, holdings,
                                  pd.DataFrame(), cashflow, None))
            sheet = pd.read_excel(pt.OUT_FILE, sheet_name="Holdings")
        finally:
            pt.OpenSecTradeContext, pt.OUT_FILE, pt.read_sheet = real
    if "Cost (RM)" not in sheet:
        return ("no Cost (RM) column", list(sheet.columns)), (True, 2, 1)
    checked = skipped = bad = 0
    for _, r in sheet.iterrows():
        if pd.isna(r["Cost (RM)"]):
            skipped += 1
            continue
        checked += 1
        tol = max(0.01, 0.0001 * abs(r["Value (RM)"]))
        bad += abs(r["Cost (RM)"] - (r["Value (RM)"] - r["Unrealised P/L (RM)"])) > tol
    return (bad == 0, checked, skipped), (True, 2, 1)


CHECKS = [
    ("deal_window: 90-day cap", deal_window, None),
    ("cashflow_dates: 5-day gap filled", cashflow_dates, None),
    ("xirr: doubling in 365 days = 100%", xirr_doubling, close),
    ("xirr: two deposits = 10%", xirr_two_deposits, close),
    ("xirr: with a withdrawal = 10%", xirr_withdrawal, close),
    ("xirr_flows: anchor rule", xirr_flows_anchor, None),
    ("build_summary: unassigned left out of weights", unassigned_weight, None),
    ("benchmark_returns: failure keeps every label", benchmark_failure, None),
    ("build_summary: income fund row outside weights", fund_cash_like, None),
    ("DEPOSIT_TYPES / IGNORED_TYPES do not overlap", types_disjoint, None),
    ("monthly_boundary: 31 Oct deposit follows the last logged row", monthly_boundary, None),
    ("holdings_cost: Cost (RM) = Value - Unrealised P/L per row", holdings_cost, None),
]


def main():
    failed = 0
    for name, fn, compare in CHECKS:
        try:
            got, want = fn()
            ok = compare(got, want) if compare else got == want
            detail = "" if ok else f"  got {got!r}, expected {want!r}"
        except Exception as e:  # a crash is a failure, not a stop
            ok, detail = False, f"  crashed: {e!r}"
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {name}{detail}")
    print(f"{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
    print("RESULT: PASS" if not failed else "RESULT: FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
