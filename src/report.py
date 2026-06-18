"""Reporting helpers: colours, chart themes, figure building.

Typical usage from app.py
--------------------------
    from src.report import vars_from_df, plotter, classify_series

    indicators, dimensions = vars_from_df(df, config_dir)

    # -- OR, when working with a full DataSet object --
    from src.report import data_map, fig_list, show_figures

    dm          = data_map(dataset)
    indicators  = dm[dm["ind_type"] == "indicator"]["name"].tolist()
    dimensions  = dm[dm["ind_type"] == "dimension"]["name"].tolist()
    figs, specs = show_figures(dataset, kind="dynamic")
"""

import json
import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
import seaborn as sns

from src.theme import Colors, get_ordinal_colors, sc_theme  # noqa: F401 (re-exported)



# ========================================================================
# DATA MAP  (indicators & dimensions available in a dataset)
# ========================================================================

def classify_series(col):
    """Return (category, range_descriptor) for a Series."""
    name = col.name.lower()
    nunique = col.nunique(dropna=True)

    # name-based override
    if "admin" in name:
        return "categorical"

    if pd.api.types.is_numeric_dtype(col):
        if nunique > 10:
            return "numeric", (col.min(), col.max())
        return "ordinal"

    return "categorical"

def classify_from_config(col, level, config_dir):
    """Return (category, range_descriptor) for a Series based on config files."""
    config_dir = Path(config_dir)

    with open(config_dir / f"{level}_config.json", encoding="utf-8") as f:
        indicator_cfg = json.load(f)
    with open(config_dir / "dimensions_config.json", encoding="utf-8") as f:
        dim_cfg = json.load(f)

    all_indicator_ids = {ind["id"]: ind for ind in indicator_cfg.get("indicators", [])}
    all_dimension_ids = {dim["id"]: dim for dim in dim_cfg.get("dimensions", [])}

    name = col.name

    if name in all_indicator_ids:
        ind_type = all_indicator_ids[name]["type"]
        if ind_type == "numeric":
            return "numeric", (col.min(), col.max())
        elif ind_type == "ordinal":
            return "ordinal", col.nunique(dropna=True)
        else:
            return "categorical", col.nunique(dropna=True)

    if name in all_dimension_ids:
        dim_type = all_dimension_ids[name]["type"]
        if dim_type == "categorical":
            return "categorical", col.nunique(dropna=True)
        elif dim_type == "ordinal":
            return "ordinal", col.nunique(dropna=True)
        elif dim_type == "numeric":
            return "numeric", (col.min(), col.max())
        elif dim_type == "derived":
            return classify_series(col)
    # Fallback to default classification

def vars_from_df(df, config_dir):
    """Return (indicators, dimensions) lists for columns that exist in *df*.

    Reads ``child_config.json`` and ``dimensions_config.json`` from
    *config_dir* and filters to the IDs that are present as columns in *df*.
    This is the correct function to use in ``app.py`` where data is loaded
    from a flat combined CSV rather than a full DataSet object.

    Parameters
    ----------
    df : pd.DataFrame
        The combined-level DataFrame loaded from CSV.
    config_dir : Path | str
        Directory containing the JSON config files.
    """
    config_dir = Path(config_dir)

    with open(config_dir / "child_config.json", encoding="utf-8") as f:
        child_cfg = json.load(f)
    with open(config_dir / "dimensions_config.json", encoding="utf-8") as f:
        dim_cfg = json.load(f)

    all_indicator_ids = [ind["id"] for ind in child_cfg.get("indicators", [])]
    all_dimension_ids = [dim["id"] for dim in dim_cfg.get("dimensions", [])]

    available_cols = set(df.columns)
    indicators = [i for i in all_indicator_ids if i in available_cols]
    dimensions = [d for d in all_dimension_ids if d in available_cols]

    return indicators, dimensions


