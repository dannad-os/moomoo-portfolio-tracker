"""Read Portfolio_Tracker.xlsx into plain DataFrames for the app. Picks values, never computes them.
No Streamlit here, so tests can use it with fake workbooks."""
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook as _open_workbook

# ---------- settings ----------
WORKBOOK = Path(__file__).with_name("Portfolio_Tracker.xlsx")
PORTFOLIO = "My Moomoo portfolio"
PORTFOLIO_SIMPLE = "My Moomoo portfolio (simple)"
BLENDED = "Blended benchmark (40/20/40)"
TOTAL_COL = "Moomoo total (RM)"
RETURN_COL = "Moomoo return %"
BLEND_COL = f"{BLENDED} %"
DAYS_COL = "Days since anchor"

_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass
class Portfolio:
    as_of: date | None
    anchor: date | None
    allocation: pd.DataFrame
    performance: pd.DataFrame
    holdings: pd.DataFrame
    daily_log: pd.DataFrame
    monthly: pd.DataFrame | None


def _frame(rows):
    """First row is the header; blank cells become NaN."""
    rows = list(rows)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows[1:], columns=list(rows[0]))
    return df.infer_objects()


def read_named_table(ws, name):
    if name not in ws.tables:
        raise KeyError(f"No table named {name!r} on sheet {ws.title!r}")
    return _frame([[c.value for c in row] for row in ws[ws.tables[name].ref]])


def _sheet(wb, name):
    return _frame(wb[name].values)


def _title_date(ws, table):
    """Date inside the title cell just above a named table's header."""
    first = ws.tables[table].ref.split(":")[0]
    header_row = int(re.sub(r"\D", "", first))
    m = _DATE.search(str(ws.cell(header_row - 1, 1).value or "")) if header_row > 1 else None
    return date.fromisoformat(m.group(1)) if m else None


def load_workbook(path=WORKBOOK):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    wb = _open_workbook(path, data_only=True)
    summary = wb["Summary"]
    log = _sheet(wb, "Daily_Log")
    if "Date" in log:
        log["Date"] = pd.to_datetime(log["Date"])
    return Portfolio(
        as_of=_title_date(summary, "Allocation"),
        anchor=_title_date(summary, "Performance"),
        allocation=read_named_table(summary, "Allocation"),
        performance=read_named_table(summary, "Performance"),
        holdings=_sheet(wb, "Holdings"),
        daily_log=log,
        monthly=_sheet(wb, "Monthly") if "Monthly" in wb.sheetnames else None,
    )


def _value(x):
    return None if pd.isna(x) else x


def _measure(p, label):
    hit = p.performance.loc[p.performance["Measure"] == label, "Return %"]
    return _value(hit.iloc[0]) if len(hit) else None


def tile_values(p):
    log = p.daily_log
    total = _value(log[TOTAL_COL].iloc[-1]) if len(log) and TOTAL_COL in log else None
    days = _value(log[DAYS_COL].iloc[-1]) if len(log) and DAYS_COL in log else None
    return {"total": total, "xirr": _measure(p, PORTFOLIO), "simple": _measure(p, PORTFOLIO_SIMPLE),
            "anchor": p.anchor, "as_of": p.as_of, "days": days}


def chart_frame(p):
    log = p.daily_log.reindex(columns=["Date", RETURN_COL, BLEND_COL])
    out = pd.DataFrame({"Date": log["Date"],
                        PORTFOLIO: pd.to_numeric(log[RETURN_COL]),
                        BLENDED: pd.to_numeric(log[BLEND_COL])})
    return out.dropna(subset=[PORTFOLIO, BLENDED], how="all").reset_index(drop=True)
