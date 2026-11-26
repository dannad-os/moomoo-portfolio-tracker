"""
Moomoo portfolio tracker.

Pulls holdings, cash, trades and cash flow from Moomoo (via OpenD) and fills Portfolio_Tracker.xlsx,
with benchmark comparison (KLCI, Asia ex-Japan, World) from Yahoo Finance.
Run:  python portfolio_tracker.py
Needs: Moomoo OpenD running and logged in, API questionnaire done in the Moomoo app.
"""
import itertools
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf
from moomoo import (RET_OK, Currency, OpenSecTradeContext, SecurityFirm,
                    TrdEnv, TrdMarket)
from openpyxl.chart import LineChart, Reference
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font
from openpyxl.worksheet.table import Table, TableStyleInfo

# ---------------- Settings (edit these) ----------------
OPEND_HOST, OPEND_PORT = "127.0.0.1", 11111

START_DATE = date(2026, 10, 20)     # day your first deposit landed in Moomoo
SAVINGS_START, SAVINGS_RATE = 5_000, 0.04   # an outside savings pot to compare against: starting RM and yearly rate

TARGETS = {"local": 0.40, "regional": 0.20, "global": 0.40}
REBALANCE_BAND = 0.05               # flag a bucket if it drifts 5 points from target
FUND_LABEL = "Income fund (cash-like)"   # Moomoo in-app fund, held outside the buckets like cash
RECONCILE_TOL = 0.02                     # warn if holdings + cash + fund differ from the account total by more

# Anything on Bursa (MY.*) counts as "local". List your ETFs here.
BUCKETS = {
    "US.VT": "global",
    "US.SPY": "global",
    "US.AAXJ": "regional",
}

# Benchmark per bucket: Yahoo ticker, label, priced in USD?
BENCHMARKS = {
    "local": ("^KLSE", "FBM KLCI", False),
    "regional": ("AAXJ", "Asia ex-Japan (AAXJ)", True),
    "global": ("VT", "World (VT)", True),
}

# Moomoo cash-flow types seen so far (exact strings). Unknown types WARN and are skipped;
# pin each new one here when it first appears in the log.
DEPOSIT_TYPES = {"Bank Transfer Deposits"}        # your own money in (+) / out (-); withdrawal string not seen yet
IGNORED_TYPES = {"Fund Subscription"}             # internal moves, fees: part of performance, not deposits
# Moomoo files monthly cash interest under "Others" (remark "Interest ..."): performance, not deposits.
# Rows of that type whose remark starts with a prefix here are ignored; any other "Others" row still
# warns, so a deposit or withdrawal filed there is noticed.
IGNORED_REMARK_PREFIXES = {"Others": ("Interest",)}

OUT_FILE = Path(__file__).with_name("Portfolio_Tracker.xlsx")
# --------------------------------------------------------

CASHFLOW_COLS = ["cashflow_id", "clearing_date", "settlement_date", "currency", "cashflow_type",
                 "cashflow_direction", "cashflow_amount", "cashflow_remark"]
BLENDED = "Blended benchmark (40/20/40)"
MONTHLY_COLS = ["Month", "End value (RM)", "Deposits (RM)", "Withdrawals (RM)", "Trades", "Month return %", "Note"]
CHART_COLS = ["Date", "Moomoo return %", f"{BLENDED} %"]


def bucket_of(code):
    if code.startswith("MY."):
        return "local"
    return BUCKETS.get(code, "unassigned")


def cost_myr(qty, average_cost, fx):
    """Cost of a holding in MYR: qty x average cost x today's rate. None (blank cell) if the cost is missing."""
    try:
        cost = float(average_cost)
    except (TypeError, ValueError):
        return None
    if cost != cost:                        # NaN
        return None
    return float(qty) * cost * fx


def check(ret, data):
    if ret != RET_OK:
        raise RuntimeError(f"Moomoo API error: {data}")
    return data


def deal_window(today):
    """History query window. Moomoo caps it at 90 days; the Trades sheet keeps older rows."""
    start = min(max(START_DATE, today - timedelta(days=89)), today)
    return start.isoformat(), today.isoformat()


def cashflow_dates(last_log_date, today):
    """Dates to pull cash flow for: from the last logged run (at least yesterday) to today, floored at START_DATE."""
    if today < START_DATE:
        return []
    d = max(START_DATE, min(last_log_date or today, today - timedelta(days=1)))
    return [d + timedelta(days=i) for i in range((today - d).days + 1)]


