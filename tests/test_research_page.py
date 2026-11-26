"""WP-3.3 Research page tests (spec v1.1, P1-P2). Source-level guards on pages/research.py and app.py,
plus the pure chip helper. Made-up codes only."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import research_data as rd  # noqa: E402


def page_src():
    return (ROOT / "pages" / "research.py").read_text(encoding="utf-8")


VIEW = str(ROOT / "research_view.py")


def view_src():
    """WP-3.4: the drawing code (helpers, header, tiles, stock and ETF body) lives in research_view.py."""
    return (ROOT / "research_view.py").read_text(encoding="utf-8")


# ---------- P1 page source guards (pattern of test_r3_page_guards_monthly_columns) ----------
def test_p1_page_does_no_arithmetic_on_yahoo_numbers():
    src = page_src()
    for bad in ("/ 100", "- 1", ".std("):
        assert bad not in src, bad


def test_p1_page_imports_research_data_and_handles_error():
    src = page_src()
    assert "import research_data" in src
    assert "ResearchError" in src


def test_p1_page_prints_country_gap():
    assert "not provided by Yahoo" in view_src()  # re-pointed WP-3.4 (ruling): the body moved to research_view.py


def test_p1_app_registers_research_page():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "pages/research.py" in src
    assert src.index("pages/portfolio.py") < src.index("pages/research.py")  # after Portfolio


# ---------- P2 chip codes ----------
def test_p2_chip_codes_in_order_dropping_none_and_duplicates():
    holdings = pd.DataFrame({"Code": ["MY.1234", "US.FAKE", "HK.00001", "MY.1234", "US.ZZZ", "US.FAKE"],
                             "Name": list("abcdef")})
    assert rd.chip_codes(holdings) == ["1234.KL", "FAKE", "ZZZ"]


def test_p2_chip_codes_empty_frame():
    assert rd.chip_codes(pd.DataFrame({"Code": []})) == []


# ---------- Mutation r1b: the page run with streamlit's AppTest (research and workbook patched) ----------
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
import portfolio_data  # noqa: E402
from test_research_data import ANN, etf_like, gamuda_like  # noqa: E402

PAGE = str(ROOT / "pages" / "research.py")


def run_page(monkeypatch, result="etf", workbook="ok", typed=None, chip=None):
    """Run pages/research.py with made-up data; returns (AppTest, list of codes passed to research)."""
    from streamlit.testing.v1 import AppTest
    calls = []

    def fake_research(code, **kw):
        calls.append(code)
        return rd.analyse(etf_like() if result == "etf" else gamuda_like())

    def fake_workbook(*a, **kw):
        if workbook == "missing":
            raise FileNotFoundError("no workbook (fake)")
        return SimpleNamespace(holdings=pd.DataFrame({"Code": ["US.FAKE", "MY.1234"]}))

    monkeypatch.setattr(rd, "research", fake_research)
    monkeypatch.setattr(portfolio_data, "load_workbook", fake_workbook)
    at = AppTest.from_file(PAGE, default_timeout=30)
    at.run()
    if chip is not None:
        at.pills[0].set_value(chip).run()
    if typed is not None:
        at.text_input[0].input(typed).run()
    return at, calls


def metric(at, label):
    return next(m.value for m in at.metric if m.label == label)


def captions(at):
    return [c.value for c in at.caption]


def test_r1c_page_etf_runs_and_shows_ringgit_size(monkeypatch):
    at, calls = run_page(monkeypatch, typed="VT")
    assert not at.exception
    assert calls == ["VT"]
    # Amended by the WP-3.2.1 r2 checker (spec v1.1 rule 6): the header tile is a fact; same string.
    assert fact(at, "Fund size") == ["RM 425.0 bn (USD 100.0 bn)"]  # 1.0e11 x 4.25


def test_r1c_page_volatility_is_the_data_layer_figure(monkeypatch):
    at, _ = run_page(monkeypatch, typed="VT")
    stats = rd.etf_stats(etf_like())
    assert metric(at, "Volatility") == f"{stats['volatility_3y'] * 100:.1f}%"
    assert metric(at, "Max drawdown") == f"{stats['max_drawdown_3y'] * 100:.1f}%"


def test_r1c_page_annualised_captions(monkeypatch):
    at, _ = run_page(monkeypatch, typed="VT")
    assert metric(at, "3y return") == "+40.0%"
    assert f"{ANN['3y'] * 100:.1f}% a year" in captions(at)  # 11.9%, not 40.0%
    assert f"{ANN['5y'] * 100:.1f}% a year" in captions(at)


def test_r1c_page_country_line(monkeypatch):
    at, _ = run_page(monkeypatch, typed="VT")
    assert "Country mix: not provided by Yahoo" in captions(at)


def test_r1c_page_stock_shows_only_tiles_and_wp32_line(monkeypatch):
    # Amended by the WP-3.2 checker (spec v1.1 P7 supersedes it): the "comes in WP-3.2" line is gone and
    # the stock view draws its own sections; the WP-3.1 fixture has no prices, so the n/a line shows.
    at, _ = run_page(monkeypatch, result="stock", typed="5398.KL")
    assert not at.exception
    assert not any("comes in WP-3.2" in i.value for i in at.info)
    heads = [s.value for s in at.subheader]
    assert "Top ten holdings" not in heads
    assert "What it holds" not in heads  # rule 14 section name (r3b)
    assert "Credit health" in heads and "Company" in heads
    texts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [t.value for t in at.text]
    assert "Price history: not provided by Yahoo for this code." in texts


def test_r1c_page_missing_workbook_no_chips_no_error(monkeypatch):
    at, calls = run_page(monkeypatch, workbook="missing")
    assert not at.exception
    assert len(at.pills) == 0
    assert [i.value for i in at.info] == ["Type a Yahoo code or pick a holding."]
    assert calls == []


def test_r1c_page_typed_code_trimmed_and_upper_cased(monkeypatch):
    _, calls = run_page(monkeypatch, typed=" vt ")
    assert calls == ["VT"]


def test_r1c_page_typed_code_overrides_chip(monkeypatch):
    at, calls = run_page(monkeypatch, chip="FAKE", typed="VT")
    assert calls == ["FAKE", "VT"]  # the chip first, then the typed code wins


def test_r1c_light_dot_colours():
    src = page_src()
    assert 'LIGHT_DOT = {"green": "\U0001F7E2", "amber": "\U0001F7E1", "red": "\U0001F534", "grey": "⚪"}' in src


def test_r1c_app_research_page_title():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'st.Page("pages/research.py", title="Research")' in src


# ---------- Review r1 F3 (spec v1.3 rule 6): a chip clicked after typing switches the page ----------
def test_r2_f3_chip_after_typing_fills_the_box_and_wins(monkeypatch):
    from streamlit.testing.v1 import AppTest
    calls = []

    def fake_research(code, **kw):
        calls.append(code)
        return rd.analyse(etf_like() if code == "VT" else gamuda_like())

    monkeypatch.setattr(rd, "research", fake_research)
    monkeypatch.setattr(portfolio_data, "load_workbook",
                        lambda *a, **k: SimpleNamespace(holdings=pd.DataFrame({"Code": ["US.VT", "MY.5398"]})))
    at = AppTest.from_file(PAGE, default_timeout=30)
    at.run()
    at.text_input(key="code").input("VT").run()
    assert calls[-1] == "VT"
    at.pills[0].set_value("5398.KL").run()  # pills on_change copies the chip into session_state["code"]
    assert not at.exception
    assert calls[-1] == "5398.KL"
    assert at.text_input(key="code").value == "5398.KL"


# ---------- Mutation r2b: deselecting a chip keeps the box ----------
def test_r2b_deselected_chip_keeps_the_box(monkeypatch):
    at, calls = run_page(monkeypatch, chip="FAKE")
    assert at.text_input(key="code").value == "FAKE"
    at.pills[0].set_value(None).run()  # click the same chip again: nothing picked
    assert not at.exception
    assert at.text_input(key="code").value == "FAKE"
    assert calls[-1] == "FAKE"


# ---------- Round 3 (spec v1.4 rules 10-12, 15): P5 page guards and AppTest ----------
import ast  # noqa: E402
import re  # noqa: E402
import tomllib  # noqa: E402

LONG_NAME = "Fake Very Long Global All Cap Ex Nothing Total Market Index Exchange Traded Fund Accumulating Class"


def test_r3_p5_no_metric_label_for_name_exchange_category():
    src = view_src()  # re-pointed WP-3.4: the header moved to research_view.py
    for label in ("Name", "Exchange", "Category", "Sector"):
        assert not re.search(r'\.metric\(\s*["\']' + label + r'["\']', src), label
    assert not re.search(r"\.metric\(\s*(r\.name|f?\"\{r\.name)", src)


def test_r3_p5_refresh_button_present():
    assert "Refresh from Yahoo" in page_src()


def test_r3_p5_light_css_four_colours():
    tree = ast.parse(view_src())  # re-pointed WP-3.4
    found = [n.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == "LIGHT_CSS" for t in n.targets)]
    assert found, "LIGHT_CSS not defined in research_view.py"
    css = ast.literal_eval(found[0])
    assert set(css) == {"green", "amber", "red", "grey"}
    hexes = {"green": "#2e7d32", "amber": "#f9a825", "red": "#c62828", "grey": "#9e9e9e"}
    for colour, hx in hexes.items():
        assert hx in str(css[colour]).lower(), colour


def test_r3_p5_streamlit_config_theme_and_no_usage_stats():
    path = ROOT / ".streamlit" / "config.toml"
    assert path.exists()
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    assert cfg["browser"]["gatherUsageStats"] is False
    theme = cfg["theme"]
    assert theme["primaryColor"].lower() == "#2e7d32"
    assert theme["backgroundColor"].lower() == "#ffffff"
    assert theme["secondaryBackgroundColor"].lower() == "#f4f6f4"
    assert theme["textColor"].lower() == "#1b1b1b"
    assert theme["font"] == "sans serif"


def run_r3(monkeypatch, name=None):
    """Run the page with research patched; records (code, force) per call."""
    from streamlit.testing.v1 import AppTest
    calls = []

    def fake_research(code, force=False, **kw):
        calls.append((code, force))
        r = rd.analyse(etf_like())
        if name:
            r.name = name
        return r

    monkeypatch.setattr(rd, "research", fake_research)
    monkeypatch.setattr(portfolio_data, "load_workbook",
                        lambda *a, **k: SimpleNamespace(holdings=pd.DataFrame({"Code": ["US.VT"]})))
    at = AppTest.from_file(PAGE, default_timeout=30)
    at.run()
    at.text_input(key="code").input("VT").run()
    return at, calls


def test_r3_apptest_refresh_button_forces_fetch(monkeypatch):
    at, calls = run_r3(monkeypatch)
    assert calls and calls[-1] == ("VT", False)
    btn = [b for b in at.button if b.label == "Refresh from Yahoo"]
    assert btn, "no Refresh from Yahoo button"
    btn[0].click().run()
    assert not at.exception
    assert calls[-1] == ("VT", True)


def test_r3_apptest_long_name_in_full_with_detail_caption(monkeypatch):
    at, _ = run_r3(monkeypatch, name=LONG_NAME)
    assert not at.exception
    assert any(LONG_NAME in s.value for s in at.subheader)
    assert not any(LONG_NAME in m.label or LONG_NAME in str(m.value) for m in at.metric)
    # exchange, category and code on one caption line beneath (rule 10)
    assert any("PCX" in c and "Fake Global Blend" in c and "VT" in c for c in captions(at)), captions(at)
    assert not [m for m in at.metric if m.label in ("Exchange", "Category", "Sector")]


def test_r3_apptest_verdict_and_data_as_of(monkeypatch):
    at, _ = run_r3(monkeypatch)
    texts = captions(at) + [m.value for m in at.markdown] + [s.value for s in at.subheader]
    assert any("Cheap to hold; large and liquid" in t for t in texts)  # r4: "; " join
    assert any(t.startswith("Data as of ") and "saved copies are reused for an hour" in t for t in captions(at))


# ---------- Mutation r3b: tests for the r3 survivors ----------
def test_r3b_badges_use_their_colour(monkeypatch):
    at, _ = run_r3(monkeypatch)  # fixture: both lights green, overall green
    md = [m.value for m in at.markdown]
    overall = [m for m in md if m.startswith("Overall")]
    assert overall and "background:#2e7d32" in overall[0]
    table = [m for m in md if m.startswith("| Item | Value | Light | Why |")]
    assert table and table[0].count("background:#2e7d32") == 2


def test_r3b_config_no_email_prompt():
    cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert cfg["server"]["showEmailPrompt"] is False


def test_r3b_holdings_progress_bars_in_source():
    src = view_src()  # re-pointed WP-3.4 (ruling): the ETF body moved to research_view.py
    assert "st.column_config.ProgressColumn(" in src
    assert 'format="%.1f%%"' in src
    assert re.search(r"st\.dataframe\(top, hide_index=True, column_config=\{", src)


def test_r3b_etf_section_order(monkeypatch):
    at, _ = run_r3(monkeypatch)
    heads = [s.value for s in at.subheader]
    assert heads[1:] == ["Costs and size", "Returns and risk", "What it holds", "Links"]


# ---------- Round 4 (spec v1.5 rule 14, review r3 F1 and the HTML-escape nit) ----------
from test_research_data import names_only_holdings  # noqa: E402


def run_with(monkeypatch, make_result):
    """Run the page with research returning make_result(); VT typed."""
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(rd, "research", lambda code, **kw: make_result())
    monkeypatch.setattr(portfolio_data, "load_workbook",
                        lambda *a, **k: SimpleNamespace(holdings=pd.DataFrame({"Code": ["US.VT"]})))
    at = AppTest.from_file(PAGE, default_timeout=30)
    at.run()
    at.text_input(key="code").input("VT").run()
    return at


def test_r4_page_holdings_without_weights_plain_table(monkeypatch):
    def make():
        raw = etf_like()
        raw.holdings = names_only_holdings()
        return rd.analyse(raw)
    at = run_with(monkeypatch, make)
    assert not at.exception, [e.value for e in at.exception]
    assert "What it holds" in [s.value for s in at.subheader]
    assert len(at.dataframe) + len(at.table) >= 1  # the holdings still shown, as a plain table


def test_r4_page_no_max_on_page():
    assert ".max(" not in page_src()


def test_r4_page_cost_table_escapes_reason(monkeypatch):
    def make():
        r = rd.analyse(etf_like())
        r.etf["lights"]["expense_ratio"] = rd.Light("green", "a < b")
        return r
    at = run_with(monkeypatch, make)
    assert not at.exception
    table = [m.value for m in at.markdown if "Expense ratio" in m.value and "|" in m.value]
    assert table, "cost table markdown not found"
    assert "a &lt; b" in table[0]
    assert "a < b" not in table[0]


# ---------- Mutation r4: tests for the r4 survivors ----------
def test_r4m_holdings_without_weights_has_no_weight_column(monkeypatch):
    def make():
        raw = etf_like()
        raw.holdings = names_only_holdings()
        return rd.analyse(raw)
    at = run_with(monkeypatch, make)
    assert not at.exception
    frames = [d.value for d in at.dataframe if "Name" in d.value.columns]
    assert frames, "holdings table not found"
    assert list(frames[0].columns) == ["Name", "Symbol"]  # plain table, no progress-bar column


def test_r4m_cost_table_escapes_value(monkeypatch):
    def make():
        r = rd.analyse(etf_like())
        r.etf["currency"] = "A<B"  # made-up currency code with an HTML character
        return r
    at = run_with(monkeypatch, make)
    assert not at.exception
    table = [m.value for m in at.markdown if "Expense ratio" in m.value and "|" in m.value]
    assert table, "cost table markdown not found"
    assert "A&lt;B 100.0 bn" in table[0]
    assert "A<B" not in table[0]


def test_r4m_cost_table_badge_stays_html(monkeypatch):
    at = run_with(monkeypatch, lambda: rd.analyse(etf_like()))
    table = [m.value for m in at.markdown if "Expense ratio" in m.value and "|" in m.value]
    assert table, "cost table markdown not found"
    assert table[0].count('<span style="background:') == 2  # the badges are real HTML, not escaped text


# ---------- WP-3.2 stock view (spec v1.1, P6-P9). Made-up numbers only. ----------
from test_research_data import (ABSENT, RATIO_NAMES, STOCK_EXTRA, _extend, aapl_stock,  # noqa: E402
                                bank_like, gamuda_stock, info_eq)

STOCK_HEADS = ["Company", "Credit health", "Price and risk", "Valuation", "Dividends", "Statements", "Links"]
CSS = {"green": "#2e7d32", "amber": "#f9a825", "red": "#c62828", "grey": "#9e9e9e"}
NO_STATEMENTS = "Yahoo has no financial statements for this code, so the ratios cannot be worked out."
LENDER_CAPTION = ("Overall light = the worst of the four lender ratios: Debt / Equity, Net debt / EBITDA, "
                  "Interest cover, Current ratio. TTM = the latest twelve months.")


def src_without_pct():
    """The view source with the pct helper's body cut out (the one place allowed to multiply by 100).
    Re-pointed WP-3.4: pct moved to research_view.py."""
    src = view_src()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "pct")
    return src.replace(ast.get_source_segment(src, fn), "")


def run_stock(monkeypatch, make_raw):
    """Run the page for a stock fixture: research returns analyse(make_raw())."""
    return run_with(monkeypatch, lambda: rd.analyse(make_raw()))


def all_text(at):
    return ([c.value for c in at.caption] + [m.value for m in at.markdown] + [i.value for i in at.info]
            + [s.value for s in at.subheader] + [t.value for t in at.text])


FACT_LABELS = ("52-week range", "Next earnings", "Analyst target", "Analysts")


def page_text(at):
    """Every markdown and caption text on the page (WP-3.2.1: where `fact` puts its label, value and caption)."""
    return [m.value for m in at.markdown] + [c.value for c in at.caption]


def unwrap(text):
    """A fact text without the fixed markdown wrapper `fact` may put round it: leading and trailing '#', '*'
    and whitespace are dropped, so '#### 5.85 MYR' and '**5.85 MYR**' both give '5.85 MYR' (WP-3.2.1 r2)."""
    return re.sub(r"^[#*\s]+|[#*\s]+$", "", text)


def fact(at, label):
    """WP-3.2.1 (r2, review nit 2, exact): the texts drawn under the fact `label` in its own column, in page
    order and unwrapped: [value] or [value, caption]. Callers compare the whole list by equality. Fails when
    a metric still carries the label, or no column shows the label as a markdown / caption text of its own."""
    assert label not in {m.label for m in at.metric}, f"{label!r} is still an st.metric"
    found = []
    for col in at.columns:
        texts = [unwrap(n.value) for _, n in sorted(col.children.items())
                 if getattr(n, "type", None) in ("markdown", "caption")]
        if label in texts:
            found.append(texts[texts.index(label) + 1:])
    assert found, f"no column shows {label!r} as a markdown or caption text"
    return min(found, key=len)  # the innermost column, if columns ever nest



def credit_table(at):
    found = [m.value for m in at.markdown if m.value.lstrip().startswith("| Group |")]
    return found[0] if found else None


def plotly_count(at):
    return len(at.get("plotly_chart"))


# ---------- P6 page source guards ----------
def test_p6_page_guards_stock_view():
    src = view_src()  # re-pointed WP-3.4: the stock view moved to research_view.py
    for bad in ("/ 100", "- 1", ".std(", "/ 1e6", "/1e6", "1_000_000", "1000000"):
        assert bad not in src, bad  # P1 patterns, extended for the statement tables
    assert "* 100" not in src_without_pct() and "*100" not in src_without_pct()
    assert "comes in WP-3.2" not in src
    assert "rd.credit_rows(" in src
    assert "rd.statement_rows(" in src
    assert "def draw_returns(" in src  # rule 9.3: one shared returns-and-risk function for both views


# ---------- P7 AppTest, stock fixture ----------
def test_p7_stock_sections_in_rule9_order(monkeypatch):
    at = run_stock(monkeypatch, gamuda_stock)
    assert not at.exception, [e.value for e in at.exception]
    heads = [s.value for s in at.subheader]
    assert heads[0] == "Gamuda-like Bhd"
    assert heads[1:] == STOCK_HEADS


def test_p7_credit_table_ratios_periods_and_badges(monkeypatch):
    at = run_stock(monkeypatch, gamuda_stock)
    assert not at.exception
    r = rd.analyse(gamuda_stock())
    table = credit_table(at)
    assert table, "credit table markdown not found"
    header = [c.strip() for c in table.lstrip().splitlines()[0].strip().strip("|").split("|")]
    assert header == ["Group", "Ratio"] + r.periods + ["Light", "Why"]  # TTM first, newest left
    assert table.count('<span style="background:') == 9  # one badge per ratio
    lines = table.splitlines()
    for name in RATIO_NAMES:
        row = next((ln for ln in lines if f"| {name} |" in ln), None)
        assert row, name
        assert f"background:{CSS[r.lights[name].colour]}" in row, name  # the badge in the light's colour
        assert rd.RATIO_GROUPS[name] in row, name


def test_p7_credit_caption_names_the_four_lender_ratios(monkeypatch):
    at = run_stock(monkeypatch, gamuda_stock)
    assert LENDER_CAPTION in captions(at)


def test_p7_market_cap_tile_ringgit_with_original(monkeypatch):
    at = run_stock(monkeypatch, aapl_stock)
    assert not at.exception
    # Amended WP-3.2.1 r2 (rule 6): a fact, same string.
    assert fact(at, "Market cap") == ["RM 21.4 tn (USD 5.0 tn)"]  # 5.03e12 x 4.25 = 2.13775e13


def test_p7_market_cap_tile_ringgit_only_for_myr(monkeypatch):
    at = run_stock(monkeypatch, gamuda_stock)
    assert not at.exception
    assert fact(at, "Market cap") == ["RM 29.8 bn"]  # 2.98e10 x 1.0, no brackets; amended WP-3.2.1 r2 (rule 6)
    # Amended by the WP-3.2.1 checker (spec v1.0 rule 2): the range and next earnings are facts, not metrics.
    assert {"Insiders own", "Institutions own"} <= {m.label for m in at.metric}
    assert fact(at, "52-week range")[0].endswith(" MYR") and fact(at, "Next earnings") == ["09 Dec 2026"]


# ---------- P8 AppTest: bank, no statements, no dividends, all-None company block ----------
def bank_stock():
    return _extend(bank_like(), {}, True, True, 1.0)


def no_statements_stock():
    e = pd.DataFrame()
    raw = rd.Raw(code="NOSTMT.KL", info=info_eq(longName="Fake No Statements Bhd"), income=e, balance=e,
                 cashflow=e, q_income=e, q_balance=e, q_cashflow=e, recs=e, fetched_at=gamuda_stock().fetched_at)
    return _extend(raw, {}, True, True, 1.0)


COMPANY_KEYS = [k for k in STOCK_EXTRA if k != "marketCap"] + ["fullTimeEmployees"]


def none_company_stock():
    """Every company-block key absent, no fx: each tile must say n/a."""
    return gamuda_stock(fx=None, **{k: ABSENT for k in COMPANY_KEYS})


def test_p8_bank_shows_bank_line_in_info_box(monkeypatch):
    at = run_stock(monkeypatch, bank_stock)
    assert not at.exception, [e.value for e in at.exception]
    assert rd.BANK_LINE in [i.value for i in at.info]
    assert "Credit health" in [s.value for s in at.subheader]


def test_p8_no_statements_info_no_table_no_statements_section(monkeypatch):
    at = run_stock(monkeypatch, no_statements_stock)
    assert not at.exception, [e.value for e in at.exception]
    assert NO_STATEMENTS in [i.value for i in at.info]
    assert credit_table(at) is None
    heads = [s.value for s in at.subheader]
    assert "Credit health" in heads
    assert "Statements" not in heads


def test_p8_no_dividends_line(monkeypatch):
    at = run_stock(monkeypatch, lambda: gamuda_stock(dividends=False))
    assert not at.exception
    # Amended by the WP-3.2 round 2 checker (spec v1.2 rule 16): the new wording, the old one gone.
    assert any("No dividends in the years shown" in t for t in all_text(at))
    assert not any("No dividends in the last five years" in t for t in all_text(at))
    assert "Dividends" in [s.value for s in at.subheader]


def test_p8_none_company_block_renders_na(monkeypatch):
    at = run_stock(monkeypatch, none_company_stock)
    assert not at.exception, [e.value for e in at.exception]
    for label in ("Insiders own", "Institutions own", "Payout ratio"):
        assert metric(at, label) == "n/a", label
    # Amended by the WP-3.2.1 checker (spec v1.0 rule 2): these two are facts now, still "n/a".
    for label in ("52-week range", "Next earnings"):
        assert fact(at, label) == ["n/a"], label  # r2 exact
    assert "Company" in [s.value for s in at.subheader]


def test_p8_company_block_values(monkeypatch):
    at = run_stock(monkeypatch, gamuda_stock)
    assert not at.exception
    # "<low> – <high> <ccy>"; the spec fixes no decimal places, so 4 / 4.0 / 4.00 are all accepted
    # Amended by the WP-3.2.1 checker (spec v1.0 rule 2): the range and next earnings are read from the
    # fact's column (label, value and caption), as substrings, instead of from st.metric.
    rng = fact(at, "52-week range")  # r2: exact, value then caption
    assert len(rng) == 2 and re.fullmatch(r"4(\.0+)? – 6(\.0+)? MYR", rng[0]), rng
    assert re.fullmatch(r"now 50(\.0)?% of the way up", rng[1]), rng  # range_position 0.5, its own label
    assert metric(at, "Insiders own") == "10.0%"  # 0.10 as a percent, 1 place
    assert metric(at, "Institutions own") == "55.0%"
    assert fact(at, "Next earnings") == ["09 Dec 2026"]  # %d %b %Y of 2026-12-09; r2 exact
    assert "What the company does" in [x.label for x in at.expander]


# ---------- P9 AppTest: the ETF view unchanged, plus the price chart ----------
def test_p9_etf_view_unchanged_plus_one_chart(monkeypatch):
    at = run_with(monkeypatch, lambda: rd.analyse(etf_like()))
    assert not at.exception
    heads = [s.value for s in at.subheader]
    assert heads[1:] == ["Costs and size", "Returns and risk", "What it holds", "Links"]  # WP-3.3 order
    stats = rd.etf_stats(etf_like())
    assert fact(at, "Fund size") == ["RM 425.0 bn (USD 100.0 bn)"]  # amended WP-3.2.1 r2 (rule 6)
    assert metric(at, "1y return") == "+16.7%"  # 175 / 150 - 1
    assert metric(at, "3y return") == "+40.0%"
    assert metric(at, "5y return") == "+75.0%"
    assert metric(at, "Volatility") == f"{stats['volatility_3y'] * 100:.1f}%"
    assert metric(at, "Max drawdown") == "-20.0%"
    assert metric(at, "Distribution yield") == "2.00%"
    assert plotly_count(at) == 2  # the sector bar (WP-3.3) plus the 5-year price chart (rule 10)


# ---------- WP-3.2 round 2, Part A: review r1 F1 page checks (made-up valuation and analyst figures) ----------
from test_research_data import NAN, divs_frame, recs_frame  # noqa: E402

# info price 5.0 (info_eq). Target 5.85: 5.85 / 5.0 - 1 = 0.17 -> "upside +17.0%".
# Target 4.80: 4.80 / 5.0 - 1 = -0.04 -> "downside -4.0%".
# recs_frame() newest row: strongBuy 2 + buy 3 = 5 buy; hold 4; sell 1 + strongSell 1 = 2 sell.
VALUED = {"trailingPE": 14.2, "forwardPE": 11.6, "priceToBook": 1.3, "enterpriseToEbitda": 9.8,
          "trailingAnnualDividendYield": 0.0234, "targetMeanPrice": 5.85, "numberOfAnalystOpinions": 20}


def valued_stock(recs=None, **info):
    """gamuda_stock with made-up valuation keys, one 0.03 dividend in 2026, a 2.5e9 revenue cell
    (2.5e9 / 1e6 = 2,500 in the statement table) and one NaN balance cell."""
    raw = gamuda_stock(**dict(VALUED, **info))
    if recs is not None:
        raw.recs = recs
    raw.dividends = divs_frame([("2026-03-10", 0.03)])
    raw.income.loc["Total Revenue", raw.income.columns[0]] = 2.5e9  # newest annual, 2026-07-31
    raw.balance.loc["Current Assets", raw.balance.columns[3]] = NAN  # 2023-07-31
    return raw


def styled_values(df_element):
    """The display strings a pandas Styler passed to st.dataframe (what the owner sees in each cell)."""
    import pyarrow as pa
    return pa.ipc.open_stream(df_element.proto.arrow_data.styler.display_values).read_all().to_pandas()


def test_r2a_valuation_tiles(monkeypatch):
    at = run_stock(monkeypatch, valued_stock)
    assert not at.exception, [e.value for e in at.exception]
    assert metric(at, "P/E") == "14.2"  # trailingPE, not forwardPE
    assert metric(at, "Forward P/E") == "11.6"
    assert metric(at, "P/B") == "1.3"
    assert metric(at, "EV/EBITDA") == "9.8x"
    assert fact(at, "Dividend yield") == ["2.34%"]  # 0.0234 x 100, 2 places; amended WP-3.2.1 r2 (rule 7)
    # Amended by the WP-3.2.1 checker (spec v1.0 rule 3): target and analysts are facts; value and caption
    # are read from the fact's column as substrings.
    assert fact(at, "Analyst target") == ["5.85 MYR", "upside +17.0%"]  # r2 exact
    assert fact(at, "Analysts") == ["5 buy · 4 hold · 2 sell", "20 analysts"]


def test_r2a_valuation_downside_caption(monkeypatch):
    at = run_stock(monkeypatch, lambda: valued_stock(targetMeanPrice=4.8))
    assert not at.exception
    # Amended by the WP-3.2.1 checker (spec v1.0 rule 3): the caption is read as a substring of the
    # target fact's column.
    assert fact(at, "Analyst target") == ["4.80 MYR", "downside -4.0%"]  # r2 exact
    assert not any("upside" in t.replace("downside", "") for t in page_text(at))


def test_r2a_analysts_one_count_missing_still_a_line(monkeypatch):
    at = run_stock(monkeypatch, lambda: valued_stock(recs=recs_frame(s=NAN)))  # sell cell missing
    assert not at.exception
    assert fact(at, "Analysts") == ["5 buy · 4 hold · n/a sell", "20 analysts"]  # WP-3.2.1 fact; r2 exact


def test_r2a_analysts_all_counts_missing_na(monkeypatch):
    at = run_stock(monkeypatch, lambda: valued_stock(recs=pd.DataFrame()))
    assert not at.exception
    # Amended WP-3.2.1: a fact, not a metric; "n/a" and no buy/hold/sell line.
    assert fact(at, "Analysts") == ["n/a", "20 analysts"]  # r2 exact
    assert not any(" buy · " in t for t in page_text(at))


def test_r2a_dividend_column_label_and_four_decimals(monkeypatch):
    # AppTest gives the raw frame, not the formatted cell, so this checks the column config the page
    # passes to st.dataframe and applies its format string to the 0.03 amount by hand.
    import json
    at = run_stock(monkeypatch, valued_stock)
    assert not at.exception
    div = next(d for d in at.dataframe if "Per share" in d.value.columns)
    assert div.value["Per share"].iloc[0] == pytest.approx(0.03)  # "2026 so far": one 0.03 payment
    cfg = json.loads(div.proto.columns)["Per share"]
    assert cfg["label"] == "Per share (MYR)"
    fmt = cfg["type_config"]["format"]
    assert fmt % 0.03 == "0.0300", fmt


def test_r2a_statement_cells_thousands_and_blank_nan(monkeypatch):
    at = run_stock(monkeypatch, valued_stock)
    assert not at.exception
    frames = {d.value.index[0]: d for d in at.dataframe if len(d.value.index)}
    income = styled_values(frames["Total Revenue"])
    assert income.loc["Total Revenue", "2026-07-31"] == "2,500"  # 2.5e9 / 1e6, no decimals
    balance = styled_values(frames["Total Debt"])
    assert balance.loc["Current Assets", "2023-07-31"] == ""  # NaN shown blank, not "nan"


def test_r2a_company_website_link_and_sector_caption(monkeypatch):
    at = run_stock(monkeypatch, valued_stock)
    assert not at.exception
    assert "[https://example.com](https://example.com)" in [m.value for m in at.markdown]
    assert "Industrials · Engineering & Construction" in captions(at)  # "<sector> · <industry>"


# ---------- WP-3.2 round 2, Part B (spec v1.2 rules 13, 15, 16) ----------

def page_helpers():
    """The page's imports, constants and functions, run without the Streamlit body (the same reach into the
    page source as the LIGHT_CSS test): returns the namespace holding price_text, pct, shown, ..."""
    tree = ast.parse(view_src())  # re-pointed WP-3.4: the helpers moved to research_view.py
    def constant(n):  # NA, LIGHT_DOT, LIGHT_CSS; not the page body's `r = ...`, `e = r.etf`
        try:
            ast.literal_eval(n.value)
            return True
        except ValueError:
            return False
    keep = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef))
            or (isinstance(n, ast.Assign) and constant(n))]
    ns = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), VIEW, "exec"), ns)
    return ns


# R1 (rule 13): 3 decimals below 1, else 2; thousands separators; "n/a" for None.
@pytest.mark.parametrize("x,shown_as", [(0.285, "0.285"), (0.035, "0.035"), (4.92, "4.92"), (1234.5, "1,234.50"),
                                        (None, "n/a"),
                                        (1.0, "1.00")])  # mutation r2: exactly 1 is "else 2", not 3 decimals
def test_r2b_price_text(x, shown_as):
    assert page_helpers()["price_text"](x) == shown_as


def penny_stock():
    """A Bursa penny stock (made up): price 0.285, 52-week range 0.285 to 0.455, analyst target 0.5."""
    return gamuda_stock(currentPrice=0.285, fiftyTwoWeekLow=0.285, fiftyTwoWeekHigh=0.455, targetMeanPrice=0.5)


def test_r2b_penny_stock_prices_three_decimals(monkeypatch):
    at = run_stock(monkeypatch, penny_stock)
    assert not at.exception, [e.value for e in at.exception]
    assert fact(at, "Price") == ["0.285 MYR"]  # amended WP-3.2.1 r2 (rule 6): a fact, same string
    # Amended by the WP-3.2.1 checker: range and target are facts, read from their columns as substrings.
    # r2: exact. 0.5 / 0.285 - 1 = 0.75439 -> "upside +75.4%"; position (0.285 - 0.285) / (0.455 - 0.285) = 0
    assert fact(at, "52-week range") == ["0.285 – 0.455 MYR", "now 0% of the way up"]  # not "0.28 – 0.46"
    assert fact(at, "Analyst target") == ["0.500 MYR", "upside +75.4%"]


def test_r2b_etf_below_one_price_three_decimals(monkeypatch):
    def make():
        raw = etf_like()
        raw.info["regularMarketPrice"] = 0.735  # made-up ETF trading below 1
        return rd.analyse(raw)
    at = run_with(monkeypatch, make)
    assert not at.exception, [e.value for e in at.exception]
    assert fact(at, "Price") == ["0.735 USD"]  # amended WP-3.2.1 r2 (rule 6): a fact, same string


def test_r2b_stock_price_tile_two_decimals_at_one_and_above(monkeypatch):
    at = run_stock(monkeypatch, lambda: gamuda_stock(currentPrice=1234.5))
    assert not at.exception
    assert fact(at, "Price") == ["1,234.50 MYR"]  # amended WP-3.2.1 r2 (rule 6): a fact, same string


# R3 (rule 15): text in a Yahoo number key renders n/a, no traceback.
@pytest.mark.parametrize("pe", ["Infinity", "abc"])
def test_r2b_text_pe_renders_na(monkeypatch, pe):
    at = run_stock(monkeypatch, lambda: gamuda_stock(trailingPE=pe))
    assert not at.exception, [e.value for e in at.exception]
    assert metric(at, "P/E") == "n/a"
    assert "Valuation" in [s.value for s in at.subheader]


# ---------- WP-3.2.1 (spec v1.0): long values drawn with `fact`, never cut off by st.metric ----------
def fact_stock():
    """Made-up stock: price 5.3 in a 4.0 to 6.0 range, target 6.201, 20 analysts, 15 buy / 2 hold / 0 sell.
    Position (5.3 - 4.0) / (6.0 - 4.0) = 0.65 -> "now 65% of the way up"; 6.201 / 5.3 - 1 = 0.17 -> "upside +17.0%";
    newest recs row strongBuy 10 + buy 5 = 15 buy, hold 2, sell 0 + strongSell 0 = 0 sell."""
    return valued_stock(recs=recs_frame(sb=10, b=5, h=2, s=0, ss=0), currentPrice=5.3, targetMeanPrice=6.201)


def test_t1_long_values_are_facts_not_metrics(monkeypatch):
    at = run_stock(monkeypatch, fact_stock)
    assert not at.exception, [e.value for e in at.exception]
    labels = {m.label for m in at.metric}
    assert not labels & set(FACT_LABELS), labels & set(FACT_LABELS)
    # r2 (review nit 2): value and caption exact, nothing else under the label
    for label, shown_as in [("52-week range", ["4.00 – 6.00 MYR", "now 65% of the way up"]),
                            ("Next earnings", ["09 Dec 2026"]),
                            ("Analyst target", ["6.20 MYR", "upside +17.0%"]),
                            ("Analysts", ["15 buy · 2 hold · 0 sell", "20 analysts"])]:
        assert fact(at, label) == shown_as, label


def test_t1_penny_range_in_full(monkeypatch):
    at = run_stock(monkeypatch, penny_stock)
    assert not at.exception, [e.value for e in at.exception]
    # (0.285 - 0.285) / (0.455 - 0.285) = 0; r2: exact
    assert fact(at, "52-week range") == ["0.285 – 0.455 MYR", "now 0% of the way up"]


def test_t2_short_values_stay_metrics(monkeypatch):
    at = run_stock(monkeypatch, valued_stock)
    assert not at.exception, [e.value for e in at.exception]
    assert metric(at, "Insiders own") == "10.0%"
    assert metric(at, "Institutions own") == "55.0%"
    assert metric(at, "P/E") == "14.2"
    assert metric(at, "Forward P/E") == "11.6"
    assert metric(at, "P/B") == "1.3"
    assert metric(at, "EV/EBITDA") == "9.8x"
    assert fact(at, "Dividend yield") == ["2.34%"]  # amended WP-3.2.1 r2 (rule 7): joins the facts' row


def test_t3_no_metric_call_carries_a_fact_label():
    for node in ast.walk(ast.parse(view_src())):  # re-pointed WP-3.4
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "metric":
            args = list(node.args[:1]) + [k.value for k in node.keywords if k.arg == "label"]
            for a in args:
                assert not (isinstance(a, ast.Constant) and a.value in FACT_LABELS), ast.unparse(node)


def test_t3_fact_helper_exists_without_unsafe_html():
    src = view_src()  # re-pointed WP-3.4
    fn = next((n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "fact"), None)
    assert fn is not None, "research_view.py has no fact() helper"
    assert [a.arg for a in fn.args.args] == ["col", "label", "value", "caption", "help"]
    assert [d.value for d in fn.args.defaults] == [None, None]
    body = ast.get_source_segment(src, fn)
    assert "unsafe_allow_html" not in body
    assert ".metric(" not in body


def test_t4_company_facts_none_render_na(monkeypatch):
    at = run_stock(monkeypatch, none_company_stock)
    assert not at.exception, [e.value for e in at.exception]
    for label in ("52-week range", "Next earnings"):
        assert fact(at, label) == ["n/a"], label  # r2 exact: no position caption without a range


def test_t4_valuation_facts_none_render_na(monkeypatch):
    at = run_stock(monkeypatch, lambda: valued_stock(recs=pd.DataFrame(), targetMeanPrice=ABSENT,
                                                     numberOfAnalystOpinions=ABSENT))
    assert not at.exception, [e.value for e in at.exception]
    for label in ("Analyst target", "Analysts"):
        assert fact(at, label) == ["n/a"], label  # r2 exact
    assert not any("upside" in t or "downside" in t for t in page_text(at))
    assert not any(t.endswith(" analysts") for t in page_text(at))


# Added by the WP-3.2.1 mutation checker (r1): survivors "fact drops the help tip" and the layout mutants.
FACT_HELP = {"52-week range": "Lowest and highest traded price over the last year",
             "Next earnings": "The next results date Yahoo expects; it may be an estimate",
             "Analyst target": "The average price analysts expect in about a year",
             "Analysts": "How many analysts say buy, hold or sell, from Yahoo's latest month"}


def test_m_fact_label_keeps_its_help_tip(monkeypatch):
    """Spec rules 1 and 4: each fact's label carries the same help tip the metric had."""
    at = run_stock(monkeypatch, fact_stock)
    assert not at.exception, [e.value for e in at.exception]
    for label, tip in FACT_HELP.items():
        assert [c.proto.help for c in at.caption if c.value == label] == [tip], label


