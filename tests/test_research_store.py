"""WP-3.4 snapshot store tests (spec v2, "Checks wanted": tests/test_research_store.py). Fakes only: the made-up
stock and ETF fixtures of test_research_data, no network, no workbook. Snapshot files go to tmp_path only.
research_store is imported inside each test (via store()), so a missing module fails each test on its own."""
import dataclasses
import importlib
import json
import math
import os
import shutil
import socket
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import research_data as rd  # noqa: E402
from test_research_data import NAN, etf_like, gamuda_stock  # noqa: E402

SAVED = date(2026, 11, 11)
NOTE = "Watching the debt line.\nSecond thought: revisit after results."


def store():
    return importlib.import_module("research_store")


REPO_RESEARCH = ROOT / "research"


def repo_research_state():
    """The repo's research/ folder: None when absent, else every path in it with its bytes."""
    if not REPO_RESEARCH.exists():
        return None
    return sorted((p.relative_to(REPO_RESEARCH).as_posix(), p.read_bytes() if p.is_file() else b"")
                  for p in REPO_RESEARCH.rglob("*"))


@pytest.fixture(autouse=True)
def repo_research_untouched():
    """v3 guard: no test here writes to (or creates) the repo's own research/ folder."""
    before = repo_research_state()
    yield
    assert repo_research_state() == before, "a test wrote to the repo's research/ folder"


# ---------- made-up Research results ----------
def stock_raw():
    """gamuda_stock with one NaN balance cell (2023-07-31 Current Assets), so a statement frame holds a NaN."""
    raw = gamuda_stock()
    raw.balance.loc["Current Assets", raw.balance.columns[3]] = NAN
    return raw


def stock_r():
    return rd.analyse(stock_raw())


def etf_r():
    return rd.analyse(etf_like())


def bare_r():
    """A stock with no prices and no dividends: empty chart and empty dividend frames (with columns)."""
    return rd.analyse(gamuda_stock(prices=False, dividends=False))


def stale_r():
    return rd.analyse(etf_like(), stale=True)


def with_code(make, code):
    r = make()
    r.code = code
    return r


# ---------- field-by-field comparison ----------
def assert_same(got, want, where="research"):
    """got equals want field by field: same types (datetime stays datetime, date stays date, int stays int),
    NaN stays NaN, frames equal in values, column order, index and dtypes, Light objects equal."""
    if dataclasses.is_dataclass(want) and not isinstance(want, type):
        assert type(got) is type(want), f"{where}: {type(got).__name__}, want {type(want).__name__}"
        for f in dataclasses.fields(want):
            assert_same(getattr(got, f.name), getattr(want, f.name), f"{where}.{f.name}")
    elif isinstance(want, pd.DataFrame):
        assert isinstance(got, pd.DataFrame), f"{where}: {type(got).__name__}, want DataFrame"
        assert list(got.columns) == list(want.columns), f"{where}: column order"
        pd.testing.assert_frame_equal(got, want, check_dtype=True, check_exact=True, check_freq=False, obj=where)
    elif isinstance(want, dict):
        assert isinstance(got, dict), f"{where}: {type(got).__name__}, want dict"
        assert set(got) == set(want), f"{where}: keys {sorted(set(got) ^ set(want))}"
        for k in want:
            assert_same(got[k], want[k], f"{where}[{k!r}]")
    elif isinstance(want, (list, tuple)):
        assert type(got) is type(want), f"{where}: {type(got).__name__}, want {type(want).__name__}"
        assert len(got) == len(want), f"{where}: length"
        for i, (g, w) in enumerate(zip(got, want)):
            assert_same(g, w, f"{where}[{i}]")
    elif isinstance(want, float) and math.isnan(want):
        assert isinstance(got, float) and math.isnan(got), f"{where}: {got!r}, want NaN"
    elif want is None:
        assert got is None, f"{where}: {got!r}, want None"
    else:
        assert type(got) is type(want), f"{where}: {type(got).__name__} {got!r}, want {type(want).__name__}"
        assert got == want, f"{where}: {got!r}, want {want!r}"


def through_json(doc):
    """The document as it comes back from real JSON text."""
    return json.loads(json.dumps(doc))


