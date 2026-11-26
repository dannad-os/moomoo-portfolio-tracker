"""WP-2.2 Portfolio page tests (spec v2, "Checks wanted"). pages/portfolio.py is run with Streamlit's AppTest and
portfolio_data.load_workbook monkeypatched to a made-up Portfolio; no workbook, no OpenD, no internet.
app.py is run against a fake `streamlit` module that records st.navigation / st.set_page_config / run.
pl_arrow and pl_colour are pulled out of the page source with ast (the page runs Streamlit on import) and
executed with the page's own NA, rm and pct. Made-up numbers only.

The Holdings display tests read what the user sees: the Styler's display values
(proto.arrow_data.styler.display_values, an Arrow IPC stream), not node.value (the raw data)."""
import ast
import json
import re
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import portfolio_data as pdata  # noqa: E402

PAGE = ROOT / "pages" / "portfolio.py"
APP = ROOT / "app.py"
PL = "Unrealised P/L (RM)"
GREEN, RED = "color: #2e7d32", "color: #c62828"
TABS = ["Holdings", "Returns", "Monthly"]
ALLOC_HEAD = "Allocation vs target"
CHART_HEAD = "Return since anchor vs blended benchmark"
NO_ROWS = "No return rows in Daily_Log yet."
MONTHLY_FALLBACK = "Monthly table arrives with WP-2.1"

# ---------- made-up Portfolio ----------
AS_OF, ANCHOR = date(2026, 11, 14), date(2026, 8, 10)
HOLD_COLS = ["Code", "Name", "Bucket", "Currency", "Qty", "Avg cost", "Price", "Cost (RM)", "Value (RM)",
             PL, "Weight %"]


def fake_allocation():
    return pd.DataFrame({
        "Bucket": ["local", "regional", "global", "Income fund"],
        "Value (RM)": [3740.4, 2190.9, 4047.8, 500.0],
        "Weight": [0.3748, 0.2195, 0.4056, np.nan],
        "Target": [0.40, 0.20, 0.40, np.nan],
        "Drift": [-0.0252, 0.0195, 0.0056, np.nan],
        "Rebalance?": [np.nan, np.nan, "Trim", "Cash-like"],
    })


def fake_performance():
    return pd.DataFrame({"Measure": [pdata.PORTFOLIO, pdata.PORTFOLIO_SIMPLE, "KLCI", pdata.BLENDED],
                         "Return %": [0.0912, 0.0431, -0.0210, 0.0439]})


def fake_holdings(with_pl=True):
    df = pd.DataFrame({
        "Code": ["MY.AAAA", "US.BBBB", "US.CCCC", "US.DDDD"],
        "Name": ["Fake Local ETF", "Fake Asia ETF", "Fake World ETF", "Fake Small Cap ETF"],
        "Bucket": ["local", "regional", "global", "global"],
        "Currency": ["MYR", "USD", "USD", "USD"],
        "Qty": [1200, 6, 5, 4],
        "Avg cost": [1.75, 335.25, 530.0, 295.5],
        "Price": [1.885, 365.15, 583.0, 283.2],
        "Cost (RM)": [2100.0, 2010.0, 2650.0, 1180.0],
        "Value (RM)": [3334.5, 1953.6, 2650.0, 1123.6],
        PL: [1234.5, -56.4, 0.0, np.nan],
        "Weight %": [0.21, 0.20, 0.27, np.nan],
    })
    return df if with_pl else df.drop(columns=[PL])


def fake_log(returns=True):
    days = pd.to_datetime(["2026-11-12", "2026-11-13", "2026-11-14"])
    return pd.DataFrame({
        "Date": days,
        pdata.TOTAL_COL: [10300.0, 10400.0, 10479.1],
        pdata.RETURN_COL: [0.081, 0.088, 0.0912] if returns else [np.nan] * 3,
        pdata.BLEND_COL: [0.040, 0.042, 0.0439] if returns else [np.nan] * 3,
        pdata.DAYS_COL: [94, 95, 96],
    })


def fake_monthly():
    return pd.DataFrame({"Month": ["2026-10", "2026-11"], "End value (RM)": [10120.0, 10479.1],
                         "Deposits (RM)": [2000.0, 0.0], "Trades": [3, 0],
                         "Month return %": [-0.0222, 0.0355], "Note": [np.nan, "Month in progress"]})


