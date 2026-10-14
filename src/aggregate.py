

import os
from dotenv import load_dotenv

import pandas as pd
from supabase import create_client

# ========================================================================
# DIMENSION CALCULATION
# ========================================================================
def calculate_dims(df, metadata=None):
    """Compute and resolve dimensions for the dataset.
    
    Reads dimension configuration, resolves source columns, computes derived
    dimensions, and updates the dataframe with dimension columns.
    """

    # ---------- helpers ----------

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

    def load_dimensions_df(supabase):

        dim_df = pd.DataFrame(
            supabase.table("dimensions")
            .select("*")
            .eq("active", True)
            .execute()
            .data
        )

        return dim_df

    def compute_derived_dimension(series, dim):
        """Transform a series into a derived dimension using the specified operation.
        
        Currently supports binning operations; can be extended for other transformations.
        """
        if dim["operation"] == "bin":
            return bin_values(series, dim["bins"])
        return None

    # ---------- build dimension map ----------

    load_dotenv()

    supabase = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_KEY")
    )

    dim_df = load_dimensions_df(supabase)

    if metadata is None:
        metadata = {}

    def resolve_column(candidates):

        for col in candidates:
            if col in df.columns:
                return col

        return None

    available_dimensions = []
    missing_dimensions = []
    new_cols = {}

    for _, dim in dim_df.iterrows():

        dim_id = dim["id"]

        candidates = (
            [x.strip() for x in dim["columns"].split(",")]
            if pd.notna(dim["columns"])
            else []
        )

        col = resolve_column(candidates)

        if col is None:
            # Backfill key dimensions from metadata when the source column is absent
            if dim_id == "admin0" and metadata.get("country"):
                new_cols[dim_id] = metadata["country"]
                available_dimensions.append(dim_id)
            elif dim_id == "date_time" and metadata.get("first_submission"):
                new_cols[dim_id] = metadata["first_submission"]
                available_dimensions.append(dim_id)
            else:
                missing_dimensions.append(dim_id)
            continue

        available_dimensions.append(dim_id)

        if dim["type"] == "derived":

            if dim["operation"] == "bin":

                bins = []

                for entry in dim["bins"].split("|"):

                    min_val, max_val, label = entry.split(":")

                    bins.append({
                        "min": float(min_val),
                        "max": float(max_val),
                        "label": label
                    })

                new_cols[dim_id] = bin_values(
                    df[col],
                    bins
                )

        elif col != dim_id:

            new_cols[dim_id] = df[col]

        if dim["type"] == "categorical":
            df[col] = df[col].astype("category")

    if new_cols:
        df = pd.concat(
            [df.drop(columns=[c for c in new_cols if c in df.columns]), pd.DataFrame(new_cols)],
            axis=1
        )

    print(f"Available dimensions: {available_dimensions}")
    print(f"Missing dimensions: {missing_dimensions}")
    print(f"New columns added: {list(new_cols.keys())}")
    

    return (
        df,
        available_dimensions,
        missing_dimensions
    )


# ========================================================================
# INDICATOR CALCULATION
# ========================================================================



