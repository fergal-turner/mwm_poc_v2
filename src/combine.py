"""Combine module: merges aggregated datasets into level-level combined files.

Public API
----------
    from src.combine import CombinedDataSet, add_to_combined

    # After running ingest + aggregate on a new dataset:
    combined = add_to_combined(dataset, output_dir)

    # combined.df_short   â€“ deduplicated combined DataFrame for this level/country
    # combined.df_summary â€“ union of available/missing indicators & dimensions
    #                       across all datasets merged so far
    # combined.metadata   â€“ dict with level, country, row count, source form IDs

Notes
-----
- Each country/level combination is stored as a separate CSV:
      <output_dir>/<country>/tables/combined_<level>_level.csv
- A sidecar JSON is written alongside each CSV:
      <output_dir>/<country>/tables/combined_<level>_summary.json
  It records the union/intersection of indicators and dimensions so the
  dashboard can load it without re-scanning every row.
- School-level aggregation of student data is intentionally not implemented
  here; it will be added as a separate function in a later iteration.
"""

from __future__ import annotations

import os

import pandas as pd
from supabase import create_client


# ========================================================================
# SUMMARY HELPERS
# ========================================================================

UPSERT_CHUNK = 2000


def fetch_all(client, table, page_size=2000, country=None):
    """Read every row of a table (optionally one country, case-insensitive), paging past the API's row cap."""
    rows, start = [], 0
    while True:
        query = client.table(table).select("*")
        if country:
            query = query.ilike("country", country)
        batch = query.range(start, start + page_size - 1).execute().data
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        start += page_size


def build_agg_dict(config_df):
    return dict(
        zip(
            config_df["id"],
            config_df["agg_method"]
        )
    )

def aggregate_to_school_month(df, dim_agg_dict, indicator_agg_dict):

        
        agg_dict = {
            **dim_agg_dict,
            **indicator_agg_dict
        }

        agg_dict = {
            k: v
            for k, v in agg_dict.items()
            if k in df.columns
            and k not in ["school_id", "date_time"]
        }

        df = df.copy()

        if df.empty or "date_time" not in df.columns:
            return pd.DataFrame(columns=["country", "school_id", "date_time"])

        if "country" not in df.columns:
            df["country"] = "unknown"

        df["country"] = df["country"].fillna("unknown")

        df["date_time"] = pd.to_datetime(
            df["date_time"],
            errors="coerce"
        )

        grouped = (
            df.groupby(
                [
                    "country",
                    "school_id",
                    df["date_time"].dt.to_period("M")
                ],
                dropna=False
            )
            .agg(agg_dict)
            .reset_index()
        )

        indicator_cols = [
            c
            for c in indicator_agg_dict
            if c in grouped.columns
        ]

        return grouped[["country", "school_id", "date_time", *indicator_cols]]

# ========================================================================
# CORE FUNCTION
# ========================================================================

def combined_df(dataset):
    """Merge *dataset* into the persisted combined file for its level/country.

    Parameters
    ----------
    dataset : src.ingest.DataSet
        A DataSet that has already been passed through ``aggregates()``, so
        ``.df_short`` and ``.df_summary`` are populated.
    output_dir : Path | str
        Project output directory (the ``output_dir`` from ``get_project_context``).

    Returns
    -------
    CombinedDataSet
        The updated combined dataset for this level/country, reflecting all
        rows ever added (existing + new, deduplicated on ``_uuid``).

    Raises
    ------
    ValueError
        If *dataset* has not been aggregated (missing ``.df_short``).


    """
    if not hasattr(dataset, "df_short") or dataset.df_short is None:
        raise ValueError(
            "dataset.df_short is not set. Run aggregates(dataset) before add_to_combined()."
        )

    supabase = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_KEY")
    )
    
    level = dataset.metadata.get("level", "unknown")

    # --- Incoming data ---
    df_new = dataset.df_short.copy()

    # Backfill country and date_time from metadata when missing
    if "country" not in df_new.columns:
        df_new["country"] = dataset.metadata.get("country", "unknown")
    if "date_time" not in df_new.columns:
        date_val = dataset.metadata.get("first_submission")
        df_new["date_time"] = str(date_val) if date_val else "unknown"

    if "date_time" in df_new.columns:
        df_new["date_time"] = df_new["date_time"].astype(str)

    df_new["_uuid"] = df_new["_uuid"].astype(str)

    df_new = df_new.drop_duplicates(subset="_uuid", keep="last")

    # NaN/NaT are not valid JSON; convert to None before syncing
    df_new = df_new.astype(object).where(pd.notna(df_new), None)

    # Upsert only the incoming rows (conflict on the table's primary key, _uuid) in chunks
    # to avoid statement timeouts; existing rows are left untouched.
    records = df_new.to_dict(orient="records")
    table = supabase.table(f"combined_{level}_level")
    for start in range(0, len(records), UPSERT_CHUNK):
        table.upsert(records[start:start + UPSERT_CHUNK]).execute()

    return df_new

