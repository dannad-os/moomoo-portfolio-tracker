import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_tracker as pt  # noqa: E402

S = pt.START_DATE
CF_COLS = ["cashflow_id", "clearing_date", "settlement_date", "currency", "cashflow_type",
           "cashflow_direction", "cashflow_amount", "cashflow_remark", "create_time"]


def cf(rows):
    return pd.DataFrame([dict(zip(CF_COLS, r)) for r in rows], columns=CF_COLS)


# ---------- deal_window ----------
def test_deal_window_caps_at_90_days():
    today = S + timedelta(days=200)
    assert pt.deal_window(today) == ((today - timedelta(days=89)).isoformat(), today.isoformat())


def test_deal_window_floors_at_start_date():
    today = S + timedelta(days=10)
    assert pt.deal_window(today) == (S.isoformat(), today.isoformat())


def test_deal_window_before_start_never_inverted():
    today = S - timedelta(days=2)
    start, end = pt.deal_window(today)
    assert start <= end == today.isoformat()


# ---------- cashflow_dates ----------
def test_cashflow_dates_normal_daily():
    today = S + timedelta(days=10)
    assert pt.cashflow_dates(today - timedelta(days=1), today) == [today - timedelta(days=1), today]


def test_cashflow_dates_gap_of_5_days():
    today = S + timedelta(days=10)
    got = pt.cashflow_dates(today - timedelta(days=5), today)
    assert got == [today - timedelta(days=i) for i in range(5, -1, -1)]


def test_cashflow_dates_before_start():
    assert pt.cashflow_dates(None, S - timedelta(days=1)) == []
    assert pt.cashflow_dates(S - timedelta(days=5), S - timedelta(days=1)) == []


def test_cashflow_dates_first_run():
    assert pt.cashflow_dates(None, S) == [S]
    # old log rows from before START_DATE are floored
    assert pt.cashflow_dates(S - timedelta(days=3), S + timedelta(days=1)) == [S, S + timedelta(days=1)]


# ---------- fetch_cashflow throttle ----------
class FakeCtx:
    def __init__(self):
        self.calls = []

    def get_acc_cash_flow(self, clearing_date, trd_env, acc_id):
        self.calls.append(clearing_date)
        if clearing_date == "2026-10-21":
            return pt.RET_OK, cf([("1", "2026-10-21", "2026-10-21", "MYR", "Deposit", "IN", 100.0, "x", "t")])
        return pt.RET_OK, pd.DataFrame(columns=CF_COLS)


def test_fetch_cashflow_throttles(monkeypatch):
    sleeps = []
    monkeypatch.setattr(pt.time, "sleep", lambda s: sleeps.append(s))
    ctx = FakeCtx()
    dates = [S + timedelta(days=i) for i in range(41)]
    df = pt.fetch_cashflow(ctx, 1, dates)
    assert len(ctx.calls) == 41 and ctx.calls[0] == S.isoformat()
    assert sleeps == [30, 30]
    assert len(df) == 1 and df.iloc[0]["cashflow_id"] == "1"


# ---------- external flow classification ----------
def test_external_flows_classification(capsys):
    df = cf([
        ("1", "2026-10-21", "", "MYR", "Bank Transfer Deposits", "IN", 1000.0, "", ""),
        ("2", "2026-10-22", "", "MYR", "Bank Transfer Deposits", "OUT", -200.0, "", ""),  # withdrawal stand-in
        ("3", "2026-10-01", "", "MYR", "Fund Subscription", "OUT", -3.0, "fund buy", ""),
        ("4", "2026-10-23", "", "MYR", "Mystery", "IN", 5.0, "huh", ""),
        ("5", "2026-10-24", "", "USD", "Bank Transfer Deposits", "IN", 50.0, "", ""),
    ])
    flows = pt.external_flows(df)
    assert flows == [(date(2026, 10, 21), 1000.0), (date(2026, 10, 22), -200.0)]
    out = capsys.readouterr().out
    assert "WARNING: unknown cashflow_type 'Mystery' (huh)" in out
    assert "Fund Subscription" not in out
    assert "USD" in out


# ---------- WP-1.1: Moomoo's real cash-flow type strings ----------
def test_wp11_t1_bank_transfer_deposit_counts_no_warning(capsys):
    df = cf([("1", "2026-10-21", "", "MYR", "Bank Transfer Deposits", "IN", 1234.0, "", "")])
    assert pt.external_flows(df) == [(date(2026, 10, 21), 1234.0)]
    assert "WARNING: unknown cashflow_type" not in capsys.readouterr().out


def test_wp11_t2_fund_subscription_ignored_no_warning(capsys):
    df = cf([("1", "2026-10-22", "", "MYR", "Fund Subscription", "OUT", -500.0, "", "")])
    assert pt.external_flows(df) == []
    assert "WARNING" not in capsys.readouterr().out


@pytest.mark.parametrize("guess", ["Deposit", "Withdrawal", "Transfer", "Others"])
def test_wp11_t3_old_guesses_now_unknown(capsys, guess):
    df = cf([("1", "2026-10-23", "", "MYR", guess, "IN", 10.0, "r", "")])
    assert pt.external_flows(df) == []
    assert f"WARNING: unknown cashflow_type '{guess}'" in capsys.readouterr().out


def test_wp11_t4_type_settings_pinned():
    assert pt.DEPOSIT_TYPES == {"Bank Transfer Deposits"}
    assert pt.IGNORED_TYPES == {"Fund Subscription"}


def test_net_deposits_setting_removed():
    assert not hasattr(pt, "NET_DEPOSITS")