def fetch_cashflow(ctx, acc_id, dates, counter=None):
    """One get_acc_cash_flow call per date; pause 30 s after every 20 calls (API rate limit).
    Pass the same counter for every account so the limit holds across accounts."""
    counter = counter or itertools.count(1)
    frames = []
    for d in dates:
        df = check(*ctx.get_acc_cash_flow(clearing_date=d.isoformat(), trd_env=TrdEnv.REAL, acc_id=acc_id))
        if len(df):
            frames.append(df)
        if next(counter) % 20 == 0:
            time.sleep(30)
    if not frames:
        return pd.DataFrame(columns=CASHFLOW_COLS)
    df = pd.concat(frames, ignore_index=True)
    df["cashflow_id"] = df["cashflow_id"].astype(str)
    return df[CASHFLOW_COLS]


def fetch(cash_dates=()):
    """Return (holdings, account_totals, deals, cashflow) from all real Moomoo accounts, values in MYR."""
    ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.NONE, host=OPEND_HOST,
                              port=OPEND_PORT, security_firm=SecurityFirm.FUTUMY)
    try:
        accs = check(*ctx.get_acc_list())
        accs = accs[accs["trd_env"] == TrdEnv.REAL]
        holdings, deals, flows = [], [], []
        calls = itertools.count(1)          # cash-flow API calls, shared by all accounts
        total = cash = fund = 0.0
        for acc_id in accs["acc_id"]:
            info = check(*ctx.accinfo_query(trd_env=TrdEnv.REAL, acc_id=acc_id, currency=Currency.MYR)).iloc[0]
            total += float(info["total_assets"])
            cash += float(info["cash"])
            fund += float(info.get("fund_assets", 0.0)) + float(info.get("bond_assets", 0.0))

            # MYR per 1 unit of another currency, worked out from the account's own totals
            rates = {"MYR": 1.0}
            def to_myr(cur):
                if cur not in rates:
                    other = check(*ctx.accinfo_query(trd_env=TrdEnv.REAL, acc_id=acc_id, currency=cur)).iloc[0]
                    rates[cur] = float(info["total_assets"]) / float(other["total_assets"])
                return rates[cur]

            pos = check(*ctx.position_list_query(trd_env=TrdEnv.REAL, acc_id=acc_id, currency=Currency.MYR))
            for _, p in pos.iterrows():
                if float(p["qty"]) == 0:
                    continue
                cur = str(p["currency"]) or "MYR"
                fx = to_myr(cur)
                holdings.append({
                    "Code": p["code"], "Name": p["stock_name"], "Bucket": bucket_of(p["code"]),
                    "Qty": float(p["qty"]), "Currency": cur,
                    "Avg cost": float(p["average_cost"]), "Price": float(p["nominal_price"]),
                    "Cost (RM)": cost_myr(p["qty"], p["average_cost"], fx),
                    "Value (RM)": float(p["market_val"]) * fx,
                    "Unrealised P/L (RM)": float(p["unrealized_pl"]) * fx,
                    "P/L %": float(p["pl_ratio_avg_cost"]) / 100,
                })

            start, end = deal_window(date.today())
            past = check(*ctx.history_deal_list_query(trd_env=TrdEnv.REAL, acc_id=acc_id, start=start, end=end))
            today = check(*ctx.deal_list_query(trd_env=TrdEnv.REAL, acc_id=acc_id))
            for _, r in pd.concat([past, today], ignore_index=True).iterrows():
                deals.append({
                    "Deal ID": str(r["deal_id"]), "Time": r["create_time"], "Code": r["code"],
                    "Name": r["stock_name"], "Bucket": bucket_of(r["code"]), "Side": r["trd_side"],
                    "Qty": float(r["qty"]), "Price": float(r["price"]),
                })
            flows.append(fetch_cashflow(ctx, acc_id, cash_dates, calls))
        cashflow = pd.concat(flows, ignore_index=True) if flows else pd.DataFrame(columns=CASHFLOW_COLS)
        return pd.DataFrame(holdings), {"total": total, "cash": cash, "fund": fund}, pd.DataFrame(deals), cashflow
    finally:
        ctx.close()