def column_weight(at, has):
    found = [col.weight for col in at.columns if has(col)]
    assert len(found) == 1, found
    return found[0]


def test_m_company_and_valuation_rows_layout(monkeypatch):
    """Spec rules 2 and 3: Company is two rows of two (facts, then the two ownership metrics); Valuation row 2
    is three columns (Dividend yield, Analyst target, Analysts); row 1 stays the four multiples."""
    at = run_stock(monkeypatch, fact_stock)
    assert not at.exception, [e.value for e in at.exception]
    def fact_col(label):
        return lambda col: any(c.value == label for c in col.caption)
    def metric_col(label):
        return lambda col: [m.label for m in col.metric] == [label]
    for has in (fact_col("52-week range"), fact_col("Next earnings"),
                metric_col("Insiders own"), metric_col("Institutions own")):
        assert column_weight(at, has) == pytest.approx(1 / 2)
    # amended WP-3.2.1 r2 (rule 7): Dividend yield is a fact in that row
    for has in (fact_col("Dividend yield"), fact_col("Analyst target"), fact_col("Analysts")):
        assert column_weight(at, has) == pytest.approx(1 / 3)
    for label in ("P/E", "Forward P/E", "P/B", "EV/EBITDA"):
        assert column_weight(at, metric_col(label)) == pytest.approx(1 / 4), label


