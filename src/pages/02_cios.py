from matplotlib import patches
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
def load_data(table, country, client=supabase, page_size=1000):
    rows, start = [], 0
    while True:
        page = (
            client.table(table)
            .select("*")
            .ilike("country", country)
            .order("country")
            .range(start, start + page_size - 1)
            .execute()
            .data
        )
        rows.extend(page)
        if len(page) < page_size:
            break
        start += page_size

    return pd.DataFrame(rows)

@st.cache_data
def wide_table(table, level, binary = False):
    if binary == False:
        wide = table.pivot(index=level, columns="variable", values = "value")
    else:
       wide = table.pivot(index=level, columns = "variable", values="value_binary")

    level_dict = dict(zip(table["variable"], table["variable_level"]))
    print(level_dict)

    suffix_dict = {
        "outcome": " \n(Outcome)",
        "context": " \n(Context)",
        "implementation_quality": " \n(Quality)",
        "implementation_quantity": " \n(Quantity)"
    }

    rename_dict = {
        col: f"{col}\n{suffix_dict[level_dict[col]]}"
        for col in wide.columns
        if col in level_dict
    }

    wide = wide.rename(columns=rename_dict)

    order = {
    " \n(Context)": 0,
    " \n(Quality)": 1,
    " \n(Quantity)": 2,
    " \n(Outcome)": 3
    }

    sorted_cols = sorted(
        wide.columns,
        key=lambda c: next(
            (v for k, v in order.items() if c.endswith(k)),
            999  # columns without a suffix go last
        )
    )

    wide = wide[sorted_cols]

    wide.columns = wide.columns.str.replace("_", " ").str.title()
    wide = wide.round(2)

    return wide

def plot_cio_dotplot(cio_table, context):
    fig, ax = plt.subplots(figsize=(6, 3))
    df = cio_table[cio_table['context'] == context].copy()
    
    df["x"] = df["implementation_quantity"].map({"Low": 0, "High": 1})
    df["y"] = df["implementation_quality"].map({"Low": 0, "High": 1})


    sns.scatterplot(
        data=df,
        x="x",
        y="y",
        hue="outcome",
        size="schools",
        palette="RdYlGn",
        sizes=(1000, 2000),
        linewidth=0,
        legend="brief",
        zorder=3
    )
    
    ax.set_xticks([])
    ax.set_yticks([])

    # ax.add_patch(patches.Rectangle((-0.5, -.5), 1, 1, linewidth=0, facecolor=Colors.light_red, zorder=1 ))
    # ax.add_patch(patches.Rectangle((-0.5, .5), 1, 1, linewidth=0, facecolor=Colors.light_yellow, zorder=1 ))
    # ax.add_patch(patches.Rectangle((.5, .5), 1, 1, linewidth=0, facecolor=Colors.light_green, zorder=1 ))
    # ax.add_patch(patches.Rectangle((.5, -.5), 1, 1, linewidth=0, facecolor=Colors.light_yellow, zorder=1 ))

    ax.text(-0.48, -0.47, 'Low quality, \nLow frequency', fontsize=8, va='bottom', color=Colors.grey_900)
    ax.text(-0.48, 1.47, 'Low quality, \nHigh frequency', fontsize=8, va='top', color=Colors.grey_900)
    ax.text(1.48, 1.47, 'High quality, \nHigh frequency', fontsize=8, ha='right', va='top', color=Colors.grey_900)
    ax.text(1.48, -0.48, 'High quality, \nLow frequency', fontsize=8, ha='right', va='bottom', color=Colors.grey_900)

    ax.set_xlim(-0.5, 1.5)
    ax.set_ylim(-0.5, 1.5)

    ax.axvline(0.5, color=Colors.grey_700, linewidth=1)
    ax.axhline(0.5, color=Colors.grey_700, linewidth=1)

    ax.grid(True, alpha=0.3)
    # ax.set_facecolor('whitesmoke')
    
    ax.set_xlabel("")
    ax.legend().set_visible(False)
    ax.set_xticklabels("", fontname='Arial', fontsize=10, fontweight='bold')
    ax.set_yticklabels("", rotation=0, fontname='Arial', fontsize=10, fontweight='bold')
    ax.set_ylabel("")
    ax.grid(False)
    ax.spines[["top", "right", "left", "bottom"]].set_visible(False)

    plt.rcParams["figure.dpi"] = 300

    return fig, ax
    

