"""Streamlit entry: only switches pages. Run with run_app.bat (streamlit run app.py)."""
import streamlit as st

pg = st.navigation([
    st.Page("pages/portfolio.py", title="Portfolio", default=True),
    st.Page("pages/research.py", title="Research"),
    st.Page("pages/library.py", title="Library"),
])
st.set_page_config(layout="wide" if pg.title == "Portfolio" else "centered")
pg.run()