def data_map(dataset):
    """Build a DataFrame describing each available indicator and dimension.

    Returns columns: name, ind_type, category, range.
    """
    dimensions = dataset.df_summary["available_dimensions"]
    indicators = dataset.df_summary["available_indicators"]

    rows = []
    for var_type, names in [("indicator", indicators), ("dimension", dimensions)]:
        for name in names:
            col = dataset.df_short[name]
            category, value_range = classify_series(col)
            rows.append({
                "name":     name,
                "ind_type": var_type,
                "category": category,
                "range":    value_range,
            })

    return pd.DataFrame(rows)


# ========================================================================
# PLOTTER
# ========================================================================

def plotter(kind, plot, df, dim, ind):
    """Render a single chart.

    Parameters
    ----------
    kind : "static" (matplotlib) | "dynamic" (plotly)
    plot : "mean_bar" | "stacked_bar" | "scatter"
    df   : DataFrame with at least [dim, ind] columns
    dim  : dimension column name
    ind  : indicator column name
    """
    ind_norm = ind.replace("_", " ").capitalize()
    dim_norm = dim.replace("_", " ").capitalize()

    if kind == "static":
        fig, ax = plt.subplots(figsize=(10, 6))

        if plot == "mean_bar":
            sns.barplot(x=dim, y=ind, data=df, color=Colors.medium_green, errorbar=None, ax=ax)
            ax.grid(False)

        elif plot == "stacked_bar":
            ct = (
                df.groupby([dim, ind])
                .size()
                .unstack(fill_value=0)
            )
            ct = ct.div(ct.sum(axis=1), axis=0)
            n = ct.shape[1]
            ct.plot(kind="bar", stacked=True, color=get_ordinal_colors(n), ax=ax)
            ax.grid(False)

        elif plot == "scatter":
            sns.scatterplot(x=dim, y=ind, data=df, color=Colors.medium_green, ax=ax)

        else:
            raise ValueError(f"Plot type '{plot}' not recognised.")

        ax.set_title(f"Plot of {ind_norm} by {dim_norm}", fontsize=16, fontname="Oswald")
        ax.set_xticks(ax.get_xticks())
        ax.set_xticklabels(
            [(textwrap.fill(str(l.get_text()), 20)).replace("_", " ").capitalize()
             for l in ax.get_xticklabels()],
            rotation=0, fontsize=10,
        )
        ax.set_xlabel(dim_norm, fontsize=12)
        ax.set_ylabel(ind_norm, fontsize=12)
        ax.legend(loc="upper left", bbox_to_anchor=(1, 1), frameon=False)
        return fig

    if kind == "dynamic":
        if plot == "mean_bar":
            df_mean = df.groupby(dim)[ind].mean().reset_index()
            fig = px.bar(df_mean, x=dim, y=ind, color_discrete_sequence=[Colors.medium_green])
            fig.update_traces(
                hovertemplate=f"{dim_norm}: %{{x}}<br>Mean {ind_norm}: %{{y:.2f}}<extra></extra>"
            )

        elif plot == "stacked_bar":
            ct = (
                df.groupby([dim, ind])
                .size()
                .unstack(fill_value=0)
            )
            ct = ct.div(ct.sum(axis=1), axis=0)
            n = ct.shape[1]
            colors = get_ordinal_colors(n) or px.colors.qualitative.Plotly
            # Melt to long format so px.bar handles it unambiguously
            ct_long = (
                ct.reset_index()
                .melt(id_vars=dim, var_name=ind, value_name="_proportion")
            )
            fig = px.bar(
                ct_long,
                x=dim,
                y="_proportion",
                color=ind,
                barmode="relative",
                color_discrete_sequence=colors,
            )
            fig.update_traces(
                hovertemplate=f"{dim_norm}: %{{x}}<br>{ind_norm}: %{{fullData.name}}<br>%{{y:.1%}}<extra></extra>"
            )
        elif plot == "line":
            df_mean = df.groupby(dim)[ind].mean().reset_index()
            fig = px.line(df_mean, x=dim, y=ind, color_discrete_sequence=[Colors.medium_green])
            fig.update_traces(
                hovertemplate=f"{dim_norm}: %{{x}}<br>Mean {ind_norm}: %{{y:.2f}}<extra></extra>"
            )

        elif plot == "scatter":
            fig = px.scatter(df, x=dim, y=ind, color_discrete_sequence=[Colors.medium_green])
            fig.update_traces(
                marker=dict(color=Colors.medium_green),
                hovertemplate=f"{dim_norm}: %{{x}}<br>{ind_norm}: %{{y:.2f}}<extra></extra>",
            )
            fig.update_layout(hovermode="closest")
            fig.update_xaxes(showspikes=True, spikecolor=Colors.grey_500)
            fig.update_yaxes(showspikes=True, spikecolor=Colors.grey_500)

        else:
            raise ValueError(f"Plot type '{plot}' not recognised.")

        fig.update_layout(
            title=f"Plot of {ind_norm} by {dim_norm}",
            xaxis_title=dim_norm,
            yaxis_title=ind_norm,
            template="simple_white",
            width=800,
            height=500,
            showlegend=True,
        )
        fig.update_xaxes(
            ticktext=[textwrap.fill(str(x), 10) for x in df[dim].unique()],
            tickvals=df[dim].unique(),
        )
        return fig