def plot_cio_heatmap(cio_table, context):
    fig, ax = plt.subplots(figsize=(8, 2))

    cmap = LinearSegmentedColormap.from_list(
        "mwm",
        [Colors.grey_500, Colors.light_green, Colors.green]
    )

    overall_avg = cio_table["outcome"].mean()
    table = cio_table[cio_table['context'] == context]
    table = table[['implementation_quality', 'implementation_quantity', 'outcome']]

    heatmap_data = table.pivot(
        index="implementation_quantity",
        columns="implementation_quality",
        values="outcome"
    )

    heatmap_data = heatmap_data.reindex(
        index=["High", "Low"],
        columns=["Low", "High"]
    )

    sns.heatmap(
        heatmap_data,
        annot=True,
        annot_kws={"size": 10, "weight": "bold"},
        linewidths=1,
        linecolor=Colors.grey_200,
        fmt=".2f",
        cmap=cmap,
        center=overall_avg,
        cbar=False,
        ax=ax
    )

    ax.set_xlabel("")
    ax.set_xticklabels(["Low \nQuality", "High \nQuality"], fontname='Arial', fontsize=10, fontweight='bold')
    ax.set_yticklabels(["Low \nFrequency", "High \nFrequency"], rotation=0, fontname='Arial', fontsize=10, fontweight='bold')
    ax.set_ylabel("")
    ax.grid(False)

    plt.rcParams["figure.dpi"] = 300

    return fig, ax

def benchmark_bar(value, benchmark=2.5, title="Quality"):

    fig = go.Figure()

    # scale line
    fig.add_shape(
        type="line",
        x0=0, x1=4,
        y0=0, y1=0,
        line=dict(color="lightgrey", width=8)
    )

    # benchmark marker
    fig.add_shape(
        type="line",
        x0=benchmark, x1=benchmark,
        y0=-0.3, y1=0.3,
        line=dict(color="red", width=3)
    )

    # value dot
    fig.add_trace(
        go.Scatter(
            x=[value],
            y=[0],
            mode="markers+text",
            text=[f"{value:.2f}"],
            textposition="top center",
            marker=dict(size=18, color="green")
        )
    )

    fig.update_layout(
        title=title,
        height=100,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis=dict(range=[0, 4]),
        yaxis=dict(visible=False),
        showlegend=False
    )

    plt.rcParams["figure.dpi"] = 200

    return fig

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

#----------- Load Data -----------

#----------- Country Selector (placeholder until Supabase auth) -------------------

COUNTRY_OPTIONS = ["syria", "sudan"]

st.sidebar.markdown('<p class="oswald" style="font-size:24px;">Select Country</p>',
    unsafe_allow_html=True)

COUNTRY = st.sidebar.selectbox("Country", options=COUNTRY_OPTIONS)

school_table_all = load_data("indicator_values", COUNTRY)
cio_table_all = load_data("cio_table", COUNTRY)
narratives_all = load_data("narratives", COUNTRY)

if school_table_all.empty or cio_table_all.empty or narratives_all.empty:
    st.warning(f"No complete results for {COUNTRY.title()} yet. Run the pipeline (including build_cmos) first.")
    st.stop()

#----------- Driver Selector -------------------

driver_options = sorted(school_table_all["driver"].unique())

@st.cache_data(ttl=600)
def load_driver_info():
    try:
        rows = supabase.table("drivers").select("*").execute().data
    except Exception:
        return {}
    return {r["driver_id"]: r for r in rows}

driver_info = load_driver_info()

st.sidebar.markdown('<p class="oswald" style="font-size:24px;">Select Driver</p>',
    unsafe_allow_html=True)
driver = st.sidebar.selectbox(
    "Driver", options=driver_options,
    format_func=lambda d: f"{d} - {driver_info[d]['label']}" if d in driver_info else d,
)
driver_label = driver_info.get(driver, {}).get("label") or driver
driver_description = driver_info.get(driver, {}).get("description") or ""