def walk(doc):
    """Every value in a JSON document, nested dicts and lists included."""
    yield doc
    if isinstance(doc, dict):
        for v in doc.values():
            yield from walk(v)
    elif isinstance(doc, list):
        for v in doc:
            yield from walk(v)


def keys_of(doc):
    return {k for v in walk(doc) if isinstance(v, dict) for k in v}


# ---------- interface ----------
def test_interface_settings_and_dataclasses():
    rs = store()
    assert rs.SNAPSHOT_DIR == Path(rs.__file__).with_name("research")  # v3: the repo folder, not the shell's
    assert rs.SNAPSHOT_DIR == ROOT / "research" and rs.SNAPSHOT_DIR.is_absolute()
    assert rs.FORMAT == 1
    assert issubclass(rs.SnapshotError, Exception)
    assert [f.name for f in dataclasses.fields(rs.Snapshot)] == ["research", "note", "saved_on", "stale"]
    assert [f.name for f in dataclasses.fields(rs.Entry)] == ["path", "saved_on", "code", "name", "overall",
                                                              "note_line", "error"]


# ---------- round trip through real JSON text ----------
@pytest.mark.parametrize("make", [stock_r, etf_r, bare_r, stale_r], ids=["stock", "etf", "bare_stock", "stale_etf"])
def test_round_trip_every_field_equal(make):
    rs = store()
    fixture_has_the_hard_cases()
    r = make()
    snap = rs.from_doc(through_json(rs.to_doc(r, NOTE, SAVED, stale=r.stale)))
    assert isinstance(snap, rs.Snapshot)
    assert_same(snap.research, make())  # also proves to_doc left r as it was
    assert_same(snap.research, r)
    assert snap.note == NOTE
    assert type(snap.saved_on) is date and snap.saved_on == SAVED
    assert snap.stale is r.stale


def fixture_has_the_hard_cases():
    """Guard on the fixtures: the stock result really holds NaN cells, an int column, a date and chart dates;
    the bare stock and the ETF hold empty frames. Called from the round-trip tests."""
    r = stock_r()
    assert r.ratios.isna().any().any()
    assert r.statements["balance"].isna().any().any()
    assert str(r.company["dividends"]["Payments"].dtype) == "int64"
    assert type(r.company["next_earnings"]) is date
    assert type(r.fetched_at) is datetime
    assert len(r.company["price_chart"]) > 0
    b = bare_r()
    assert b.company["price_chart"].empty and list(b.company["price_chart"].columns) == ["Date", "Close"]
    assert b.company["dividends"].empty and list(b.company["dividends"].columns) == ["Year", "Per share", "Payments"]
    assert etf_r().statements["income"].shape == (5, 0)


def test_round_trip_nan_cells_stay_nan():
    rs = store()
    r = stock_r()
    back = rs.from_doc(through_json(rs.to_doc(r, "", SAVED))).research
    pd.testing.assert_frame_equal(back.ratios, r.ratios, check_exact=True)
    pd.testing.assert_frame_equal(back.statements["balance"], r.statements["balance"], check_exact=True)
    assert math.isnan(back.statements["balance"].loc["Current Assets", "2023-07-31"])


def test_round_trip_int_column_stays_int():
    rs = store()
    back = rs.from_doc(through_json(rs.to_doc(stock_r(), "", SAVED))).research
    assert str(back.company["dividends"]["Payments"].dtype) == "int64"
    assert type(back.valuation["buy"]) is int and back.valuation["buy"] == 5


@pytest.mark.parametrize("make", [bare_r, etf_r], ids=["empty_chart_and_dividends", "etf_no_statements"])
def test_round_trip_empty_frames_keep_columns_and_dtypes(make):
    rs = store()
    r = make()
    back = rs.from_doc(through_json(rs.to_doc(r, "", SAVED))).research
    if r.company is not None:
        for k in ("price_chart", "dividends"):
            pd.testing.assert_frame_equal(back.company[k], r.company[k], check_dtype=True)
    for s in ("income", "balance", "cashflow"):
        pd.testing.assert_frame_equal(back.statements[s], r.statements[s], check_dtype=True)
    pd.testing.assert_frame_equal(back.ratios, r.ratios, check_dtype=True)
    pd.testing.assert_frame_equal(back.labels, r.labels, check_dtype=True)


