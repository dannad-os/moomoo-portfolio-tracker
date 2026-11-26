"""WP-3.4 Library page tests (spec v2, "Checks wanted": tests/test_library_page.py). Streamlit AppTest; snapshots
written with research_store.save to tmp_path, never the repo's research/. The store's list_entries is pointed at
the tmp folder; Yahoo, the research cache and the workbook raise if touched. Made-up fixtures only."""
import ast
import importlib
import re
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import portfolio_data  # noqa: E402
import research_data as rd  # noqa: E402
from test_research_data import etf_like, gamuda_stock  # noqa: E402

LIB = str(ROOT / "pages" / "library.py")
PAGE = str(ROOT / "pages" / "research.py")
REMINDER = "Notes are saved to git. Leave out amounts and holding sizes."
LIGHT_SHOWN = {"green": ("green", "\U0001F7E2", "#2e7d32"), "amber": ("amber", "\U0001F7E1", "#f9a825"),
               "red": ("red", "\U0001F534", "#c62828"), "grey": ("grey", "⚪", "#9e9e9e")}


def date_forms(d):
    """The ways a date may be shown: 2026-11-10, 10 Nov 2026, 10 November 2026."""
    return {d.isoformat(), f"{d:%d %b %Y}", f"{d.day} {d:%b %Y}", f"{d:%d %B %Y}", f"{d.day} {d:%B %Y}"}


def boom(*a, **k):
    raise AssertionError("the Library page reached Yahoo, the research cache or the workbook")


class Lib:
    """research_store pointed at tmp_path/research; network, cache and workbook blocked. The store is imported
    on first use (inside the test), so a missing module fails the test rather than erroring its setup."""

    def __init__(self, monkeypatch, tmp_path):
        self.mp, self.folder = monkeypatch, tmp_path / "research"
        self._rs = None
        monkeypatch.chdir(tmp_path)  # a relative research/ also lands in tmp_path
        for name in ("research", "fetch_raw", "fetch_fx", "load_cache", "save_cache"):
            monkeypatch.setattr(rd, name, boom)
        monkeypatch.setattr(portfolio_data, "load_workbook", boom)

    @property
    def rs(self):
        if self._rs is None:
            rs = importlib.import_module("research_store")
            self.real_list = rs.list_entries
            folder, real = self.folder, rs.list_entries
            self.mp.setattr(rs, "SNAPSHOT_DIR", folder)
            self.mp.setattr(rs, "list_entries", lambda *a, **k: real(folder))
            self._rs = rs
        return self._rs


@pytest.fixture(autouse=True, scope="module")
def no_streamlit_left_behind():
    """This file sorts before test_portfolio_data.py, whose test_t8_no_streamlit asserts streamlit is not in
    sys.modules. Streamlit (and the view and store modules that hold a reference to it) imported here are
    dropped again after this module, so that old check still sees a clean process."""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        if name.split(".")[0] in ("streamlit", "research_view", "research_store"):
            del sys.modules[name]


@pytest.fixture
def lib(monkeypatch, tmp_path):
    return Lib(monkeypatch, tmp_path)


def run_lib(lib):
    from streamlit.testing.v1 import AppTest
    lib.rs  # the store pointed at tmp_path before the page runs
    at = AppTest.from_file(LIB, default_timeout=30)
    at.run()
    return at


# ---------- reading the page ----------
def leaves(node):
    """Every element on the page in page order, blocks opened (columns, expanders included)."""
    for _, c in sorted((getattr(node, "children", None) or {}).items()):
        kids = getattr(c, "children", None)
        if kids and getattr(c, "type", None) not in ("dataframe", "table"):
            if getattr(c, "type", None) == "expander":
                yield c
            yield from leaves(c)
        else:
            yield c


def shown(at):
    """(kind, text) for every drawn thing on the page in order; widgets left out."""
    out = []
    for n in leaves(at._tree):
        t = getattr(n, "type", None)
        if t in ("markdown", "caption", "subheader", "header", "title", "text", "info", "warning", "error",
                 "success", "code", "latex"):
            out.append((t, str(n.value)))
        elif t == "metric":
            out.append((t, f"{n.label}={n.value}"))
        elif t in ("dataframe", "table"):
            out.append((t, n.value.to_csv()))
        elif t == "expander":
            out.append((t, n.label))
        elif t == "plotly_chart":
            out.append((t, ""))
    return out


def texts(at):
    return [s for _, s in shown(at)]


def table_rows(at):
    """Each row of every table on the page as one text: st.dataframe / st.table rows, and markdown table lines."""
    rows = []
    for n in leaves(at._tree):
        t = getattr(n, "type", None)
        if t in ("dataframe", "table"):
            df = n.value
            rows += [" | ".join(str(v) for v in row) for row in df.astype(str).itertuples(index=False)]
        elif t == "markdown":
            rows += [ln for ln in str(n.value).splitlines() if ln.strip()]
    return rows


