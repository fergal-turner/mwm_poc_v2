import matplotlib.pyplot as plt
import streamlit as st

from theme import Colors
from db import load_data

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Oswald:wght@200;300;400;500;600;700&display=swap');

.oswald {
    font-family: 'Oswald', sans-serif;
}
</style>
""", unsafe_allow_html=True)


def plot_dotplot(driver_df, qual_benchmark=None, quant_benchmark=None, qual_label=None, quant_label=None):
    fig, ax = plt.subplots(figsize=(6, 4), dpi=120)

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
        ax.axhline(qual_benchmark, color=Colors.grey_500, linestyle='--', linewidth=1)
    if quant_benchmark is not None:
        ax.axvline(quant_benchmark, color=Colors.grey_500, linestyle='--', linewidth=1)

    ax.grid(True, alpha=0.3)

    ax.set_xlim(0, quant_benchmark * 2.2)
    ax.set_xlabel(quant_label if quant_label is not None else "Implementation Quantity", fontsize=12)
    ax.set_ylabel(qual_label if qual_label is not None else "Implementation Quality", fontsize=12)
    ax.set_ylim(0, qual_benchmark * 2.2)

    ax.spines[["top", "right"]].set_visible(False)

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

indicator_table = load_data(
    "indicator_values", COUNTRY,
    columns="school_id,driver,variable_level,value",
)
driver_indicators = load_data(
    "driver_indicators",
    columns="driver_id,role,indicator_id,benchmark",
)
drivers = load_data("drivers", columns="driver_id,label,description")

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

plot_df = (
    filtered_indicator_table
    .groupby(['driver', 'variable_level', 'school_id'])['value']
    .first()
    .unstack('variable_level')
    .reset_index()
)

bench = driver_indicators.drop_duplicates(['driver_id', 'role']).set_index(['driver_id', 'role'])[['benchmark', 'indicator_id']]
driver_meta = drivers.drop_duplicates('driver_id').set_index('driver_id')

for driver in driver_list:
    driver_df = plot_df[plot_df['driver'] == driver]
    quality_benchmark, quality_label = bench.loc[(driver, "implementation_quality")]
    quantity_benchmark, quantity_label = bench.loc[(driver, "implementation_quantity")]
    quality_label = quality_label.replace("_", " ").title()
    quantity_label = quantity_label.replace("_", " ").title()
    driver_name = driver_meta.at[driver, 'label']
    driver_description = driver_meta.at[driver, 'description']
    with (col1 if driver.endswith(("1", "3", "5", "7")) else col2):
        st.markdown(f"<p class='oswald' style='font-size:24px;'>{driver_name}</p>", unsafe_allow_html=True)
        st.markdown(f"<p class='arial' style='font-size:16px;'>{driver_description}</p>", unsafe_allow_html=True)
        simple_divider(20)
        fig, ax = plot_dotplot(driver_df, qual_benchmark=quality_benchmark, quant_benchmark=quantity_benchmark, qual_label=quality_label, quant_label=quantity_label)
        st.pyplot(fig)
        plt.close(fig)


def logout():
    st.session_state.clear()
    st.rerun()
    
with st.sidebar:
    st.caption(f"Signed in as {st.session_state['user'].email}")

    if st.button("🚪 Logout", use_container_width=True):
        logout()