def benchmark_returns(today):
    """Return {label: return since START_DATE in RM terms}, plus a blended benchmark at target weights."""
    start = min(START_DATE, today)
    tickers = [t for t, _, _ in BENCHMARKS.values()] + ["MYR=X"]
    try:
        px = yf.download(tickers, start=start - timedelta(days=10), end=today + timedelta(days=1),
                         progress=False, auto_adjust=True)["Close"].ffill()
        base = px[px.index.date <= start].iloc[-1]
        last = px.iloc[-1]
    except Exception as e:  # no internet / Yahoo down: blank benchmarks this run, keep the columns
        print(f"WARNING: benchmarks skipped ({e})")
        return {**{label: float("nan") for _, label, _ in BENCHMARKS.values()}, BLENDED: float("nan")}
    fx = last["MYR=X"] / base["MYR=X"]
    out, blended = {}, 0.0
    for bucket, (t, label, in_usd) in BENCHMARKS.items():
        r = last[t] / base[t] * (fx if in_usd else 1) - 1
        out[label] = r
        blended += TARGETS[bucket] * r
    out[BLENDED] = blended
    return out


def known_cashflow(kind, remark):
    """True if the type is pinned, or is an "Others"-style type whose remark starts with an ignored prefix."""
    if kind in DEPOSIT_TYPES | IGNORED_TYPES:
        return True
    text = str(remark).strip().lower()          # a missing remark becomes "nan"/"none": not known
    return any(text.startswith(p.lower()) for p in IGNORED_REMARK_PREFIXES.get(kind, ()))


def external_flows(cashflow, warn=True):
    """[(clearing date, amount)] of your own MYR deposits (+) / withdrawals (-). Warns on unknown rows
    unless warn=False."""
    out = []
    for _, r in cashflow.iterrows():
        kind = str(r["cashflow_type"])
        if warn and not known_cashflow(kind, r["cashflow_remark"]):
            print(f"WARNING: unknown cashflow_type '{kind}' ({r['cashflow_remark']}) "
                  f"— add to DEPOSIT_TYPES or IGNORED_TYPES")
        if kind not in DEPOSIT_TYPES:
            continue
        if r["currency"] != "MYR":
            if warn:
                print(f"WARNING: {r['currency']} cash flow {r['cashflow_id']} ({kind}) skipped — only MYR is counted")
            continue
        out.append((pd.to_datetime(r["clearing_date"]).date(), float(r["cashflow_amount"])))
    return out


def anchor(log, today, total):
    """(date, opening total): first Daily_Log row on/after START_DATE, or today if this is that first run."""
    if today < START_DATE:
        return None
    if len(log):
        days = pd.to_datetime(log["Date"]).dt.date
        later = log.assign(_d=days)[days >= START_DATE].sort_values("_d")
        if len(later) and later["_d"].iloc[0] < today:
            return later["_d"].iloc[0], float(later["Moomoo total (RM)"].iloc[0])
    return today, total


def xirr_flows(log, cashflow, today, total):
    """Investor-sign flows: opening value (-), deposits after the anchor (-), today's value (+). None if no anchor."""
    a = anchor(log, today, total)
    if a is None:
        return None
    flows = [(a[0], -a[1])]
    flows += [(d, -amt) for d, amt in external_flows(cashflow) if d > a[0]]
    return flows + [(today, total)]