def pick(at, lib, path, code, saved_on):
    """Pick the row for `path` with whatever widget the page offers (selectbox, radio, pills / segmented
    control, or a button per row). The option is found by its shown text: the file name, or code and date."""
    def matches(text):
        text = str(text)
        return (path.name in text or path.stem in text
                or (code in text and any(d in text for d in date_forms(saved_on))))

    entry = next((e for e in lib.real_list(lib.folder) if e.path.name == path.name), None)
    candidates = lambda opt, i: [opt, i, path, str(path), path.name, path.stem, Path("research") / path.name,
                                 str(Path("research") / path.name), entry, getattr(entry, "path", None)]
    for kind in ("selectbox", "radio", "button_group"):
        for w in at.get(kind):
            opts = list(w.options)
            hits = [i for i, o in enumerate(opts) if matches(o)]
            if len(hits) != 1:
                continue
            i = hits[0]
            for c in candidates(opts[i], i):
                try:
                    w.set_value(c)
                    ok = (w.indices == [i]) if kind == "button_group" else (w.index == i)
                except Exception:
                    ok = False
                if ok:
                    at.run()
                    return at
    for b in at.button:
        if matches(b.label):
            b.click().run()
            return at
    raise AssertionError("no widget found to pick the snapshot row " + path.name)


# ---------- made-up snapshots ----------
OLD_DAY, NEW_DAY = date(2026, 11, 1), date(2026, 11, 10)
OLD_NOTE = "Older stock note\nsecond line of the stock note"
NEW_NOTE = "Newer ETF note"


def stock_r():
    return rd.analyse(gamuda_stock())


def etf_r():
    return rd.analyse(etf_like())


def two(lib):
    old = lib.rs.save(stock_r(), OLD_NOTE, saved_on=OLD_DAY, folder=lib.folder)
    new = lib.rs.save(etf_r(), NEW_NOTE, saved_on=NEW_DAY, folder=lib.folder)
    return old, new


# ---------- no snapshots ----------
@pytest.mark.parametrize("make_folder", [False, True], ids=["no_folder", "empty_folder"])
def test_no_snapshots_line(lib, make_folder):
    if make_folder:
        lib.folder.mkdir()
    at = run_lib(lib)
    assert not at.exception, [e.value for e in at.exception]
    assert any("No snapshots yet" in t for t in texts(at)), texts(at)
    assert not at.error


# ---------- the table ----------
def row_index(rows, code, day):
    hits = [i for i, row in enumerate(rows) if code in row and any(d in row for d in date_forms(day))]
    assert hits, f"no table row with {code} and {day}: {rows}"
    return hits[0]


def test_two_snapshots_rows_in_order_with_fields(lib):
    old, new = two(lib)
    at = run_lib(lib)
    assert not at.exception, [e.value for e in at.exception]
    rows = table_rows(at)
    i_new, i_old = row_index(rows, "VT", NEW_DAY), row_index(rows, "5398.KL", OLD_DAY)
    assert i_new < i_old, "newest first"
    new_row, old_row = rows[i_new], rows[i_old]
    assert "Fake World ETF" in new_row and "Gamuda-like Bhd" in old_row  # name
    assert any(s in new_row for s in LIGHT_SHOWN["green"]), new_row  # overall light: green for the fake ETF
    assert any(s in old_row for s in LIGHT_SHOWN["amber"]), old_row  # amber for the fake stock
    assert "Newer ETF note" in new_row
    assert "Older stock note" in old_row and "second line" not in old_row  # first line of the note only


# ---------- reopening ----------
def reopened(lib, make=stock_r, note=OLD_NOTE, day=OLD_DAY, stale=False):
    path = lib.rs.save(make(), note, saved_on=day, stale=stale, folder=lib.folder)
    at = run_lib(lib)
    assert not at.exception, [e.value for e in at.exception]
    pick(at, lib, path, make().code, day)
    assert not at.exception, [e.value for e in at.exception]
    return at


def banner_texts(at, day):
    return [t for t in texts(at) if "Snapshot saved on" in t and any(d in t for d in date_forms(day))]


def test_pick_draws_research_layout_with_banner_and_note(lib):
    at = reopened(lib)
    heads = [s.value for s in at.subheader]
    assert "Gamuda-like Bhd" in heads and "Credit health" in heads and "Company" in heads  # the Research layout
    assert banner_texts(at, OLD_DAY), texts(at)
    items = shown(at)
    header_at = items.index(("subheader", "Gamuda-like Bhd"))
    before = " ".join(s for _, s in items[:header_at])
    for line in OLD_NOTE.splitlines():
        assert line in before, f"note line {line!r} not shown above the figures"


def test_reopened_view_has_no_code_box_refresh_save_or_cache_wording(lib):
    at = reopened(lib)
    assert len(at.text_input) == 0, "a code box on the reopened view"
    assert len(at.text_area) == 0, "a notes box on the reopened view"
    labels = [b.label for b in at.button]
    assert "Refresh from Yahoo" not in labels
    assert not [lb for lb in labels if "Save" in lb], labels
    for t in texts(at):
        assert "saved copies are reused for an hour" not in t, t
        assert "cached one hour" not in t, t
        assert REMINDER not in t, t


def test_stale_snapshot_shows_the_stale_wording(lib):
    at = reopened(lib, make=lambda: rd.analyse(etf_like(), stale=True), note="", day=NEW_DAY, stale=True)
    assert banner_texts(at, NEW_DAY), texts(at)
    assert any("from an older cached copy" in t for t in texts(at)), texts(at)


def test_fresh_snapshot_has_no_stale_wording(lib):
    at = reopened(lib)
    assert not any("from an older cached copy" in t for t in texts(at))