@pytest.mark.parametrize("make", [stock_r, etf_r], ids=["stock", "etf"])
def test_round_trip_lights_are_light_objects(make):
    rs = store()
    r = make()
    back = rs.from_doc(through_json(rs.to_doc(r, "", SAVED))).research
    assert type(back.overall) is rd.Light and back.overall == r.overall
    assert all(type(v) is rd.Light for v in back.lights.values())
    assert back.lights == r.lights
    if r.etf is not None:
        assert back.etf["lights"] == r.etf["lights"] and back.etf["overall"] == r.etf["overall"]


def test_round_trip_datetime_date_and_chart_dates():
    rs = store()
    r = stock_r()
    back = rs.from_doc(through_json(rs.to_doc(r, "", SAVED))).research
    assert type(back.fetched_at) is datetime and back.fetched_at == r.fetched_at
    assert type(back.company["next_earnings"]) is date and back.company["next_earnings"] == date(2026, 12, 9)
    chart, want = back.company["price_chart"], r.company["price_chart"]
    assert chart["Date"].dtype == want["Date"].dtype
    assert list(chart["Date"]) == list(want["Date"])
    assert list(chart["Close"]) == list(want["Close"])


# ---------- frozen lights ----------
def test_frozen_lights_stock(monkeypatch, tmp_path):
    rs = store()
    r = stock_r()
    path = rs.save(r, "", saved_on=SAVED, folder=tmp_path)
    monkeypatch.setitem(rd.THRESHOLDS, "Debt / Equity", (0.1, 0.2))  # D/E 0.60 was amber; now it would be red
    fresh = stock_r()
    assert fresh.lights["Debt / Equity"].colour == "red" != r.lights["Debt / Equity"].colour  # the change bites
    back = rs.load(path).research
    assert back.lights == r.lights
    assert back.overall == r.overall


def test_frozen_lights_etf(monkeypatch, tmp_path):
    rs = store()
    r = etf_r()
    path = rs.save(r, "", saved_on=SAVED, folder=tmp_path)
    monkeypatch.setitem(rd.ETF_THRESHOLDS, "expense_ratio", (0.0001, 0.0002))  # 0.05% was green; now red
    fresh = etf_r()
    assert fresh.etf["lights"]["expense_ratio"].colour == "red" != r.etf["lights"]["expense_ratio"].colour
    back = rs.load(path).research
    assert back.etf["lights"] == r.etf["lights"]
    assert back.etf["overall"] == r.etf["overall"]
    assert back.overall == r.overall


# ---------- what to_doc holds ----------
def test_to_doc_top_keys():
    rs = store()
    doc = rs.to_doc(stock_r(), NOTE, SAVED)
    assert doc["format"] == 1
    assert doc["saved_on"] == "2026-11-11"
    assert doc["note"] == NOTE
    assert doc["stale"] is False
    assert rs.to_doc(stock_r(), NOTE, SAVED, stale=True)["stale"] is True


def test_to_doc_is_json_ready():
    rs = store()
    for r in (stock_r(), etf_r(), bare_r()):
        json.dumps(rs.to_doc(r, NOTE, SAVED))  # no default=: every value already JSON-ready


# Strings found only in the raw Yahoo reply (info keys and values, raw-only rows and columns), never in Research.
RAW_ONLY_STOCK = ("exchangeTimezoneName", "Asia/Kuala_Lumpur", "longBusinessSummary", "heldPercentInsiders",
                  "fiftyTwoWeekLow", "strongBuy", "Reconciled Depreciation", "q_income", "q_cashflow")
RAW_ONLY_ETF = ("netExpenseRatio", "FAKE WORLD", "Annual Holdings Turnover", "Holding Percent",
                "consumer_cyclical", "stockPosition", "totalAssets")


@pytest.mark.parametrize("make,raw_only", [(stock_r, RAW_ONLY_STOCK), (etf_r, RAW_ONLY_ETF)], ids=["stock", "etf"])
def test_to_doc_holds_no_raw_yahoo_reply(make, raw_only):
    rs = store()
    doc = rs.to_doc(make(), "", SAVED)
    text = json.dumps(doc)
    for s in raw_only:
        assert s not in text, s
    assert not {"info", "raw", "q_income", "q_balance", "q_cashflow", "recs", "ops"} & keys_of(doc)