def fake_portfolio(holdings=None, log=None, monthly="default", anchor=ANCHOR):
    return pdata.Portfolio(as_of=AS_OF, anchor=anchor, allocation=fake_allocation(),
                           performance=fake_performance(),
                           holdings=fake_holdings() if holdings is None else holdings,
                           daily_log=fake_log() if log is None else log,
                           monthly=fake_monthly() if isinstance(monthly, str) else monthly)


def run_page(monkeypatch, p=None, raises=None):
    from streamlit.testing.v1 import AppTest

    def fake_load(*a, **k):
        if raises:
            raise raises
        return fake_portfolio() if p is None else p

    monkeypatch.setattr(pdata, "load_workbook", fake_load)
    at = AppTest.from_file(str(PAGE), default_timeout=30)
    at.run()
    return at


@pytest.fixture(autouse=True, scope="module")
def no_streamlit_left_behind():
    """test_portfolio_data.py's test_t8_no_streamlit asserts streamlit is not in sys.modules. Streamlit imported
    here (by AppTest) is dropped again after this module, so that check passes in any test order."""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        if name.split(".")[0] == "streamlit":
            del sys.modules[name]


@pytest.fixture
def page(monkeypatch):
    at = run_page(monkeypatch)
    assert not at.exception, [e.value for e in at.exception]
    return at


# ---------- reading the AppTest tree ----------
def kids(node):
    return [c for _, c in sorted((getattr(node, "children", None) or {}).items())]


def ntype(node):
    return getattr(node, "type", None)


def walk(node):
    """Every node below `node` in page order (blocks and elements)."""
    for c in kids(node):
        yield c
        if ntype(c) not in ("dataframe", "table"):
            yield from walk(c)


def find(node, kind):
    return [n for n in walk(node) if ntype(n) == kind]


def frames(node):
    return [n.value for n in find(node, "dataframe")]


def frame_with(node, column):
    hits = [n for n in find(node, "dataframe") if column in list(n.value.columns)]
    return hits


def subheads(node):
    return [str(n.value) for n in find(node, "subheader")]


def plain_texts(node):
    return [str(n.value) for n in walk(node)
            if ntype(n) in ("markdown", "caption", "text", "subheader", "title", "info", "warning", "error")]


def column_rows(at):
    """Each st.columns row on the main page, top level only: (row node, [column nodes])."""
    rows = []
    for c in kids(at.main):
        cols = [k for k in kids(c) if ntype(k) == "column"]
        if cols:
            rows.append((c, cols))
    return rows


def two_col_row(at):
    rows = [cols for _, cols in column_rows(at) if len(cols) == 2]
    assert rows, f"no two-column row on the page; rows have {[len(c) for _, c in column_rows(at)]} columns"
    return rows[0]


def tab_map(at):
    return {t.label: t for t in at.tabs}


def tab(at, label):
    m = tab_map(at)
    assert label in m, f"no tab {label!r}; tabs are {list(m)}"
    return m[label]


def styles(df_node):
    """{(row, col): css} from the Styler the page sent, or {} if the table has no Styler."""
    arrow = df_node.proto.arrow_data
    if not arrow.HasField("styler"):
        return {}
    out = {}
    for r, c, css in re.findall(r"_row(\d+)_col(\d+)\s*\{\s*([^}]*?)\s*\}", arrow.styler.styles):
        out[(int(r), int(c))] = css.strip().rstrip(";").strip()
    return out


def holdings_node(at):
    hits = frame_with(at.main, "Code")
    assert len(hits) == 1, f"expected one Holdings table, found {len(hits)}"
    return hits[0]


# ---------- pl_arrow / pl_colour, pulled from the page source ----------
def page_src():
    return PAGE.read_text(encoding="utf-8")


def page_functions(*names):
    """Run the page's NA assignment, its imports of pandas/numpy, and the named defs (plus rm, pct) in a fresh
    namespace. A missing def fails the test with a plain message."""
    tree = ast.parse(page_src())
    want = set(names) | {"rm", "pct"}
    body, found = [], set()
    for node in tree.body:
        if isinstance(node, ast.Import) and all(a.name in ("pandas", "numpy", "math") for a in node.names):
            body.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "NA" for t in node.targets):
            body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in want:
            body.append(node)
            found.add(node.name)
    missing = set(names) - found
    assert not missing, f"pages/portfolio.py defines no {sorted(missing)} at top level"
    ns = {}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(PAGE), "exec"), ns)
    return ns


