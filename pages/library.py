"""Library page (WP-3.4): every snapshot in research/, newest first; pick one to reopen it in the Research
layout exactly as it was saved. Reads only the snapshot files until "Compare with today" is clicked (WP-3.4.1),
which fetches today's result for that code; formatting only, nothing is computed here."""
import pandas as pd
import streamlit as st

import research_data as rd
import research_store
from research_view import draw, draw_compare

st.title("Library")
st.caption("Research snapshots saved by hand in research/. Each reopens as it was saved.")

entries = research_store.list_entries()
if not entries:
    st.write("No snapshots yet. Save one from the Research page.")
    st.stop()

st.dataframe(pd.DataFrame([
    {"Date": "" if e.error else e.saved_on.isoformat(), "Code": e.code,
     "Name": "cannot be read" if e.error else e.name, "Overall": "" if e.error else e.overall.colour,
     "Note": e.error or e.note_line, "File": e.path.name} for e in entries]), hide_index=True)

readable = {e.path.name: e for e in entries if e.error is None}
picked = st.selectbox("Open a snapshot", list(readable), index=None, placeholder="Pick a file",
                      format_func=lambda n: f"{readable[n].saved_on.isoformat()} · {readable[n].code} · {n}")
held = st.session_state.get("compare")
if held is not None and held[0] != picked:  # a comparison made for another snapshot (or none picked): drop it
    st.session_state["compare"] = None
if picked is None:
    st.stop()

try:
    snap = research_store.load(readable[picked].path)
except research_store.SnapshotError as exc:
    st.error(f"{picked} cannot be read: {exc}")
    st.stop()

r = snap.research
when = snap.saved_on.isoformat()
st.info(f"Snapshot saved on {when}" + (", from an older cached copy" if snap.stale else ""))
if snap.note:
    st.text(snap.note)
for w in r.warnings:
    if not w.startswith("Yahoo unreachable"):  # the banner above says it was a cached copy
        st.caption(w)

# "Compare with today" (WP-3.4.1): fetched only on a click; the result belongs to this snapshot alone and is
# forgotten as soon as another snapshot is picked (v2.8).
held = st.session_state.get("compare")
if st.button("Compare with today"):
    try:
        with st.spinner("Fetching today's figures..."):
            fresh = rd.research(r.code)
        held = (picked, rd.compare(r, fresh), None)
    except rd.ResearchError as exc:
        held = (picked, None, f"Today's figures could not be fetched: {exc}. The saved view below is unchanged.")
    except Exception as exc:  # anything else from the fetch or the comparison: keep the saved view up (v3.3)
        held = (picked, None, f"Today's figures could not be compared: {str(exc) or type(exc).__name__}. "
                              "The saved view below is unchanged.")
    st.session_state["compare"] = held
if held is not None:
    if held[2] is not None:
        st.warning(held[2])
    else:
        draw_compare(held[1])

try:
    draw(r, caption=f"Data as of {r.fetched_at:%Y-%m-%d %H:%M}, Yahoo Finance; snapshot saved on {when}")
except Exception as exc:  # a file that loads but holds something this version cannot draw
    st.error(f"{picked} cannot be drawn by this version of the app: {exc!r}")