def xirr(flows):
    """Annualised money-weighted return, solved by bisection. None if it cannot be solved."""
    if not any(a < 0 for _, a in flows) or not any(a > 0 for _, a in flows):
        return None
    d0 = min(d for d, _ in flows)
    if all(d == d0 for d, _ in flows):
        return 0.0
    npv = lambda r: sum(a / (1 + r) ** ((d - d0).days / 365) for d, a in flows)
    lo, hi = -0.99, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def build_summary(holdings, totals, bench, today, log=None, cashflow=None):
    """Return (allocation table, performance table, Daily_Log row, anchor date or None)."""
    log = pd.DataFrame() if log is None else log
    cashflow = pd.DataFrame(columns=CASHFLOW_COLS) if cashflow is None else cashflow
    by_bucket = holdings.groupby("Bucket")["Value (RM)"].sum() if len(holdings) else pd.Series(dtype=float)
    invested = sum(float(by_bucket.get(b, 0.0)) for b in TARGETS)  # unassigned is left out of weights
    rows = []
    for b, target in TARGETS.items():
        val = float(by_bucket.get(b, 0.0))
        weight = val / invested if invested else 0.0
        drift = weight - target
        action = ""
        if abs(drift) > REBALANCE_BAND:
            action = f"{'SELL' if drift > 0 else 'BUY'} ~RM{abs(drift) * invested:,.0f}"
        rows.append({"Bucket": b, "Value (RM)": val, "Weight": weight, "Target": target,
                     "Drift": drift, "Rebalance?": action})
    fund = totals.get("fund", 0.0)
    if fund > 0:
        rows.append({"Bucket": FUND_LABEL, "Value (RM)": fund, "Rebalance?": "Cash-like, outside the buckets"})
    if by_bucket.get("unassigned", 0):
        rows.append({"Bucket": "unassigned", "Value (RM)": float(by_bucket["unassigned"]),
                     "Rebalance?": "Add these codes to BUCKETS in the script"})

    days = max((today - START_DATE).days, 0)
    pot_growth = (1 + SAVINGS_RATE / 365) ** days
    pot = SAVINGS_START * pot_growth

    since = my_xirr = my_return = all_in = net_dep = None
    a = anchor(log, today, totals["total"])
    if a:
        since, opening = a
        flows = xirr_flows(log, cashflow, today, totals["total"])
        net_dep = -sum(amt for _, amt in flows[1:-1])
        my_xirr = xirr(flows)
        my_return = totals["total"] / (opening + net_dep) - 1 if opening + net_dep else None
        all_in = (totals["total"] + pot) / (opening + net_dep + SAVINGS_START) - 1
    perf = {"My Moomoo portfolio": my_xirr, "My Moomoo portfolio (simple)": my_return,
            **bench, "Savings pot 4%": pot_growth - 1}
    perf = pd.DataFrame({"Measure": list(perf), "Return %": list(perf.values())})

    row = {
        "Date": today, "Moomoo total (RM)": totals["total"], "Cash (RM)": totals["cash"], "Fund (RM)": fund,
        **{f"{b.capitalize()} (RM)": float(by_bucket.get(b, 0.0)) for b in TARGETS},
        "Net deposits (RM)": net_dep,
        "Days since anchor": (today - since).days if since else None,
        "Moomoo return %": my_return,
        "Moomoo XIRR %": my_xirr,
        **{f"{k} %": v for k, v in bench.items()},
        "Savings pot (RM)": pot,
        "All-in total (RM)": totals["total"] + pot,
        "All-in return %": all_in,
    }
    return pd.DataFrame(rows), perf, row, since


def _month_row(month, start, end, end_date, inside, flows, trade_days):
    """One Monthly row; inside(d) says whether a date is in this month's window."""
    dep = float(sum(a for d, a in flows if inside(d) and a > 0))
    wd = float(-sum(a for d, a in flows if inside(d) and a < 0))
    base = start + dep - wd
    ret = (end - start - (dep - wd)) / base if base else None
    return {"Month": month, "End value (RM)": end, "Deposits (RM)": dep, "Withdrawals (RM)": wd,
            "Trades": sum(1 for d in trade_days if inside(d)), "Month return %": ret, "Note": ""}


def monthly_table(log, flows, deals, since):
    """One row per month from the anchor on. A month's window is (previous end-row date, its last logged date];
    return = (E - S - F) / (S + F), flows at start. Empty frame with MONTHLY_COLS if nothing to show."""
    empty = pd.DataFrame(columns=MONTHLY_COLS)
    if since is None or not len(log):
        return empty
    days = pd.to_datetime(log["Date"]).dt.date
    rows = log.assign(_d=days)[days >= since].sort_values("_d")
    if not len(rows):
        return empty
    rows = rows.assign(_m=rows["_d"].map(lambda d: d.strftime("%Y-%m")))
    times = pd.to_datetime(deals["Time"], format="mixed", errors="coerce").dropna() if len(deals) else []
    trade_days = [t.date() for t in times]  # a blank Time is dropped, never aborts save
    prev, start = rows["_d"].iloc[0], float(rows["Moomoo total (RM)"].iloc[0])
    out = []
    for _, r in rows.drop_duplicates("_m", keep="last").iterrows():
        end_d, end = r["_d"], float(r["Moomoo total (RM)"])
        out.append(_month_row(r["_m"], start, end, end_d, lambda d, lo=prev, hi=end_d: lo < d <= hi,
                              flows, trade_days))
        prev, start = end_d, end
    out[0]["Note"] = f"from {since}"
    out[-1]["Note"] = ", ".join(filter(None, [out[-1]["Note"], f"to {prev}"]))
    return pd.DataFrame(out, columns=MONTHLY_COLS)