def page_function_node(name):
    for node in ast.parse(page_src()).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"pages/portfolio.py defines no {name} at top level")


@pytest.mark.parametrize("x, want", [(1234.5, "▲ 1,234.50"), (0.01, "▲ 0.01"), (-56.4, "▼ -56.40"),
                                     (-1234567.891, "▼ -1,234,567.89"), (0.0, "0.00"), (0, "0.00")],
                         ids=["gain", "small_gain", "loss_minus_kept", "big_loss", "zero_float", "zero_int"])
def test_pl_arrow_exact_strings(x, want):
    assert page_functions("pl_arrow")["pl_arrow"](x) == want


@pytest.mark.parametrize("x", [float("nan"), np.nan, None, pd.NA], ids=["nan", "np_nan", "none", "pd_na"])
def test_pl_arrow_blank_is_na(x):
    ns = page_functions("pl_arrow")
    assert ns["pl_arrow"](x) == "n/a" == ns["NA"]


def test_pl_arrow_blank_argument_used():
    assert page_functions("pl_arrow")["pl_arrow"](np.nan, blank="") == ""


@pytest.mark.parametrize("text, want", [("▲ 1,234.50", GREEN), ("▼ -56.40", RED), ("0.00", ""), ("n/a", ""),
                                        ("", ""), ("-56.40", ""), ("x ▲", "")],
                         ids=["up_green", "down_red", "zero_none", "na_none", "empty_none", "bare_minus_none",
                              "arrow_not_first_none"])
def test_pl_colour_three_cases(text, want):
    assert page_functions("pl_colour")["pl_colour"](text) == want


def test_pl_arrow_does_no_arithmetic_on_x():
    """Spec: no abs(), no negation, no rounding; comparing x with 0 is allowed."""
    fn = page_function_node("pl_arrow")
    arg = fn.args.args[0].arg
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            assert n.func.id not in ("abs", "round", "int", "float"), f"{n.func.id}() in pl_arrow"
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            assert n.func.attr not in ("abs", "round", "__neg__", "__abs__"), f".{n.func.attr}() in pl_arrow"
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            assert isinstance(n.operand, ast.Constant), "negation in pl_arrow"
        if isinstance(n, ast.BinOp):
            for side in (n.left, n.right):
                assert not (isinstance(side, ast.Name) and side.id == arg), f"arithmetic on {arg} in pl_arrow"


# ---------- page: unchanged blocks (pins) ----------
def test_pin_load_errors_unchanged(monkeypatch):
    at = run_page(monkeypatch, raises=FileNotFoundError("gone"))
    assert [str(e.value) for e in at.error] == [f"{pdata.WORKBOOK} not found: run the tracker first."]
    assert not at.title, "page went on after the not-found error"
    at = run_page(monkeypatch, raises=PermissionError("locked"))
    assert [str(e.value) for e in at.error] == ["Close Portfolio_Tracker.xlsx in Excel and reload."]
    assert not at.title


def test_pin_title_and_caption_first(page):
    top = kids(page.main)
    assert ntype(top[0]) == "title" and str(top[0].value) == "Portfolio"
    assert ntype(top[1]) == "caption" and str(top[1].value) == (
        f"Numbers from Portfolio_Tracker.xlsx, as of {AS_OF}. Nothing is recomputed here.")


def test_pin_four_tiles_labels_values_captions(page):
    rows = [cols for _, cols in column_rows(page) if len(cols) == 4]
    assert len(rows) == 1, "one st.columns(4) row of tiles"
    cols = rows[0]
    got = [[(m.label, m.value) for m in find(c, "metric")] for c in cols]
    assert got == [[("Total value (RM)", "10,479.10")], [("XIRR", "9.12 %")], [("Simple return", "4.31 %")],
                   [("Days since anchor", "Day 96")]]
    assert [str(n.value) for n in find(cols[0], "caption")] == [f"as of {AS_OF}"]
    assert [str(n.value) for n in find(cols[3], "caption")] == [f"since {ANCHOR}"]


def test_pin_measured_since_fallback(monkeypatch):
    log = fake_log().drop(columns=[pdata.DAYS_COL])
    at = run_page(monkeypatch, fake_portfolio(log=log))
    assert not at.exception, [e.value for e in at.exception]
    labels = [(m.label, m.value) for m in at.metric]
    assert ("Measured since", str(ANCHOR)) in labels and "Days since anchor" not in [lb for lb, _ in labels]


