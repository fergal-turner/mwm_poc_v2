import numpy as np
from matplotlib import patches
from numpy.char import endswith
import pandas as pd

import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap
import plotly.graph_objects as go

from theme import Colors

import supabase
import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

supabase = supabase.create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Oswald:wght@200;300;400;500;600;700&display=swap');

.oswald {
    font-family: 'Oswald', sans-serif;
}
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=300)
def load_data(table, country=None, client=supabase, page_size=1000):
    country_tables = {
        "indicator_values",
        "driver_values",
        "school_values",
    }

    rows = []
    start = 0

    while True:
        query = client.table(table).select("*")

        if country is not None and table in country_tables:
            query = query.ilike("country", country)

        page = (
            query
            .range(start, start + page_size - 1)
            .execute()
            .data
        )

        rows.extend(page)

        if len(page) < page_size:
            break

        start += page_size

    return pd.DataFrame(rows)


def plot_dotplot(data, driver, qual_benchmark=None, quant_benchmark=None, qual_label=None, quant_label=None):
    fig, ax = plt.subplots(figsize=(6, 4))

    plot_df = (
    data.groupby(['driver', 'variable_level', 'school_id'])['value']
    .first()
      .unstack('variable_level')
        .reset_index()
    )

    driver_df = plot_df[plot_df['driver'] == driver]

    ax.scatter(
    driver_df['implementation_quantity'],
    driver_df['implementation_quality'],
    c=[
        Colors.red if sid == 'average' else Colors.green
        for sid in driver_df['school_id']
    ],
    alpha=0.7,
    s=200
    )
    
    if qual_benchmark is not None:
        if qual_benchmark.empty:
            benchmark_qual = None
        else:
            benchmark_qual = qual_benchmark.values[0]
        if benchmark_qual is not None:
            ax.axhline(benchmark_qual, color=Colors.grey_500, linestyle='--', linewidth=1)
    if quant_benchmark is not None:
        if quant_benchmark.empty:
            benchmark_quant = None
        else:
            benchmark_quant = quant_benchmark.values[0]
        if benchmark_quant is not None:
            ax.axvline(benchmark_quant, color=Colors.grey_500, linestyle='--', linewidth=1)


    ax.grid(True, alpha=0.3)
    # ax.set_facecolor('whitesmoke')
    

    ax.set_xlim(0, quant_benchmark.values[0] * 2.2)
    ax.set_xlabel(quant_label if quant_label is not None else "Implementation Quantity", fontsize=12)
    ax.set_ylabel(qual_label if qual_label is not None else "Implementation Quality", fontsize=12)
    ax.set_ylim(0, qual_benchmark.values[0] * 2.2)

    ax.spines[["top", "right"]].set_visible(False)

    plt.rcParams["figure.dpi"] = 200

    return fig, ax

def title_font(text, size=32):
    st.markdown(f'<p class="oswald" style="font-size:{size}px;">{text}</p>', unsafe_allow_html=True)

