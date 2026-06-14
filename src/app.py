import streamlit as st
import pandas as pd
from pathlib import Path
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

# --- CONFIG ---
st.set_page_config(layout="wide")

# --- COUNTRY SELECTION ---

country_list = list(pd.read_csv(DATA_DIR / "import_log.csv")["country"].unique())
country = st.sidebar.selectbox("Select country", country_list)


# --- LOAD DATA ---
@st.cache_data
def load_data(level, country):
    combined = load_combined(OUTPUT_DIR, country=country, level=level)
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

    indicators = summary["available_indicators"]
    dimensions = summary["available_dimensions"]

    if not indicators:
        st.info("No indicators available")
        return

    # Sidebar dimension filters.
    df_filtered = df.copy()

    with st.sidebar.expander(f"{label} filters", expanded=False):
        for dim in dimensions:
            if dim in df_filtered.columns:
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
                if dim not in df_filtered.columns:
                    continue
                df_pair = df_filtered[[indicator, dim]].dropna()
                if df_pair.empty:
                    continue

                ind_cat, _ = classify_from_config(df_pair[indicator], level=level, config_dir=CONFIG_DIR)
                dim_cat, _ = classify_from_config(df_pair[dim], level=level, config_dir=CONFIG_DIR)

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

                else:
                    plot_type = "scatter"
                fig = plotter("dynamic", plot_type, df_pair, dim, indicator)
                if plot_type == "scatter" and ind_cat == "ordinal":
                    fig.update_yaxes(dtick=1, tickmode="linear")
                st.markdown(f"**By {dim.replace('_', ' ').capitalize()}**")
                st.plotly_chart(fig, use_container_width=True)


if page == "Dashboard":
    st.title("Dashboard")
    tab1, tab2, tab3 = st.tabs(["Child", "Teacher", "School"])
    with tab1:
        render_tab(child_df, child_summary, "child", "Child")
    with tab2:
        render_tab(teacher_df, teacher_summary, "teacher", "Teacher")
    with tab3:
        render_tab(school_df, school_summary, "school", "School")

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