@pytest.mark.parametrize("make", [stock_r, etf_r], ids=["stock", "etf"])
def test_to_doc_chart_as_two_lists(make):
    rs = store()
    r = make()
    chart = (r.etf or r.company)["price_chart"]
    want_dates = [d.strftime("%Y-%m-%d") for d in chart["Date"]]
    want_closes = [float(x) for x in chart["Close"]]
    doc = through_json(rs.to_doc(r, "", SAVED))
    lists = [v for v in walk(doc) if isinstance(v, list)]
    assert want_dates in lists, "no list of YYYY-MM-DD chart dates in the document"
    assert want_closes in lists, "no list of chart closes (numbers) in the document"


# ---------- file names ----------
def test_file_name_code_and_date(tmp_path):
    rs = store()
    assert rs.snapshot_path("5398.KL", SAVED, tmp_path) == tmp_path / "5398.KL_2026-11-11.json"
    path = rs.save(stock_r(), "", saved_on=SAVED, folder=tmp_path)
    assert path == tmp_path / "5398.KL_2026-11-11.json"
    assert path.exists()


def test_second_and_third_save_same_day_never_overwrite(tmp_path):
    rs = store()
    first = rs.save(stock_r(), "first", saved_on=SAVED, folder=tmp_path)
    before = first.read_bytes()
    second = rs.save(stock_r(), "second", saved_on=SAVED, folder=tmp_path)
    third = rs.save(stock_r(), "third", saved_on=SAVED, folder=tmp_path)
    assert first.name == "5398.KL_2026-11-11.json"
    assert second.name == "5398.KL_2026-11-11_2.json"
    assert third.name == "5398.KL_2026-11-11_3.json"
    assert first.read_bytes() == before  # the first file untouched
    assert [rs.load(p).note for p in (first, second, third)] == ["first", "second", "third"]
    assert rs.snapshot_path("5398.KL", SAVED, tmp_path).name == "5398.KL_2026-11-11_4.json"


@pytest.mark.parametrize("code,name", [("^KLSE", "^KLSE_2026-11-11.json"), ("0005.HK", "0005.HK_2026-11-11.json")])
def test_file_name_index_and_hong_kong_codes(tmp_path, code, name):
    rs = store()
    assert rs.snapshot_path(code, SAVED, tmp_path).name == name
    path = rs.save(with_code(stock_r, code), "", saved_on=SAVED, folder=tmp_path)
    assert path.name == name and path.exists()
    assert rs.load(path).research.code == code


@pytest.mark.parametrize("code", ["BAD/CODE", "BAD\\CODE", "BAD:CODE"])
def test_code_with_a_path_character_raises(tmp_path, code):
    rs = store()
    with pytest.raises(rs.SnapshotError):
        rs.snapshot_path(code, SAVED, tmp_path)
    with pytest.raises(rs.SnapshotError):
        rs.save(with_code(stock_r, code), "", saved_on=SAVED, folder=tmp_path)
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]  # nothing written


# ---------- save ----------
def test_save_creates_the_folder(tmp_path):
    rs = store()
    folder = tmp_path / "deeper" / "research"
    path = rs.save(stock_r(), "", saved_on=SAVED, folder=folder)
    assert folder.is_dir()
    assert path.parent == folder


def test_save_writes_compact_utf8_with_lf_line_ends(tmp_path):
    rs = store()
    note = "Kedai kopi – café\nline two\r\nline three"
    path = rs.save(stock_r(), note, saved_on=SAVED, folder=tmp_path)
    data = path.read_bytes()
    assert b"\r" not in data  # no CRLF line ends (a CR inside the note is escaped by JSON)
    text = data.decode("utf-8")
    assert text.count("\n") <= 1, "not compact: the document is spread over several lines"
    assert json.loads(text)["note"] == note
    assert rs.load(path).note == note


def test_save_defaults_to_today(tmp_path):
    rs = store()
    today = date.today()
    path = rs.save(stock_r(), "", folder=tmp_path)
    assert path.name == f"5398.KL_{today.isoformat()}.json"
    assert rs.load(path).saved_on == today


