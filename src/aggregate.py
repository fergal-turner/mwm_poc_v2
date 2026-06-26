

import json
from pathlib import Path

import pandas as pd

from src.utils import get_project_context

# ========================================================================
# DIMENSION CALCULATION
# ========================================================================
def calculate_dims(df, config_dir):
    """Compute and resolve dimensions for the dataset.
    
    Reads dimension configuration, resolves source columns, computes derived
    dimensions, and updates the dataframe with dimension columns.
    """

    # ---------- helpers ----------

    def resolve_column(df, candidates):
        """Return the first column from candidates that exists in the dataframe.
        
        Used to match configured column names against actual column names in the data.
        """
        for col in candidates:
            if col in df.columns:
                return col
        return None

    def bin_values(series, bins):
        """Convert numeric values into categorical bins based on configured ranges.
        
        Parameters
        ----------
        series : pd.Series
            Numeric values to bin
        bins : list of dict
            Each dict contains 'min', 'max', and 'label' keys defining bin boundaries
        
        Returns
        -------
        pd.Series
            Categorical labels for each value, or None if outside all ranges
        """
        def assign(val):
            if pd.isna(val):
                return None

            for b in bins:
                if b["min"] <= val <= b["max"]:
                    return b["label"]

            return None

        return series.apply(assign)

    def compute_derived_dimension(series, dim):
        """Transform a series into a derived dimension using the specified operation.
        
        Currently supports binning operations; can be extended for other transformations.
        """
        if dim["operation"] == "bin":
            return bin_values(series, dim["bins"])
        return None

    # ---------- build dimension map ----------
    with open(config_dir / "dimensions_config.json", "r", encoding="utf-8") as f:
        dimensions_config = json.load(f)

    dimension_map = {
        dim["id"]: dim for dim in dimensions_config["dimensions"]
    }

    # ---------- resolve columns ----------

    resolved_columns = {}

    for dim_id, dim in dimension_map.items():
        if dim["type"] in ["categorical", "ordinal", "numeric", "derived"]:
            resolved_columns[dim_id] = resolve_column(df, dim["columns"])

    # ---------- determine availability ----------

    available_dimensions = []
    missing_dimensions = []

    for dim_id, col in resolved_columns.items():
        if col is not None:
            available_dimensions.append(dim_id)
        else:
            missing_dimensions.append(dim_id)

    # ---------- compute / map dimensions ----------

    new_cols = {}
    dims_derived = []

    for dim_id in available_dimensions:
        dim = dimension_map[dim_id]
        col = resolved_columns[dim_id]

        if dim["type"] == "derived":
            new_cols[dim_id] = compute_derived_dimension(df[col], dim)
            dims_derived.append(dim_id)

        elif dim["type"] in ["categorical", "ordinal", "numeric"]:
            if col != dim_id:  # only copy if needed
                new_cols[dim_id] = df[col]

        if dim["type"] == "categorical":
            if col in df.columns:
                df[col] = df[col].astype("category")
        
    if new_cols:
        df = pd.concat([df, pd.DataFrame(new_cols)], axis=1)
        if "date_time" in df.columns:
            df["date_time"] = pd.to_datetime(df["date_time"], errors="coerce").dt.floor("D")

    # ---------- logging ----------

    print("Available dimensions:", available_dimensions)
    print("Missing dimensions:", missing_dimensions)
    print("Resolved columns:", resolved_columns)
    print("Derived dimensions computed:", dims_derived)

    return df, available_dimensions, missing_dimensions