def read_sheet(name):
    if OUT_FILE.exists():
        try:
            return pd.read_excel(OUT_FILE, sheet_name=name)
        except ValueError:  # sheet not there yet
            pass
    return pd.DataFrame()


def merge_cashflow(old, new):
    """Old + new Cashflow rows, one per cashflow_id."""
    frames = [f for f in (old, new) if f is not None and len(f)]
    if not frames:
        return pd.DataFrame(columns=CASHFLOW_COLS)
    cf = pd.concat(frames, ignore_index=True)
    cf = cf.astype({"cashflow_id": str, "clearing_date": str})
    return cf.drop_duplicates("cashflow_id", keep="last").sort_values("clearing_date")[CASHFLOW_COLS]


# ---------------- Styling ----------------
PCT_COLS = {"Weight", "Target", "Drift"}
SIGNED_HINTS = ("%", "P/L", "Drift")   # columns coloured green/red by sign
GREEN, RED = Font(color="1E7B34"), Font(color="C0392B")


def number_format(col):
    if col in PCT_COLS or col.endswith("%"):
        return "0.00%"
    if "(RM)" in col or col in ("Avg cost", "Price"):
        return "#,##0.00"
    if col == "Qty":
        return "#,##0"
    if col == "Date":
        return "yyyy-mm-dd"
    return None