def test_failed_write_leaves_no_file(monkeypatch, tmp_path):
    """The rename at the end of the write fails: neither the snapshot nor a temp file is left behind."""
    rs = store()

    def boom(*a, **k):
        raise OSError("disk full (fake)")

    originals = (os.replace, os.rename, shutil.move)
    for name, val in list(vars(rs).items()):
        if any(val is o for o in originals):  # a `from os import replace` inside the store
            monkeypatch.setattr(rs, name, boom)
    monkeypatch.setattr(os, "replace", boom)
    monkeypatch.setattr(os, "rename", boom)
    monkeypatch.setattr(shutil, "move", boom)
    monkeypatch.setattr(Path, "replace", boom)
    monkeypatch.setattr(Path, "rename", boom)
    folder = tmp_path / "research"
    with pytest.raises((OSError, rs.SnapshotError)):
        rs.save(stock_r(), "a note", saved_on=SAVED, folder=folder)
    left = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert left == [], left


# ---------- notes and stale ----------
def test_empty_note_allowed(tmp_path):
    rs = store()
    path = rs.save(stock_r(), "", saved_on=SAVED, folder=tmp_path)
    assert rs.load(path).note == ""


def test_multi_line_note_kept_whole(tmp_path):
    rs = store()
    note = "First line\nSecond line\n\n  indented fourth line\n"
    path = rs.save(stock_r(), note, saved_on=SAVED, folder=tmp_path)
    assert rs.load(path).note == note


def test_stale_kept(tmp_path):
    rs = store()
    path = rs.save(stale_r(), "", saved_on=SAVED, stale=True, folder=tmp_path)
    snap = rs.load(path)
    assert snap.stale is True
    assert json.loads(path.read_text(encoding="utf-8"))["stale"] is True
    plain = rs.load(rs.save(etf_r(), "", saved_on=SAVED, folder=tmp_path))
    assert plain.stale is False


def test_load_gives_a_snapshot(tmp_path):
    rs = store()
    path = rs.save(stock_r(), NOTE, saved_on=SAVED, folder=tmp_path)
    snap = rs.load(path)
    assert isinstance(snap, rs.Snapshot)
    assert snap.note == NOTE and snap.saved_on == SAVED and snap.stale is False
    assert_same(snap.research, stock_r())


# ---------- load: unreadable files ----------
def find_dict_with(doc, key):
    return next((v for v in walk(doc) if isinstance(v, dict) and key in v), None)


def mangled(rs, how):
    """A snapshot file's bytes, broken in one way."""
    doc = through_json(rs.to_doc(stock_r(), NOTE, SAVED))
    if how == "broken_json":
        return b'{"format": 1, "note": '
    if how == "empty_file":
        return b""
    if how == "not_utf8":
        return b"\xff\xfe\xfa not text"
    if how == "not_an_object":
        return b"[1, 2, 3]"
    if how == "format_2":
        doc["format"] = 2
    elif how == "bad_saved_on":
        doc["saved_on"] = "2026-13-45"
    elif how == "no_fetched_at":
        holder = find_dict_with(doc, "fetched_at")
        assert holder is not None, "the document holds no fetched_at"
        del holder["fetched_at"]
    else:
        del doc[how.removeprefix("no_")]
    return json.dumps(doc).encode("utf-8")


@pytest.mark.parametrize("how", ["broken_json", "empty_file", "not_utf8", "not_an_object", "format_2",
                                 "no_format", "no_note", "no_saved_on", "no_stale", "bad_saved_on",
                                 "no_fetched_at"])
def test_load_unreadable_raises_snapshot_error(tmp_path, how):
    rs = store()
    path = tmp_path / "5398.KL_2026-11-11.json"
    path.write_bytes(mangled(rs, how))
    with pytest.raises(rs.SnapshotError) as info:  # never None, never another exception type
        rs.load(path)
    assert str(info.value).strip(), "SnapshotError without a message"


def test_from_doc_unknown_format_and_missing_key_raise_snapshot_error():
    rs = store()
    doc = through_json(rs.to_doc(stock_r(), NOTE, SAVED))
    with pytest.raises(rs.SnapshotError) as info:
        rs.from_doc(dict(doc, format=2))
    assert str(info.value).strip()
    short = dict(doc)
    del short["note"]
    with pytest.raises(rs.SnapshotError) as info:
        rs.from_doc(short)
    assert str(info.value).strip()