def test_pin_allocation_formatted_as_today(page):
    hits = frame_with(page.main, "Bucket")
    alloc = [h.value for h in hits if "Drift" in h.value.columns]
    assert len(alloc) == 1
    a = alloc[0]
    assert list(a.columns) == list(fake_allocation().columns)
    assert list(a["Weight"]) == ["37.48 %", "21.95 %", "40.56 %", ""]
    assert list(a["Target"]) == ["40.00 %", "20.00 %", "40.00 %", ""]
    assert list(a["Drift"]) == ["-2.52 %", "1.95 %", "0.56 %", ""]
    assert list(a["Value (RM)"]) == ["3,740.40", "2,190.90", "4,047.80", "500.00"]
    assert list(a["Rebalance?"]) == ["", "", "Trim", "Cash-like"]


def test_pin_returns_formatted_as_today(page):
    perf = [f for f in frames(page.main) if "Measure" in f.columns]
    assert len(perf) == 1
    assert list(perf[0]["Return %"]) == ["9.12 %", "4.31 %", "-2.10 %", "4.39 %"]


def test_pin_holdings_keeps_every_column(page):
    assert list(holdings_node(page).value.columns) == HOLD_COLS


def test_pin_holdings_other_columns_formatted_as_today(page):
    h = holdings_node(page).value
    assert list(h["Cost (RM)"]) == ["2,100.00", "2,010.00", "2,650.00", "1,180.00"]
    assert list(h["Value (RM)"]) == ["3,334.50", "1,953.60", "2,650.00", "1,123.60"]
    assert list(h["Weight %"]) == ["21.00 %", "20.00 %", "27.00 %", "n/a"]
    assert list(h["Currency"]) == ["MYR", "USD", "USD", "USD"]
    assert [float(v) for v in h["Qty"]] == [1200, 6, 5, 4]  # left raw
    assert [float(v) for v in h["Avg cost"]] == [1.75, 335.25, 530.0, 295.5]
    assert [float(v) for v in h["Price"]] == [1.885, 365.15, 583.0, 283.2]


def test_pin_monthly_formatted_as_today(page):
    m = [f for f in frames(page.main) if "Month" in f.columns]
    assert len(m) == 1
    assert list(m[0]["End value (RM)"]) == ["10,120.00", "10,479.10"]
    assert list(m[0]["Month return %"]) == ["-2.22 %", "3.55 %"]
    assert list(m[0]["Note"]) == ["", "Month in progress"]


def test_pin_holdings_without_pl_column_renders(monkeypatch):
    at = run_page(monkeypatch, fake_portfolio(holdings=fake_holdings(with_pl=False)))
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error
    node = holdings_node(at)
    assert list(node.value.columns) == [c for c in HOLD_COLS if c != PL]
    cells = node.value.astype(str).to_numpy().ravel()
    assert not [c for c in cells if c.startswith(("▲", "▼"))], "an arrow without a P/L column"
    assert not [v for v in styles(node).values() if v], "a colour without a P/L column"


def test_pin_returns_and_monthly_carry_no_arrow(page):
    for f in frames(page.main):
        if "Code" in f.columns:
            continue
        cells = f.astype(str).to_numpy().ravel()
        assert not [c for c in cells if "▲" in c or "▼" in c], list(f.columns)


def test_pin_chart_keeps_y_format_and_no_titles(page):
    lay = chart_layout(page)
    assert lay.get("yaxis", {}).get("tickformat") == ".1%"
    assert not (lay.get("yaxis", {}).get("title") or {}).get("text")
    assert not ((lay.get("legend") or {}).get("title") or {}).get("text")


# ---------- page: new order ----------
def test_page_order_title_tiles_row_tabs(page):
    """Top level: title, caption, the four tiles, the [2, 3] row, then the tabs (nothing between)."""
    shape = []
    for c in kids(page.main):
        cols = [k for k in kids(c) if ntype(k) == "column"]
        tabs = [k for k in kids(c) if ntype(k) == "tab"]
        shape.append(f"cols{len(cols)}" if cols else "tabs" if tabs else ntype(c))
    assert shape == ["title", "caption", "cols4", "cols2", "tabs"], shape


def test_row_is_two_columns_2_to_3_gap_large(page):
    left, right = two_col_row(page)
    assert (round(left.weight, 6), round(right.weight, 6)) == (0.4, 0.6), "st.columns([2, 3])"
    assert left.gap == right.gap == "large"


