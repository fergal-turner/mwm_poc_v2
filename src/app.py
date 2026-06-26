import streamlit as st
import pandas as pd
from pathlib import Path
import sys
import os, json
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils import get_project_context
from src.report import vars_from_df, plotter, classify_series, classify_from_config
from src.combine import load_combined, add_to_combined
from src.ingest import build_dataset
from src.aggregate import aggregates

context = get_project_context(start_path=Path(__file__).resolve())
OUTPUT_DIR = context["output_dir"]
DATA_DIR   = context["data_dir"]
INPUT_DIR  = context["input_dir"]
CONFIG_DIR = context["config_dir"]

# --- load classification map for all indicators at all levels ---

@st.cache_data
def load_classification_maps():
    \"\"\"Load indicator and dimension classification maps from config files.
    
    Reads all level config files and dimensions config to create mappings of\n    indicator/dimension ID -> type (categorical, ordinal, numeric) and\n    indicator ID -> level (child, teacher, school).\n    \n    Returns\n    -------\n    tuple\n        (classification_map dict, level_map dict)\n    \"\"\"\n    classification_map = {}
    level_map = {}

    for level in ["child", "teacher", "school"]:
        with open(os.path.join(CONFIG_DIR, f"{level}_config.json"), encoding="utf-8") as f:
            config = json.load(f)

        # adjust keys to your schema
        for ind in config.get("indicators", []):
            classification_map[ind["id"]] = ind.get("type")
            level_map[ind["id"]] = ind.get("level")

    with open(os.path.join(CONFIG_DIR, f"dimensions_config.json"), encoding="utf-8") as f:
        config = json.load(f)

    for dim in config.get("dimensions", []):
            classification_map[dim["id"]] = dim.get("type")

    return classification_map, level_map

classification_map, level_map = load_classification_maps()

level_to_inds = defaultdict(list)
for ind, lvl in level_map.items():
    level_to_inds[lvl].append(ind)


# --- CONFIG ---
st.set_page_config(layout="wide")

# --- COUNTRY SELECTION ---

country_list = list(pd.read_csv(DATA_DIR / "import_log.csv")["country"].unique())
country = st.sidebar.selectbox("Select country", country_list)


# --- LOAD DATA ---
@st.cache_data
def load_data(level, country):
    \"\"\"Load combined dataset for a specific level and country from disk.
    
    Reads the combined CSV and summary JSON for a level/country, deduplicates\n    on UUID, and returns both the full dataframe and a summary of available\n    indicators/dimensions.\n    \n    Parameters\n    ----------\n    level : str\n        Survey level ('child', 'teacher', or 'school')\n    country : str\n        Country name\n        \n    Returns\n    -------\n    tuple\n        (df_short, df_summary) where df_short has deduplicated rows and\n        df_summary contains available/missing indicator and dimension lists\n    \"\"\"\n    combined = load_combined(OUTPUT_DIR, country=country, level=level)
    if combined is None:
        return None, None
    return combined.df_short, combined.df_summary

child_df,   child_summary   = load_data(level="child",   country=country)
teacher_df, teacher_summary = load_data(level="teacher", country=country)
school_df,  school_summary  = load_data(level="school",  country=country)


# --- PAGE SELECT ---
page = st.sidebar.selectbox(
    "Page",
    ["Dashboard", "Input / Output"]
)

# =========================
# DASHBOARD PAGE
# =========================