# ---------- list_entries ----------
def three_snapshots(rs, folder):
    old = rs.save(etf_r(), "Old ETF note", saved_on=date(2026, 10, 1), folder=folder)
    new = rs.save(stock_r(), "Newest line one\nline two", saved_on=date(2026, 11, 10), folder=folder)
    mid = rs.save(etf_r(), "", saved_on=date(2026, 11, 2), folder=folder)
    return old, mid, new


def test_list_entries_newest_first_with_fields(tmp_path):
    rs = store()
    old, mid, new = three_snapshots(rs, tmp_path)
    entries = rs.list_entries(tmp_path)
    assert all(isinstance(e, rs.Entry) for e in entries)
    assert [e.path.name for e in entries] == [new.name, mid.name, old.name]
    first = entries[0]
    assert first.saved_on == date(2026, 11, 10)
    assert first.code == "5398.KL" and first.name == "Gamuda-like Bhd"
    assert first.overall == stock_r().overall  # the overall light, a Light
    assert first.note_line == "Newest line one"  # first line of the note only
    assert first.error is None
    assert entries[1].note_line == ""
    assert entries[2].overall == etf_r().overall and entries[2].note_line == "Old ETF note"


def test_list_entries_broken_file_listed_with_error(tmp_path):
    rs = store()
    old, mid, new = three_snapshots(rs, tmp_path)
    broken = tmp_path / "BROKEN_2026-11-05.json"
    broken.write_text('{"format": 1, "note": ', encoding="utf-8")
    entries = rs.list_entries(tmp_path)
    bad = [e for e in entries if e.path.name == broken.name]
    assert len(bad) == 1 and isinstance(bad[0].error, str) and bad[0].error.strip()
    good = [e for e in entries if e.error is None]
    assert [e.path.name for e in good] == [new.name, mid.name, old.name]  # the others still listed, in order


def test_list_entries_missing_folder_empty(tmp_path):
    rs = store()
    assert rs.list_entries(tmp_path / "no_such_folder") == []
    (tmp_path / "empty").mkdir()
    assert rs.list_entries(tmp_path / "empty") == []