# ---------- WP-1.4: interest rows under Others ----------
def test_wp14_t1_others_interest_known_no_warning(capsys):
    df = cf([("1", "2026-10-31", "", "MYR", "Others", "IN", 1.23, "Interest In Oct.", "")])
    assert pt.external_flows(df) == []
    assert "WARNING" not in capsys.readouterr().out


@pytest.mark.parametrize("remark", ["interest in nov", "  Interest paid"])
def test_wp14_t2_interest_case_and_leading_spaces(capsys, remark):
    df = cf([("1", "2026-11-30", "", "MYR", "Others", "IN", 0.45, remark, "")])
    assert pt.external_flows(df) == []
    assert "WARNING" not in capsys.readouterr().out


def test_wp14_t3_others_other_remark_still_warns(capsys):
    df = cf([("1", "2026-10-25", "", "MYR", "Others", "IN", 10.0, "Transfer in", "")])
    assert pt.external_flows(df) == []
    assert "WARNING: unknown cashflow_type 'Others' (Transfer in)" in capsys.readouterr().out


@pytest.mark.parametrize("remark", [None, ""])
def test_wp14_t4_others_missing_remark_still_warns(capsys, remark):
    df = cf([("1", "2026-10-26", "", "MYR", "Others", "IN", 2.0, remark, "")])
    assert pt.external_flows(df) == []
    assert "WARNING: unknown cashflow_type 'Others'" in capsys.readouterr().out


def test_wp14_t5_remark_prefix_setting_pinned():
    assert pt.IGNORED_REMARK_PREFIXES == {"Others": ("Interest",)}
    assert pt.DEPOSIT_TYPES == {"Bank Transfer Deposits"}
    assert pt.IGNORED_TYPES == {"Fund Subscription"}


def test_wp14_t6_warn_false_prints_nothing(capsys):
    df = cf([
        ("1", "2026-10-31", "", "MYR", "Others", "IN", 1.23, "Interest In Oct.", ""),
        ("2", "2026-10-25", "", "MYR", "Others", "IN", 10.0, "Transfer in", ""),
    ])
    assert pt.external_flows(df, warn=False) == []
    assert capsys.readouterr().out == ""


def test_wp14_mixed_deposit_and_interest(capsys):
    df = cf([
        ("1", "2026-10-21", "", "MYR", "Bank Transfer Deposits", "IN", 1000.0, "", ""),
        ("2", "2026-10-31", "", "MYR", "Others", "IN", 1.23, "Interest In Oct.", ""),
    ])
    assert pt.external_flows(df) == [(date(2026, 10, 21), 1000.0)]
    assert "WARNING" not in capsys.readouterr().out


# ---------- xirr ----------
def test_xirr_doubling_one_year():
    d0 = date(2025, 1, 1)
    assert pt.xirr([(d0, -100.0), (d0 + timedelta(days=365), 200.0)]) == pytest.approx(1.0, abs=1e-6)


def test_xirr_two_deposits():
    d0 = date(2025, 1, 1)
    flows = [(d0, -100.0), (d0 + timedelta(days=365), -100.0), (d0 + timedelta(days=730), 231.0)]
    r = pt.xirr(flows)
    # 100*(1+r)^2 + 100*(1+r) = 231 -> r = 0.1
    assert r == pytest.approx(0.1, abs=1e-6)


def test_xirr_with_withdrawal():
    d0 = date(2025, 1, 1)
    flows = [(d0, -1000.0), (d0 + timedelta(days=365), 100.0), (d0 + timedelta(days=730), 1100.0)]
    assert pt.xirr(flows) == pytest.approx(0.1, abs=1e-6)


def test_xirr_none_cases():
    d0 = date(2025, 1, 1)
    assert pt.xirr([(d0, -100.0)]) is None
    assert pt.xirr([(d0, -100.0), (d0 + timedelta(days=30), -50.0)]) is None
    assert pt.xirr([]) is None


# ---------- xirr_flows ----------
def log(rows):
    return pd.DataFrame([{"Date": d, "Moomoo total (RM)": t} for d, t in rows])


def test_xirr_flows_no_anchor():
    today = S - timedelta(days=2)
    assert pt.xirr_flows(log([(S - timedelta(days=3), 900.0)]), cf([]), today, 900.0) is None


def test_xirr_flows_anchor_day():
    flows = pt.xirr_flows(log([(S - timedelta(days=2), 900.0)]), cf([]), S, 30_000.0)
    assert flows == [(S, -30_000.0), (S, 30_000.0)]
    assert pt.xirr(flows) == 0.0


def test_xirr_flows_anchor_deposit_today():
    today = S + timedelta(days=30)
    lg = log([(S - timedelta(days=2), 900.0), (pd.Timestamp(S), 30_000.0), (S + timedelta(days=1), 30_100.0)])
    c = cf([
        ("1", S.isoformat(), "", "MYR", "Bank Transfer Deposits", "IN", 999.0, "", ""),   # on anchor day: excluded
        ("2", (S + timedelta(days=5)).isoformat(), "", "MYR", "Bank Transfer Deposits", "IN", 5000.0, "", ""),
        ("3", (S + timedelta(days=6)).isoformat(), "", "MYR", "Fund Subscription", "OUT", -3.0, "", ""),
    ])
    flows = pt.xirr_flows(lg, c, today, 36_000.0)
    assert flows == [(S, -30_000.0), (S + timedelta(days=5), -5000.0), (today, 36_000.0)]


# ---------- build_summary ----------
def holdings():
    return pd.DataFrame([
        {"Code": "MY.0005", "Bucket": "local", "Value (RM)": 800.0},
        {"Code": "US.XYZ", "Bucket": "unassigned", "Value (RM)": 100.0},
    ])