def test_allocation_in_left_column(page):
    left, right = two_col_row(page)
    assert subheads(left) == [ALLOC_HEAD]
    tables = frames(left)
    assert len(tables) == 1 and "Drift" in tables[0].columns
    assert not find(left, "plotly_chart")


def test_chart_in_right_column_with_caption(page):
    left, right = two_col_row(page)
    assert subheads(right) == [CHART_HEAD]
    assert len(find(right, "plotly_chart")) == 1
    assert not frames(right)
    caps = [str(n.value) for n in find(right, "caption")]
    assert caps == [f"The two lines start on different dates: the portfolio from the anchor ({ANCHOR}), "
                    "the blend from the tracker's START_DATE."]


def test_no_anchor_no_dates_caption(monkeypatch):
    at = run_page(monkeypatch, fake_portfolio(anchor=None))
    assert not at.exception, [e.value for e in at.exception]
    left, right = two_col_row(at)
    assert len(find(right, "plotly_chart")) == 1
    assert not [t for t in plain_texts(at.main) if "start on different dates" in t]


def test_empty_chart_text_in_right_column(monkeypatch):
    at = run_page(monkeypatch, fake_portfolio(log=fake_log(returns=False)))
    assert not at.exception, [e.value for e in at.exception]
    left, right = two_col_row(at)
    assert not find(right, "plotly_chart")
    assert NO_ROWS in plain_texts(right), plain_texts(right)


def chart_layout(at):
    charts = find(at.main, "plotly_chart")
    assert len(charts) == 1, f"{len(charts)} charts"
    return json.loads(charts[0].proto.spec)["layout"]


def test_chart_compact(page):
    """Mock-up look: height 300, no x-axis title, legend across the top, tight margins (each side <= 30 px)."""
    lay = chart_layout(page)
    assert lay.get("height") == 300
    assert not (lay.get("xaxis", {}).get("title") or {}).get("text"), "x-axis title still shown"
    legend = lay.get("legend") or {}
    assert legend.get("orientation") == "h", "legend not across"
    assert legend.get("y", 0) >= 1, "legend not on top"
    margin = lay.get("margin") or {}
    assert set("lrtb") <= set(margin), f"margins not set: {margin}"
    assert all(margin[s] <= 30 for s in "lrtb"), margin


def test_tab_labels_exact(page):
    assert [t.label for t in page.tabs] == TABS


def test_no_subheader_inside_tabs(page):
    assert len(page.tabs) == 3
    for t in page.tabs:
        assert not subheads(t), (t.label, subheads(t))


def test_holdings_table_in_holdings_tab(page):
    t = tab(page, "Holdings")
    tables = frames(t)
    assert len(tables) == 1 and list(tables[0].columns) == HOLD_COLS


def test_returns_table_in_returns_tab(page):
    tables = frames(tab(page, "Returns"))
    assert len(tables) == 1 and list(tables[0].columns) == ["Measure", "Return %"]
    assert list(tables[0]["Return %"]) == ["9.12 %", "4.31 %", "-2.10 %", "4.39 %"]


def test_monthly_table_in_monthly_tab(page):
    tables = frames(tab(page, "Monthly"))
    assert len(tables) == 1 and list(tables[0].columns) == list(fake_monthly().columns)


def test_monthly_none_fallback_in_monthly_tab(monkeypatch):
    at = run_page(monkeypatch, fake_portfolio(monthly=None))
    assert not at.exception, [e.value for e in at.exception]
    t = tab(at, "Monthly")
    assert MONTHLY_FALLBACK in plain_texts(t)
    assert not frames(t)


def test_nothing_after_tabs_outside_them(page):
    """Every table outside the [2, 3] row sits in a tab."""
    left, right = two_col_row(page)
    inside = len(frames(left)) + sum(len(frames(t)) for t in page.tabs)
    assert inside == len(frames(page.main)) == 4


# ---------- P/L arrow and colour on the page ----------
def test_holdings_pl_column_shows_arrows(page):
    h = frames(tab(page, "Holdings"))[0]
    assert list(h[PL]) == ["▲ 1,234.50", "▼ -56.40", "0.00", "n/a"]


def test_holdings_pl_column_coloured_only(page):
    node = find(tab(page, "Holdings"), "dataframe")[0]
    st_ = {k: v for k, v in styles(node).items() if v}
    pl_col = HOLD_COLS.index(PL)
    assert st_ == {(0, pl_col): GREEN, (1, pl_col): RED}, st_


