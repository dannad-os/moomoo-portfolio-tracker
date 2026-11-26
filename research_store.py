"""Research snapshots (WP-3.4): one finished Research result plus a note, saved by hand as one JSON file in
research/, listed and reopened exactly as saved. Reads nothing from Yahoo, the research cache or the workbook.

The document: {"format": 1, "saved_on": "YYYY-MM-DD", "note": ..., "stale": ..., "research": {field: value}}.
Plain JSON values stay plain; everything else is a one-key tagged object so it comes back with its exact type:
{"$light": [colour, reason]}, {"$datetime": iso}, {"$date": iso}, {"$timestamp": iso}, {"$float": "nan"},
{"$np": [dtype, value]}, {"$tuple": [...]}, {"$dict": [[key, value], ...]} (a dict with a non-text or "$" key)
and {"$frame": {"columns": index, "index": index, "dtypes": [...], "data": [column list, ...]}}.
A frame is stored column by column, so the price chart is a list of YYYY-MM-DD dates and a list of closes."""
import dataclasses
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

import research_data as rd

SNAPSHOT_DIR = Path(__file__).with_name("research")  # beside this file, whatever the shell's folder
FORMAT = 1
BAD_NAME_CHARS = '/\\:<>"|?*'  # characters a file name cannot hold
TOP_KEYS = ("format", "saved_on", "note", "stale", "research")


class SnapshotError(Exception):
    pass


@dataclass
class Snapshot:
    research: rd.Research
    note: str
    saved_on: date
    stale: bool


@dataclass
class Entry:
    path: Path
    saved_on: date | None
    code: str
    name: str
    overall: rd.Light | None
    note_line: str
    error: str | None


# ---------- values to JSON and back ----------
def _float(x):
    """A plain float; a numpy float becomes one too (its repr would be "np.float64(nan)")."""
    x = float(x)
    return {"$float": repr(x)} if math.isnan(x) or math.isinf(x) else x


def _enc(v):
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    if isinstance(v, float):
        return _float(v)
    if isinstance(v, rd.Light):
        return {"$light": [v.colour, v.reason]}
    if v is pd.NaT:
        return {"$timestamp": None}
    if isinstance(v, pd.Timestamp):
        return {"$timestamp": v.isoformat()}
    if isinstance(v, datetime):
        return {"$datetime": v.isoformat()}
    if isinstance(v, date):
        return {"$date": v.isoformat()}
    if isinstance(v, np.generic) and v.dtype.kind in "biuf":
        return {"$np": [v.dtype.name, _float(v.item()) if v.dtype.kind == "f" else v.item()]}
    if isinstance(v, pd.DataFrame):
        return {"$frame": _enc_frame(v)}
    if isinstance(v, list):
        return [_enc(x) for x in v]
    if isinstance(v, tuple):
        return {"$tuple": [_enc(x) for x in v]}
    if isinstance(v, dict):
        if all(isinstance(k, str) and not k.startswith("$") for k in v):
            return {k: _enc(x) for k, x in v.items()}
        return {"$dict": [[_enc(k), _enc(x)] for k, x in v.items()]}
    raise SnapshotError(f"A snapshot cannot store a value of type {type(v).__name__}.")


def _dec(v):
    if isinstance(v, list):
        return [_dec(x) for x in v]
    if not isinstance(v, dict):
        return v
    if len(v) == 1:
        (tag, x), = v.items()
        if tag == "$light":
            return rd.Light(*x)
        if tag == "$timestamp":
            return pd.NaT if x is None else pd.Timestamp(x)
        if tag == "$datetime":
            return datetime.fromisoformat(x)
        if tag == "$date":
            return date.fromisoformat(x)
        if tag == "$float":
            return float(x)
        if tag == "$np":
            return np.dtype(x[0]).type(_dec(x[1]))
        if tag == "$frame":
            return _dec_frame(x)
        if tag == "$tuple":
            return tuple(_dec(i) for i in x)
        if tag == "$dict":
            return {_dec(k): _dec(i) for k, i in x}
    return {k: _dec(x) for k, x in v.items()}


