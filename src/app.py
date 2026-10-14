import streamlit as st

alldrivers = st.Page("pages/01_alldrivers.py", title="Data for all Drivers")
cios = st.Page("pages/02_cios.py", title="CIO Combinations")

pg = st.navigation([alldrivers, cios])

st.set_page_config(page_title="Measuring What Matters Data Hub")

pg.run()