# ---------- a broken file ----------
def test_broken_file_cannot_be_read_and_page_does_not_raise(lib):
    old, new = two(lib)
    (lib.folder / "BROKEN_2026-11-05.json").write_text('{"format": 1, "note": ', encoding="utf-8")
    (lib.folder / "FUTURE_2026-11-06.json").write_text('{"format": 2}', encoding="utf-8")
    at = run_lib(lib)
    assert not at.exception, [e.value for e in at.exception]
    every = table_rows(at) + texts(at)
    for name in ("BROKEN_2026-11-05.json", "FUTURE_2026-11-06.json"):
        assert any(name in t and "cannot be read" in t for t in every), f"{name} not listed as cannot be read"
    rows = table_rows(at)
    row_index(rows, "VT", NEW_DAY)  # the other rows still show
    row_index(rows, "5398.KL", OLD_DAY)


# ---------- the reopened text equals the Research page's ----------
def research_page_items(monkeypatch, r):
    """What pages/research.py draws for r, from its header onward, the Save block's reminder left out."""
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(rd, "research", lambda code, **kw: r)
    monkeypatch.setattr(portfolio_data, "load_workbook",
                        lambda *a, **k: SimpleNamespace(holdings=pd.DataFrame({"Code": ["US.VT"]})))
    at = AppTest.from_file(PAGE, default_timeout=30)
    at.run()
    at.text_input(key="code").input(r.code).run()
    assert not at.exception, [e.value for e in at.exception]
    items = shown(at)
    # the Save block (reminder line, any "snapshot" wording) is the Research page's own part
    return [x for x in items[items.index(("subheader", r.name)):]
            if REMINDER not in x[1] and "snapshot" not in x[1].lower()]


@pytest.mark.parametrize("make", [stock_r, etf_r], ids=["stock", "etf"])
def test_reopened_text_equals_research_page(monkeypatch, lib, make):
    r = make()
    want = research_page_items(monkeypatch, r)
    monkeypatch.setattr(rd, "research", boom)
    monkeypatch.setattr(portfolio_data, "load_workbook", boom)
    at = reopened(lib, make=make, note="A note", day=NEW_DAY)
    items = shown(at)
    got = items[items.index(("subheader", r.name)):]
    k = next(i for i, (t, s) in enumerate(want) if t == "caption" and s.startswith("Data as of "))
    without = want[:k] + want[k + 1:]
    # draw(r, caption=...): the "Data as of" line is replaced by the Library's caption, or left out
    replaced = len(got) >= len(want) and got[:k] == want[:k] and got[k + 1:len(want)] == want[k + 1:]
    dropped = got[:len(without)] == without
    assert replaced or dropped, "\n".join(f"{a!r}  |  {b!r}" for a, b in zip(got, want) if a != b)


# ---------- app and source ----------
def test_app_registers_library_after_research():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'st.Page("pages/library.py", title="Library")' in src
    assert src.index("pages/research.py") < src.index("pages/library.py")


def lib_src():
    return (ROOT / "pages" / "library.py").read_text(encoding="utf-8")


def test_library_page_uses_the_store_and_the_view():
    src = lib_src()
    assert re.search(r"^\s*(import research_store|from research_store import)", src, re.M)
    assert re.search(r"^\s*(import research_view|from research_view import)", src, re.M)
    for name in ("list_entries", "load", "draw"):
        assert re.search(rf"\b{name}\(", src), name
    assert "caption=" in src


def test_library_page_computes_no_number():
    """The pattern of test_p1 / test_p6: no arithmetic on figures in the page."""
    src = lib_src()
    for bad in ("/ 100", "* 100", "*100", "- 1", ".std(", "/ 1e6", "/1e6", "1_000_000", "1000000", ".max(",
                ".sum(", ".mean("):
        assert bad not in src, bad
    ast.parse(src)  # the page is valid Python


# ---------- added by the mutation pass (WP-3.4 mutation-r1) ----------
def cells(row):
    return [c.strip() for c in row.strip().strip("|").split("|")]


def test_table_date_and_code_in_their_own_cells(lib):
    """Kills LB03 / LB04: the file name holds the code and the date, so a table without its Date or Code
    column still passed the row check. Each row must show the date and the code as cells of their own."""
    two(lib)
    at = run_lib(lib)
    rows = table_rows(at)
    for code, day in (("VT", NEW_DAY), ("5398.KL", OLD_DAY)):
        cs = cells(rows[row_index(rows, code, day)])
        assert code in cs, f"no Code cell {code!r}: {cs}"
        assert date_forms(day) & set(cs), f"no date cell for {day}: {cs}"


# ---------- v3 (supervisor rulings on review-r1, 2026-11-11) ----------
REPO_RESEARCH = ROOT / "research"


def repo_research_state():
    if not REPO_RESEARCH.exists():
        return None
    return sorted((p.relative_to(REPO_RESEARCH).as_posix(), p.read_bytes() if p.is_file() else b"")
                  for p in REPO_RESEARCH.rglob("*"))


@pytest.fixture(autouse=True)
def repo_research_untouched():
    """v3 guard: no Library test writes to (or creates) the repo's own research/ folder."""
    before = repo_research_state()
    yield
    assert repo_research_state() == before, "a test wrote to the repo's research/ folder"


def odd_file(lib, name, change, make=stock_r, day=date(2026, 11, 7)):
    """A snapshot document of make(), changed by change(doc["research"]), written as lib.folder/name."""
    import json
    doc = json.loads(json.dumps(lib.rs.to_doc(make(), "Odd note", day)))
    change(doc["research"])
    path = lib.folder / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def blue_light(res):
    res["lights"]["Debt / Equity"] = {"$light": ["blue", "a colour this version does not know"]}


