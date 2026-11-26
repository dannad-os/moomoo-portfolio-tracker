"""Portfolio page: renders the workbook's own numbers. Formatting only, nothing is recomputed."""
import pandas as pd
import plotly.express as px
import streamlit as st

import portfolio_data as data

NA = "n/a"


def pct(x, blank=NA):
    return blank if pd.isna(x) else f"{x * 100:.2f} %"


def rm(x, blank=NA):
    return blank if pd.isna(x) else f"{x:,.2f}"


def shown(x):
    return NA if x is None else str(x)


PL = "Unrealised P/L (RM)"


def pl_arrow(x, blank=NA):
    """P/L text with a green up or red down arrow. The sign of x picks the arrow; the number is rm(x) as is."""
    if pd.isna(x):
        return blank
    if x > 0:
        return "▲ " + rm(x)
    if x < 0:
        return "▼ " + rm(x)
    return rm(x)


def cell_text(v):
    """Holdings cell outside P/L under the Styler: blank for missing, floats to at most 4 decimals."""
    if pd.isna(v):
        return ""
    if isinstance(v, float):
        s = f"{v:.4f}".rstrip("0").rstrip(".")
        return "0" if s == "-0" else s
    return str(v)


def pl_colour(text):
    if text.startswith("▲"):
        return "color: #2e7d32"
    if text.startswith("▼"):
        return "color: #c62828"
    return ""


try:
    p = data.load_workbook()
except FileNotFoundError:
    st.error(f"{data.WORKBOOK} not found: run the tracker first.")
    st.stop()
except PermissionError:
    st.error("Close Portfolio_Tracker.xlsx in Excel and reload.")
    st.stop()

t = data.tile_values(p)

st.title("Portfolio")
st.caption(f"Numbers from Portfolio_Tracker.xlsx, as of {shown(p.as_of)}. Nothing is recomputed here.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total value (RM)", NA if t["total"] is None else rm(t["total"]))
c1.caption(f"as of {shown(t['as_of'])}")
c2.metric("XIRR", NA if t["xirr"] is None else pct(t["xirr"]))
c3.metric("Simple return", NA if t["simple"] is None else pct(t["simple"]))
if t["days"] is None:
    c4.metric("Measured since", shown(t["anchor"]))
else:
    c4.metric("Days since anchor", f"Day {t['days']:.0f}")
    c4.caption(f"since {shown(t['anchor'])}")

left, right = st.columns([2, 3], gap="large")

with left:
    st.subheader("Allocation vs target")
    alloc = p.allocation.copy()
    for col in ("Weight", "Target", "Drift"):
        alloc[col] = alloc[col].map(lambda x: pct(x, blank=""))
    alloc["Value (RM)"] = alloc["Value (RM)"].map(lambda x: rm(x, blank=""))
    alloc["Rebalance?"] = alloc["Rebalance?"].map(lambda x: "" if pd.isna(x) else str(x))
    st.dataframe(alloc, hide_index=True)

with right:
    st.subheader("Return since anchor vs blended benchmark")
    cf = data.chart_frame(p)
    if len(cf):
        fig = px.line(cf, x="Date", y=[data.PORTFOLIO, data.BLENDED])
        fig.update_layout(yaxis_tickformat=".1%", yaxis_title=None, xaxis_title=None, legend_title=None,
                          height=300, margin=dict(l=0, r=0, t=10, b=0),
                          legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
        st.plotly_chart(fig)
    else:
        st.write("No return rows in Daily_Log yet.")
    if p.anchor:
        st.caption(f"The two lines start on different dates: the portfolio from the anchor ({p.anchor}), "
                   "the blend from the tracker's START_DATE.")

tab_hold, tab_ret, tab_month = st.tabs(["Holdings", "Returns", "Monthly"])

with tab_hold:
    hold = p.holdings.copy()
    for col in hold.columns:
        if col == PL:
            hold[col] = hold[col].map(pl_arrow)
        elif col.endswith("%"):
            hold[col] = hold[col].map(pct)
        elif "(RM)" in col:
            hold[col] = hold[col].map(rm)
    if PL in hold:
        others = [c for c in hold.columns if c != PL]
        st.dataframe(hold.style.map(pl_colour, subset=[PL]).format(cell_text, subset=others), hide_index=True)
    else:
        st.dataframe(hold, hide_index=True)

with tab_ret:
    perf = p.performance.copy()
    perf["Return %"] = perf["Return %"].map(pct)
    st.dataframe(perf, hide_index=True)

with tab_month:
    if p.monthly is None:
        st.write("Monthly table arrives with WP-2.1")
    else:
        month = p.monthly.copy()
        for col in month.columns:
            if "(RM)" in col:
                month[col] = month[col].map(rm)
        if "Month return %" in month:
            month["Month return %"] = month["Month return %"].map(pct)
        if "Note" in month:
            month["Note"] = month["Note"].map(lambda x: "" if pd.isna(x) else str(x))
        st.dataframe(month, hide_index=True)