def render_tab(df, summary, level, label):
    """Render indicator tabs and dimension filters for one survey level."""
    if df is None or df.empty:
        st.info(f"No {label.lower()} data available")
        return

    st.header(label)

    indicators = [i for i in summary.get("available_indicators", []) if i in df.columns]
    dimensions = [d for d in summary.get("available_dimensions", []) if d in df.columns]

    if not indicators:
        st.info("No indicators available in the loaded dataset")
        return

    # Sidebar dimension filters.
    df_filtered = df.copy()

    with st.sidebar.expander(f"{label} filters", expanded=False):
        for dim in dimensions:
            if dim in ['admin1', 'admin2', 'admin3', 'school']:
                options = sorted(df_filtered[dim].dropna().unique())
                chosen  = st.multiselect(dim.replace("_", " ").capitalize(), options, key=f"{label}_{dim}")
                if chosen:
                    df_filtered = df_filtered[df_filtered[dim].isin(chosen)]

    # One tab per indicator.
    indicator_tabs = st.tabs([i.replace("_", " ").capitalize() for i in indicators])

    for i, indicator in enumerate(indicators):
        with indicator_tabs[i]:
            st.subheader(indicator.replace("_", " ").capitalize())
            
            for dim in dimensions:
                if dim not in ['sex', 'age', 'location', 'protection_status', 'round', 'date_time']:
                    continue
                df_pair = df_filtered[[indicator, dim]].dropna()
                if df_pair.empty:
                    continue

                ind_cat = classification_map.get(indicator)
                dim_cat = classification_map.get(dim)

                if dim_cat in ("categorical", "ordinal"):
                    if dim == "date_time":
                        df_pair[dim] = pd.to_datetime(df_pair[dim], errors="coerce").dt.floor("D")
                        df_pair = df_pair.sort_values(dim)
                    else:
                        df_pair = df_pair.copy()
                        col = df_pair[dim]
                        numeric = pd.to_numeric(col, errors="coerce")
                        if numeric.notna().any() and (numeric.dropna() % 1 == 0).all():
                            df_pair[dim] = numeric.astype("Int64").astype(str)
                        else:
                            df_pair[dim] = col.astype(str)

                if dim_cat in ("categorical", "ordinal") and ind_cat == "ordinal":
                    plot_type = "stacked_bar"

                elif dim_cat == "categorical" and ind_cat == "numeric":
                    plot_type = "mean_bar"

                elif dim_cat == "ordinal" and ind_cat == "numeric":
                    plot_type = "line"

                elif dim_cat == "numeric" and ind_cat == "ordinal":
                    ind_num = pd.to_numeric(df_pair[indicator], errors="coerce")
                    if ind_num.notna().any() and (ind_num.dropna() % 1 == 0).all():
                        df_pair[indicator] = ind_num.astype("Int64")
                        plot_type = "line"

                elif dim_cat == "numeric" and ind_cat == "numeric":
                    plot_type = "scatter"

                fig = plotter("dynamic", plot_type, df_pair, dim, indicator)
                
                if plot_type == "scatter" and ind_cat == "ordinal":
                    fig.update_yaxes(dtick=1, tickmode="linear")

                if dim == "date_time":    
                    fig.update_xaxes(
                        type="date",
                        tickformat="%Y-%m-%d",
                        nticks=8
                    )

                st.markdown(f"**By {dim.replace('_', ' ').capitalize()}**")
                st.plotly_chart(fig, width="content")

def render_school_tab(df, summary, level, label):
    """Render indicator tabs and dimension filters for school level data."""
    if df is None or df.empty:
        st.info(f"No {label.lower()} data available")
        return

    st.header(label)

    indicators = [i for i in summary.get("available_indicators", []) if i in df.columns]
    dimensions = [d for d in summary.get("available_dimensions", []) if d in df.columns]

    if not indicators:
        st.info("No indicators available in the loaded dataset")
        return

    # Sidebar dimension filters.
    df_filtered = df.copy()

    with st.sidebar.expander(f"{label} filters", expanded=False):
        for dim in dimensions:
            if dim in ['admin1', 'admin2', 'admin3', 'school']:
                options = sorted(df_filtered[dim].dropna().unique())
                chosen  = st.multiselect(dim.replace("_", " ").capitalize(), options, key=f"{label}_{dim}")
                if chosen:
                    df_filtered = df_filtered[df_filtered[dim].isin(chosen)]


    level_names = ['School', 'Teacher', 'Child']
    level_tabs = st.tabs(level_names)
    
    for i, level in enumerate(level_names):   # whatever you used to create tabs
        with level_tabs[i]:

            for indicator in indicators:
                if level_map.get(indicator).capitalize() != level:
                    continue
                if level == "School":
                    dims_to_use = ['school', 'location', 'round', 'date_time']
                else:
                    dims_to_use = ['school']

                for dim in dimensions:
                    if dim not in dims_to_use:
                        continue

                    df_pair = df_filtered[[indicator, dim]].dropna()
                    if df_pair.empty:
                        continue
                    
                    if indicator in ['aser_literacy', 'aser_numeracy']:
                        ind_cat = 'numeric'
                    else:
                        ind_cat = classification_map.get(indicator)

                    dim_cat = classification_map.get(dim)

                    if dim_cat in ("categorical", "ordinal"):
                        df_pair = df_pair.copy()
                        col = df_pair[dim]
                        numeric = pd.to_numeric(col, errors="coerce")
                        if numeric.notna().any() and (numeric.dropna() % 1 == 0).all():
                            df_pair[dim] = numeric.astype("Int64").astype(str)
                        else:
                            df_pair[dim] = col.astype(str)
                            
                    if dim_cat in ("categorical", "ordinal") and ind_cat == "ordinal":
                        plot_type = "stacked_bar"

                    elif dim_cat == "categorical" and ind_cat == "numeric":
                        plot_type = "mean_bar"

                    elif dim_cat == "ordinal" and ind_cat == "numeric":
                        plot_type = "line"

                    elif dim_cat == "numeric" and ind_cat == "ordinal":
                        ind_num = pd.to_numeric(df_pair[indicator], errors="coerce")
                        if ind_num.notna().any() and (ind_num.dropna() % 1 == 0).all():
                            df_pair[indicator] = ind_num.astype("Int64")
                            plot_type = "line"

                    elif dim_cat == "numeric" and ind_cat == "numeric":
                        plot_type = "scatter"
                    else:
                        continue

                    fig = plotter("dynamic", plot_type, df_pair, dim, indicator)

                    if dim == "date_time":
                        fig.update_xaxes(dtick="D1", tickformat="%Y-%m-%d")

                    if plot_type == "scatter" and ind_cat == "ordinal":
                        fig.update_yaxes(dtick=1, tickmode="linear")

                    st.markdown(f"**{ind.replace('_', ' ').capitalize()} by {dim.replace('_', ' ').capitalize()}**")
                    st.plotly_chart(fig, width="content")