# ---------- WP-3.2.1 round 2 (spec v1.1 rules 6-8): header tiles and the stock Dividend yield are facts ----------
HEADER_HELP = {
    "Price": "",  # the Price tile never had a help tip
    "Market cap": "What the market values the whole company at, in Ringgit with the listing currency in brackets",
    "Fund size": "Total assets of the fund, in Ringgit with the fund's own currency in brackets"}
DIVIDEND_HELP = "Dividends paid over the last year as a share of the price"
R2_FACT_LABELS = ("Price", "Market cap", "Fund size", "Dividend yield")


def label_help(at, label):
    """The help tips on the caption(s) that show `label` as a fact label ('' when a caption has none)."""
    return [c.proto.help for c in at.caption if c.value == label]


@pytest.mark.parametrize("make,size_label,shown_as", [
    (aapl_stock, "Market cap", ["5.00 USD", "RM 21.4 tn (USD 5.0 tn)"]),  # 5.03e12 x 4.25, USD in brackets
    (gamuda_stock, "Market cap", ["5.00 MYR", "RM 29.8 bn"]),  # Ringgit only, no brackets
    (etf_like, "Fund size", ["175.00 USD", "RM 425.0 bn (USD 100.0 bn)"]),  # 1.0e11 x 4.25
], ids=["usd_stock", "myr_stock", "usd_etf"])
def test_r2_header_tiles_are_facts_in_full(monkeypatch, make, size_label, shown_as):
    """Rule 6: Price and Market cap / Fund size drawn with `fact`, same strings and help tips; none a metric."""
    at = run_with(monkeypatch, lambda: rd.analyse(make()))
    assert not at.exception, [e.value for e in at.exception]
    labels = {m.label for m in at.metric}
    assert not labels & {"Price", "Market cap", "Fund size"}, labels
    assert fact(at, "Price") == shown_as[:1]
    assert fact(at, size_label) == shown_as[1:]
    for label in ("Price", size_label):
        assert label_help(at, label) == [HEADER_HELP[label]], label


