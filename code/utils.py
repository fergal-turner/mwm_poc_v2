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
    """Find the smallest left-to-right column subset that uniquely identifies rows."""
    cols = df.columns.tolist()

    for i in range(1, len(cols) + 1):
        subset = cols[:i]
        if df.duplicated(subset=subset).sum() == 0:
            return subset

    # fallback: all columns (still may not be unique!)
    return cols


def make_uuid(row, hash_cols):
    """Build a deterministic row UUID from the selected hash columns."""
    key = "|".join(str(row[col]) for col in hash_cols)
    return hashlib.md5(key.encode()).hexdigest()