if page == "Dashboard":
    st.title("Dashboard")
    tab1, tab2, tab3 = st.tabs(["Child", "Teacher", "School"])
    with tab1:
        render_tab(child_df, child_summary, "child", "Child")
    with tab2:
        render_tab(teacher_df, teacher_summary, "teacher", "Teacher")
    with tab3:
        render_school_tab(school_df, school_summary, "school", "School")

# =========================
# INPUT / OUTPUT PAGE
# =========================
elif page == "Input / Output":

    st.title("Input / Output")

    source = st.radio("Data source", ["Upload file", "Kobo API"], horizontal=True)

    # ------------------------------------------------------------------
    # FILE UPLOAD
    # ------------------------------------------------------------------
    if source == "Upload file":
        uploaded_file = st.file_uploader("Upload CSV or Excel", type=["csv", "xls", "xlsx"])

        st.markdown("### Metadata (for new form IDs)")
        meta_form_id = st.text_input("Form ID (optional if present in file)")
        meta_survey = st.text_input("Survey name")
        meta_level = st.selectbox("Survey level", ["child", "teacher", "school"])
        meta_country = st.text_input("Country (optional if present in data)")
        meta_first = st.date_input("First date (optional if present in data)", value=None)

        if uploaded_file:
            import tempfile, os
            suffix = Path(uploaded_file.name).suffix
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(uploaded_file.read())
                tmp_path = tmp.name

            st.subheader("Preview")
            if suffix == ".csv":
                st.dataframe(pd.read_csv(tmp_path).head())
            else:
                st.dataframe(pd.read_excel(tmp_path).head())

            if st.button("Add to data model"):
                with st.spinner("Running ingest \u2192 aggregate \u2192 combine \u2026"):
                    try:
                        metadata_overrides = {
                            "form_id": meta_form_id or None,
                            "survey_name": meta_survey or None,
                            "level": meta_level or None,
                            "country": meta_country or None,
                            "first_submission" : meta_first.isoformat() if meta_first else None,
                        }
                        dataset  = build_dataset(
                            file_path=tmp_path,
                            metadata_overrides=metadata_overrides,
                            interactive=False,
                        )
                        dataset  = aggregates(dataset)
                        combined = add_to_combined(dataset, OUTPUT_DIR)
                        load_data.clear()
                        st.success(
                            f"Added {combined.metadata['row_count']} rows to "
                            f"{combined.metadata['country']} / {combined.metadata['level']} combined dataset."
                        )
                    except Exception as exc:
                        st.error(f"Pipeline failed: {exc}")
                    finally:
                        os.unlink(tmp_path)

    # ------------------------------------------------------------------
    # KOBO API
    # ------------------------------------------------------------------
    
    elif source == "Kobo API":
        with st.form("kobo_form"):
            base_url  = st.text_input("Kobo base URL", placeholder="https://kobocat.example.org/api/v2/assets/")
            asset_id  = st.text_input("Asset ID")
            api_key   = st.text_input("API key", type="password")
            meta_survey = st.text_input("Survey name")
            meta_level = st.selectbox("Survey level", ["child", "teacher", "school"], key="kobo_level")
            meta_country = st.text_input("Country (optional if present in data)")
            submitted = st.form_submit_button("Fetch and add to data model")

        if submitted:
            if not all([base_url, asset_id, api_key]):
                st.warning("Please fill in all three Kobo fields.")
            else:
                with st.spinner("Fetching from Kobo \u2192 aggregate \u2192 combine \u2026"):
                    try:
                        metadata_overrides = {
                            "survey_name": meta_survey or None,
                            "level": meta_level or None,
                            "country": meta_country or None,
                        }
                        dataset  = build_dataset(
                            BASE_URL=base_url,
                            ASSET_ID=asset_id,
                            API_KEY=api_key,
                            metadata_overrides=metadata_overrides,
                            interactive=False,
                        )
                        dataset  = aggregates(dataset)
                        combined = add_to_combined(dataset, OUTPUT_DIR)
                        load_data.clear()
                        st.success(
                            f"Added {combined.metadata['row_count']} rows to "
                            f"{combined.metadata['country']} / {combined.metadata['level']} combined dataset."
                        )
                    except Exception as exc:
                        st.error(f"Pipeline failed: {exc}")