def test_build_summary_unassigned_excluded_from_weights():
    summary, perf, row, since = pt.build_summary(holdings(), {"total": 900.07, "cash": 0.0}, {},
                                                 S - timedelta(days=2), log([]), cf([]))
    s = summary.set_index("Bucket")
    assert s.loc["local", "Weight"] == pytest.approx(1.0)
    assert s.loc["unassigned", "Rebalance?"] == "Add these codes to BUCKETS in the script"
    assert row["Moomoo XIRR %"] is None and row["Moomoo return %"] is None
    assert since is None


def test_build_summary_with_anchor_and_deposit():
    today = S + timedelta(days=30)
    lg = log([(S, 30_000.0)])
    c = cf([("2", (S + timedelta(days=5)).isoformat(), "", "MYR", "Bank Transfer Deposits", "IN", 5000.0, "", "")])
    summary, perf, row, since = pt.build_summary(holdings(), {"total": 36_000.0, "cash": 0.0}, {}, today, lg, c)
    assert since == S
    assert row["Net deposits (RM)"] == 5000.0
    assert row["Moomoo return %"] == pytest.approx(36_000 / 35_000 - 1)
    assert row["Moomoo XIRR %"] > 0
    m = perf.set_index("Measure")["Return %"]
    assert m["My Moomoo portfolio"] == row["Moomoo XIRR %"]
    assert m["My Moomoo portfolio (simple)"] == row["Moomoo return %"]