# ========================================================================
# INDICATOR CALCULATION
# ========================================================================
def calculate_indicators(df, metadata, config_dir):
    """Compute and resolve indicators for the dataset.
    
    Reads indicator configuration, resolves source columns, computes calculated
    and aggregate indicators, and updates the dataframe with indicator columns.
    """

    level = metadata.get("level")

    with open(config_dir / f"{level}_config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    indicator_map = {
        ind["id"]: ind for ind in config["indicators"]
    }

    def resolve_column(df, candidates):
        cols = [col for col in candidates if col in df.columns]
        return cols if cols else None

    available_indicators = []
    missing_indicators = []
    resolved_columns = {}

    # --- Resolve indicators ---
    simple_inds = []

    for ind_id, ind in indicator_map.items():
        if ind["agg_type"] == "calculated":
            requested_cols = ind["calc"]["columns"]
            found_cols = resolve_column(df, requested_cols)

            resolved_columns[ind_id] = found_cols

            if found_cols is not None and len(found_cols) == len(requested_cols):
                available_indicators.append(ind_id)
            else:
                missing_indicators.append(ind_id)

        elif ind["agg_type"] == "simple":
            candidates = ind.get("columns", [])
            found_cols = resolve_column(df, candidates)
            resolved_columns[ind_id] = found_cols
            if found_cols is not None:
                available_indicators.append(ind_id)
                simple_inds.append(ind_id)
            else:
                missing_indicators.append(ind_id)

    # --- Compute calculated indicators (vectorised) ---
    ind_df = pd.DataFrame(index=df.index)

    for ind in available_indicators:
        meta = indicator_map[ind]
        if meta["agg_type"] == "simple":
            continue
        op = meta["calc"]["op"]
        cols = resolved_columns[ind]

        if op == "sum":
            ind_df[ind] = df[cols].sum(axis=1)

        elif op == "mean":
            ind_df[ind] = df[cols].mean(axis=1)

        elif op == "divide":
            denom = meta["calc"]["by"]
            ind_df[ind] = df[cols].sum(axis=1) / denom

        elif op == "max":
            # max index where value == 1
            mask = df[cols].eq(1)

            weights = pd.DataFrame(
                [range(1, len(cols)+1)] * len(df),
                columns=cols,
                index=df.index
            )

            ind_df[ind] = (mask * weights).max(axis=1)

    for ind_id in simple_inds:
        col = resolved_columns[ind_id][0]
        ind_df[ind_id] = df[col]

    # --- Resolve aggregate indicators (based on calculated outputs) ---
    agg_inds = []
    component_inds = set()

    for ind_id, ind in indicator_map.items():
        if ind["agg_type"] == "aggregate":
            requested_cols = ind["calc"]["columns"]
            found_cols = resolve_column(ind_df, requested_cols)

            resolved_columns[ind_id] = found_cols

            if found_cols is not None and len(found_cols) == len(requested_cols):
                agg_inds.append(ind_id)
                component_inds.update(found_cols)
                available_indicators.append(ind_id)
            else:
                missing_indicators.append(ind_id)
    
    available_indicators = [
        ind for ind in available_indicators
        if ind not in component_inds
    ]

    # --- Compute aggregates (vectorised) ---
    agg_df = pd.DataFrame(index=df.index)

    for ind in agg_inds:
        cols = resolved_columns[ind]
        agg_df[ind] = ind_df[cols].mean(axis=1)

    # --- Combine ---
    df = pd.concat([df, ind_df, agg_df], axis=1)

    print("Available indicators:", available_indicators)
    print("Missing indicators:", missing_indicators)

    return df, available_indicators, missing_indicators


# ========================================================================
# MAIN AGGREGATION ORCHESTRATOR
# ========================================================================
def aggregates(dataset):
    """Compute indicators and dimensions for a dataset.
    
    This is the main aggregation function that processes raw survey data and derives
    all indicators and dimensions based on configuration files. It:
    - Reads configuration files for the survey level (child, teacher, school)
    - Resolves which columns map to which indicators/dimensions
    - Computes derived dimensions (binning, transformations)
    - Calculates indicators (simple mappings, arithmetic operations, aggregations)
    - Updates the dataset with results and availability metadata
    
    Parameters
    ----------
    dataset : DataSet
        A DataSet object containing raw df, metadata, and configuration references.
        The dataset object is modified in-place with computed results.
    
    Returns
    -------
    dataset : DataSet
        The updated dataset with df_short and df_summary populated.
    """
    df = dataset.df
    metadata = dataset.metadata
    
    context = get_project_context(start_path=Path(__file__).resolve())
    config_dir = context["config_dir"]

    # Calculate dimensions and indicators
    df, available_dimensions, missing_dimensions = calculate_dims(df, config_dir)
    df, available_indicators, missing_indicators = calculate_indicators(df, metadata, config_dir)

    # Build summary and update dataset
    df_summary = {
        "available_dimensions": available_dimensions,
        "missing_dimensions": missing_dimensions,
        "available_indicators": available_indicators,
        "missing_indicators": missing_indicators
    }
    if 'uid' in df.columns:
        df_short = df[['uid'] + available_dimensions + available_indicators + ["_uuid"]]
    else:
        df_short = df[available_dimensions + available_indicators + ["_uuid"]]

    dataset.df = df
    dataset.df_short = df_short
    dataset.df_summary = df_summary

    return dataset