# ---------- Holdings: what the user sees (ruling 1, review-r1 finding 1) ----------
def display_text(df_node):
    """The Styler's display values: the text each Holdings cell shows on screen."""
    import pyarrow as pa
    from pyarrow import ipc
    arrow = df_node.proto.arrow_data
    assert arrow.HasField("styler"), "Holdings table sent without a Styler"
    dv = arrow.styler.display_values
    assert dv, "Styler carries no display values"
    return ipc.open_stream(pa.BufferReader(dv)).read_pandas()


def display_holdings():
    """Made-up Holdings: Qty an int column; Avg cost and Price floats; Price is an object column holding a
    float NaN and a None. (RM) and % columns are pre-formatted by the page as today."""
    df = fake_holdings()
    df["Avg cost"] = [1.75, 335.25, 1200.0, 0.5]
    df["Price"] = pd.Series([1.885, np.nan, None, 283.2], dtype=object)
    return df


@pytest.fixture
def seen(monkeypatch):
    at = run_page(monkeypatch, fake_portfolio(holdings=display_holdings()))
    assert not at.exception, [e.value for e in at.exception]
    node = holdings_node(at)
    return node, display_text(node)


def test_holdings_display_floats_trailing_zeros_dropped(seen):
    _, d = seen
    assert list(d["Avg cost"]) == ["1.75", "335.25", "1200", "0.5"]
    assert list(d["Price"])[0] == "1.885"
    assert list(d["Price"])[3] == "283.2"


FLOAT_SHOWN = [(335.2533333333, "335.2533"), (1.7533333333, "1.7533"), (1.75, "1.75"), (1200.0, "1200"),
               (98765.4321, "98765.4321"), (12345678901.0, "12345678901"), (-0.0, "0"), (0.00001234, "0"),
               (1.23456, "1.2346"), (0.99996, "1"),
               (-0.5, "-0.5"), (-0.0500, "-0.05"), (-12.3456, "-12.3456"), (-0.00001, "0")]


@pytest.mark.parametrize("v, want", FLOAT_SHOWN,
                         ids=["long_tail_335", "long_tail_1_75", "two_dp", "whole", "four_dp", "eleven_digits",
                              "minus_zero", "below_1e-4", "round_up_4th", "round_up_carry",
                              "neg_half", "neg_small", "neg_four_dp", "neg_rounds_to_zero"])
def test_holdings_display_float_at_most_four_decimals(monkeypatch, v, want):
    """Ruling on review-r2 (2026-11-15): a float outside P/L shows as plain st.dataframe did: at most 4
    decimals, trailing zeros dropped, no thousands separator, "-0" shown as "0"."""
    df = fake_holdings()
    df["Avg cost"] = [v, 335.25, 530.0, 295.5]
    at = run_page(monkeypatch, fake_portfolio(holdings=df))
    assert not at.exception, [e.value for e in at.exception]
    d = display_text(holdings_node(at))
    assert list(d["Avg cost"])[0] == want


def test_holdings_display_floats_keep_up_to_four_decimals(monkeypatch):
    """Mutation r2: values with many significant digits but no more than 4 decimals show in full, not cut to
    fewer significant digits."""
    df = fake_holdings()
    df["Avg cost"] = [12345.678, 1234567.5, 98765.4321, 1.75]
    at = run_page(monkeypatch, fake_portfolio(holdings=df))
    assert not at.exception, [e.value for e in at.exception]
    d = display_text(holdings_node(at))
    assert list(d["Avg cost"]) == ["12345.678", "1234567.5", "98765.4321", "1.75"]


def test_holdings_display_int_as_str(seen):
    _, d = seen
    assert list(d["Qty"]) == ["1200", "6", "5", "4"]


def test_holdings_display_missing_is_empty(seen):
    _, d = seen
    assert list(d["Price"])[1:3] == ["", ""], list(d["Price"])
    for col in d.columns:
        if col == PL:
            continue
        bad = [v for v in d[col] if str(v).strip().lower() in ("nan", "none", "<na>", "nat")]
        assert not bad, (col, bad)