def shown_len(v, fmt):
    """Rough width of a value as Excel will display it."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0
    if isinstance(v, (datetime, date)):
        return len(str(v)[:19])
    if not isinstance(v, (int, float)):
        return len(str(v))
    if fmt == "0.00%":
        return len(f"{v:.2%}")
    if fmt == "#,##0.00":
        return len(f"{v:,.2f}")
    if fmt == "#,##0":
        return len(f"{v:,.0f}")
    return len(str(v)[:19])


def write_table(xw, sheet, df, name, startrow=0, title=None):
    """Write df as a styled Excel table: banded rows, filters, number formats, fitted columns."""
    if title:
        pd.DataFrame().to_excel(xw, sheet_name=sheet, startrow=startrow)  # ensure sheet exists
        ws = xw.sheets[sheet]
        ws.cell(startrow + 1, 1, title).font = Font(bold=True, size=13, color="1F3864")
        startrow += 1
    df.to_excel(xw, sheet_name=sheet, index=False, startrow=startrow)
    ws = xw.sheets[sheet]
    top, bottom = startrow + 1, startrow + 1 + len(df)

    for i, col in enumerate(df.columns, start=1):
        fmt = number_format(col)
        letter = ws.cell(top, i).column_letter
        cells = [ws.cell(r, i) for r in range(top + 1, bottom + 1)]
        for c in cells:
            if fmt:
                c.number_format = fmt
            c.alignment = Alignment(vertical="center")
        ws.cell(top, i).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        width = max([len(str(col))] + [shown_len(c.value, fmt) for c in cells]) + 3
        ws.column_dimensions[letter].width = max(ws.column_dimensions[letter].width or 0, min(width, 50))
        if any(h in col for h in SIGNED_HINTS) and cells:
            rng = f"{letter}{top + 1}:{letter}{bottom}"
            ws.conditional_formatting.add(rng, CellIsRule(operator="lessThan", formula=["0"], font=RED))
            ws.conditional_formatting.add(rng, CellIsRule(operator="greaterThan", formula=["0"], font=GREEN))
    ws.row_dimensions[top].height = 30

    if len(df):
        ref = f"A{top}:{ws.cell(bottom, len(df.columns)).coordinate}"
        table = Table(displayName=name, ref=ref)
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        ws.add_table(table)
    else:
        for i in range(1, len(df.columns) + 1):
            ws.cell(top, i).font = Font(bold=True)
    return bottom


def write_chart(xw, log, since):
    """Chart sheet: a copied ChartData block (Date, return, blend) and a line chart if any return exists."""
    block = log.reindex(columns=CHART_COLS)
    if since is not None:
        block = block[pd.to_datetime(block["Date"]).dt.date >= since]
    write_table(xw, "Chart", block, "ChartData")
    if not block["Moomoo return %"].notna().any():
        return
    ws, n = xw.sheets["Chart"], len(block) + 1
    chart = LineChart()
    chart.title = "Return since anchor vs blended benchmark"
    chart.y_axis.number_format = "0%"
    chart.display_blanks = "gap"
    chart.x_axis.delete = chart.y_axis.delete = False  # openpyxl hides both axes by default
    chart.add_data(Reference(ws, min_col=2, max_col=3, min_row=1, max_row=n), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=n))
    chart.width, chart.height = 24, 12
    ws.add_chart(chart, "E2")


def save(summary, perf, log_row, holdings, deals, cashflow, since):
    log = read_sheet("Daily_Log")
    log = pd.concat([log, pd.DataFrame([log_row])], ignore_index=True)
    log["Date"] = pd.to_datetime(log["Date"]).dt.date
    log = log.drop_duplicates("Date", keep="last").sort_values("Date").dropna(axis=1, how="all")
    log = log[[c for c in log_row if c in log] + [c for c in log if c not in log_row]]

    old_deals = read_sheet("Trades")
    if len(old_deals):
        old_deals["Deal ID"] = old_deals["Deal ID"].astype(str)
    deals = pd.concat([old_deals, deals], ignore_index=True)
    if len(deals):
        deals = deals.drop_duplicates("Deal ID", keep="last").sort_values("Time")
    else:
        deals = pd.DataFrame(columns=["Deal ID", "Time", "Code", "Name", "Bucket", "Side", "Qty", "Price"])
    if not len(holdings):
        holdings = pd.DataFrame(columns=["Code", "Name", "Bucket", "Qty", "Cost (RM)", "Value (RM)"])

    monthly = monthly_table(log, external_flows(cashflow, warn=False), deals, since)

    with pd.ExcelWriter(OUT_FILE, engine="openpyxl") as xw:
        end = write_table(xw, "Summary", summary, "Allocation", title=f"Allocation  (as of {log_row['Date']})")
        write_table(xw, "Summary", perf, "Performance", startrow=end + 1,
                    title=f"Return since {since or START_DATE}  (in RM)")
        write_table(xw, "Monthly", monthly, "Monthly")
        write_chart(xw, log, since)
        write_table(xw, "Holdings", holdings, "Holdings")
        write_table(xw, "Daily_Log", log, "DailyLog")
        write_table(xw, "Trades", deals, "Trades")
        write_table(xw, "Cashflow", cashflow, "Cashflow")
        for ws in xw.sheets.values():
            ws.freeze_panes = "A2" if ws.title != "Summary" else None
            ws.sheet_view.showGridLines = False


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # non-Latin API text must never crash the run
    today = date.today()
    old_log = read_sheet("Daily_Log")
    last = pd.to_datetime(old_log["Date"]).dt.date.max() if len(old_log) else None
    holdings, totals, deals, new_cf = fetch(cashflow_dates(last, today))
    cashflow = merge_cashflow(read_sheet("Cashflow"), new_cf)
    bench = benchmark_returns(today)
    summary, perf, log_row, since = build_summary(holdings, totals, bench, today, old_log, cashflow)
    held = holdings["Value (RM)"].sum() if len(holdings) else 0.0
    fund = totals.get("fund", 0.0)
    if totals["total"] and abs(held + totals["cash"] + fund - totals["total"]) / totals["total"] > RECONCILE_TOL:
        print(f"WARNING: holdings RM{held:,.0f} + cash RM{totals['cash']:,.0f} + fund RM{fund:,.0f} != total "
              f"RM{totals['total']:,.0f}. Check currency conversion against the app.")
    try:
        save(summary, perf, log_row, holdings, deals, cashflow, since)
    except PermissionError:
        raise SystemExit(f"Close {OUT_FILE.name} in Excel and run again.")
    if log_row["Moomoo XIRR %"] is not None:
        ret = f"XIRR {log_row['Moomoo XIRR %']:+.2%}"
    elif log_row["Moomoo return %"] is not None:
        ret = f"simple {log_row['Moomoo return %']:+.2%}"
    else:
        ret = f"return tracking starts {START_DATE}"
    print(f"{datetime.now():%Y-%m-%d %H:%M}  Moomoo RM{totals['total']:,.2f}  ({ret})  -> {OUT_FILE.name}")


if __name__ == "__main__":
    main()