def test_r2_stock_dividend_yield_is_a_fact(monkeypatch):
    """Rule 7: the stock Dividend yield is a fact with the same string and help tip."""
    at = run_stock(monkeypatch, valued_stock)
    assert not at.exception, [e.value for e in at.exception]
    assert "Dividend yield" not in {m.label for m in at.metric}
    assert fact(at, "Dividend yield") == ["2.34%"]  # 0.0234 x 100, 2 places
    assert label_help(at, "Dividend yield") == [DIVIDEND_HELP]


def test_r2_stock_dividend_yield_na_is_a_fact(monkeypatch):
    at = run_stock(monkeypatch, aapl_stock)  # the fixture has no dividend yield
    assert not at.exception, [e.value for e in at.exception]
    assert fact(at, "Dividend yield") == ["n/a"]


def rows_of_columns(node):
    """Every row of columns (st.columns) on the page, as a list of its columns."""
    from streamlit.testing.v1.element_tree import Column
    kids = [c for _, c in sorted((getattr(node, "children", None) or {}).items())]
    cols = [c for c in kids if isinstance(c, Column)]
    rows = [cols] if cols else []
    for c in kids:
        rows += rows_of_columns(c)
    return rows


@pytest.mark.parametrize("make", [valued_stock, aapl_stock, etf_like], ids=["myr_stock", "usd_stock", "usd_etf"])
def test_r2_no_row_mixes_facts_and_metrics(monkeypatch, make):
    """Rule 7: a row holding a metric holds only metric columns (the header and Valuation row 2 hold none)."""
    at = run_with(monkeypatch, lambda: rd.analyse(make()))
    assert not at.exception, [e.value for e in at.exception]
    rows = rows_of_columns(at._tree)
    assert rows
    for row in rows:
        with_metric = [len(col.metric) > 0 for col in row]
        assert all(with_metric) or not any(with_metric), [[m.label for m in col.metric] for col in row]