def test_holdings_display_preformatted_text_unchanged(seen):
    _, d = seen
    assert list(d["Cost (RM)"]) == ["2,100.00", "2,010.00", "2,650.00", "1,180.00"]
    assert list(d["Value (RM)"]) == ["3,334.50", "1,953.60", "2,650.00", "1,123.60"]
    assert list(d["Weight %"]) == ["21.00 %", "20.00 %", "27.00 %", "n/a"]
    assert list(d["Code"]) == ["MY.AAAA", "US.BBBB", "US.CCCC", "US.DDDD"]
    assert list(d["Currency"]) == ["MYR", "USD", "USD", "USD"]


def test_holdings_display_pl_keeps_arrows(seen):
    _, d = seen
    assert list(d[PL]) == ["▲ 1,234.50", "▼ -56.40", "0.00", "n/a"]


def test_other_tables_have_no_styler(page):
    for node in find(page.main, "dataframe"):
        if "Code" in list(node.value.columns):
            continue
        assert not node.proto.arrow_data.HasField("styler"), list(node.value.columns)


# ---------- source checks ----------
ARITH = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow, ast.Mod)


def is_text(n):
    return isinstance(n, ast.JoinedStr) or (isinstance(n, ast.Constant) and isinstance(n.value, str))


def test_pin_page_computes_no_number():
    """No abs/round/sum/mean, no arithmetic. The one allowed numeric operation is pct's existing x * 100;
    string joins ("▲ " + ...) are formatting."""
    src = page_src()
    for bad in (r"(?<![\w.])abs\(", r"(?<![\w.])round\(", r"\.sum\(", r"\.mean\(", r"\.diff\(", r"\.pct_change\(",
                r"\.cumsum\(", r"\.max\(", r"\.min\(", r"\.abs\(", r"\.round\("):
        assert not re.search(bad, src), bad  # lookbehind: "st.tabs(" is not abs(
    tree = ast.parse(src)
    pct_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "pct")
    allowed = {id(n) for n in ast.walk(pct_node) if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mult)}
    for n in ast.walk(tree):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ARITH) and id(n) not in allowed:
            assert isinstance(n.op, ast.Add) and (is_text(n.left) or is_text(n.right)), (
                f"arithmetic at line {n.lineno}: {ast.unparse(n)}")
        if isinstance(n, ast.AugAssign):
            raise AssertionError(f"augmented assignment at line {n.lineno}")
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            assert isinstance(n.operand, ast.Constant), f"negation at line {n.lineno}"


def test_pin_page_keeps_monthly_guards():
    src = page_src()
    assert '"Month return %" in' in src and '"Note" in' in src


def test_pin_no_set_page_config_under_pages():
    for f in sorted((ROOT / "pages").glob("*.py")):
        assert "set_page_config" not in f.read_text(encoding="utf-8"), f.name


def test_pin_app_page_lines_byte_for_byte_and_in_order():
    src = APP.read_text(encoding="utf-8")
    lines = ['    st.Page("pages/portfolio.py", title="Portfolio", default=True),',
             '    st.Page("pages/research.py", title="Research"),',
             '    st.Page("pages/library.py", title="Library"),']
    at = [src.find(ln + "\n") for ln in lines]
    assert all(i >= 0 for i in at), at
    assert at == sorted(at)


class FakeSt:
    """Stands in for streamlit while app.py runs: records the calls in order."""

    def __init__(self, picked):
        self.calls, self.picked = [], picked

    def Page(self, path, title=None, **kw):  # noqa: N802 (streamlit's name)
        return SimpleNamespace(path=path, title=title, kw=kw)

    def navigation(self, pages, **kw):
        self.calls.append(("navigation", [p.title for p in pages]))
        chosen = next(p for p in pages if p.title == self.picked)
        calls = self.calls

        class Picked:
            title = chosen.title

            def run(self):
                calls.append(("run", chosen.title))

        return Picked()

    def set_page_config(self, **kw):
        self.calls.append(("set_page_config", kw))


def run_app(monkeypatch, picked):
    fake = FakeSt(picked)
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    exec(compile(APP.read_text(encoding="utf-8"), str(APP), "exec"), {"__name__": "__main__"})
    return fake.calls


@pytest.mark.parametrize("picked, layout", [("Portfolio", "wide"), ("Research", "centered"),
                                            ("Library", "centered")])
def test_app_sets_width_for_every_page(monkeypatch, picked, layout):
    calls = run_app(monkeypatch, picked)
    assert calls == [("navigation", ["Portfolio", "Research", "Library"]),
                     ("set_page_config", {"layout": layout}),
                     ("run", picked)], calls
