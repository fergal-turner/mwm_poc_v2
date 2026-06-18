"""Combine module: merges aggregated datasets into level-level combined files.

Public API
----------
    from src.combine import CombinedDataSet, add_to_combined

    # After running ingest + aggregate on a new dataset:
    combined = add_to_combined(dataset, output_dir)

    # combined.df_short   – deduplicated combined DataFrame for this level/country
    # combined.df_summary – union of available/missing indicators & dimensions
    #                       across all datasets merged so far
    # combined.metadata   – dict with level, country, row count, source form IDs

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

import json
from pathlib import Path
from typing import Any
from src.output import CONFIG_DIR
from src.utils import get_project_context

import pandas as pd


# ========================================================================
# COMBINED DATASET OBJECT
# ========================================================================

class CombinedDataSet:
    """Represents the combined, deduplicated data for one level + country.

    Attributes
    ----------
    df_short : pd.DataFrame
        Deduplicated rows containing only indicator/dimension/uuid columns.
    df_summary : dict
        ``available_*`` and ``missing_*`` lists reflecting the *union* of
        indicators and dimensions found across all constituent datasets.
    metadata : dict
        level, country, row_count, source_form_ids, output_path.
    """

    def __init__(
        self,
        df_short: pd.DataFrame,
        df_summary: dict[str, list],
        metadata: dict[str, Any],
    ) -> None:
        self.df_short   = df_short
        self.df_summary = df_summary
        self.metadata   = metadata

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"CombinedDataSet(level={self.metadata.get('level')!r}, "
            f"country={self.metadata.get('country')!r}, "
            f"rows={len(self.df_short)})"
        )


# ========================================================================
# SUMMARY HELPERS
# ========================================================================

def _merge_summaries(existing: dict, new: dict) -> dict:
    """Return a summary whose available_* lists are the union of both inputs
    and whose missing_* lists are those absent from *both* inputs."""
    available_dims  = sorted(set(existing.get("available_dimensions", []))
                             | set(new.get("available_dimensions", [])))
    available_inds  = sorted(set(existing.get("available_indicators", []))
                             | set(new.get("available_indicators", [])))

    # A dimension/indicator is only truly missing if neither dataset has it.
    missing_dims = sorted(set(existing.get("missing_dimensions", []))
                          & set(new.get("missing_dimensions", [])))
    missing_inds = sorted(set(existing.get("missing_indicators", []))
                          & set(new.get("missing_indicators", [])))

    return {
        "available_dimensions": available_dims,
        "missing_dimensions":   missing_dims,
        "available_indicators": available_inds,
        "missing_indicators":   missing_inds,
    }


def _load_summary(summary_path: Path) -> dict:
    if summary_path.exists():
        with open(summary_path, encoding="utf-8") as f:
            return json.load(f)
    return {
        "available_dimensions": [],
        "missing_dimensions":   [],
        "available_indicators": [],
        "missing_indicators":   [],
    }


def _save_summary(summary: dict, summary_path: Path) -> None:
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)


# ========================================================================
# CORE FUNCTION
# ========================================================================

def add_to_combined(dataset, output_dir: Path | str) -> CombinedDataSet:
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

    output_dir = Path(output_dir)
    country    = dataset.metadata.get("country", "unknown")
    level      = dataset.metadata.get("level", "unknown")
    form_id    = dataset.metadata.get("form_id", "unknown")

    table_dir    = output_dir / country / "tables"
    csv_path     = table_dir / f"combined_{level}_level.csv"
    summary_path = table_dir / f"combined_{level}_summary.json"

    table_dir.mkdir(parents=True, exist_ok=True)

    # --- Incoming data ---
    df_new = dataset.df_short.copy()

    if "date_time" in df_new.columns:
        df_new["date_time"] = df_new["date_time"].astype(str)

    df_new["_uuid"] = df_new["_uuid"].astype(str)

    # --- Merge with existing combined file (if any) ---
    if csv_path.exists():
        df_existing = pd.read_csv(csv_path, dtype={"_uuid": "string"})
        df_existing["_uuid"] = df_existing["_uuid"].astype("string").str.strip()
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    else:
        df_combined = df_new

    df_combined = df_combined.drop_duplicates(subset="_uuid")

    if "date_time" in df_combined.columns:
        df_combined["date_time"] = df_combined["date_time"].astype(str)

    df_combined["_uuid"] = df_combined["_uuid"].astype(str)

    # --- Persist CSV ---
    df_combined.to_csv(csv_path, index=False)

    # --- Merge summaries ---
    existing_summary = _load_summary(summary_path)
    merged_summary   = _merge_summaries(existing_summary, dataset.df_summary)
    _save_summary(merged_summary, summary_path)

    # --- Collate source form IDs ---
    existing_ids = existing_summary.get("source_form_ids", [])
    if form_id not in existing_ids:
        existing_ids.append(form_id)
    merged_summary["source_form_ids"] = existing_ids
    _save_summary(merged_summary, summary_path)

    metadata = {
        "level":           level,
        "country":         country,
        "row_count":       len(df_combined),
        "source_form_ids": merged_summary["source_form_ids"],
        "output_path":     str(csv_path),
    }

    return CombinedDataSet(df_short=df_combined, df_summary=merged_summary, metadata=metadata)

def school_combined(dataset, output_dir: Path | str) -> pd.DataFrame:

        country = dataset.metadata.get("country", "unknown")

        context = get_project_context()
        CONFIG_DIR = context["config_dir"]

        output_dir = Path(output_dir)
        country = dataset.metadata.get("country", "unknown")
        form_id = dataset.metadata.get("form_id", "unknown")

        table_dir = output_dir / country / "tables"
        csv_path = table_dir / "combined_school_level.csv"
        summary_path = table_dir / "combined_school_summary.json"

        with open(CONFIG_DIR / "dimensions_config.json", "r", encoding="utf-8") as f:
                dimensions_config = json.load(f)
        dim_agg_dict = dict(zip([d["id"] for d in dimensions_config["dimensions"]], [d["agg_method"] for d in dimensions_config["dimensions"]]))

        with open(CONFIG_DIR / "child_config.json", "r", encoding="utf-8") as f:
                child_config = json.load(f)
        child_agg_dict = dict(zip([i["id"] for i in child_config["indicators"]], [i["agg_method"] for i in child_config["indicators"]]))

        with open(CONFIG_DIR / "teacher_config.json", "r", encoding="utf-8") as f:
                teacher_config = json.load(f)
        teacher_agg_dict = dict(zip([i["id"] for i in teacher_config["indicators"]], [i["agg_method"] for i in teacher_config["indicators"]]))

        with open(CONFIG_DIR / "school_config.json", "r", encoding="utf-8") as f:
                school_config = json.load(f)
        school_agg_dict = dict(zip([i["id"] for i in school_config["indicators"]], [i["agg_method"] for i in school_config["indicators"]]))

        child_combined = pd.read_csv(output_dir / country / "tables" / "combined_child_level.csv")
        agg_dict = {**dim_agg_dict, **child_agg_dict}
        agg_dict = {k: v for k, v in agg_dict.items() if k in child_combined.columns}
        agg_dict = {k: v for k, v in agg_dict.items() if k not in ["school", "date_time"]}
        if "date_time" in child_combined.columns:
                child_combined["date_time"] = pd.to_datetime(child_combined["date_time"], errors="coerce")
        child_grouped = (
                child_combined
                .groupby(["school", child_combined["date_time"].dt.to_period("M")], dropna=False)
                .agg(agg_dict)
                .reset_index()
        )
        child_inds = child_grouped.drop(columns=[d for d in dim_agg_dict.keys() if d in child_grouped.columns and d not in ["school", "date_time"]])

        teacher_combined = pd.read_csv(output_dir / country / "tables" / "combined_teacher_level.csv")
        agg_dict = {**dim_agg_dict, **teacher_agg_dict}
        agg_dict = {k: v for k, v in agg_dict.items() if k in teacher_combined.columns}
        agg_dict = {k: v for k, v in agg_dict.items() if k not in ["school", "date_time"]}
        if "date_time" in teacher_combined.columns:
                teacher_combined["date_time"] = pd.to_datetime(teacher_combined["date_time"], errors="coerce")
        teacher_grouped = (
                teacher_combined
                .groupby(["school", teacher_combined["date_time"].dt.to_period("M")], dropna=False)
                .agg(agg_dict)
                .reset_index()
        )
        teacher_inds = teacher_grouped.drop(columns=[d for d in dim_agg_dict.keys() if d in teacher_grouped.columns and d not in ["school", "date_time"]])

        school_new = dataset.df_short.copy()

        if "date_time" in school_new.columns:
                school_new["date_time"] = pd.to_datetime(school_new["date_time"], errors="coerce")
                school_new["date_time"] = school_new["date_time"].dt.to_period("M")

                school_agg = {**dim_agg_dict, **school_agg_dict}
                school_agg = {k: v for k, v in school_agg.items() if k in school_new.columns}
                school_agg = {k: v for k, v in school_agg.items() if k not in ["school", "date_time"]}

                school_new_grouped = (
                        school_new.groupby(["school", "date_time"], dropna=False)
                        .agg(school_agg)
                        .reset_index()
                )
        else:
                school_new_grouped = pd.DataFrame(columns=["school", "date_time"])

        if csv_path.exists():
                school_existing = pd.read_csv(csv_path)
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
                        .groupby(["school", "date_time"], as_index=False, dropna=False)
                        .agg(rollup_agg)
                )
        else:
                school_grouped = school_new_grouped

        school_grouped = school_grouped.merge(child_inds, on=["school", "date_time"], how="outer", suffixes=("", "_child"))
        school_grouped = school_grouped.merge(teacher_inds, on=["school", "date_time"], how="outer", suffixes=("", "_teacher"))

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
            d["id"] for d in dimensions_config["dimensions"]
            if d["id"] in school_grouped.columns
        ]
        allowed_indicators = [
            ind["id"] for cfg in (school_config["indicators"], child_config["indicators"], teacher_config["indicators"])
            for ind in cfg
            if ind["id"] in school_grouped.columns
        ]

        final_cols = ["school", "date_time", *allowed_dimensions, *allowed_indicators]
        final_cols = [c for c in dict.fromkeys(final_cols) if c in school_grouped.columns]
        school_grouped = school_grouped.loc[:, final_cols]

        def build_summary_from_df(df: pd.DataFrame) -> dict:
            all_dimensions = [d["id"] for d in dimensions_config["dimensions"]]
            all_indicators = [
                ind["id"]
                for cfg in (school_config["indicators"], child_config["indicators"], teacher_config["indicators"])
                for ind in cfg
            ]
            available_dimensions = [d for d in all_dimensions if d in df.columns]
            available_indicators = list(dict.fromkeys([i for i in all_indicators if i in df.columns]))

            return {
                "available_dimensions": available_dimensions,
                "missing_dimensions": [d for d in all_dimensions if d not in df.columns],
                "available_indicators": available_indicators,
                "missing_indicators": [i for i in all_indicators if i not in df.columns],
            }

        school_grouped.to_csv(csv_path, index=False)

        existing_summary = _load_summary(summary_path)
        merged_summary = build_summary_from_df(school_grouped)

        existing_ids = existing_summary.get("source_form_ids", [])
        if form_id not in existing_ids:
            existing_ids.append(form_id)
        merged_summary["source_form_ids"] = existing_ids

        _save_summary(merged_summary, summary_path)

        metadata = {
            "level": "school",
            "country": country,
            "row_count": len(school_grouped),
            "source_form_ids": merged_summary["source_form_ids"],
            "output_path": str(csv_path),
        }
        return CombinedDataSet(df_short=school_grouped, df_summary=merged_summary, metadata=metadata)

# ========================================================================
# LOADER  (used by app.py to read persisted combined data)
# ========================================================================

def load_combined(output_dir: Path | str, country: str, level: str) -> CombinedDataSet | None:
    """Load a previously built combined dataset from disk.

    Returns ``None`` if no combined file exists yet for this country/level.
    """
    output_dir   = Path(output_dir)
    table_dir    = output_dir / country / "tables"
    csv_path     = table_dir / f"combined_{level}_level.csv"
    summary_path = table_dir / f"combined_{level}_summary.json"

    if not csv_path.exists():
        return None

    df_combined  = pd.read_csv(csv_path, dtype={"_uuid": "string"})
    df_summary   = _load_summary(summary_path)

    metadata = {
        "level":           level,
        "country":         country,
        "row_count":       len(df_combined),
        "source_form_ids": df_summary.get("source_form_ids", []),
        "output_path":     str(csv_path),
    }

    return CombinedDataSet(df_short=df_combined, df_summary=df_summary, metadata=metadata)