def test_r2_no_metric_call_carries_a_header_or_dividend_label():
    """Rule 8: the source guard of rule 5 extended; the ETF's "Distribution yield" metric stays."""
    src = view_src()  # re-pointed WP-3.4
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "metric":
            args = list(node.args[:1]) + [k.value for k in node.keywords if k.arg == "label"]
            for a in args:
                assert not (isinstance(a, ast.Constant) and a.value in R2_FACT_LABELS), ast.unparse(node)
    assert re.search(r'\.metric\(\s*"Distribution yield"', src)


# Added by the WP-3.2.1 mutation checker (r2): survivor "header Price no longer renders n/a when Yahoo has no price".
def test_m2_header_price_none_renders_na(monkeypatch):
    """Rule 6 keeps every string, n/a included: no currentPrice and no regularMarketPrice -> Price fact "n/a"."""
    at = run_stock(monkeypatch, lambda: gamuda_stock(currentPrice=ABSENT, regularMarketPrice=ABSENT))
    assert not at.exception, [e.value for e in at.exception]
    assert fact(at, "Price") == ["n/a"]


# ---------- WP-3.4 (spec v2): the Save block, and the drawing code moved to research_view.py ----------
import importlib  # noqa: E402
import inspect  # noqa: E402

REMINDER = "Notes are saved to git. Leave out amounts and holding sizes."
SAVE_LABEL = "Save snapshot"
WRITTEN = ROOT / "research" / "VT_2026-11-11_2.json"  # what the patched save says it wrote (v3: absolute)


