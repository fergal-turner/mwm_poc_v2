

import json
from pathlib import Path

import pandas as pd

from src.utils import get_project_context


# ========================================================================
# AGGREGATION PIPELINE
# ========================================================================
def aggregates(dataset):

    df = dataset.df
    metadata = dataset.metadata
    
    context = get_project_context(start_path=Path(__file__).resolve())
    CONFIG_DIR = context["config_dir"]

    # --------------------------------------------------------------------
    # Dimension calculations
    # --------------------------------------------------------------------
    def calculate_dims(df):

        # ---------- helpers ----------

        def resolve_column(df, candidates):
            """Return first matching column in df"""
            for col in candidates:
                if col in df.columns:
                    return col
            return None

        def bin_values(series, bins):
            """Apply binning logic"""
            def assign(val):
                if pd.isna(val):
                    return None

                for b in bins:
                    if b["min"] <= val <= b["max"]:
                        return b["label"]

                return None

            return series.apply(assign)

        def compute_derived_dimension(series, dim):
            """Compute derived dimension"""
            if dim["operation"] == "bin":
                return bin_values(series, dim["bins"])
            return None

        # ---------- build dimension map ----------

        with open(CONFIG_DIR / "dimensions_config.json", "r", encoding="utf-8") as f:
            dimensions_config = json.load(f)

        dimension_map = {
            dim["id"]: dim for dim in dimensions_config["dimensions"]
        }

        # ---------- resolve columns ----------

        resolved_columns = {}

        
        for dim_id, dim in dimension_map.items():
            if dim["type"] in ["categorical", "numeric", "derived"]:
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

            elif dim["type"] in ["categorical", "numeric"]:
                if col != dim_id:  # only copy if needed
                    new_cols[dim_id] = df[col]

            if dim["type"] == "categorical":
                if col in df.columns:
                    df[col] = df[col].astype("category")

        if new_cols:
            df = pd.concat([df, pd.DataFrame(new_cols)], axis=1)

        # ---------- logging ----------

        print("Available dimensions:", available_dimensions)
        print("Missing dimensions:", missing_dimensions)
        print("Resolved columns:", resolved_columns)
        print("Derived dimensions computed:", dims_derived)

        return df, available_dimensions, missing_dimensions

    # --------------------------------------------------------------------
    # Indicator calculations
    # --------------------------------------------------------------------
    def calculate_indicators(df, metadata):

        level = metadata.get("level")

        with open(CONFIG_DIR / f"{level}_config.json", "r", encoding="utf-8") as f:
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

        for ind_id, ind in indicator_map.items():
            if ind["agg_type"] == "aggregate":
                requested_cols = ind["calc"]["columns"]
                found_cols = resolve_column(ind_df, requested_cols)

                resolved_columns[ind_id] = found_cols

                if found_cols is not None and len(found_cols) == len(requested_cols):
                    agg_inds.append(ind_id)
                    available_indicators.append(ind_id)
                else:
                    missing_indicators.append(ind_id)

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

    df, available_dimensions, missing_dimensions = calculate_dims(df)
    df, available_indicators, missing_indicators = calculate_indicators(df, metadata)

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