school_table = school_table_all[school_table_all["driver"] == driver]
cio_table = cio_table_all[cio_table_all["driver"] == driver]
narratives = narratives_all[narratives_all["driver"] == driver]

values_wide = wide_table(school_table, level="school_id")
binary_wide = wide_table(school_table, level="school_id", binary=True)

# average row first (the app reads it as iloc[0]), then schools sorted by id
def average_first(df):
    schools = sorted(i for i in df.index if i != "average")
    return df.loc[[i for i in ["average"] if i in df.index] + schools]

values_wide = average_first(values_wide)
binary_wide = average_first(binary_wide)

outcome_variable = school_table[school_table['variable_level'] == "outcome"]['variable'].values[0]
outcome_variable = outcome_variable.replace("_", " ").title()

#----------- Sidebar Selecter -------------------

context_options = cio_table['context'].unique()

st.sidebar.markdown('<p class="oswald" style="font-size:24px;">Select Context Variable</p>',
    unsafe_allow_html=True)
st.sidebar.text("Choosing a variable allows you to see how it influences ")

sidebar = st.sidebar.radio(
    "Context Variable",
    options=[option.replace("_", " ").title() for option in context_options]
)

filtered_cio_table = cio_table[cio_table['context'].str.replace("_", " ").str.title() == sidebar]

st.sidebar.markdown('<p class="oswald" style="font-size:24px;">Outcome Variable</p>',
    unsafe_allow_html=True)

st.sidebar.text(f"{outcome_variable}")

st.sidebar.markdown('<p class="oswald" style="font-size:24px;">Implementation Variables</p>',
    unsafe_allow_html=True)

# =================MAIN APP==================

st.markdown(f'<p class="oswald" style="font-size:64px;">{driver_label}</p>',
    unsafe_allow_html=True)

if driver_description:
    st.markdown(f"*{driver_description}*")

st.text("The following page shows how implementation quantity, quality and context relate to the outcome variable.")


#------------ Benchmark Bars --------------------


columns = values_wide.columns.to_list()

averages = values_wide.iloc[0]
outcome = averages[columns[-1]] 
quantity = averages[columns[-2]]
quality = averages[columns[-3]]

col1, col2, col3 = st.columns(3)


with col1:
    st.metric("Attendance", "72%", "+4%")

with col2:
    st.metric("Teaching Quality", "3.2", "-0.1")

with col3:
    st.metric("Literacy", "61%", "+8%")

section_divider(0)


#------------ General Heatmap -------------------

title_font("Overall Averages", size=28)
st.text("This shows how implementation impacts outcomes when no context variables are considered")

fig, ax= plot_cio_dotplot(cio_table, "None")

with st.container(border=False):
    st.pyplot(fig)

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

match = narratives.loc[narratives['table_name'] == "none", 'narrative']
narrative = match.values[0] if len(match) else ""

narrative_card(title="Narrative", text=narrative,  size=24) 

simple_divider(10)

#------------ Context-Specific Heatmap -------------------
context = sidebar.replace(" ", "_").lower()

fig, ax = plot_cio_dotplot(filtered_cio_table, context)
fig.patch.set_facecolor("#FFFFFF")
ax.set_facecolor("#FFFFFF")

title_font(f"Context: {sidebar}", size=28)

with st.container():
    st.pyplot(fig)


match = narratives.loc[narratives['table_name'] == context, 'narrative']
narrative = match.values[0] if len(match) else ""

narrative_card(title="Narrative", text=narrative, color=Colors.purple, size=24) 

section_divider(10)

#----------- Create Bottom Summary Table --------------------

title_font("Data for all schools", size=28)

numeric_cols = values_wide.select_dtypes("number").columns
diffs = values_wide[numeric_cols].subtract(values_wide[numeric_cols].iloc[0])


styler = values_wide.style
for col in numeric_cols:
    styler = styler.background_gradient(cmap="RdYlGn", subset=[col], gmap=diffs[col], axis=0)

st.table(
    styler.set_properties(subset=pd.IndexSlice[[values_wide.index[0]], :], **{
            "background-color": Colors.grey_200
        })
        .format("{:.2f}")
            )

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