# ========================================================================
# FIGURE LIST & BATCH RENDERER
# ========================================================================

def fig_list(dataset, preferred_plot=None, max_figs=10):
    """Return a DataFrame of (indicator, dimension, plot) rows to render."""
    if not hasattr(dataset, "data_map") or dataset.data_map is None:
        dataset.data_map = data_map(dataset)

    ind_df = dataset.data_map[dataset.data_map["ind_type"] == "indicator"]
    dim_df = dataset.data_map[dataset.data_map["ind_type"] == "dimension"]

    pairs = ind_df.merge(dim_df, how="cross", suffixes=("_ind", "_dim"))

    def get_plots(ind_cat, dim_cat):
        plots = []
        if dim_cat in ["categorical", "ordinal"]:
            if ind_cat in ["numeric", "ordinal"]:
                plots.append("mean_bar")
            if ind_cat == "ordinal":
                plots.append("stacked_bar")
        if dim_cat == "numeric" and ind_cat in ["numeric", "ordinal"]:
            plots.append("scatter")
        return plots

    rows = []
    for _, r in pairs.iterrows():
        for p in get_plots(r["category_ind"], r["category_dim"]):
            rows.append({"indicator": r["name_ind"], "dimension": r["name_dim"], "plot": p})

    fig_map = pd.DataFrame(rows)

    if fig_map.empty:
        return fig_map

    if preferred_plot:
        reduced = []
        for _, group in fig_map.groupby(["indicator", "dimension"]):
            if preferred_plot in group["plot"].values:
                reduced.append(group[group["plot"] == preferred_plot].iloc[0])
            else:
                reduced.append(group.iloc[0])
        fig_map = pd.DataFrame(reduced)
    else:
        fig_map = fig_map.drop_duplicates(["indicator", "dimension"], keep="first")

    return fig_map.head(max_figs).reset_index(drop=True)


def show_figures(dataset, kind="dynamic", preferred_plot=None, max_figs=10):
    """Build and return all figures for a dataset.

    Returns (list[fig], specs_DataFrame).
    """
    specs = fig_list(dataset, preferred_plot=preferred_plot, max_figs=max_figs)

    if specs.empty:
        print("No figures to plot.")
        return [], specs

    figs = []
    for row in specs.itertuples(index=False):
        df = dataset.df_short[[row.indicator, row.dimension]].dropna()
        figs.append(plotter(kind, row.plot, df, row.dimension, row.indicator))

    return figs, specs