def narrative_card(title, text, color=Colors.red, size=24):
    st.markdown(
        f"""
        <div style="
            background:white;
            border-left:6px solid {color};
            border-radius:12px;
            padding:20px;
            box-shadow:0 3px 10px rgba(0,0,0,0.1);
        ">
            <div style="font-family:Oswald;font-size:{size}px;">
                {title}
            </div>
            <div style="margin-top:5px;">
                {text}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

def simple_divider(height):
    st.markdown(f"<div style='height:{height}px'></div>", unsafe_allow_html=True)

def section_divider(height):
    st.markdown(f"<div style='height:{height}px'></div>", unsafe_allow_html=True)

    st.markdown(f"""
    <hr style="
        border: none;
        height: 1px;
        background-color: {Colors.grey_700};
        margin-top: 20px;
        margin-bottom: 20px;
    ">
    """, unsafe_allow_html=True)

    st.markdown(f"<div style='height:{height}px'></div>", unsafe_allow_html=True)


#----------- Country Selector (placeholder until Supabase auth) -------------------

COUNTRY_OPTIONS = ["syria", "sudan"]

#----------- Country Selector (placeholder until Supabase auth) -------------------

st.sidebar.markdown('<p class="oswald" style="font-size:24px;">Select Country</p>',
    unsafe_allow_html=True)

COUNTRY = st.sidebar.selectbox("Country", options=COUNTRY_OPTIONS)

indicator_table = load_data("indicator_values", COUNTRY)
driver_indicators = load_data("driver_indicators", country=None)
drivers = load_data("drivers", country=None)

if indicator_table.empty:
    st.warning(f"No complete results for {COUNTRY.title()} yet. Run the pipeline (including build_cmos) first.")
    st.stop()

#------------School Selector--------------------------------------------

st.sidebar.markdown('<p class="oswald" style="font-size:24px;">Select School</p>',
    unsafe_allow_html=True)

SCHOOL_OPTIONS = indicator_table['school_id'].unique()
SCHOOL_OPTIONS = list(SCHOOL_OPTIONS)
SCHOOL_OPTIONS.append('All Schools')
SCHOOL_OPTIONS = sorted(SCHOOL_OPTIONS)
SCHOOL = st.sidebar.selectbox("School", options=SCHOOL_OPTIONS)

#==================MAIN APP==================================

st.markdown(f'<p class="oswald" style="font-size:45px;">Implementation Monitoring for All Drivers</p>',
    unsafe_allow_html=True)

st.text("The following page shows how each of the drivers is performing on both quality and quantity measures.")

#-----------Dotplots-----------------------------------
filtered_indicator_table = indicator_table[indicator_table['school_id'] == SCHOOL] if SCHOOL != 'All Schools' else indicator_table.copy()
driver_list = indicator_table['driver'].unique()

col1, col2 = st.columns(2)

for driver in driver_list:
    df = filtered_indicator_table[filtered_indicator_table['driver'] == driver]
    quality_benchmark = driver_indicators[(driver_indicators['driver_id'] == driver) & (driver_indicators["role"] == "implementation_quality")]['benchmark']
    quality_label = driver_indicators[(driver_indicators['driver_id'] == driver) & (driver_indicators["role"] == "implementation_quality")]['indicator_id'].values[0]
    quality_label = quality_label.replace("_", " ").title()
    quantity_benchmark = driver_indicators[(driver_indicators['driver_id'] == driver) & (driver_indicators["role"] == "implementation_quantity")]['benchmark']
    quantity_label = driver_indicators[(driver_indicators['driver_id'] == driver) & (driver_indicators["role"] == "implementation_quantity")]['indicator_id'].values[0]
    quantity_label = quantity_label.replace("_", " ").title()
    driver_name = drivers.loc[drivers['driver_id'] == driver, 'label'].iloc[0]
    driver_description = drivers.loc[drivers['driver_id'] == driver, 'description'].iloc[0]
    if driver.endswith(("1", "3", "5", "7")):
        with col1:
            st.markdown(f"<p class='oswald' style='font-size:24px;'>{driver_name}</p>", unsafe_allow_html=True)
            st.markdown(f"<p class='arial' style='font-size:16px;'>{driver_description}</p>", unsafe_allow_html=True)
            simple_divider(20)
            fig, ax = plot_dotplot(df, driver, qual_benchmark=quality_benchmark, quant_benchmark=quantity_benchmark, qual_label=quality_label, quant_label=quantity_label)
            st.pyplot(fig)
    else:
        with col2:
            st.markdown(f"<p class='oswald' style='font-size:24px;'>{driver_name}</p>", unsafe_allow_html=True)
            st.markdown(f"<p class='arial' style='font-size:16px;'>{driver_description}</p>", unsafe_allow_html=True)
            simple_divider(20)
            fig, ax = plot_dotplot(df, driver, qual_benchmark=quality_benchmark, quant_benchmark=quantity_benchmark, qual_label=quality_label, quant_label=quantity_label)
            st.pyplot(fig)



def logout():

    try:
        supabase.auth.sign_out()
    except:
        pass

    st.session_state.clear()
    st.rerun()
    
with st.sidebar:
    st.caption(f"Signed in as {st.session_state['user'].email}")

    if st.button("🚪 Logout", use_container_width=True):
        logout()