def calculate_indicators(df, metadata):

    '''Calculate indicators for the given DataFrame based on the provided metadata.'''

    def load_indicators_df(supabase, level):

        ind_df = pd.DataFrame(
            supabase.table("indicators")
            .select("*")
            .eq("active", True)
        .eq("level", level)
            .execute()
            .data
        )

        return ind_df

    level = metadata.get("level")

    load_dotenv()

    supabase = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_KEY")
    )

    config_df = load_indicators_df(supabase, level)

    def split_cols(value):

        if pd.isna(value) or value == "":
            return []

        return [
            x.strip()
            for x in str(value).split(",")
        ]

    def resolve_columns(columns):

        found = [
            col
            for col in columns
            if col in df.columns
        ]

        return found if found else None

    available_indicators = []
    missing_indicators = []

    result_df = pd.DataFrame(index=df.index)

    # --------------------------------------------------
    # SIMPLE + CALCULATED INDICATORS
    # --------------------------------------------------

    calc_df = config_df[
        config_df["agg_type"].isin(
            ["simple", "calculated"]
        )
    ]

    for _, indicator in calc_df.iterrows():

        ind_id = indicator["id"]

        requested_cols = split_cols(
            indicator["columns"]
        )

        found_cols = resolve_columns(
            requested_cols
        )

        if indicator["agg_type"] == "simple":

            if found_cols:

                available_indicators.append(
                    ind_id
                )

                result_df[ind_id] = df[
                    found_cols[0]
                ]

            else:

                missing_indicators.append(
                    ind_id
                )

        elif indicator["agg_type"] == "calculated":

            if (
                found_cols is None
                or
                len(found_cols)
                != len(requested_cols)
            ):

                missing_indicators.append(
                    ind_id
                )

                continue

            available_indicators.append(
                ind_id
            )

            op = indicator["calc_op"]

            if op == "sum":

                result_df[ind_id] = (
                    df[found_cols]
                    .sum(axis=1)
                )

            elif op == "mean":

                result_df[ind_id] = (
                    df[found_cols]
                    .mean(axis=1)
                )

            elif op == "divide":

                # calc_by is either a number or the name of a denominator column
                try:
                    denominator = float(indicator["calc_by"])
                except (TypeError, ValueError):
                    if indicator["calc_by"] in df.columns:
                        denominator = pd.to_numeric(
                            df[indicator["calc_by"]], errors="coerce"
                        ).replace(0, float("nan"))
                    else:
                        available_indicators.remove(ind_id)
                        missing_indicators.append(ind_id)
                        continue

                result_df[ind_id] = (
                    df[found_cols]
                    .sum(axis=1)
                    / denominator
                )

            elif op == "max":

                mask = df[found_cols].eq(1)

                weights = pd.DataFrame(
                    [range(
                        1,
                        len(found_cols) + 1
                    )] * len(df),
                    columns=found_cols,
                    index=df.index
                )
                result_df[ind_id] = (
                    mask * weights
                ).max(axis=1)

            elif op == "threshold":

                threshold = float(
                    indicator["calc_by"]
                )

                result_df[ind_id] = (
                    df[found_cols]
                    .sum(axis=1)
                    .ge(threshold)
                    .astype(int)
                )
            elif op == "all":

                result_df[ind_id] = (
                    df[found_cols]
                    .all(axis=1)
                    .astype(int)
                )

            elif op == "count_at_least":

                result_df[ind_id] = (
                    df[found_cols]
                    .apply(pd.to_numeric, errors="coerce")
                    .sum(axis=1)
                    .ge(float(indicator["calc_by"]))
                    .astype(int)
                )

            else:
                print(f"Unsupported calc_op '{op}' for indicator '{ind_id}'; marking as missing.")
                available_indicators.remove(ind_id)
                missing_indicators.append(ind_id)
                
    # --------------------------------------------------
    # AGGREGATE INDICATORS
    # --------------------------------------------------

    agg_config = config_df[
        config_df["agg_type"]
        == "aggregate"
    ]

    component_inds = set()

    for _, indicator in agg_config.iterrows():

        ind_id = indicator["id"]

        components = split_cols(
            indicator["columns"]
        )

        if all(
            component in result_df.columns
            for component in components
        ):

            result_df[ind_id] = (
                result_df[components]
                .mean(axis=1)
            )

            component_inds.update(
                components
            )

            available_indicators.append(
                ind_id
            )

        else: missing_indicators.append(ind_id)

    # --------------------------------------------------
    # REMOVE INTERMEDIATE COMPONENTS
    # --------------------------------------------------

    available_indicators = [ind for ind in available_indicators if ind not in component_inds]

    # --------------------------------------------------
    # COMBINE
    # --------------------------------------------------

    df = pd.concat(
        [df.drop(columns=[c for c in result_df.columns if c in df.columns]), result_df],
        axis=1
    )

    print(
        "Available indicators:",
        available_indicators
    )

    print("Missing indicators:", missing_indicators)

    return (df, available_indicators, missing_indicators)


# ========================================================================
# MAIN AGGREGATION ORCHESTRATOR
# ========================================================================
def aggregates(dataset):
    """Compute indicators and dimensions for a dataset.
    
    This is the main aggregation function that processes raw survey data and derives
    all indicators and dimensions based on configuration files. It:
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

    load_dotenv()

    supabase = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_KEY")
        )

    # Calculate dimensions and indicators
    df, available_dimensions, missing_dimensions = calculate_dims(df, metadata)
    df, available_indicators, missing_indicators = calculate_indicators(df, metadata)

    # The log row was already created by update_log() during ingest; update it by form_id and country
    log_update = supabase.table("import_log").update({
            "available_dimensions": available_dimensions,
            "missing_dimensions": missing_dimensions,
            "available_indicators": available_indicators,
            "missing_indicators": missing_indicators
            }).eq("form_id", metadata["form_id"]).execute()
    

    if 'uid' in df.columns:
        df_short = df[['uid'] + available_dimensions + available_indicators + ["_uuid"]]
    else:
        df_short = df[available_dimensions + available_indicators + ["_uuid"]]

    dataset.df = df
    dataset.df_short = df_short

    return dataset