def page_items(at):
    """(kind, text) of every drawn thing on the page in order (widgets left out); blocks opened."""
    def leaves(node):
        for _, c in sorted((getattr(node, "children", None) or {}).items()):
            t = getattr(c, "type", None)
            if getattr(c, "children", None) and t not in ("dataframe", "table"):
                if t == "expander":
                    yield c
                yield from leaves(c)
            else:
                yield c
    out = []
    for n in leaves(at._tree):
        t = getattr(n, "type", None)
        if t in ("markdown", "caption", "subheader", "header", "title", "text", "info", "warning", "error",
                 "success", "code"):
            out.append((t, str(n.value)))
        elif t == "metric":
            out.append((t, f"{n.label}={n.value}"))
        elif t in ("dataframe", "table"):
            out.append((t, n.value.to_csv()))
        elif t == "expander":
            out.append((t, n.label))
    return out


def notes_box(at):
    """The notes box: a text area (or a text input other than the code box)."""
    boxes = list(at.text_area) + [w for w in at.text_input if w.key != "code"]
    return boxes[0] if boxes else None


def save_buttons(at):
    return [b for b in at.button if b.label == SAVE_LABEL]


def run_save(monkeypatch, r, code="VT"):
    """The page with research returning the one object r every run, and research_store.save recorded."""
    from streamlit.testing.v1 import AppTest
    rs = importlib.import_module("research_store")
    calls = []

    def fake_save(*args, **kwargs):
        calls.append((args, kwargs))
        return WRITTEN

    monkeypatch.setattr(rs, "save", fake_save)
    monkeypatch.setattr(rd, "research", lambda c, **kw: r)
    monkeypatch.setattr(portfolio_data, "load_workbook",
                        lambda *a, **k: SimpleNamespace(holdings=pd.DataFrame({"Code": ["US.VT"]})))
    at = AppTest.from_file(PAGE, default_timeout=30)
    at.run()
    if code:
        at.text_input(key="code").input(code).run()
    return at, calls