# ---------- frames: column by column, with dtypes ----------
def _enc_values(values, dtype):
    """One column (or index) as a plain list; dtype says how to read it back."""
    if isinstance(dtype, pd.DatetimeTZDtype):
        return [None if pd.isna(x) else x.isoformat() for x in values]
    if dtype.kind == "M":
        stamps = list(values)
        if all(pd.isna(x) or x == x.normalize() for x in stamps):  # whole days: YYYY-MM-DD
            return [None if pd.isna(x) else x.strftime("%Y-%m-%d") for x in stamps]
        return [None if pd.isna(x) else x.isoformat() for x in stamps]
    if isinstance(dtype, np.dtype) and dtype.kind in "biuf":
        if dtype.kind == "f":
            return [None if math.isnan(x) else _float(x) for x in values.tolist()]
        return values.tolist()
    if str(dtype) == "str":
        return [None if pd.isna(x) else x for x in values]
    return [_enc(x) for x in values]  # object and anything else: cell by cell


def _dec_values(values, dtype_name):
    dtype = pd.api.types.pandas_dtype(dtype_name)
    if isinstance(dtype, pd.DatetimeTZDtype):
        return pd.to_datetime(pd.Series(values, dtype=object), utc=True).dt.tz_convert(dtype.tz).astype(dtype).array
    if dtype.kind == "M":
        return pd.to_datetime(pd.Series(values, dtype=object)).astype(dtype).array
    if isinstance(dtype, np.dtype) and dtype.kind == "f":
        return np.array([math.nan if x is None else _dec(x) for x in values], dtype=dtype)
    if isinstance(dtype, np.dtype) and dtype.kind in "biu":
        return np.array(values, dtype=dtype)
    if str(dtype) == "str":
        return pd.array(values, dtype=dtype)
    cells = [_dec(x) for x in values]
    out = np.empty(len(cells), dtype=object)
    out[:] = cells
    return out if dtype == object else pd.array(out, dtype=dtype)


def _enc_index(ix):
    if isinstance(ix, pd.MultiIndex):
        raise SnapshotError("A snapshot cannot store a frame with a multi-level index.")
    if isinstance(ix, pd.RangeIndex):
        return {"range": [ix.start, ix.stop, ix.step], "name": _enc(ix.name)}
    return {"dtype": str(ix.dtype), "values": _enc_values(ix, ix.dtype), "name": _enc(ix.name)}


def _dec_index(spec):
    if "range" in spec:
        return pd.RangeIndex(*spec["range"], name=_dec(spec["name"]))
    return pd.Index(_dec_values(spec["values"], spec["dtype"]), dtype=pd.api.types.pandas_dtype(spec["dtype"]),
                    name=_dec(spec["name"]))


def _enc_frame(df):
    return {"columns": _enc_index(df.columns), "index": _enc_index(df.index),
            "dtypes": [str(df.iloc[:, i].dtype) for i in range(df.shape[1])],
            "data": [_enc_values(df.iloc[:, i], df.iloc[:, i].dtype) for i in range(df.shape[1])]}


def _dec_frame(spec):
    index, columns = _dec_index(spec["index"]), _dec_index(spec["columns"])
    df = pd.DataFrame({i: pd.Series(_dec_values(vals, dt), index=index, dtype=pd.api.types.pandas_dtype(dt))
                       for i, (vals, dt) in enumerate(zip(spec["data"], spec["dtypes"], strict=True))}, index=index)
    df.columns = columns
    return df


# ---------- the document ----------
def to_doc(r, note, saved_on, stale=False):
    """The JSON-ready document for one Research result; r is left as it was."""
    return {"format": FORMAT, "saved_on": saved_on.isoformat(), "note": note, "stale": bool(stale),
            "research": {f.name: _enc(getattr(r, f.name)) for f in dataclasses.fields(rd.Research)}}


