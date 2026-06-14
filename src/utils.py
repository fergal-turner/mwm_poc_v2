"""Shared utility helpers for ingestion, aggregation, and output modules."""

import hashlib
import json
from pathlib import Path


def find_project_root(start_path=None, marker_file="path_config.json"):
    """Find the nearest parent directory containing the marker file."""
    if start_path is None:
        start_path = Path.cwd()
    else:
        start_path = Path(start_path)

    for candidate in [start_path.resolve(), *start_path.resolve().parents]:
        if (candidate / marker_file).exists():
            return candidate
    raise FileNotFoundError(f"Could not find {marker_file} above {start_path}")


def get_project_context(start_path=None, marker_file="path_config.json"):
    """Load project root, config path, raw path config, and resolved directory paths."""
    project_root = find_project_root(start_path=start_path, marker_file=marker_file)
    config_path = project_root / marker_file

    with open(config_path, "r", encoding="utf-8") as f:
        paths = json.load(f)

    context = {
        "project_root": project_root,
        "config_path": config_path,
        "paths": paths,
    }

    for key, value in paths.items():
        if key.endswith("_dir"):
            context[key] = (project_root / value).resolve()

    return context


def find_hash_columns(df):
    """Select hash columns with a minimum size and a practical upper bound."""

    min_cols = 3
    max_cols = min(12, len(df.columns))

    def score_column(col):
        series = df[col]
        unique_ratio = series.nunique(dropna=False) / max(len(df), 1)
        missing_ratio = series.isna().mean()
        return (unique_ratio - missing_ratio, unique_ratio, col)

    cols = sorted(df.columns, key=score_column, reverse=True)

    selected = []
    for col in cols:
        if len(selected) >= max_cols:
            break

        selected.append(col)

        # Require a minimum number of columns for future-proofing.
        if len(selected) >= min_cols and df.duplicated(subset=selected).sum() == 0:
            return selected

    # If strict uniqueness still is not met, return capped columns.
    return selected



def make_uuid(row, hash_cols):
    """Build a deterministic row UUID from the selected hash columns."""
    key = "|".join(str(row[col]) for col in hash_cols)
    return hashlib.md5(key.encode()).hexdigest()