def no_price_chart(res):
    del res["company"]["price_chart"]


@pytest.mark.parametrize("change", [blue_light, no_price_chart], ids=["unknown_colour", "nested_key_removed"])
def test_v3_snapshot_that_loads_but_cannot_be_drawn(lib, change):
    """v3.2: picking it shows a plain error naming the file and 'cannot be drawn'; no exception; the list stays
    usable and another snapshot still reopens."""
    old, new = two(lib)
    odd = odd_file(lib, "ODD_2026-11-07.json", change)
    lib.rs.load(odd)  # the file loads: only drawing fails
    at = run_lib(lib)
    assert not at.exception, [e.value for e in at.exception]
    pick(at, lib, odd, "5398.KL", date(2026, 11, 7))
    assert not at.exception, [e.value for e in at.exception]
    errors = [str(e.value) for e in at.error]
    assert any(odd.name in t and "cannot be drawn" in t for t in errors), errors
    rows = table_rows(at)
    row_index(rows, "VT", NEW_DAY)  # the table still shows the others
    row_index(rows, "5398.KL", OLD_DAY)
    pick(at, lib, new, "VT", NEW_DAY)  # and another snapshot still reopens
    assert not at.exception, [e.value for e in at.exception]
    assert banner_texts(at, NEW_DAY), texts(at)


def test_v3_overall_null_is_cannot_be_read_and_table_still_shows(lib):
    """v3.2: from_doc rejects an overall that is not a Light, so the file is a 'cannot be read' row, not a crash."""
    old, new = two(lib)
    odd_file(lib, "NULL_2026-11-07.json", lambda res: res.__setitem__("overall", None))
    at = run_lib(lib)
    assert not at.exception, [e.value for e in at.exception]
    every = table_rows(at) + texts(at)
    assert any("NULL_2026-11-07.json" in t and "cannot be read" in t for t in every), every
    rows = table_rows(at)
    row_index(rows, "VT", NEW_DAY)
    row_index(rows, "5398.KL", OLD_DAY)



# ---------- WP-3.4.1 "Compare with today" (spec v1, 2026-11-16) ----------
from datetime import datetime  # noqa: E402

COMPARE = "Compare with today"
TODAY_AT = datetime(2026, 11, 16, 10, 30)
COMPARE_COLS = ["Section", "Figure", "Saved (2026-10-31)", "Today (2026-11-16)", "Change", "Note"]
KINDS_NOTE = "The saved copy and today's result are different kinds (stock / ETF); nothing to compare."


def fresh_stock_r():
    """Today's made-up result for 5398.KL: the saved fixture fetched later, price 5.0 -> 5.4 (+8.0%)."""
    r = stock_r()
    r.fetched_at, r.price = TODAY_AT, 5.4
    r.valuation["price"] = 5.4
    return r


def fresh_etf_r():
    r = etf_r()
    r.fetched_at, r.price = TODAY_AT, 189.0  # 175.0 -> 189.0: +8.0%
    return r


class FakeResearch:
    """Stands in for rd.research on a click: records each call, returns today's made-up result or raises."""

    def __init__(self, results=None, error=None):
        self.calls, self.results, self.error = [], results or {}, error

    def __call__(self, code, *args, **kwargs):
        self.calls.append((code, args, kwargs))
        if self.error is not None:
            raise self.error
        return self.results[code]


def fake_research(monkeypatch, **kw):
    fake = FakeResearch(**kw)
    monkeypatch.setattr(rd, "research", fake)
    return fake


def shown_and_buttons(at):
    """shown(at) with buttons kept, as ("button", label), in page order."""
    out = []
    for n in leaves(at._tree):
        t = getattr(n, "type", None)
        if t == "button":
            out.append(("button", n.label))
        elif t in ("subheader", "caption", "info", "text", "warning", "markdown"):
            out.append((t, str(n.value)))
        elif t in ("dataframe", "table"):
            out.append((t, n.value.to_csv()))
    return out


def compare_tables(at):
    return [d.value for d in at.dataframe if "Change" in [str(c) for c in d.value.columns]]