# ---------- benchmark failure ----------
def test_benchmark_failure_keeps_labels(monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(pt.yf, "download", boom)
    out = pt.benchmark_returns(S)
    labels = [label for _, label, _ in pt.BENCHMARKS.values()] + ["Blended benchmark (40/20/40)"]
    assert list(out) == labels
    assert all(pd.isna(v) for v in out.values())
    assert "WARNING: benchmarks skipped" in capsys.readouterr().out


# ================= Round 2 =================
import io  # noqa: E402
import itertools  # noqa: E402

D0 = date(2025, 1, 1)


def test_xirr_losing_case():  # mutant: lower bound -0.99 -> 0.0
    assert pt.xirr([(D0, -100.0), (D0 + timedelta(days=365), 80.0)]) == pytest.approx(-0.2, abs=1e-6)


def test_xirr_all_positive_same_day_is_none():  # mutant: drop "needs a negative flow"
    assert pt.xirr([(D0, 100.0), (D0, 50.0)]) is None


def test_xirr_out_of_bracket_is_none():  # mutant: drop "no sign change" check
    assert pt.xirr([(D0, -1.0), (D0 + timedelta(days=1), 2.0)]) is None


def test_anchor_same_day_rerun_uses_live_total():
    lg = log([(S, 39_000.0)])
    assert pt.anchor(lg, S, 30_000.0) == (S, 30_000.0)
    _, _, row, _ = pt.build_summary(holdings(), {"total": 30_000.0, "cash": 0.0}, {}, S, lg, cf([]))
    assert row["Moomoo return %"] == 0.0


def test_cashflow_dates_same_day_rerun_includes_yesterday():
    today = S + timedelta(days=10)
    assert pt.cashflow_dates(today, today) == [today - timedelta(days=1), today]


class IntIdCtx:
    def __init__(self):
        self.calls = 0

    def get_acc_cash_flow(self, clearing_date, trd_env, acc_id):
        self.calls += 1
        return pt.RET_OK, cf([(123456789012345678, clearing_date, "", "MYR", "Deposit", "IN", 1.0, "", "")])


def test_fetch_cashflow_id_is_text():
    df = pt.fetch_cashflow(IntIdCtx(), 1, [S])
    assert df.iloc[0]["cashflow_id"] == "123456789012345678"


def test_fetch_cashflow_counter_shared_across_accounts(monkeypatch):
    sleeps = []
    monkeypatch.setattr(pt.time, "sleep", lambda s: sleeps.append(s))
    ctx, counter = FakeCtx(), itertools.count(1)
    dates = [S + timedelta(days=i) for i in range(15)]
    pt.fetch_cashflow(ctx, 1, dates, counter)
    assert sleeps == []
    pt.fetch_cashflow(ctx, 2, dates, counter)
    assert len(ctx.calls) == 30 and sleeps == [30]  # slept after call 20, inside account 2


def test_build_summary_all_in_return():
    today = S + timedelta(days=30)
    c = cf([("2", (S + timedelta(days=5)).isoformat(), "", "MYR", "Bank Transfer Deposits", "IN", 5000.0, "", "")])
    _, _, row, _ = pt.build_summary(holdings(), {"total": 36_000.0, "cash": 0.0}, {}, today, log([(S, 30_000.0)]), c)
    pot = pt.SAVINGS_START * (1 + pt.SAVINGS_RATE / 365) ** 30
    assert row["All-in return %"] == pytest.approx((36_000 + pot) / (30_000 + 5000 + pt.SAVINGS_START) - 1)


def test_build_summary_zero_opening_no_crash():
    today = S + timedelta(days=30)
    _, _, row, _ = pt.build_summary(holdings(), {"total": 100.0, "cash": 0.0}, {}, today, log([(S, 0.0)]), cf([]))
    assert row["Moomoo return %"] is None


def test_merge_cashflow_dedups_int_old_vs_str_new():
    old = cf([(123456789012345678, "2026-10-21", "", "MYR", "Deposit", "IN", 1.0, "old", "")])
    new = cf([("123456789012345678", "2026-10-21", "", "MYR", "Deposit", "IN", 1.0, "new", "")])
    m = pt.merge_cashflow(old, new)
    assert len(m) == 1
    assert m.iloc[0]["cashflow_id"] == "123456789012345678" and m.iloc[0]["cashflow_remark"] == "new"
    assert list(m.columns) == pt.CASHFLOW_COLS


def run_main(monkeypatch, today, last_log, new_cf, totals=None):
    class FakeDate(date):
        @classmethod
        def today(cls):
            return today
    seen = {}
    monkeypatch.setattr(pt, "date", FakeDate)
    monkeypatch.setattr(pt, "read_sheet", lambda name: log([(last_log, 30_000.0)]) if name == "Daily_Log" else pd.DataFrame())
    def fake_fetch(dates):
        seen["dates"] = dates
        return holdings(), totals or {"total": 30_000.0, "cash": 0.0}, pd.DataFrame(), new_cf
    monkeypatch.setattr(pt, "fetch", fake_fetch)
    monkeypatch.setattr(pt, "benchmark_returns", lambda t: {})
    monkeypatch.setattr(pt, "save", lambda *a: None)
    pt.main()
    return seen


def test_main_pulls_cashflow_since_last_log(monkeypatch):
    today = S + timedelta(days=10)
    seen = run_main(monkeypatch, today, today - timedelta(days=4), cf([]))
    assert seen["dates"] == pt.cashflow_dates(today - timedelta(days=4), today)


def test_main_survives_non_latin_warning_on_cp1252_stdout(monkeypatch):
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    today = S + timedelta(days=10)
    c = cf([("9", today.isoformat(), "", "MYR", "入金", "IN", 5.0, "银行转账", "")])
    run_main(monkeypatch, today, today - timedelta(days=1), c)


class TwoAccountCtx(FakeCtx):
    """Fake OpenD context with two REAL accounts, no positions, no deals."""
    def __init__(self, **kw):
        super().__init__()

    def get_acc_list(self):
        return pt.RET_OK, pd.DataFrame({"acc_id": [1, 2], "trd_env": [pt.TrdEnv.REAL] * 2})

    def accinfo_query(self, **kw):
        return pt.RET_OK, pd.DataFrame([{"total_assets": 100.0, "cash": 10.0}])

    def position_list_query(self, **kw):
        return pt.RET_OK, pd.DataFrame(columns=["qty"])

    def history_deal_list_query(self, **kw):
        return pt.RET_OK, pd.DataFrame()

    deal_list_query = history_deal_list_query

    def close(self):
        pass


def test_fetch_throttle_counter_shared_across_two_accounts(monkeypatch):
    sleeps = []
    monkeypatch.setattr(pt.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(pt, "OpenSecTradeContext", TwoAccountCtx)
    _, totals, _, cashflow = pt.fetch([S + timedelta(days=i) for i in range(15)])
    assert totals == {"total": 200.0, "cash": 20.0, "fund": 0.0}  # WP-1.2: no fund fields -> 0.0
    assert sleeps == [30]  # 30 calls over 2 accounts -> one pause after call 20
    assert len(cashflow) == 2  # one row from each account


# ================= WP-1.2: income fund carried as cash-like =================
FUND_TEXT = "Cash-like, outside the buckets"


def three_buckets():
    return pd.DataFrame([
        {"Code": "MY.0005", "Bucket": "local", "Value (RM)": 400.0},
        {"Code": "SG.ES3", "Bucket": "regional", "Value (RM)": 300.0},
        {"Code": "US.VT", "Bucket": "global", "Value (RM)": 300.0},
    ])


def test_build_summary_fund_row_outside_weights():  # T1
    fund = 123.45
    summary, _, row, _ = pt.build_summary(three_buckets(), {"total": 1200.0, "cash": 76.55, "fund": fund},
                                          {}, S - timedelta(days=2), log([]), cf([]))
    base, _, _, _ = pt.build_summary(three_buckets(), {"total": 1076.55, "cash": 76.55, "fund": 0.0},
                                     {}, S - timedelta(days=2), log([]), cf([]))
    s, b = summary.set_index("Bucket"), base.set_index("Bucket")
    assert pt.FUND_LABEL in s.index
    f = s.loc[pt.FUND_LABEL]
    assert f["Value (RM)"] == fund
    assert pd.isna(f["Weight"]) and pd.isna(f["Target"]) and pd.isna(f["Drift"])
    assert f["Rebalance?"] == FUND_TEXT
    assert list(summary["Bucket"]).index(pt.FUND_LABEL) > max(list(summary["Bucket"]).index(k) for k in pt.TARGETS)
    for k in pt.TARGETS:
        assert s.loc[k, "Weight"] == b.loc[k, "Weight"]
        assert s.loc[k, "Drift"] == b.loc[k, "Drift"]
        assert s.loc[k, "Rebalance?"] == b.loc[k, "Rebalance?"]
    keys = list(row)
    assert row["Fund (RM)"] == fund
    assert keys.index("Fund (RM)") == keys.index("Cash (RM)") + 1


@pytest.mark.parametrize("totals", [{"total": 1000.0, "cash": 0.0, "fund": 0.0}, {"total": 1000.0, "cash": 0.0}])
def test_build_summary_no_fund_no_row(totals):  # T2
    summary, _, row, _ = pt.build_summary(three_buckets(), totals, {}, S - timedelta(days=2), log([]), cf([]))
    assert pt.FUND_LABEL not in list(summary["Bucket"])
    assert "Fund (RM)" in row and row["Fund (RM)"] == 0.0


class FundCtx(TwoAccountCtx):
    """Two REAL accounts whose accinfo carries the income fund (and a bond) field."""
    ROWS = {1: {"total_assets": 100.0, "cash": 10.0, "fund_assets": 25.5, "bond_assets": 1.25},
            2: {"total_assets": 200.0, "cash": 20.0, "fund_assets": 40.0, "bond_assets": 0.0}}

    def accinfo_query(self, acc_id=None, **kw):
        return pt.RET_OK, pd.DataFrame([self.ROWS[acc_id]])


def test_fetch_fund_summed_across_accounts(monkeypatch):  # T3
    monkeypatch.setattr(pt.time, "sleep", lambda s: None)
    monkeypatch.setattr(pt, "OpenSecTradeContext", FundCtx)
    _, totals, _, _ = pt.fetch([])
    assert totals["total"] == 300.0 and totals["cash"] == 30.0
    assert totals["fund"] == pytest.approx(25.5 + 1.25 + 40.0)


def test_fetch_no_fund_fields_is_zero(monkeypatch):  # T3, missing fields
    monkeypatch.setattr(pt, "OpenSecTradeContext", TwoAccountCtx)
    _, totals, _, _ = pt.fetch([])
    assert totals["fund"] == 0.0


# holdings() sums to 900.0; the fund closes the gap to the total exactly
FUND_OK = {"total": 1000.0, "cash": 0.0, "fund": 105.8}
FUND_MISSING = {"total": 1000.0, "cash": 0.0}  # same total, fund not counted: 10.58% gap


def test_main_fund_closes_reconciliation(monkeypatch, capsys):  # T4
    today = S + timedelta(days=10)
    run_main(monkeypatch, today, today - timedelta(days=1), cf([]), dict(FUND_OK))
    assert "WARNING: holdings" not in capsys.readouterr().out


def test_main_real_gap_warns_and_names_fund(monkeypatch, capsys):  # T4
    today = S + timedelta(days=10)
    run_main(monkeypatch, today, today - timedelta(days=1), cf([]), dict(FUND_MISSING))
    warn = [ln for ln in capsys.readouterr().out.splitlines() if "WARNING: holdings" in ln]
    assert len(warn) == 1 and "fund" in warn[0]


def test_main_reconcile_tol_is_used(monkeypatch, capsys):  # T5
    assert pt.RECONCILE_TOL == 0.02
    monkeypatch.setattr(pt, "RECONCILE_TOL", 0.5)
    today = S + timedelta(days=10)
    run_main(monkeypatch, today, today - timedelta(days=1), cf([]), dict(FUND_MISSING))
    assert "WARNING: holdings" not in capsys.readouterr().out


# ================= WP-2.1: Monthly and Chart sheets, days since anchor =================
MCOLS = ["Month", "End value (RM)", "Deposits (RM)", "Withdrawals (RM)", "Trades", "Month return %", "Note"]
A21 = date(2026, 10, 20)  # anchor used by the monthly tests (fixed, not START_DATE)
DEAL_COLS = ["Deal ID", "Time", "Code", "Name", "Bucket", "Side", "Qty", "Price"]


def no_deals():
    return pd.DataFrame(columns=DEAL_COLS)


def deals(times):
    return pd.DataFrame([{"Deal ID": str(i), "Time": t, "Code": "MY.0001", "Name": "Fake", "Bucket": "local",
                          "Side": "BUY", "Qty": 1.0, "Price": 1.0} for i, t in enumerate(times)], columns=DEAL_COLS)


def mrow(df, month):
    hit = df[df["Month"] == month]
    assert len(hit) == 1, f"{month}: {len(hit)} rows"
    return hit.iloc[0]


def test_wp21_t1_month_return_formula():  # T1: (E - S - F) / (S + F)
    lg = log([(A21, 1000.0), (date(2026, 10, 31), 1600.0)])
    m = pt.monthly_table(lg, [(date(2026, 10, 25), 500.0)], no_deals(), A21)
    assert list(m.columns) == MCOLS and len(m) == 1
    r = m.iloc[0]
    assert r["Month"] == "2026-10"
    assert r["End value (RM)"] == 1600.0 and r["Deposits (RM)"] == 500.0 and r["Withdrawals (RM)"] == 0
    assert r["Month return %"] == pytest.approx(100 / 1500)


def test_wp21_t1_zero_base_is_none():  # T1: S + F == 0 -> None
    m = pt.monthly_table(log([(A21, 0.0), (date(2026, 10, 31), 0.0)]), [], no_deals(), A21)
    assert pd.isna(m.iloc[0]["Month return %"])


def test_wp21_t2_month_boundary_both_days_logged():  # T2
    lg = log([(A21, 1000.0), (date(2026, 10, 30), 1040.0), (date(2026, 10, 31), 1100.0),
              (date(2026, 11, 1), 1300.0)])
    flows = [(date(2026, 10, 31), 50.0), (date(2026, 11, 1), 150.0)]
    m = pt.monthly_table(lg, flows, no_deals(), A21)
    assert list(m["Month"]) == ["2026-10", "2026-11"]
    assert mrow(m, "2026-10")["Deposits (RM)"] == 50.0 and mrow(m, "2026-10")["End value (RM)"] == 1100.0
    assert mrow(m, "2026-11")["Deposits (RM)"] == 150.0
    assert mrow(m, "2026-11")["Month return %"] == pytest.approx((1300 - 1100 - 150) / (1100 + 150))


def test_wp21_t2_missing_last_day_row_moves_flow_to_next_window():  # T2
    lg = log([(A21, 1000.0), (date(2026, 10, 30), 1040.0), (date(2026, 11, 1), 1300.0)])
    flows = [(date(2026, 10, 31), 50.0), (date(2026, 11, 1), 150.0)]
    m = pt.monthly_table(lg, flows, no_deals(), A21)
    oct_, nov = mrow(m, "2026-10"), mrow(m, "2026-11")
    assert oct_["Deposits (RM)"] == 0 and oct_["End value (RM)"] == 1040.0
    assert oct_["Month return %"] == pytest.approx(0.04)
    assert nov["Deposits (RM)"] == 200.0
    assert nov["Month return %"] == pytest.approx((1300 - 1040 - 200) / (1040 + 200))


def test_wp21_t3_anchor_day_and_pre_anchor_excluded():  # T3
    lg = log([(date(2026, 9, 30), 500.0), (date(2026, 10, 18), 900.0), (A21, 1000.0),
              (date(2026, 10, 28), 1100.0)])
    flows = [(date(2026, 9, 30), 7.0), (date(2026, 10, 19), 77.0), (A21, 999.0)]
    m = pt.monthly_table(lg, flows, no_deals(), A21)
    assert list(m["Month"]) == ["2026-10"]
    r = m.iloc[0]
    assert r["Deposits (RM)"] == 0 and r["Withdrawals (RM)"] == 0
    assert r["Month return %"] == pytest.approx(0.1)  # start = anchor total 1000, not 900 or 500


@pytest.mark.parametrize("since,rows", [(None, [(A21, 1000.0)]), (A21, [(date(2026, 10, 18), 900.0)]), (A21, [])])
def test_wp21_t3_empty_frame(since, rows):  # T3: no anchor / no rows on or after it
    lg = log(rows) if rows else pd.DataFrame(columns=["Date", "Moomoo total (RM)"])
    m = pt.monthly_table(lg, [], no_deals(), since)
    assert list(m.columns) == MCOLS and len(m) == 0


def test_wp21_t4_no_flow_month():  # T4
    lg = log([(A21, 1000.0), (date(2026, 10, 31), 1050.0), (date(2026, 11, 30), 1155.0)])
    m = pt.monthly_table(lg, [], no_deals(), A21)
    nov = mrow(m, "2026-11")
    assert nov["Deposits (RM)"] == 0 and nov["Withdrawals (RM)"] == 0
    assert nov["Month return %"] == pytest.approx(1155 / 1050 - 1)


def test_wp21_t4_internal_move_only():  # T4: Fund Subscription is not a flow
    c = cf([("1", "2026-10-25", "", "MYR", "Fund Subscription", "OUT", -300.0, "", "")])
    flows = pt.external_flows(c)
    assert flows == []
    m = pt.monthly_table(log([(A21, 1000.0), (date(2026, 10, 31), 1020.0)]), flows, no_deals(), A21)
    r = m.iloc[0]
    assert r["Deposits (RM)"] == 0 and r["Withdrawals (RM)"] == 0
    assert r["Month return %"] == pytest.approx(0.02)


def test_wp21_t5_withdrawal_positive_and_reduces_f():  # T5
    lg = log([(A21, 1000.0), (date(2026, 10, 31), 850.0)])
    m = pt.monthly_table(lg, [(date(2026, 10, 25), -200.0), (date(2026, 10, 26), 100.0)], no_deals(), A21)
    r = m.iloc[0]
    assert r["Withdrawals (RM)"] == 200.0 and r["Deposits (RM)"] == 100.0
    # F = 100 - 200 = -100
    assert r["Month return %"] == pytest.approx((850 - 1000 + 100) / (1000 - 100))


def test_wp21_t6_trade_count_per_window():  # T6: Time is a string; window is by date
    lg = log([(A21, 1000.0), (date(2026, 10, 31), 1010.0), (date(2026, 11, 2), 1020.0)])
    d = deals(["2026-10-22 10:00:00.123", "2026-10-31 23:59:59", "2026-11-01 09:30:00", "2026-10-19 09:00:00"])
    m = pt.monthly_table(lg, [], d, A21)
    assert int(mrow(m, "2026-10")["Trades"]) == 2
    assert int(mrow(m, "2026-11")["Trades"]) == 1


def test_wp21_t6_no_trades_is_zero():  # T6
    m = pt.monthly_table(log([(A21, 1000.0), (date(2026, 10, 31), 1010.0)]), [], no_deals(), A21)
    assert int(m.iloc[0]["Trades"]) == 0


def test_wp21_t7_note_column():  # T7
    lg = log([(A21, 1000.0), (date(2026, 10, 31), 1010.0), (date(2026, 11, 30), 1020.0),
              (date(2026, 12, 5), 1030.0)])
    m = pt.monthly_table(lg, [], no_deals(), A21)
    assert list(m["Month"]) == ["2026-10", "2026-11", "2026-12"]
    assert list(m["Note"]) == ["from 2026-10-20", "", "to 2026-12-05"]


def test_wp21_t7_note_single_open_month():  # T7: first AND open month
    m = pt.monthly_table(log([(A21, 1000.0), (date(2026, 10, 25), 1010.0)]), [], no_deals(), A21)
    assert list(m["Note"]) == ["from 2026-10-20, to 2026-10-25"]


def test_wp21_t8_external_flows_warn_flag(capsys):  # T8
    c = cf([("1", "2026-10-21", "", "MYR", "Bank Transfer Deposits", "IN", 10.0, "", ""),
            ("2", "2026-10-22", "", "MYR", "Mystery", "IN", 5.0, "huh", ""),
            ("3", "2026-10-23", "", "USD", "Bank Transfer Deposits", "IN", 50.0, "", "")])
    assert pt.external_flows(c, warn=False) == [(date(2026, 10, 21), 10.0)]
    assert capsys.readouterr().out == ""
    assert pt.external_flows(c) == [(date(2026, 10, 21), 10.0)]
    out = capsys.readouterr().out
    assert "WARNING: unknown cashflow_type 'Mystery'" in out and "USD" in out


@pytest.mark.parametrize("today,lg,want", [
    (S, log([]), 0),
    (S + timedelta(days=5), log([(S, 1000.0)]), 5),
    (S - timedelta(days=2), log([]), None),
])
def test_wp21_t9_days_since_anchor(today, lg, want):  # T9
    _, _, row, _ = pt.build_summary(holdings(), {"total": 1000.0, "cash": 0.0}, {}, today, lg, cf([]))
    assert "Days since anchor" in row and row["Days since anchor"] == want
    keys = list(row)
    assert keys.index("Days since anchor") == keys.index("Net deposits (RM)") + 1


SHEETS = ["Summary", "Monthly", "Chart", "Holdings", "Daily_Log", "Trades", "Cashflow"]
BLEND_PCT = "Blended benchmark (40/20/40) %"


def save_fake(monkeypatch, tmp_path, rows, since, cashflow=None):
    """pt.save into tmp_path; rows: (date, total, return, blend), the last one is this run's row."""
    from openpyxl import load_workbook as ox_load
    out = tmp_path / "Fake_Tracker.xlsx"
    monkeypatch.setattr(pt, "OUT_FILE", out)
    mk = lambda d, t, r, b: {"Date": d, "Moomoo total (RM)": t, "Moomoo return %": r, BLEND_PCT: b}  # noqa: E731
    prior = pd.DataFrame([mk(*r) for r in rows[:-1]])
    monkeypatch.setattr(pt, "read_sheet", lambda name: prior.copy() if name == "Daily_Log" else pd.DataFrame())
    summary = pd.DataFrame([{"Bucket": "local", "Value (RM)": 1.0, "Weight": 1.0, "Target": 0.4,
                             "Drift": 0.6, "Rebalance?": ""}])
    perf = pd.DataFrame({"Measure": ["My Moomoo portfolio"], "Return %": [0.01]})
    cashflow = pd.DataFrame(columns=pt.CASHFLOW_COLS) if cashflow is None else cashflow
    pt.save(summary, perf, mk(*rows[-1]), holdings(), deals(["2026-10-22 10:00:00"]), cashflow, since)
    return ox_load(out)


def test_wp21_t10_save_sheets_monthly_chart(monkeypatch, tmp_path, capsys):  # T10
    c = cf([("1", "2026-10-22", "", "MYR", "Bank Transfer Deposits", "IN", 10.0, "", ""),
            ("2", "2026-10-23", "", "MYR", "Mystery", "IN", 5.0, "huh", "")])
    rows = [(date(2026, 10, 18), 900.0, None, 0.001), (A21, 1000.0, 0.0, 0.002),
            (date(2026, 10, 25), 1021.0, 0.011, 0.015)]
    wb = save_fake(monkeypatch, tmp_path, rows, A21, c[pt.CASHFLOW_COLS])
    assert wb.sheetnames == SHEETS
    assert [cell.value for cell in wb["Monthly"][1]] == MCOLS
    assert wb["Monthly"]["A2"].value == "2026-10"
    assert len(wb["Chart"]._charts) == 1
    assert "ChartData" in wb["Chart"].tables
    assert "WARNING" not in capsys.readouterr().out  # save calls external_flows(warn=False)


def test_wp21_t10_no_chart_without_returns(monkeypatch, tmp_path):  # T10
    rows = [(A21, 1000.0, None, None), (date(2026, 10, 25), 1021.0, None, None)]
    wb = save_fake(monkeypatch, tmp_path, rows, A21)
    assert wb.sheetnames == SHEETS
    assert [cell.value for cell in wb["Monthly"][1]] == MCOLS
    assert len(wb["Chart"]._charts) == 0
    assert "ChartData" in wb["Chart"].tables


# ================= WP-2.1 round 2 =================
def test_wp21_r1_chart_axes_shown(monkeypatch, tmp_path):  # R1: delete=None reads as hidden in Excel
    rows = [(A21, 1000.0, 0.0, 0.002), (date(2026, 10, 25), 1021.0, 0.011, 0.015)]
    wb = save_fake(monkeypatch, tmp_path, rows, A21)
    (chart,) = wb["Chart"]._charts
    assert chart.x_axis.delete is False
    assert chart.y_axis.delete is False


@pytest.mark.parametrize("blank", ["", None])
def test_wp21_r2_blank_trade_time_dropped(blank):  # R2
    lg = log([(A21, 1000.0), (date(2026, 10, 31), 1010.0)])
    m = pt.monthly_table(lg, [], deals([blank, "2026-10-22 10:00:00"]), A21)
    assert int(m.iloc[0]["Trades"]) == 1


@pytest.mark.parametrize("blank", ["", None])
def test_wp21_r2_save_survives_blank_trade_time(monkeypatch, tmp_path, blank):  # R2: the day's row is kept
    from openpyxl import load_workbook as ox_load
    out = tmp_path / "Fake_Tracker.xlsx"
    monkeypatch.setattr(pt, "OUT_FILE", out)
    prior = pd.DataFrame([{"Date": A21, "Moomoo total (RM)": 1000.0, "Moomoo return %": 0.0}])
    monkeypatch.setattr(pt, "read_sheet", lambda name: prior.copy() if name == "Daily_Log" else pd.DataFrame())
    summary = pd.DataFrame([{"Bucket": "local", "Value (RM)": 1.0, "Weight": 1.0, "Target": 0.4,
                             "Drift": 0.6, "Rebalance?": ""}])
    perf = pd.DataFrame({"Measure": ["My Moomoo portfolio"], "Return %": [0.01]})
    row = {"Date": date(2026, 10, 25), "Moomoo total (RM)": 1021.0, "Moomoo return %": 0.021}
    pt.save(summary, perf, row, holdings(), deals(["2026-10-22 10:00:00", blank]),
            pd.DataFrame(columns=pt.CASHFLOW_COLS), A21)
    dates = [r[0] for r in ox_load(out)["Daily_Log"].iter_rows(min_row=2, values_only=True)]
    assert pd.Timestamp(dates[-1]).date() == date(2026, 10, 25) and len(dates) == 2


@pytest.mark.parametrize("junk", ["n/a", " "])
def test_wp21_r4_junk_trade_time_dropped(junk):  # R4: unparseable text, not only blank
    test_wp21_r2_blank_trade_time_dropped(junk)


@pytest.mark.parametrize("junk", ["n/a", " "])
def test_wp21_r4_save_survives_junk_trade_time(monkeypatch, tmp_path, junk):  # R4
    test_wp21_r2_save_survives_blank_trade_time(monkeypatch, tmp_path, junk)


# ================= WP-1.3: Cost (RM) column on Holdings =================
HOLDING_ORDER = ["Code", "Name", "Bucket", "Qty", "Currency", "Avg cost", "Price",
                 "Cost (RM)", "Value (RM)", "Unrealised P/L (RM)", "P/L %"]


def cost_myr():
    """pt.cost_myr looked up at call time, so a missing function fails only the WP-1.3 tests."""
    fn = getattr(pt, "cost_myr", None)
    assert fn is not None, "portfolio_tracker.cost_myr is missing"
    return fn


def test_wp13_t1_cost_myr_value():
    assert cost_myr()(10, 2.50, 4.0) == pytest.approx(100.00)
    assert isinstance(cost_myr()(10, 2.50, 4.0), float)


def test_wp13_t1_cost_myr_myr_rate_one():
    assert cost_myr()(100, 1.5, 1.0) == pytest.approx(150.0)


@pytest.mark.parametrize("missing", [None, float("nan"), "N/A"])
def test_wp13_t2_cost_myr_missing_is_none(missing):
    assert cost_myr()(10, missing, 4.0) is None


def pos(code, name, qty, cur, avg, price, mval, upl, ratio):
    return {"code": code, "stock_name": name, "qty": qty, "currency": cur, "average_cost": avg,
            "nominal_price": price, "market_val": mval, "unrealized_pl": upl, "pl_ratio_avg_cost": ratio}


class PositionCtx(TwoAccountCtx):
    """One REAL account: a USD row (rate 4.0 from 400 MYR / 100 USD totals), a MYR row, a qty-0 row."""
    ROWS = [
        pos("US.FAKE", "Fake USD", 10.0, "USD", 2.5, 3.0, 30.0, 5.0, 20.0),       # cost 100, value 120, P/L 20
        pos("MY.0001", "Fake MYR", 100.0, "MYR", 1.5, 1.6, 160.0, 10.0, 6.6667),  # cost 150, value 160, P/L 10
        pos("MY.0002", "Sold out", 0.0, "MYR", 9.0, 9.0, 0.0, 0.0, 0.0),
    ]

    def get_acc_list(self):
        return pt.RET_OK, pd.DataFrame({"acc_id": [1], "trd_env": [pt.TrdEnv.REAL]})

    def accinfo_query(self, currency=None, **kw):
        total = 400.0 if currency == pt.Currency.MYR else 100.0
        return pt.RET_OK, pd.DataFrame([{"total_assets": total, "cash": 0.0}])

    def position_list_query(self, **kw):
        return pt.RET_OK, pd.DataFrame(self.ROWS)


def fetched_holdings(monkeypatch):
    monkeypatch.setattr(pt, "OpenSecTradeContext", PositionCtx)
    h, _, _, _ = pt.fetch([])
    return h.set_index("Code", drop=False)


def test_wp13_t3_fetch_writes_cost_column(monkeypatch):
    h = fetched_holdings(monkeypatch)
    assert "Cost (RM)" in h.columns
    assert h.loc["US.FAKE", "Cost (RM)"] == pytest.approx(10 * 2.5 * 4.0)
    assert h.loc["MY.0001", "Cost (RM)"] == pytest.approx(100 * 1.5 * 1.0)


def test_wp13_t3_fetch_column_order(monkeypatch):
    assert list(fetched_holdings(monkeypatch).columns) == HOLDING_ORDER


def test_wp13_t3_value_minus_cost_is_pl(monkeypatch):
    h = fetched_holdings(monkeypatch)
    assert "Cost (RM)" in h.columns
    for code in ("US.FAKE", "MY.0001"):
        r = h.loc[code]
        assert r["Value (RM)"] - r["Cost (RM)"] == pytest.approx(r["Unrealised P/L (RM)"], abs=0.01)


def test_wp13_t4_qty_zero_still_left_out(monkeypatch):
    h = fetched_holdings(monkeypatch)
    assert list(h["Code"]) == ["US.FAKE", "MY.0001"]
    assert "Cost (RM)" in h.columns


def test_wp13_t5_empty_holdings_fallback_has_cost(monkeypatch, tmp_path):
    from openpyxl import load_workbook as ox_load
    out = tmp_path / "Fake_Tracker.xlsx"
    monkeypatch.setattr(pt, "OUT_FILE", out)
    monkeypatch.setattr(pt, "read_sheet", lambda name: pd.DataFrame())
    summary = pd.DataFrame([{"Bucket": "local", "Value (RM)": 0.0, "Weight": None, "Target": 0.4,
                             "Drift": None, "Rebalance?": ""}])
    perf = pd.DataFrame({"Measure": ["My Moomoo portfolio"], "Return %": [None]})
    pt.save(summary, perf, {"Date": A21, "Moomoo total (RM)": 0.0}, pd.DataFrame(), no_deals(),
            pd.DataFrame(columns=pt.CASHFLOW_COLS), None)
    header = [c.value for c in ox_load(out)["Holdings"][1]]
    assert "Cost (RM)" in header
    assert header.index("Cost (RM)") == header.index("Value (RM)") - 1