def from_doc(doc):
    """A Snapshot from a document; SnapshotError on an unknown format or a missing or bad key."""
    if not isinstance(doc, dict):
        raise SnapshotError("The file does not hold a snapshot document.")
    fmt = doc.get("format")
    if type(fmt) is not int or fmt != FORMAT:
        raise SnapshotError(f"Unknown snapshot format {fmt!r}; this version reads format {FORMAT}.")
    missing = [k for k in TOP_KEYS if k not in doc]
    if missing:
        raise SnapshotError("The snapshot has no " + ", ".join(missing) + ".")
    note, stale, fields = doc["note"], doc["stale"], doc["research"]
    if not isinstance(note, str) or not isinstance(stale, bool) or not isinstance(fields, dict):
        raise SnapshotError("The snapshot's note, stale flag or result has the wrong type.")
    try:
        saved_on = date.fromisoformat(doc["saved_on"])
    except (TypeError, ValueError):
        raise SnapshotError(f"The snapshot's saved_on {doc['saved_on']!r} is not a date.") from None
    known = dataclasses.fields(rd.Research)
    missing = [f.name for f in known if f.name not in fields and f.default is dataclasses.MISSING
               and f.default_factory is dataclasses.MISSING]
    if missing:
        raise SnapshotError("The snapshot's result has no " + ", ".join(missing) + ".")
    try:  # a field added to Research after the file was saved takes its dataclass default
        research = rd.Research(**{f.name: _dec(fields[f.name]) for f in known if f.name in fields})
    except Exception as exc:  # a hand-edited or damaged value
        raise SnapshotError(f"The snapshot's result cannot be read: {exc}") from None
    if not isinstance(research.overall, rd.Light):
        raise SnapshotError(f"The snapshot's overall light {research.overall!r} is not a light.")
    return Snapshot(research=research, note=note, saved_on=saved_on, stale=stale)


# ---------- files ----------
def snapshot_path(code, saved_on, folder):
    """research/<CODE>_<YYYY-MM-DD>.json, or _2, _3, ... when that name is taken; never an existing file."""
    if not code or any(c in BAD_NAME_CHARS for c in code):
        raise SnapshotError(f"The code {code!r} cannot be used in a file name.")
    folder, base = Path(folder), f"{code}_{saved_on.isoformat()}"
    path, n = folder / f"{base}.json", 1
    while path.exists():
        n += 1
        path = folder / f"{base}_{n}.json"
    return path


def save(r, note, *, saved_on=None, stale=False, folder=None):
    """Write one snapshot file and return its path (folder None = SNAPSHOT_DIR, read now). The text is first
    read back with from_doc; then temp file and rename, so a failed write leaves no file."""
    saved_on = saved_on or date.today()
    path = snapshot_path(r.code, saved_on, SNAPSHOT_DIR if folder is None else folder)
    text = json.dumps(to_doc(r, note, saved_on, stale), ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))
    from_doc(json.loads(text))  # SnapshotError here: nothing is written
    data = (text + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def load(path):
    """The Snapshot in one file; SnapshotError (never None) when the file cannot be read."""
    try:
        doc = json.loads(Path(path).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SnapshotError(f"{Path(path).name} is not a readable snapshot file: {exc}") from None
    return from_doc(doc)


def list_entries(folder=None):
    """Every *.json in the folder (None = SNAPSHOT_DIR, read now), newest first (saved_on, then file name);
    an unreadable file has error set."""
    folder = Path(SNAPSHOT_DIR if folder is None else folder)
    if not folder.is_dir():
        return []
    out = []
    for p in folder.glob("*.json"):
        if not p.is_file():
            continue
        try:
            s = load(p)
        except SnapshotError as exc:
            out.append(Entry(p, None, "", "", None, "", str(exc)))
            continue
        line = s.note.splitlines()[0] if s.note else ""
        out.append(Entry(p, s.saved_on, s.research.code, s.research.name, s.research.overall, line, None))
    return sorted(out, key=lambda e: (e.saved_on or date.min, e.path.name), reverse=True)