def click_compare(at):
    hits = [b for b in at.button if b.label == COMPARE]
    assert len(hits) == 1, f"want one {COMPARE!r} button, got labels {[b.label for b in at.button]}"
    hits[0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def saved_view(at, r):
    items = shown(at)
    return items[items.index(("subheader", r.name)):]


def test_wp341_reopened_snapshot_has_one_compare_button(lib):
    at = reopened(lib)
    assert [b.label for b in at.button] == [COMPARE]


def test_wp341_button_after_banner_and_note_before_saved_view(lib):
    at = reopened(lib)
    items = shown_and_buttons(at)
    banner = next(i for i, (t, s) in enumerate(items) if t == "info" and "Snapshot saved on" in s)
    note = max(i for i, (t, s) in enumerate(items) if OLD_NOTE.splitlines()[-1] in s)
    header = items.index(("subheader", "Gamuda-like Bhd"))
    assert ("button", COMPARE) in items, items[:header + 1]
    button = items.index(("button", COMPARE))
    assert banner < note < button < header, items[:header + 1]


def test_wp341_no_fetch_and_no_table_before_a_click(monkeypatch, lib):
    """Pin: opening the Library and a snapshot fetches nothing (the cache readers stay blocked by Lib)."""
    fake = fake_research(monkeypatch, results={"5398.KL": fresh_stock_r()})
    at = reopened(lib)
    assert fake.calls == []
    assert compare_tables(at) == []
    assert not [t for t in texts(at) if "What moved" in t]


def test_wp341_click_fetches_the_snapshot_code_with_default_arguments(monkeypatch, lib):
    fake = fake_research(monkeypatch, results={"5398.KL": fresh_stock_r()})
    at = reopened(lib)
    click_compare(at)
    assert len(fake.calls) == 1, fake.calls
    code, args, kwargs = fake.calls[0]
    assert code == "5398.KL"
    assert args == () and kwargs == {}, f"research called with more than the code: {args} {kwargs}"


def test_wp341_click_draws_what_moved_heading_caption_and_table(monkeypatch, lib):
    fake_research(monkeypatch, results={"5398.KL": fresh_stock_r()})
    at = click_compare(reopened(lib))
    assert "What moved" in [s.value for s in at.subheader]
    assert "Saved figures from 2026-10-31 beside today's from 2026-11-16." in [c.value for c in at.caption]
    tables = compare_tables(at)
    assert len(tables) == 1, tables
    t = tables[0]
    assert [str(c) for c in t.columns] == COMPARE_COLS
    rows = [list(map(str, x)) for x in t.astype(str).itertuples(index=False)]
    assert ["Price and size", "Price", "5.00 MYR", "5.40 MYR", "▲ +8.0%", ""] in rows, rows


def test_wp341_table_between_button_and_saved_view(monkeypatch, lib):
    fake_research(monkeypatch, results={"5398.KL": fresh_stock_r()})
    at = click_compare(reopened(lib))
    items = shown_and_buttons(at)
    button = items.index(("button", COMPARE))
    heading = items.index(("subheader", "What moved"))
    table = next(i for i, (t, s) in enumerate(items) if t == "dataframe" and "Change" in s.splitlines()[0])
    header = items.index(("subheader", "Gamuda-like Bhd"))
    assert button < heading < table < header, items[:header + 1]


def test_wp341_click_calls_compare_with_saved_then_fresh(monkeypatch, lib):
    real = getattr(rd, "compare", None)
    assert real is not None, "research_data has no compare()"
    fresh = fresh_stock_r()
    fake_research(monkeypatch, results={"5398.KL": fresh})
    seen = []
    monkeypatch.setattr(rd, "compare", lambda saved, today: seen.append((saved, today)) or real(saved, today))
    click_compare(reopened(lib))
    assert len(seen) == 1, seen
    saved, today = seen[0]
    assert today is fresh
    assert saved.code == "5398.KL" and saved.fetched_at == stock_r().fetched_at and saved.price == 5.0


@pytest.mark.parametrize("make,fresh", [(stock_r, fresh_stock_r), (etf_r, fresh_etf_r)], ids=["stock", "etf"])
def test_wp341_saved_view_unchanged_by_a_click(monkeypatch, lib, make, fresh):
    r = make()
    fake_research(monkeypatch, results={r.code: fresh()})
    at = reopened(lib, make=make, note="A note", day=NEW_DAY)
    before = saved_view(at, r)
    click_compare(at)
    assert compare_tables(at), "no comparison table after the click"
    assert saved_view(at, r) == before


def test_wp341_research_error_warns_and_keeps_saved_view(monkeypatch, lib):
    fake_research(monkeypatch, error=rd.ResearchError("Yahoo has no data for 5398.KL"))
    at = reopened(lib)
    before = saved_view(at, stock_r())
    click_compare(at)
    assert [w.value for w in at.warning] == [
        "Today's figures could not be fetched: Yahoo has no data for 5398.KL. The saved view below is unchanged."]
    assert compare_tables(at) == []
    assert saved_view(at, stock_r()) == before


def test_wp341_result_stays_across_reruns(monkeypatch, lib):
    fake_research(monkeypatch, results={"5398.KL": fresh_stock_r()})
    at = click_compare(reopened(lib))
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(compare_tables(at)) == 1
    assert "What moved" in [s.value for s in at.subheader]


def test_wp341_other_snapshot_shows_no_table_until_its_own_click(monkeypatch, lib):
    old, new = two(lib)
    fake_research(monkeypatch, results={"5398.KL": fresh_stock_r(), "VT": fresh_etf_r()})
    at = run_lib(lib)
    pick(at, lib, old, "5398.KL", OLD_DAY)
    click_compare(at)
    assert len(compare_tables(at)) == 1
    pick(at, lib, new, "VT", NEW_DAY)
    assert not at.exception, [e.value for e in at.exception]
    assert compare_tables(at) == [], "the stock's comparison is still shown on the ETF snapshot"
    assert "What moved" not in [s.value for s in at.subheader]
    click_compare(at)
    tables = compare_tables(at)
    assert len(tables) == 1
    figures = list(tables[0]["Figure"].astype(str))
    assert "Fund size" in figures and "Market cap" not in figures, figures


def test_wp341_click_writes_no_file(monkeypatch, lib, tmp_path):
    fake_research(monkeypatch, results={"5398.KL": fresh_stock_r()})
    at = reopened(lib)

    def state():
        return sorted((p.relative_to(tmp_path).as_posix(), p.read_bytes() if p.is_file() else b"")
                      for p in tmp_path.rglob("*"))

    before = state()
    click_compare(at)
    assert compare_tables(at)
    assert state() == before


def test_wp341_after_click_still_no_code_box_refresh_or_save(monkeypatch, lib):
    fake_research(monkeypatch, results={"5398.KL": fresh_stock_r()})
    at = click_compare(reopened(lib))
    assert compare_tables(at)
    assert len(at.text_input) == 0 and len(at.text_area) == 0
    assert [b.label for b in at.button] == [COMPARE]
    for t in texts(at):
        assert "saved copies are reused for an hour" not in t, t


def test_wp341_stale_today_note_shown(monkeypatch, lib):
    fresh = fresh_stock_r()
    fresh.stale, fresh.fetched_at = True, datetime(2026, 11, 15, 8, 5)
    fake_research(monkeypatch, results={"5398.KL": fresh})
    at = click_compare(reopened(lib))
    assert ("Yahoo could not be reached; the Today column shows figures fetched 2026-11-15 08:05."
            in [c.value for c in at.caption])


def test_wp341_kind_mismatch_note_and_no_table(monkeypatch, lib):
    fake_research(monkeypatch, results={"5398.KL": fresh_etf_r()})
    at = click_compare(reopened(lib))
    assert "What moved" in [s.value for s in at.subheader]
    assert KINDS_NOTE in [c.value for c in at.caption]
    assert compare_tables(at) == []


def test_wp341_library_source_fetches_compares_and_draws():
    src = lib_src()
    for call in ("research", "compare", "draw_compare"):
        assert re.search(rf"\b{call}\(", src), call
    # Round 2 (review-r1 note, ruled): narrowed from the word "force" anywhere to a force= keyword in any call.
    forced = [ast.unparse(n) for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
              and any(k.arg == "force" for k in n.keywords)]
    assert forced == [], forced
    assert "ResearchError" in src


def test_wp341_store_source_knows_nothing_of_compare():
    """Pin: research_store stays a store; no fetch, no comparison, no view in it."""
    # Round 2 (review-r1 note, ruled): narrowed from words anywhere (docstrings and comments included) to call
    # names and imports.
    tree = ast.parse((ROOT / "research_store.py").read_text(encoding="utf-8"))
    banned = {"compare", "Comparison", "Moved", "research", "fetch_raw", "load_cache", "save_cache", "draw_compare"}

    def name_of(f):
        return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None

    calls = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call) and name_of(n.func) in banned]
    assert calls == [], calls
    imported = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names] + \
               [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + \
               [a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names]
    assert not [m for m in imported if "research_view" in m or m in banned], imported


# ---------- research_view.draw_compare (spec "View") ----------
class FakeSt:
    """Records every st.<name>(...) call draw_compare makes, in order."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return record


def moved(section, figure, saved, today, change, note=""):
    return SimpleNamespace(section=section, figure=figure, saved=saved, today=today, change=change, note=note)


def comparison(rows, notes=()):
    return SimpleNamespace(code="5398.KL", saved_on=date(2026, 10, 31), today_on=date(2026, 11, 16),
                           rows=list(rows), notes=list(notes))


ROWS = [moved("Price and size", "Price", "5.00 MYR", "5.40 MYR", "▲ +8.0%"),
        moved("Credit health", "Debt / Equity", "0.60", "0.85", "▲ +0.25", "saved: 2026-07-31, today: TTM"),
        moved("Lights", "Overall", "amber", "green", "amber → green", "worst: made-up reason")]


def draw_compare_calls(monkeypatch, c):
    import research_view
    fake = FakeSt()
    monkeypatch.setattr(research_view, "st", fake)
    research_view.draw_compare(c)
    return fake.calls


def test_wp341_draw_compare_heading_caption_notes_then_table(monkeypatch):
    calls = draw_compare_calls(monkeypatch, comparison(ROWS, ["First note.", "Second note."]))
    assert [(n, a[0] if a else None) for n, a, _ in calls[:4]] == [
        ("subheader", "What moved"), ("caption", "Saved figures from 2026-10-31 beside today's from 2026-11-16."),
        ("caption", "First note."), ("caption", "Second note.")]
    assert [n for n, _, _ in calls] == ["subheader", "caption", "caption", "caption", "dataframe"], calls


def test_wp341_draw_compare_table_columns_and_cells(monkeypatch):
    calls = draw_compare_calls(monkeypatch, comparison(ROWS))
    tables = [(a, k) for n, a, k in calls if n == "dataframe"]
    assert len(tables) == 1, calls
    (df, *_), kwargs = tables[0]
    assert isinstance(df, pd.DataFrame), f"not a plain table (styled?): {type(df)}"
    assert kwargs.get("hide_index") is True
    assert "column_config" not in kwargs
    assert [str(c) for c in df.columns] == COMPARE_COLS
    assert [list(map(str, x)) for x in df.itertuples(index=False)] == [
        [m.section, m.figure, m.saved, m.today, m.change, m.note] for m in ROWS]


def test_wp341_draw_compare_empty_rows_heading_and_notes_only(monkeypatch):
    calls = draw_compare_calls(monkeypatch, comparison([], [KINDS_NOTE]))
    assert [(n, a[0] if a else None) for n, a, _ in calls] == [("subheader", "What moved"), ("caption", KINDS_NOTE)]


def draw_compare_node():
    tree = ast.parse((ROOT / "research_view.py").read_text(encoding="utf-8"))
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "draw_compare"), None)
    assert fn is not None, "research_view.py has no draw_compare()"
    return fn


def test_wp341_draw_compare_takes_one_comparison():
    fn = draw_compare_node()
    assert len(fn.args.args) == 1 and not fn.args.kwonlyargs and not fn.args.vararg


def test_wp341_draw_compare_prints_texts_only():
    """No arithmetic, no ordering comparison, no number format spec and no formatter call inside draw_compare."""
    fn = draw_compare_node()
    bad = []
    formatters = {"pct", "times", "price_text", "priced", "money", "short_money", "fmt", "round", "float", "int",
                  "abs", "format"}
    for n in ast.walk(fn):
        if isinstance(n, ast.BinOp) and not isinstance(n.op, ast.Add):
            bad.append(ast.unparse(n))
        elif isinstance(n, ast.Compare) and any(isinstance(o, (ast.Lt, ast.Gt, ast.LtE, ast.GtE)) for o in n.ops):
            bad.append(ast.unparse(n))
        elif isinstance(n, ast.FormattedValue) and n.format_spec is not None:
            bad.append(ast.unparse(n))
        elif isinstance(n, ast.Call):
            name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
            if name in formatters:
                bad.append(ast.unparse(n))
        elif isinstance(n, ast.AugAssign) or (isinstance(n, ast.UnaryOp) and not isinstance(n.op, ast.Not)):
            bad.append(ast.unparse(n))
    assert bad == [], bad



# ---------- round 1b: v2 rulings (2026-11-16) ----------
def test_v2_switching_back_shows_no_table_until_clicked_again(monkeypatch, lib):
    """v2.8: no remembered results. Compare A, open B, open A again: no table until A's button is clicked."""
    old, new = two(lib)
    fake = fake_research(monkeypatch, results={"5398.KL": fresh_stock_r(), "VT": fresh_etf_r()})
    at = run_lib(lib)
    pick(at, lib, old, "5398.KL", OLD_DAY)
    click_compare(at)
    assert len(compare_tables(at)) == 1
    pick(at, lib, new, "VT", NEW_DAY)
    assert compare_tables(at) == []
    pick(at, lib, old, "5398.KL", OLD_DAY)
    assert not at.exception, [e.value for e in at.exception]
    assert compare_tables(at) == [], "the earlier comparison came back without a click"
    assert "What moved" not in [s.value for s in at.subheader]
    assert len(fake.calls) == 1, fake.calls
    click_compare(at)
    assert len(compare_tables(at)) == 1


# v2.1: one formatter serves the layout and compare
NAN_ = float("nan")
FORMAT_CASES = {
    "pct": [((None,), {}), ((NAN_,), {}), ((0.1234,), {}), ((-0.221,), {}), ((0.0007,), {"places": 2}),
            ((0.123,), {"sign": True}), ((0.0,), {"places": 0}), ((None,), {"blank": ""})],
    "times": [((None,), {}), ((NAN_,), {}), ((12.04,), {}), ((9.8, "x"), {})],
    "price_text": [((None,), {}), ((NAN_,), {}), ((0.285,), {}), ((4.92,), {}), ((1234.5,), {}), ((1.0,), {})],
    "priced": [((None, "MYR"), {}), ((5.0, "MYR"), {}), ((0.285, "MYR"), {}), ((175.0, "USD"), {}),
               ((5.0, None), {})],
}


@pytest.mark.parametrize("name", list(FORMAT_CASES))
def test_v2_view_formatter_gives_the_data_layer_text(name):
    import research_view
    data_fn = getattr(rd, name, None)
    assert data_fn is not None, f"research_data has no {name}()"
    for args, kwargs in FORMAT_CASES[name]:
        assert getattr(research_view, name)(*args, **kwargs) == data_fn(*args, **kwargs), (name, args, kwargs)


@pytest.mark.parametrize("name", list(FORMAT_CASES))
def test_v2_view_formatter_is_a_wrapper_calling_the_data_layer(name):
    """research_view keeps the name as a thin wrapper that calls rd.<name>, as money calls rd.short_money."""
    tree = ast.parse((ROOT / "research_view.py").read_text(encoding="utf-8"))
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name), None)
    assert fn is not None, f"research_view.py lost {name}()"
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == name and isinstance(n.func.value, ast.Name) and n.func.value.id == "rd"]
    assert calls, f"research_view.{name} does not call rd.{name}"


