"""Research page: one Yahoo code. Draws research_data's figures (the layout is research_view.draw); formatting
only, nothing is computed here. A shown result can be saved as a snapshot with a note (WP-3.4)."""
from pathlib import Path

import streamlit as st

import portfolio_data as data
import research_data as rd
import research_store
from research_view import draw

LIGHT_DOT = {"green": "🟢", "amber": "🟡", "red": "🔴", "grey": "⚪"}  # emoji form, as the CLI words it
REMINDER = "Notes are saved to git. Leave out amounts and holding sizes."


def use_chip():
    if st.session_state["chip"] is not None:
        st.session_state["code"] = st.session_state["chip"]


st.title("Research")
st.caption("Yahoo Finance, cached one hour. Public data, nothing from the broker.")

try:
    codes = rd.chip_codes(data.load_workbook().holdings)
except (FileNotFoundError, PermissionError):
    codes = []

if codes:
    st.pills("Your holdings", codes, key="chip", on_change=use_chip)
box, button = st.columns([4, 1], vertical_alignment="bottom")
code = box.text_input("Yahoo code", placeholder="5398.KL or VT", key="code").strip().upper()
refresh = button.button("Refresh from Yahoo")
if not code:
    st.info("Type a Yahoo code or pick a holding.")
    st.stop()

try:
    r = rd.research(code, force=refresh)
except rd.ResearchError as exc:
    st.error(str(exc))
    st.stop()

if r.stale:
    st.warning(f"Showing a saved copy; Yahoo was unreachable. Fetched {r.fetched_at:%Y-%m-%d %H:%M}.")
for w in r.warnings:
    if not w.startswith("Yahoo unreachable"):  # already in the banner above
        st.caption(w)

draw(r)

st.divider()
note = st.text_area("Notes for this snapshot", key="note")
st.caption(REMINDER)
if st.button("Save snapshot"):
    try:
        path = research_store.save(r, note, stale=r.stale)
    except (research_store.SnapshotError, OSError) as exc:
        st.error(f"Not saved: {exc}")
    else:
        repo = Path(research_store.__file__).parent
        st.success(f"Saved {(path.relative_to(repo) if path.is_relative_to(repo) else path).as_posix()}")