def save_arguments(args, kwargs):
    """The arguments of one save call, bound to the spec's signature save(r, note, *, saved_on, stale, folder)."""
    def spec(r, note, *, saved_on=None, stale=False, folder=None):
        pass
    b = inspect.signature(spec).bind(*args, **kwargs)
    b.apply_defaults()
    return b.arguments


@pytest.mark.parametrize("make", [lambda: rd.analyse(etf_like()), lambda: rd.analyse(gamuda_stock())],
                         ids=["etf", "stock"])
def test_wp34_save_block_shown_with_a_result(monkeypatch, make):
    at, calls = run_save(monkeypatch, make())
    assert not at.exception, [e.value for e in at.exception]
    assert notes_box(at) is not None, "no notes box"
    assert any(REMINDER in s for _, s in page_items(at)), "reminder line missing"
    assert len(save_buttons(at)) == 1, [b.label for b in at.button]
    assert calls == []  # nothing saved before the button is clicked


def test_wp34_no_save_block_without_a_code(monkeypatch):
    at, calls = run_save(monkeypatch, rd.analyse(etf_like()), code=None)
    assert not at.exception
    assert [i.value for i in at.info] == ["Type a Yahoo code or pick a holding."]
    assert save_buttons(at) == [] and notes_box(at) is None
    assert not any(REMINDER in s for _, s in page_items(at))


def test_wp34_no_save_block_for_a_bad_code(monkeypatch):
    from streamlit.testing.v1 import AppTest
    rs = importlib.import_module("research_store")
    monkeypatch.setattr(rs, "save", lambda *a, **k: pytest.fail("save called"))

    def no_data(code, **kw):
        raise rd.ResearchError(f"Yahoo has no data for {code}")

    monkeypatch.setattr(rd, "research", no_data)
    monkeypatch.setattr(portfolio_data, "load_workbook",
                        lambda *a, **k: SimpleNamespace(holdings=pd.DataFrame({"Code": []})))
    at = AppTest.from_file(PAGE, default_timeout=30)
    at.run()
    at.text_input(key="code").input("ZZZZNOPE.KL").run()
    assert not at.exception
    assert [e.value for e in at.error] == ["Yahoo has no data for ZZZZNOPE.KL"]
    assert save_buttons(at) == [] and notes_box(at) is None
    assert not any(REMINDER in s for _, s in page_items(at))