# ---------- round 2: v3 rulings (2026-11-16) ----------
COMPARE_FAILED = "Today's figures could not be compared: {}. The saved view below is unchanged."


def assert_click_failed_cleanly(at, before, text):
    assert not at.exception, [e.value for e in at.exception]
    assert [w.value for w in at.warning] == [COMPARE_FAILED.format(text)]
    assert compare_tables(at) == []
    assert "What moved" not in [s.value for s in at.subheader]
    assert saved_view(at, stock_r()) == before


def click_raw(at):
    hits = [b for b in at.button if b.label == COMPARE]
    assert len(hits) == 1, [b.label for b in at.button]
    hits[0].click().run()
    return at


# v3.3: any other exception from the fetch or from compare: its own warning, no table, saved view drawn.
def test_v3_fetch_oserror_warns_compared_and_keeps_saved_view(monkeypatch, lib):
    fake_research(monkeypatch, error=OSError("cache file locked"))
    at = reopened(lib)
    before = saved_view(at, stock_r())
    assert_click_failed_cleanly(click_raw(at), before, "cache file locked")


def test_v3_compare_raising_warns_compared_and_keeps_saved_view(monkeypatch, lib):
    fake_research(monkeypatch, results={"5398.KL": fresh_stock_r()})

    def broken(saved, fresh):
        raise ValueError("odd data in the ratios")

    monkeypatch.setattr(rd, "compare", broken)
    at = reopened(lib)
    before = saved_view(at, stock_r())
    assert_click_failed_cleanly(click_raw(at), before, "odd data in the ratios")