def school_combined(dataset=None, country=None, rollup=True):
    """Aggregate child and teacher level data into school-level combined dataset.

    dataset is optional: with only ``country`` the school-month table is rebuilt from the
    child, teacher and school data already in Supabase (used after any form is loaded).
    With rollup=False and a school dataset, only that form's own columns are upserted
    and the child/teacher tables are not downloaded.
    
    This function takes child and teacher level combined datasets and aggregates them
    to the school level using configured aggregation methods (mean, sum, etc.).
    It also incorporates any school-level data from the input dataset.
    
    The resulting school-level dataset is merged with child and teacher aggregates
    and persisted to a combined school-level CSV file.
    
    Parameters
    ----------
    dataset : DataSet
        A school-level DataSet object with metadata and df_short
    output_dir : Path | str
        Project output directory where combined tables are stored
        
    Returns
    -------
    CombinedDataSet
        The aggregated school-level combined dataset
    """

    supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

    dim_config = pd.DataFrame(supabase.table("dimensions")
                              .select("*")
                              .execute()
                              .data)
    child_config = pd.DataFrame(supabase.table("indicators")
                                .select("*")
                                .eq("level", "child")
                                .execute()
                                .data)
    teacher_config = pd.DataFrame(supabase.table("indicators")
                                    .select("*")
                                    .eq("level", "teacher")
                                    .execute()
                                    .data)
    school_config = pd.DataFrame(supabase.table("indicators")
                                 .select("*")
                                 .eq("level", "school")
                                 .execute()
                                 .data)

    dim_agg_dict = build_agg_dict(dim_config)
    child_agg_dict = build_agg_dict(child_config)
    teacher_agg_dict = build_agg_dict(teacher_config)
    school_agg_dict = build_agg_dict(school_config)


    if country is None and dataset is not None:
        country = dataset.metadata.get("country")
    if rollup and not country:
        raise ValueError("A country is required to roll up to school level.")

    if rollup:
        child_combined = pd.DataFrame(fetch_all(supabase, "combined_child_level", country=country))
        child_inds = aggregate_to_school_month(child_combined, dim_agg_dict, child_agg_dict)

        teacher_combined = pd.DataFrame(fetch_all(supabase, "combined_teacher_level", country=country))
        teacher_inds = aggregate_to_school_month(teacher_combined, dim_agg_dict, teacher_agg_dict)

    if dataset is not None:
        school_new = dataset.df_short.copy()
    else:
        school_new = pd.DataFrame(columns=["country", "school_id", "date_time"])

    if "country" not in school_new.columns:
        school_new["country"] = dataset.metadata.get("country", "unknown")

    school_new["country"] = school_new["country"].fillna("unknown")

    if "date_time" in school_new.columns and not school_new.empty:
        school_new["date_time"] = pd.to_datetime(school_new["date_time"], errors="coerce")
        school_new["date_time"] = school_new["date_time"].dt.to_period("M")

        school_agg = {**dim_agg_dict, **school_agg_dict}
        school_agg = {k: v for k, v in school_agg.items() if k in school_new.columns and k not in ["country", "school_id", "date_time"]}

        school_new_grouped = (
            school_new.groupby(["country", "school_id", "date_time"], dropna=False)
            .agg(school_agg)
            .reset_index()
        )
    else:
        school_new_grouped = pd.DataFrame(columns=["country", "school_id", "date_time"])

    if not rollup:
        school_grouped = school_new_grouped
        school_ids = school_config["id"].unique()
        final_cols = ["country", "school_id", "date_time",
                      *[d for d in dim_config["id"] if d in school_grouped.columns],
                      *[i for i in school_ids if i in school_grouped.columns]]
        school_grouped = school_grouped.loc[:, list(dict.fromkeys(final_cols))]
        school_grouped["date_time"] = school_grouped["date_time"].astype(str)
        school_grouped = school_grouped.astype(object).where(pd.notna(school_grouped), None)
        records = school_grouped.to_dict("records")
        table = supabase.table("combined_school_level")
        for start in range(0, len(records), UPSERT_CHUNK):
            table.upsert(records[start:start + UPSERT_CHUNK], on_conflict="country,school_id,date_time").execute()
        return

    school_existing = pd.DataFrame(fetch_all(supabase, "combined_school_level", country=country))

    if not school_existing.empty:
        if "country" not in school_existing.columns:
            school_existing["country"] = "unknown"

        school_existing["country"] = school_existing["country"].fillna("unknown")

        school_existing["date_time"] = pd.PeriodIndex(
            pd.to_datetime(school_existing["date_time"], errors="coerce"),
            freq="M",
        )

        school_existing = school_existing.loc[:, ~school_existing.columns.duplicated()]
        school_new_grouped = school_new_grouped.loc[:, ~school_new_grouped.columns.duplicated()]

        all_cols = list(dict.fromkeys(list(school_existing.columns) + list(school_new_grouped.columns)))
        school_existing = school_existing.reindex(columns=all_cols)
        school_new_grouped = school_new_grouped.reindex(columns=all_cols)

        school_grouped = pd.concat([school_existing, school_new_grouped], ignore_index=True, sort=False)

        rollup_agg = {k: v for k, v in school_agg_dict.items() if k in school_grouped.columns}
        school_grouped = (
            school_grouped
            .groupby(["country", "school_id", "date_time"], as_index=False, dropna=False)
            .agg(rollup_agg)
        )
    else:
        school_grouped = school_new_grouped

    school_grouped = school_grouped.merge(child_inds, on=["country", "school_id", "date_time"], how="outer", suffixes=("", "_child"))
    school_grouped = school_grouped.merge(teacher_inds, on=["country", "school_id", "date_time"], how="outer", suffixes=("", "_teacher"))

    # Coalesce suffixed columns back to base names so existing null columns do not shadow fresh values.
    for suffix in ["_child", "_teacher"]:
        suffixed_cols = [c for c in school_grouped.columns if c.endswith(suffix)]
        for suffixed in suffixed_cols:
            base = suffixed[: -len(suffix)]
            if base in school_grouped.columns:
                school_grouped[base] = school_grouped[base].combine_first(school_grouped[suffixed])
                school_grouped = school_grouped.drop(columns=[suffixed])
            else:
                school_grouped = school_grouped.rename(columns={suffixed: base})

    allowed_dimensions = [
                        d
                        for d in dim_config["id"]
                        if d in school_grouped.columns
                    ]
    
    allowed_indicators = [
        i
        for i in pd.concat(
            [
                child_config["id"],
                teacher_config["id"],   
                school_config["id"]
            ]
        ).unique()
        if i in school_grouped.columns
        ]

    final_cols = ["country", "school_id", "date_time", *allowed_dimensions, *allowed_indicators]
    final_cols = [c for c in dict.fromkeys(final_cols) if c in school_grouped.columns]
    school_grouped = school_grouped.loc[:, final_cols]

    # Period dtypes and NaN/NaT are not JSON serializable; convert before syncing
    school_grouped["date_time"] = school_grouped["date_time"].astype(str)
    school_grouped = school_grouped.astype(object).where(pd.notna(school_grouped), None)

    records = school_grouped.to_dict("records")
    table = supabase.table("combined_school_level")
    for start in range(0, len(records), UPSERT_CHUNK):
        table.upsert(records[start:start + UPSERT_CHUNK], on_conflict="country,school_id,date_time").execute()

def combine(dataset, rollup=True):
    """Persist a dataset to its combined table. With rollup=True (default) the school-month
    table for the dataset's country is then rebuilt from child, teacher and school data,
    whatever level this form was. Pass rollup=False when loading several forms and call
    ``school_combined(country=...)`` once at the end."""
    level = dataset.metadata.get("level")
    if level in ["child", "teacher"]:
        combined_df(dataset)
        if rollup:
            school_combined(country=dataset.metadata.get("country"))
    elif level == "school":
        school_combined(dataset, rollup=rollup)
