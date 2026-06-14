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

    # --- Merge with existing combined file (if any) ---
    if csv_path.exists():
        df_existing = pd.read_csv(csv_path)
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    else:
        df_combined = df_new

    df_combined = df_combined.drop_duplicates(subset="_uuid")

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

    df_combined  = pd.read_csv(csv_path)
    df_summary   = _load_summary(summary_path)

    metadata = {
        "level":           level,
        "country":         country,
        "row_count":       len(df_combined),
        "source_form_ids": df_summary.get("source_form_ids", []),
        "output_path":     str(csv_path),
    }

    return CombinedDataSet(df_short=df_combined, df_summary=df_summary, metadata=metadata)