def test_v3_failed_compare_warning_stays_on_rerun(monkeypatch, lib):
    fake_research(monkeypatch, error=OSError("cache file locked"))
    at = reopened(lib)
    before = saved_view(at, stock_r())
    click_raw(at).run()
    assert_click_failed_cleanly(at, before, "cache file locked")


# v3.4: the fetch runs inside st.spinner("Fetching today's figures...").
def test_v3_fetch_runs_inside_the_spinner(monkeypatch, lib):
    import contextlib
    import streamlit

    depth = []

    @contextlib.contextmanager
    def spinner(text="", *a, **k):
        depth.append(text)
        try:
            yield
        finally:
            depth.pop()

    fresh, inside = fresh_stock_r(), []

    def research(code, *a, **k):
        inside.append(list(depth))
        return fresh

    monkeypatch.setattr(rd, "research", research)
    at = reopened(lib)
    monkeypatch.setattr(streamlit, "spinner", spinner)
    click_compare(at)
    assert inside == [["Fetching today's figures..."]], inside
    assert compare_tables(at)


# ---------- round 3: v4 rulings (2026-11-16) ----------
# v4.4: a generic click error with an empty message shows its type name in place of the empty text.
@pytest.mark.parametrize("error,name", [(AssertionError(), "AssertionError"), (Exception(), "Exception")],
                         ids=["AssertionError", "Exception"])
