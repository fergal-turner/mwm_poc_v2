"""Shared utility helpers for ingestion, aggregation, and output modules."""

import hashlib
import json
from pathlib import Path


def ensure_table(supabase, table_name, create_sql):
    try:
        supabase.table(table_name).select("*").limit(1).execute()
        print(f"{table_name} exists")
    except Exception:
        supabase.rpc(
            "execute_sql",
            {"sql": create_sql}
        ).execute()
        print(f"{table_name} created")

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


TIME_COLUMNS = ["round", "wave", "timepoint", "year_month", "period", "month", "term",
                "assessment_date", "submission_date", "date", "today"]


def find_hash_columns(df):
    """Pick the natural key: the most granular id column plus the minimum extra
    time/id columns needed to make rows unique. Measurements are never used.
    Raises if no stable key can be found."""

    ids = sorted((c for c in df.columns if c == "id" or c.endswith("_id")),
                 key=lambda c: df[c].nunique(dropna=False), reverse=True)
    times = [c for c in TIME_COLUMNS if c in df.columns]
    if ids:
        candidates = ids[:1] + times + ids[1:]
        selected = []
        for col in candidates:
            selected.append(col)
            if not df.duplicated(subset=selected).any():
                if "country" in df.columns:
                    selected = ["country"] + selected
                return selected
        raise ValueError(
            f"Rows are not unique on identifier/time columns {selected}. "
            "Check for duplicate submissions in the source data.")
    return _find_measurement_hash_columns(df)


def _find_measurement_hash_columns(df):
    """Fallback for data with no id columns: rank columns by uniqueness."""

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