@pytest.mark.parametrize("stale", [False, True], ids=["fresh", "stale"])
def test_wp34_save_calls_store_with_result_note_and_stale(monkeypatch, stale):
    r = rd.analyse(etf_like(), stale=stale)
    at, calls = run_save(monkeypatch, r)
    note = "Cheap world fund.\nCheck again in March."
    notes_box(at).input(note).run()
    assert calls == [], "saved before the button was clicked"
    save_buttons(at)[0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(calls) == 1, calls
    got = save_arguments(*calls[0])
    assert got["r"] is r, "save was not given the result shown"
    assert got["note"] == note
    assert got["stale"] is stale


def test_wp34_save_reports_the_file_and_nothing_else_changes(monkeypatch):
    at, calls = run_save(monkeypatch, rd.analyse(etf_like()))
    before = page_items(at)
    save_buttons(at)[0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(calls) == 1
    after = page_items(at)
    reported = [s for _, s in after if WRITTEN.name in s]
    assert reported, "the written file name is not shown"
    assert [x for x in after if WRITTEN.name not in x[1]] == before  # nothing else on the page changes


def test_wp34_v3_save_reports_the_path_relative_to_the_repo(monkeypatch):
    """v3.1: save returns the absolute research/ path beside research_store.py; the page names it as
    research/<name>.json, relative to the repo folder, with forward slashes. The fake save writes nothing."""
    before_repo = (ROOT / "research").exists()
    at, calls = run_save(monkeypatch, rd.analyse(etf_like()))
    save_buttons(at)[0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(calls) == 1
    reported = [s for _, s in page_items(at) if WRITTEN.name in s]
    assert reported, "the written file is not shown"
    for s in reported:
        assert "research/VT_2026-11-11_2.json" in s, s
        assert ROOT.as_posix() not in s and str(ROOT) not in s, f"absolute path shown: {s}"
        assert "\\" not in s, f"backslash in the shown path: {s}"
    assert (ROOT / "research").exists() == before_repo  # nothing created in the repo's research/


# ---------- WP-3.4 source checks ----------
def test_wp34_view_draw_signature():
    fn = next((n for n in ast.parse(view_src()).body if isinstance(n, ast.FunctionDef) and n.name == "draw"), None)
    assert fn is not None, "research_view.py has no draw()"
    assert [a.arg for a in fn.args.args] == ["r"]
    assert [a.arg for a in fn.args.kwonlyargs] == ["caption"]
    assert [d.value for d in fn.args.kw_defaults] == [None]


def test_wp34_view_computes_no_number():
    """research_view.py holds the moved drawing code: the page's no-arithmetic rules apply to it."""
    src = view_src()
    for bad in ("/ 100", "- 1", ".std(", "/ 1e6", "/1e6", "1_000_000", "1000000", ".max("):
        assert bad not in src, bad
    assert "* 100" not in src_without_pct() and "*100" not in src_without_pct()


def test_wp34_page_computes_no_number():
    """pages/research.py keeps only its own part and no arithmetic; pct moved out, so no * 100 at all."""
    src = page_src()
    for bad in ("/ 100", "* 100", "*100", "- 1", ".std(", "/ 1e6", "/1e6", "1_000_000", "1000000", ".max("):
        assert bad not in src, bad


def test_wp34_page_keeps_only_its_own_part():
    """The drawing code moved: the page imports research_view and calls draw(r); it defines none of the helpers."""
    src = page_src()
    tree = ast.parse(src)
    defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    moved = {"pct", "money", "badge", "times", "price_text", "priced", "fact", "draw_price_chart", "draw_returns",
             "draw_links", "draw_company", "draw_credit", "draw_price", "draw_valuation", "draw_dividends",
             "draw_statements"}
    assert not defined & moved, defined & moved
    assigned = {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    assert "LIGHT_CSS" not in assigned
    assert re.search(r"^\s*(import research_view|from research_view import)", src, re.M)
    assert re.search(r"\bdraw\(r\)", src)


# ---------- added by the mutation pass (WP-3.4 mutation-r1) ----------
def arithmetic_outside(src, allowed_funcs=()):
    """Arithmetic operators in src, other than string joining ("text" + x) and those inside allowed_funcs."""
    tree = ast.parse(src)
    inside = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name in allowed_funcs:
            inside |= {id(n) for n in ast.walk(fn)}

    def texty(n):
        return (isinstance(n, ast.JoinedStr) or (isinstance(n, ast.Constant) and isinstance(n.value, str))
                or (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add) and (texty(n.left) or texty(n.right))))

    bad = []
    for n in ast.walk(tree):
        if id(n) in inside:
            continue
        if isinstance(n, ast.BinOp) and not (isinstance(n.op, ast.Add) and (texty(n.left) or texty(n.right))):
            bad.append(ast.unparse(n))
        elif isinstance(n, ast.AugAssign) or (isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub)
                                              and not isinstance(n.operand, ast.Constant)):
            bad.append(ast.unparse(n))
    return bad


@pytest.mark.parametrize("rel,allowed", [("pages/research.py", ()), ("pages/library.py", ()),
                                         ("research_view.py", ("pct",))], ids=["research", "library", "view"])
def test_wp34_no_arithmetic_operator_on_figures(rel, allowed):
    """Kills LB22 / RP12 / RV12b: the pattern lists miss e.g. `r.price * 2`. No arithmetic operator at all in
    the pages, and in research_view.py only pct's `x * 100`; joining text with + is allowed."""
    bad = arithmetic_outside((ROOT / rel).read_text(encoding="utf-8"), allowed)
    assert bad == [], bad


# ---------- WP-3.8 (spec v1, rule B7): the Beta tile on both views. Made-up fixtures; rd.beta_text is reached
# inside each test, so the file still collects before the build. ----------
from test_research_data import gamuda_stock, stock_close  # noqa: E402

BETA_HELP_KLCI = "Against FBM KLCI, last 3 years. 1.00 moves in step with the market."
BETA_HELP_SPX = "Against S&P 500, last 3 years. 1.00 moves in step with the market."
BETA_HELP_NONE = "No home market index for this code."


def beta_stock():
    raw = gamuda_stock()
    raw.index_prices = pd.DataFrame({"Close": stock_close()})  # identical to the stock: beta 1.00
    return raw


def beta_etf():
    raw = etf_like()
    raw.index_prices = pd.DataFrame({"Close": raw.prices["Close"].copy()})  # identical: beta 1.00
    return raw


def beta_hk_stock():
    raw = gamuda_stock()
    raw.code = "0700.HK"  # no home market index (B1)
    raw.index_prices = pd.DataFrame()
    return raw


def beta_tile(at):
    tiles = [m for m in at.metric if m.label == "Beta"]
    assert len(tiles) == 1, [m.label for m in at.metric]
    return tiles[0]


def risk_row(at):
    """The row of columns holding the Volatility tile, as the metric labels of each column."""
    for cols in rows_of_columns(at._tree):
        labels = [[m.label for m in col.metric] for col in cols]
        if ["Volatility"] in labels:
            return labels
    raise AssertionError("no row holds the Volatility tile")


@pytest.mark.parametrize("make,help_text", [(beta_stock, BETA_HELP_KLCI), (beta_etf, BETA_HELP_SPX)],
                         ids=["stock", "etf"])
def test_wp38_beta_tile_value_and_help(monkeypatch, make, help_text):
    at = run_with(monkeypatch, lambda: rd.analyse(make()))
    assert not at.exception, [e.value for e in at.exception]
    tile = beta_tile(at)
    assert tile.value == "1.00" == rd.beta_text(1.0)
    assert tile.proto.help == help_text


@pytest.mark.parametrize("make", [beta_stock, beta_etf], ids=["stock", "etf"])
def test_wp38_beta_is_the_third_tile_after_volatility_and_drawdown(monkeypatch, make):
    at = run_with(monkeypatch, lambda: rd.analyse(make()))
    assert not at.exception, [e.value for e in at.exception]
    assert risk_row(at) == [["Volatility"], ["Max drawdown"], ["Beta"]]
    labels = [m.label for m in at.metric]
    assert labels.index("Beta") == labels.index("Max drawdown") + 1


def test_wp38_beta_tile_no_home_index(monkeypatch):
    at = run_with(monkeypatch, lambda: rd.analyse(beta_hk_stock()))
    assert not at.exception, [e.value for e in at.exception]
    tile = beta_tile(at)
    assert tile.value == "n/a"
    assert tile.proto.help == BETA_HELP_NONE


def test_wp38_beta_tile_index_without_prices_na_with_index_help(monkeypatch):
    def make():
        raw = gamuda_stock()
        raw.index_prices = pd.DataFrame()
        return raw
    at = run_with(monkeypatch, lambda: rd.analyse(make()))
    assert not at.exception, [e.value for e in at.exception]
    tile = beta_tile(at)
    assert tile.value == "n/a" and tile.proto.help == BETA_HELP_KLCI
    assert "Beta not available: no FBM KLCI prices from Yahoo." in captions(at)  # B5 line shown as a caption


@pytest.mark.parametrize("make,block", [(beta_stock, "company"), (beta_etf, "etf")], ids=["stock", "etf"])
def test_wp38_dict_without_beta_keys_draws_na(monkeypatch, make, block):
    """An old snapshot's company / etf dict has neither key: the view draws n/a and does not raise."""
    def result():
        r = rd.analyse(make())
        d = getattr(r, block)
        assert "beta_3y" in d and "beta_index" in d  # the build carries them; this old copy does not
        d.pop("beta_3y")
        d.pop("beta_index")
        return r
    at = run_with(monkeypatch, result)
    assert not at.exception, [e.value for e in at.exception]
    tile = beta_tile(at)
    assert tile.value == "n/a"
    assert tile.proto.help == BETA_HELP_NONE


def test_wp38_view_formats_beta_with_beta_text():
    src = view_src()
    assert "rd.beta_text(" in src
    assert '"Beta"' in src
