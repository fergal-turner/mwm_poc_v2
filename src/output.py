
from pathlib import Path

import pandas as pd

from src.utils import find_hash_columns, get_project_context, make_uuid


context = get_project_context(start_path=Path(__file__).resolve())
CONFIG_DIR = context["config_dir"]
OUTPUT_DIR = context["output_dir"]
DATA_DIR = context["data_dir"]


def add_uuid(df, hash_cols):
    """Generate deterministic UUIDs for dataset rows for deduplication.
    
    Parameters
    ----------
    df : pd.DataFrame
        DataFrame to add UUIDs to
    hash_cols : list
        Column names to use for UUID generation
        
    Returns
    -------
    tuple
        (df with _uuid column added, list of hash column names)
    """
    hash_cols = find_hash_columns(df)

    if len(hash_cols) > 5:
        print("UID depends on many columns – may be unstable")

    df["_uuid"] = df.apply(
        lambda row: make_uuid(row, hash_cols),
        axis=1
        )

    df["_uuid_cols"] = ",".join(hash_cols)

    return df, hash_cols


def output_df(dataset):
    """Write processed dataset to CSV, with deduplication and version control.
    
    Writes the dataset to output/<country>/<level>/ directory using the form ID,
    country, and first submission date in the filename. On subsequent imports of
    the same form, compares UUIDs to detect data loss and creates versioned
    backups if necessary.
    
    Parameters
    ----------
    dataset : DataSet
        Processed dataset with UUID and metadata
    """
    df = dataset.df

    date_str = dataset.metadata.get("first_submission").strftime("%Y-%m-%d")
    form_id = dataset.metadata.get("form_id")
    country = dataset.metadata.get("country")
    level = dataset.metadata.get("level")

    file_name = form_id + "_" + country + "_" + date_str + ".csv"

    output_path = OUTPUT_DIR / country / level / file_name
    output_path.parent.mkdir(parents=True, exist_ok=True)

    timestamp = pd.Timestamp.now().strftime("%Y-%m-%d_%H-%M-%S")

    if output_path.exists():
        test_df = pd.read_csv(output_path)

        if "_uuid" in test_df.columns:
            existing_uuids = set(test_df["_uuid"])

            if "_uuid" in df.columns:
                new_uuids = set(df["_uuid"])

            elif "_uuid_cols" in test_df.columns:
                uuid_cols = test_df["_uuid_cols"].iloc[0].split(",")

                df["_uuid"] = df.apply(
                    lambda row: make_uuid(row, uuid_cols), axis=1
                )

                df["_uuid_cols"] = ",".join(uuid_cols)

                new_uuids = set(df["_uuid"])

            else:
                raise ValueError("Cannot reconstruct UUIDs for comparison")

            # ---- compare ----
            if existing_uuids.issubset(new_uuids):
                print("Safe overwrite: no data loss detected")

                added = new_uuids - existing_uuids
                print(f"Added rows: {len(added)}")

                df.to_csv(output_path, index=False)

            else:
                print("Data loss detected: saving new version")

                missing = existing_uuids - new_uuids
                print(f"Missing rows: {len(missing)}")

                new_path = output_path.with_name(
                    f"{output_path.stem}_{timestamp}{output_path.suffix}"
                )
                df.to_csv(new_path, index=False)

        else:
            print("No UID in existing file -> creating versioned dataset")

            hash_cols = find_hash_columns(df)

            df["_uuid"] = df.apply(
                lambda row: make_uuid(row, hash_cols), axis=1
            )
            df["_uuid_cols"] = ",".join(hash_cols)

            new_path = output_path.with_name(
                f"{output_path.stem}_{timestamp}{output_path.suffix}"
            )
            df.to_csv(new_path, index=False)

    else:
        print("No existing file -> adding uuids and saving new dataset")
        hash_cols = find_hash_columns(df)

        df["_uuid"] = df.apply(
            lambda row: make_uuid(row, hash_cols), axis=1
        )
        df["_uuid_cols"] = ",".join(hash_cols)

        df.to_csv(output_path, index=False)