def test_list_entries_ignores_non_json_files(tmp_path):
    rs = store()
    path = rs.save(stock_r(), "", saved_on=SAVED, folder=tmp_path)
    (tmp_path / "readme.txt").write_text("not a snapshot", encoding="utf-8")
    (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
    (tmp_path / "5398.KL_2026-11-11.json.tmp").write_text("{", encoding="utf-8")
    assert [e.path.name for e in rs.list_entries(tmp_path)] == [path.name]


# ---------- a snapshot stands alone ----------
def test_load_stands_alone(monkeypatch, tmp_path):
    """Reopening reads nothing from the research cache, Yahoo or the workbook: cache dir empty, sockets blocked."""
    rs = store()
    r = stock_r()
    path = rs.save(r, NOTE, saved_on=SAVED, folder=tmp_path / "research")
    empty = tmp_path / "empty_cache"
    empty.mkdir()

    def boom(*a, **k):
        raise AssertionError("snapshot load reached outside its file")

    monkeypatch.setattr(rd, "CACHE_DIR", empty)
    for name in ("research", "fetch_raw", "fetch_fx", "load_cache", "save_cache"):
        monkeypatch.setattr(rd, name, boom)
    import portfolio_data
    monkeypatch.setattr(portfolio_data, "load_workbook", boom)
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    snap = rs.load(path)
    assert_same(snap.research, r)
    assert snap.note == NOTE
    assert list(empty.iterdir()) == []


# ---------- source checks ----------
def test_store_imports_no_streamlit():
    src = (ROOT / "research_store.py").read_text(encoding="utf-8")
    assert "streamlit" not in src
    out = subprocess.run([sys.executable, "-c", "import research_store, sys; print('streamlit' in sys.modules)"],
                         cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


# ---------- added by the mutation pass (WP-3.4 mutation-r1) ----------
def test_round_trip_scalar_nan_inf_and_named_index():
    """Kills RT07 (a NaN held as a single value written as null) and RT03 (an index name dropped): the fixtures
    hold NaN only inside frames and no named index, so this result is edited to hold both."""
    rs = store()
    r = stock_r()
    r.valuation["pe"] = math.nan
    r.valuation["forward_pe"] = math.inf
    r.ratios.index.name = "Ratio"
    r.ratios.columns.name = "Period"
    back = rs.from_doc(through_json(rs.to_doc(r, "", SAVED))).research
    assert_same(back, r)
    assert back.ratios.index.name == "Ratio" and back.ratios.columns.name == "Period"


@pytest.mark.parametrize("bad", [{"$datetime": "not a time"}, {"$date": "2026-13-45"}, {"$light": ["green"]}],
                         ids=["bad_datetime", "bad_date", "short_light"])
def test_load_damaged_value_raises_snapshot_error(tmp_path, bad):
    """Kills ER09: a hand-damaged value inside the result is an unreadable file too, so load raises
    SnapshotError with a message, never another exception type."""
    rs = store()
    doc = through_json(rs.to_doc(stock_r(), "", SAVED))
    doc["research"]["fetched_at"] = bad
    path = tmp_path / "5398.KL_2026-11-11.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(rs.SnapshotError) as err:
        rs.load(path)
    assert str(err.value).strip()
    with pytest.raises(rs.SnapshotError):
        rs.from_doc(doc)


# ---------- v3 (supervisor rulings on review-r1, 2026-11-11) ----------
# v3.1 folder
def test_v3_snapshot_dir_does_not_follow_the_current_folder(tmp_path):
    """Imported from another current folder, SNAPSHOT_DIR is still the research folder beside research_store.py."""
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    out = subprocess.run([sys.executable, "-c", "import research_store; print(research_store.SNAPSHOT_DIR)"],
                         cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert Path(out.stdout.strip()) == ROOT / "research", out.stdout


def test_v3_save_without_folder_uses_snapshot_dir_at_call_time(monkeypatch, tmp_path):
    rs = store()
    target, elsewhere = tmp_path / "snaps", tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # an old relative default lands here, never in the repo
    monkeypatch.setattr(rs, "SNAPSHOT_DIR", target)
    path = rs.save(stock_r(), "", saved_on=SAVED)
    assert path.parent == target, path
    assert path.exists()
    assert not (elsewhere / "research").exists()


def test_v3_list_entries_without_folder_uses_snapshot_dir_at_call_time(monkeypatch, tmp_path):
    rs = store()
    target, elsewhere = tmp_path / "snaps", tmp_path / "elsewhere"
    elsewhere.mkdir()
    path = rs.save(stock_r(), "a note", saved_on=SAVED, folder=target)
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(rs, "SNAPSHOT_DIR", target)
    assert [e.path.name for e in rs.list_entries()] == [path.name]


# v3.2 overall must be a Light
@pytest.mark.parametrize("bad", [None, "green", ["green", "x"], 3], ids=["null", "text", "list", "number"])
def test_v3_overall_not_a_light_raises_snapshot_error(tmp_path, bad):
    rs = store()
    doc = through_json(rs.to_doc(stock_r(), "", SAVED))
    doc["research"]["overall"] = bad
    with pytest.raises(rs.SnapshotError) as err:
        rs.from_doc(doc)
    assert str(err.value).strip()
    path = tmp_path / "5398.KL_2026-11-11.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(rs.SnapshotError):
        rs.load(path)


def test_v3_overall_null_is_an_error_entry_others_listed(tmp_path):
    rs = store()
    old, mid, new = three_snapshots(rs, tmp_path)
    doc = through_json(rs.to_doc(stock_r(), "", date(2026, 11, 5)))
    doc["research"]["overall"] = None
    bad = tmp_path / "NULL_2026-11-05.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    entries = rs.list_entries(tmp_path)
    hit = [e for e in entries if e.path.name == bad.name]
    assert len(hit) == 1 and isinstance(hit[0].error, str) and hit[0].error.strip(), hit
    assert [e.path.name for e in entries if e.error is None] == [new.name, mid.name, old.name]


# v3.3 numpy floats
NP_CASES = [("nan", np.float64("nan")), ("inf", np.float64("inf")), ("finite", np.float64(1.25))]


def same_plain_float(got, want, where):
    assert type(got) is float, f"{where}: {type(got).__name__} {got!r}, want a plain float"
    if math.isnan(want):
        assert math.isnan(got), f"{where}: {got!r}"
    else:
        assert got == float(want), f"{where}: {got!r}, want {float(want)!r}"


@pytest.mark.parametrize("label,x", NP_CASES, ids=[c[0] for c in NP_CASES])
def test_v3_numpy_float_loose_in_a_dict_round_trips(tmp_path, label, x):
    rs = store()
    r = stock_r()
    r.valuation["pe"] = x
    back = rs.from_doc(through_json(rs.to_doc(r, "", SAVED))).research
    same_plain_float(back.valuation["pe"], x, "through JSON")
    path = rs.save(r, "", saved_on=SAVED, folder=tmp_path)
    same_plain_float(rs.load(path).research.valuation["pe"], x, "save and load")


@pytest.mark.parametrize("label,x", NP_CASES, ids=[c[0] for c in NP_CASES])
def test_v3_numpy_float_in_an_object_column_round_trips(tmp_path, label, x):
    rs = store()
    r = stock_r()
    r.company["extra"] = pd.DataFrame({"v": pd.Series([x, "text"], dtype=object)})
    back = rs.from_doc(through_json(rs.to_doc(r, "", SAVED))).research
    col = back.company["extra"]["v"]
    assert col.dtype == object
    same_plain_float(col.iloc[0], x, "through JSON")
    assert col.iloc[1] == "text"
    path = rs.save(r, "", saved_on=SAVED, folder=tmp_path)
    same_plain_float(rs.load(path).research.company["extra"]["v"].iloc[0], x, "save and load")


def test_v3_save_refuses_text_that_does_not_load_back(monkeypatch, tmp_path):
    """save checks its encoded text with from_doc before writing: here from_doc is made to fail, so save raises
    SnapshotError and leaves no file and no temp file."""
    rs = store()

    def cannot_read(doc):
        raise rs.SnapshotError("cannot read this back (fake)")

    monkeypatch.setattr(rs, "from_doc", cannot_read)
    folder = tmp_path / "research"
    with pytest.raises(rs.SnapshotError):
        rs.save(stock_r(), "a note", saved_on=SAVED, folder=folder)
    left = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert left == [], left


# v3.4 missing fields in an old snapshot
DEFAULTED = [f.name for f in dataclasses.fields(rd.Research) if f.default is not dataclasses.MISSING]
REQUIRED = [f.name for f in dataclasses.fields(rd.Research) if f.default is dataclasses.MISSING]


def test_v3_research_fields_split_as_expected():
    assert "company" in DEFAULTED and "etf" in DEFAULTED
    assert {"code", "overall", "fetched_at"} <= set(REQUIRED)


@pytest.mark.parametrize("name", DEFAULTED)
def test_v3_missing_defaulted_field_filled_from_default(tmp_path, name):
    rs = store()
    r = stock_r()
    doc = through_json(rs.to_doc(r, NOTE, SAVED))
    del doc["research"][name]
    default = next(f.default for f in dataclasses.fields(rd.Research) if f.name == name)
    snap = rs.from_doc(doc)
    assert getattr(snap.research, name) == default
    assert snap.research.code == r.code and snap.note == NOTE
    path = tmp_path / "5398.KL_2026-11-11.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert getattr(rs.load(path).research, name) == default


@pytest.mark.parametrize("name", ["code", "overall", "fetched_at", "ratios"])
def test_v3_missing_required_field_raises_naming_it(name):
    rs = store()
    doc = through_json(rs.to_doc(stock_r(), "", SAVED))
    del doc["research"][name]
    with pytest.raises(rs.SnapshotError) as err:
        rs.from_doc(doc)
    assert name in str(err.value), str(err.value)


# v3.5 UTF-8 written as itself
def test_v3_non_ascii_note_and_name_written_as_utf8(tmp_path):
    rs = store()
    r = stock_r()
    r.name = "株式会社テスト café"
    note = "Kopi at the café; 日本 trip."
    path = rs.save(r, note, saved_on=SAVED, folder=tmp_path)
    data = path.read_bytes()
    for s in ("café", "日本", "株式会社テスト"):
        assert s.encode("utf-8") in data, s
    assert b"\\u" not in data, "non-ASCII text escaped as \\u"
    snap = rs.load(path)
    assert snap.note == note and snap.research.name == r.name


# v3.6 .gitignore
def test_v3_gitignore_keeps_snapshot_temp_files_out():
    lines = [ln.strip() for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert "research/*.tmp" in lines
    assert "research/" not in lines and "research" not in lines  # the folder itself stays tracked