def test_v4_empty_error_message_shows_the_type_name(monkeypatch, lib, error, name):
    fake_research(monkeypatch, error=error)
    at = reopened(lib)
    before = saved_view(at, stock_r())
    assert_click_failed_cleanly(click_raw(at), before, name)


def test_v4_empty_message_from_compare_shows_the_type_name(monkeypatch, lib):
    fake_research(monkeypatch, results={"5398.KL": fresh_stock_r()})

    def broken(saved, fresh):
        raise ValueError()

    monkeypatch.setattr(rd, "compare", broken)
    at = reopened(lib)
    before = saved_view(at, stock_r())
    assert_click_failed_cleanly(click_raw(at), before, "ValueError")


# ---------- WP-3.8 (spec v1, rule B8): Beta in snapshots and in the Library. Made-up fixtures only. ----------
from test_research_data import stock_close  # noqa: E402


def beta_stock_r():
    raw = gamuda_stock()
    raw.index_prices = pd.DataFrame({"Close": stock_close()})  # identical to the stock: beta 1.00
    return rd.analyse(raw)


def beta_etf_r():
    raw = etf_like()
    raw.index_prices = pd.DataFrame({"Close": raw.prices["Close"].copy()})
    return rd.analyse(raw)


def drop_beta_keys(block):
    def change(res):
        assert "beta_3y" in res[block] and "beta_index" in res[block]  # the build saves them
        del res[block]["beta_3y"], res[block]["beta_index"]  # a snapshot saved before WP-3.8
    return change


def beta_metric(at):
    tiles = [m for m in at.metric if m.label == "Beta"]
    assert len(tiles) == 1, [m.label for m in at.metric]
    return tiles[0]


@pytest.mark.parametrize("make,block,name", [(beta_stock_r, "company", "FBM KLCI"), (beta_etf_r, "etf", "S&P 500")],
                         ids=["stock", "etf"])
def test_wp38_new_save_carries_beta_keys_format_1(lib, make, block, name):
    r = make()
    doc = lib.rs.to_doc(r, "note", date(2026, 11, 23))
    assert doc["format"] == 1
    assert doc["research"][block]["beta_3y"] == pytest.approx(1.0, abs=1e-9)
    assert doc["research"][block]["beta_index"] == name
    path = lib.rs.save(r, "note", saved_on=date(2026, 11, 23), folder=lib.folder)
    back = getattr(lib.rs.load(path).research, block)
    assert back["beta_3y"] == pytest.approx(1.0, abs=1e-9) and back["beta_index"] == name


@pytest.mark.parametrize("make,block,code", [(beta_stock_r, "company", "5398.KL"), (beta_etf_r, "etf", "VT")],
                         ids=["stock", "etf"])
def test_wp38_reopened_snapshot_shows_beta(lib, make, block, code):
    at = reopened(lib, make=make)
    assert beta_metric(at).value == "1.00"


@pytest.mark.parametrize("make,block,code", [(beta_stock_r, "company", "5398.KL"), (beta_etf_r, "etf", "VT")],
                         ids=["stock", "etf"])
def test_wp38_old_snapshot_without_beta_reopens_with_na(lib, make, block, code):
    day = date(2026, 11, 7)
    lib.folder.mkdir(parents=True, exist_ok=True)  # setup only: odd_file writes straight into the folder
    odd = odd_file(lib, f"{code}_2026-11-07.json", drop_beta_keys(block), make=make, day=day)
    lib.rs.load(odd)
    at = run_lib(lib)
    assert not at.exception, [e.value for e in at.exception]
    pick(at, lib, odd, code, day)
    assert not at.exception, [e.value for e in at.exception]
    assert not [e.value for e in at.error if "cannot be drawn" in str(e.value)], [e.value for e in at.error]
    assert beta_metric(at).value == "n/a"
