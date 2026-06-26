
from dash import Dash, html, dcc, Input, Output
import pandas as pd

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

def load_classification_maps():
    classification_map = {}
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

# --- COUNTRY SELECTION ---

country_list = list(pd.read_csv(DATA_DIR / "import_log.csv")["country"].unique())


app = Dash(__name__)

# --- helpers (reuse your existing ones) ---
def load_data(level, country):
    combined = load_combined(OUTPUT_DIR, country=country, level=level)
    if combined is None:
        return None, None
    return combined.df_short, combined.df_summary


# --- UI ---
app.layout = html.Div([

    dcc.Dropdown(
        id="country",
        options=[{"label": c, "value": c} for c in country_list],
        placeholder="Select country"
    ),

    dcc.Tabs(
        id="level",
        value="child",
        children=[
            dcc.Tab(label="Child", value="child"),
            dcc.Tab(label="Teacher", value="teacher"),
            dcc.Tab(label="School", value="school"),
        ]
    ),

    dcc.Dropdown(id="indicator_filter", multi=True, placeholder="Filter indicators"),
    dcc.Dropdown(id="dimension_filter", multi=True, placeholder="Filter dimensions"),

    html.Div(id="grid")
])

def make_grid(figures):
    return html.Div(
        [
            dcc.Graph(figure=fig)
            for fig in figures
        ],
        style={
            "display": "grid",
            "gridTemplateColumns": "repeat(3, 1fr)",
            "gap": "20px"
        }
    )

def generate_plot_list(df, summary):

    indicators = summary.get("available_indicators", [])
    dimensions = summary.get("available_dimensions", [])

    plots = []

    for indicator in indicators:
        for dim in dimensions:

            if indicator not in df.columns or dim not in df.columns:
                continue

            df_pair = df[[indicator, dim]].dropna()
            if df_pair.empty:
                continue

            ind_cat = classification_map.get(indicator)
            dim_cat = classification_map.get(dim)

            # plot selection (same logic as yours)
            if dim_cat in ("categorical", "ordinal") and ind_cat == "ordinal":
                plot_type = "stacked_bar"

            elif dim_cat == "categorical" and ind_cat == "numeric":
                plot_type = "mean_bar"

            elif dim_cat == "ordinal" and ind_cat == "numeric":
                plot_type = "line"

            elif dim_cat == "numeric" and ind_cat == "numeric":
                plot_type = "scatter"

            else:
                continue

            fig = plotter("dynamic", plot_type, df_pair, dim, indicator)

            plots.append({
                "indicator": indicator,
                "dimension": dim,
                "fig": fig
            })

    return plots

@app.callback(
    Output("grid", "children"),
    Input("country", "value"),
    Input("level", "value"),
    Input("indicator_filter", "value"),
    Input("dimension_filter", "value"),
)

def toggle_filters(country, level):
    disabled = not (country and level)
    return disabled, disabled

def update_grid(country, level, indicator_filter, dimension_filter):

    if not country or not level:
        return html.Div("Select country and level")

    df, summary = load_data(level, country)
    if df is None:
        return html.Div("No data")

    plots = generate_plot_list(df, summary)

    # --- apply filters ---
    if indicator_filter:
        plots = [p for p in plots if p["indicator"] in indicator_filter]

    if dimension_filter:
        plots = [p for p in plots if p["dimension"] in dimension_filter]

    # --- take first 6 ---
    plots = plots[:6]

    # extract figures
    figures = [p["fig"] for p in plots]

    return make_grid(figures)



if __name__ == "__main__":
    app.run(debug=True)
