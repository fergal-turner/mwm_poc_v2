
import os
from pathlib import Path

import pandas as pd
import requests

from src.utils import find_hash_columns, get_project_context, make_uuid


# ========================================================================
# KOBO IMPORT AND PREP FUNCTIONS
# ========================================================================
def get_kobo_data(BASE_URL, ASSET_ID, API_KEY):
    """
    Fetches Kobo survey data and returns a DataFrame. If GROUP_BY is specified, it will allow for repeat groups, using the name of the group.

    """

    def get_kobo_meta(BASE_URL, ASSET_ID, API_KEY):

        url = f"{BASE_URL}{ASSET_ID}/valid_content/"

        response = requests.get(
            url,
            headers={"Authorization": f"Token {API_KEY}",
                    "Accept": "application/json"}
            )

        def extract_label(value):
            """Return the first usable label from Kobo's variable label formats."""
            if value is None:
                return None

            if isinstance(value, str):
                cleaned = value.strip()
                return cleaned or None

            if isinstance(value, dict):
                for v in value.values():
                    if isinstance(v, str) and v.strip():
                        return v.strip()
                return None

            if isinstance(value, list):
                for v in value:
                    if isinstance(v, str) and v.strip():
                        return v.strip()
                    if isinstance(v, dict):
                        nested = extract_label(v)
                        if nested:
                            return nested
                return None

            return None

        def get_questions_df(data):
            survey = data["data"]["survey"]

            rows = []
            for q in survey:
                    rows.append({
                        "name": q.get("name"),
                        "type": q.get("type"),
                        "label": extract_label(q.get("label")),
                        "required": q.get("required", False),
                        "list_name": q.get("select_from_list_name"),
                        "relevant": q.get("relevant"),
                        "calculation": q.get("calculation")
                    })

            return pd.DataFrame(rows)

        def get_choices_df(data):
            choices = data["data"]["choices"]

            rows = []
            for c in choices:
                rows.append({
                    "list_name": c.get("list_name"),
                    "choice_name": c.get("name"),
                    "label": extract_label(c.get("label")),
                })

            return pd.DataFrame(rows)

        qdf = get_questions_df(response.json())
        cdf = get_choices_df(response.json())

        return qdf, cdf

    url = f"{BASE_URL}{ASSET_ID}/data/"

    qdf, cdf = get_kobo_meta(BASE_URL, ASSET_ID, API_KEY)

    if qdf['type'].str.startswith('begin_repeat').any():
        if qdf['type'].str.startswith('begin_repeat').sum() > 1:
            raise ValueError("Multiple repeat groups detected. This function currently only supports one repeat group.")
        else:
            GROUP_BY = qdf[qdf['type'].str.startswith('begin_repeat')]['name'].values[0]

    response = requests.get(
        url,
        headers={"Authorization": f"Token {API_KEY}",
                 "Accept": "application/json"}
    )

    response = response.json()

    if 'GROUP_BY' in locals():
        df = pd.json_normalize(response['results'], record_path=GROUP_BY, meta=[elem for elem in response['results'][0].keys() if elem != GROUP_BY])
        df.columns = df.columns.str.replace(f"{GROUP_BY}/", '', regex=False)

    else:
        df = pd.json_normalize(response['results'])

    form_id = df['_xform_id_string'].unique()

    if len(form_id) > 1:
        raise ValueError("Multiple form IDs detected. This function currently only supports one form ID.")

    qdf['form_id'] = form_id[0]
    cdf['form_id'] = form_id[0]
    df = df.rename(columns={'_xform_id_string': 'form_id'})

    return df, qdf, cdf


def import_data(file_path):
    """Import survey data from a CSV or Excel file.
    
    Attempts to detect file format and delimiter, then reads data into a DataFrame.
    
    Parameters
    ----------
    file_path : str
        Path to the .csv, .xls, or .xlsx file
        
    Returns
    -------
    pd.DataFrame
        The imported survey data
        
    Raises
    ------
    ValueError
        If file format is unsupported or delimiter cannot be detected
    """
    if file_path.endswith('.xls') or file_path.endswith('.xlsx'):
        df = pd.read_excel(file_path)
    elif file_path.endswith('.csv'):
        for sep in [',', ';']:
                try:
                    df = pd.read_csv(file_path, sep=sep)
                    # basic sanity check: more than 1 column
                    if df.shape[1] > 1:
                        return df
                except Exception:
                    pass
        raise ValueError("Could not detect delimiter")
    else:
        raise ValueError("Unsupported file format. Please provide a .csv, .xls, or .xlsx file.")

    return df


def split_multi(df, qdf):
    """Split select_multiple columns into individual binary columns.
    
    When a Kobo form has select_multiple questions, responses are stored as
    space-separated values. This function expands them into separate binary columns
    for easier analysis and aggregation.
    
    Parameters
    ----------
    df : pd.DataFrame
        Data to transform
    qdf : pd.DataFrame
        Question dataframe with 'type' column to identify select_multiple questions
        
    Returns
    -------
    pd.DataFrame
        DataFrame with select_multiple columns split into individual columns
    """
    if not qdf['type'].str.startswith('select_multiple').any():
        return df

    columns = qdf[qdf['type'].str.startswith('select_multiple')]['name'].values

    # split into columns
    for col in columns:
        dummies = df[col].str.get_dummies(sep=" ")
        dummies.columns = [f"{col}_{subcol}" for subcol in dummies.columns]
        df = pd.concat([df, dummies], axis=1)
        df.drop(columns=[col], inplace=True)
    return df


def add_to_log(df, source='kobo', metadata_overrides=None, interactive=True):
    """Extract metadata from survey data and add/update the import log.
    
    This function parses submission timestamps and form IDs from data, prompts for
    missing metadata (survey name, level, country) if running interactively, and
    logs the dataset to data/import_log.csv to track all imported surveys.
    
    Parameters
    ----------
    df : pd.DataFrame
        Raw survey data with submission metadata
    source : str, default 'kobo'
        'kobo' for Kobo API data or 'file' for CSV/Excel imports
    metadata_overrides : dict, optional
        Pre-filled metadata values (form_id, survey_name, level, country, dates)
    interactive : bool, default True
        Whether to prompt for missing metadata interactively
        
    Returns
    -------
    dict
        Metadata dictionary with form_id, survey_name, level, country, first/last submission,
        row count, and UUID column specification
    """
    context = get_project_context(start_path=Path(__file__).resolve())
    DATA_DIR = context["data_dir"]
    metadata_overrides = metadata_overrides or {}

    log_path = f"{DATA_DIR}/import_log.csv"

    if not os.path.exists(log_path):
        log_df = pd.DataFrame(columns=['form_id', 'survey_name', 'level', 'first_submission', 'last_submission', 'rows', 'country', '_uuid_cols', 'logged_at'])
    else:
        log_df = pd.read_csv(log_path)

    def parse_kobo_metadata(df):
        df = df.copy()

        form_id = df['form_id'].unique()[0]
        survey_name = None

        df['_submission_time'] = pd.to_datetime(df['_submission_time'], format='%Y-%m-%d %H:%M:%S', errors='coerce').dt.floor('min').dt.tz_localize(None)

        first_submission = df['_submission_time'].min().floor('min')
        last_submission = df['_submission_time'].max().floor('min')
        rows = len(df)

        df_low = df.copy()
        df_low.columns = df_low.columns.str.lower()

        if 'country' in df_low.columns:
            if df_low['country'].nunique() > 1:
                country = 'multiple'
            else:
                country = df_low['country'].unique()[0]
        else:
            country = None

        metadata = {
            'form_id': form_id,
            'survey_name': survey_name,
            'level': None,
            'first_submission': first_submission,
            'last_submission': last_submission,
            'rows': rows,
            'country': country,
            '_uuid_cols': None
        }

        return metadata

    def parse_xls_csv_metadata(df):

        if 'form_id' in df.columns:
            form_id = df['form_id'].unique()[0]
        else:
            form_id = None

        survey_name = None
        if '_submission_time' not in df.columns:

            cols = df.columns.str.lower()

            if any(col in cols for col in ['today', 'start', 'end', 'date', 'submission_date', 'timestamp']):
                date_col = next(col for col in df.columns if col.lower() in ['today', 'start', 'end', 'date', 'submission_date', 'timestamp'])
                df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                df['_submission_time'] = df[date_col]

            else:
                df['_submission_time'] = pd.NaT

        df['_submission_time'] = pd.to_datetime(df['_submission_time'], format='%Y-%m-%d %H:%M:%S', errors='coerce').dt.floor('min').dt.tz_localize(None)

        first_submission = pd.to_datetime(df['_submission_time'].min(), format='%Y-%m-%d %H:%M:%S', errors='coerce').floor('min')
        last_submission = pd.to_datetime(df['_submission_time'].max(), format='%Y-%m-%d %H:%M:%S', errors='coerce').floor('min')

        rows = len(df)

        if 'country' in df.columns.str.lower():
            if df['country'].nunique() > 1:
                country = 'multiple'
            else:
                country = df['country'].unique()[0]
        else:
            country = None

        metadata = {
            'form_id': form_id,
            'survey_name': survey_name,
            'level': None,
            'first_submission': first_submission,
            'last_submission': last_submission,
            'rows': rows,
            'country': country,
            '_uuid_cols': None
        }

        return metadata

    if source == 'kobo':
        metadata = parse_kobo_metadata(df)
    else:
        metadata = parse_xls_csv_metadata(df)

    if metadata['form_id'] is None:
        metadata['form_id'] = metadata_overrides.get('form_id')
        if metadata['form_id'] is None:
            if interactive:
                metadata['form_id'] = input("No form ID found in the data. Please enter a form ID to use for logging purposes. if this form has been used previously, use the same form ID to link the datasets. Form ID: ")
            else:
                raise ValueError("Missing form_id. Provide metadata_overrides['form_id'] when running non-interactively.")

    if metadata['form_id'] in log_df['form_id'].values:
        print(f"Form ID {metadata['form_id']} already exists in the log. Processed data will be added to the existing dataset.")

        metadata['survey_name'] = log_df[log_df['form_id'] == metadata['form_id']]['survey_name'].values[0]
        metadata['level'] = log_df[log_df['form_id'] == metadata['form_id']]['level'].values[0]
        metadata['country'] = log_df[log_df['form_id'] == metadata['form_id']]['country'].values[0]
        metadata['first_submission'] = log_df[log_df['form_id'] == metadata['form_id']]['first_submission'].values[0]
        metadata['last_submission'] = log_df[log_df['form_id'] == metadata['form_id']]['last_submission'].values[0]
        metadata['_uuid_cols'] = log_df[log_df['form_id'] == metadata['form_id']]['_uuid_cols'].values[0]

    else:
        print(f"Form ID {metadata['form_id']} added to log. Processed data will be saved as a new file.")

        metadata['survey_name'] = metadata_overrides.get('survey_name')
        if not metadata['survey_name']:
            if interactive:
                metadata['survey_name'] = input("Please enter the survey name: ")
            else:
                raise ValueError("Missing survey_name. Provide metadata_overrides['survey_name'] when running non-interactively.")

        metadata['level'] = metadata_overrides.get('level')
        if interactive:
            while metadata['level'] not in ['child', 'teacher', 'school']:
                metadata['level'] = input("Please enter the survey level (child, teacher or school): ")
                if metadata['level'] not in ['child', 'teacher', 'school']:
                    print("Invalid level. Try again.")
        elif metadata['level'] not in ['child', 'teacher', 'school']:
            raise ValueError("Missing or invalid level. Provide metadata_overrides['level'] as one of: child, teacher, school.")

        if metadata['country'] is None:
            metadata['country'] = metadata_overrides.get('country')
            if metadata['country'] is None:
                if interactive:
                    metadata['country'] = input("Please enter the country name for this survey (multiple if applicable): ")
                else:
                    raise ValueError("Missing country. Provide metadata_overrides['country'] when running non-interactively.")

        if pd.isna(metadata['first_submission']):
            date_input = metadata_overrides.get('first_submission')
            if date_input is None and interactive:
                date_input = input("No submission time found. Please enter the date of the first submission (YYYY-MM-DD) or leave blank: ")
            if date_input:
                metadata['first_submission'] = pd.to_datetime(date_input, errors='coerce')
            else:
                metadata['first_submission'] = pd.NaT

        if pd.isna(metadata['last_submission']):
            date_input = metadata_overrides.get('last_submission')
            if date_input is None and interactive:
                date_input = input("No submission time found. Please enter the date of the last submission (YYYY-MM-DD) or leave blank: ")
            if date_input:
                if pd.notna(metadata['first_submission']) and pd.to_datetime(date_input, errors='coerce') < metadata['first_submission']:
                    if interactive:
                        print("Last submission date cannot be before first submission date. Please enter a valid date.")
                        date_input = input("Please enter the date of the last submission (YYYY-MM-DD) or leave blank: ")
                    else:
                        raise ValueError("last_submission cannot be before first_submission.")
                metadata['last_submission'] = pd.to_datetime(date_input, errors='coerce')
            else:
                metadata['last_submission'] = pd.NaT

    print("Metadata added to log:")
    print(metadata)

    return metadata

def update_log(dataset):
    """Update the import log with the dataset's final metadata after processing.
    
    Appends or updates the log entry for a dataset and records the current timestamp.
    
    Parameters
    ----------
    dataset : DataSet
        Processed dataset with metadata populated
    """
    log_path = Path(get_project_context(start_path=Path(__file__).resolve())["data_dir"]) / "import_log.csv"
    log_df = pd.read_csv(log_path)

    metadata = dataset.metadata

    log_df = pd.concat([log_df, pd.DataFrame([metadata])], ignore_index=True)

    log_df['logged_at'] = pd.to_datetime(log_df['logged_at'], format='%Y-%m-%d %H:%M:%S', errors='coerce')

    log_df.loc[log_df.index[-1], 'logged_at'] = pd.Timestamp.now().floor('min')

    log_df.to_csv(log_path, index=False)

    for key, value in metadata.items():
        log_df.loc[log_df['form_id'] == metadata['form_id'], key] = value

    log_df.to_csv(log_path, index=False)
    

# ========================================================================
# DATASET OBJECT AND IDENTIFIER HELPERS
# ========================================================================
class DataSet:
    """Container for raw survey data with methods for preprocessing.
    
    Holds the raw dataframe, question/choice metadata, and dataset metadata.
    Provides convenience methods for splitting multi-select columns and
    removing personally identifiable information.
    
    Attributes
    ----------
    df : pd.DataFrame
        Raw survey responses
    qdf : pd.DataFrame, optional
        Question metadata from form schema (column metadata)
    cdf : pd.DataFrame, optional
        Choice options metadata for select questions
    metadata : dict
        Form ID, submission dates, country, survey level, UUID columns
    """
    def __init__(self, df, qdf, cdf, metadata):
        self.df = df
        self.qdf = qdf
        self.cdf = cdf
        self.metadata = metadata

    def split_multi(self):
        """Split select_multiple columns into individual binary columns.
        
        Returns
        -------
        DataSet
            New DataSet with select_multiple expanded
        """
        df = self.df.copy()

        if not self.qdf['type'].str.startswith('select_multiple').any():
            return DataSet(df, self.qdf, self.cdf, self.metadata)

        columns = self.qdf[self.qdf['type'].str.startswith('select_multiple')]['name'].values

        # split into columns
        for col in columns:
            dummies = df[col].str.get_dummies(sep=" ")
            dummies.columns = [f"{col}_{subcol}" for subcol in dummies.columns]
            df = pd.concat([df, dummies], axis=1)
            df.drop(columns=[col], inplace=True)

        return DataSet(df, self.qdf, self.cdf, self.metadata)
    
    def split_group_name(self):
        """Remove group prefixes from column names after repeat group expansion.
        
        Kobo repeat groups create nested column names like 'group/column'.
        This method extracts just the column part.
        
        Returns
        -------
        DataSet
            New DataSet with simplified column names
        """
        df = self.df.copy()
        df.columns = df.columns.str.split("/").str[-1]

        return DataSet(df, self.qdf, self.cdf, self.metadata)


def drop_child_name_cols(dataset):
    """Remove child name columns to protect privacy during data processing.
    
    Searches for and removes columns containing 'child_name' or 'name' (case-insensitive)
    to ensure personally identifiable information is not retained in processed datasets.
    
    Parameters
    ----------
    dataset : DataSet
        Dataset to clean
        
    Returns
    -------
    DataSet
        Dataset with name columns removed
    """
    df = dataset.df.copy()

    # find columns with 'child' or 'name' in them
    cols_to_drop = [
        c for c in df.columns.str.lower().str.replace(" ", "_") if c == "child_name" or c == "name"
    ]

    if cols_to_drop:
        df = df.drop(columns=cols_to_drop)
        print(f"Dropped columns: {cols_to_drop} to protect child privacy")

    dataset.df = df
    return dataset


def add_uuid(dataset):
    """Generate deterministic row UUIDs based on key columns to enable deduplication.
    
    Selects columns with high uniqueness and low missing data, then creates a hash-based
    UUID for each row. If UUIDs from a previous import are available in metadata,
    uses those same columns for consistency. Handles duplicate keys by appending an index.
    
    Parameters
    ----------
    dataset : DataSet
        Dataset to add UUIDs to
        
    Returns
    -------
    DataSet
        Dataset with _uuid column added and metadata updated with column specification
    """
    uuid_cols = dataset.metadata.get('_uuid_cols')

    if '_uuid' in dataset.df.columns:
        print("UUID column already exists. Skipping UUID generation.")
        return dataset

    elif pd.notna(uuid_cols) and uuid_cols != "":
        hash_cols = uuid_cols.split(",")
        print(f"Using previously logged hash columns for UUID generation: {hash_cols}")

    else:
        hash_cols = find_hash_columns(dataset.df)

    if len(hash_cols) > 5:
        print(f"UID depends on {len(hash_cols)} columns - may be unstable")

    frame = dataset.df.copy()
    key_series = frame[hash_cols].astype("string").fillna("").agg("|".join, axis=1)
    uuid_series = pd.util.hash_pandas_object(key_series, index=False).astype(str)

    if uuid_series.duplicated().any():
        dup_counts = key_series.groupby(key_series).cumcount().astype(str)
        is_dup = key_series.duplicated(keep=False)
        uuid_series.loc[is_dup] = uuid_series.loc[is_dup] + "_" + dup_counts.loc[is_dup]
        print("Detected duplicate hash keys; appended duplicate index suffix for uniqueness.")

    
    dataset.df['_uuid'] = uuid_series
    _uuid_cols = ",".join(hash_cols)
    dataset.metadata['_uuid_cols'] = _uuid_cols

    return dataset


# ========================================================================
# PUBLIC BUILDER ENTRYPOINT
# ========================================================================
def build_dataset(BASE_URL=None, ASSET_ID=None, API_KEY=None, file_path=None, metadata_overrides=None, interactive=True):
    """Import and prepare survey data from Kobo or file, with metadata logging and deduplication.
    
    This is the main public entry point for ingesting survey data. It handles both
    API imports (Kobo) and file uploads (CSV/Excel), extracts metadata, removes PII,
    generates UUIDs, and logs the import. The resulting DataSet is ready for aggregation.
    
    Parameters
    ----------
    BASE_URL : str, optional
        Kobo server URL (e.g., 'https://kf.kobotoolbox.org/api/v2/assets/')
    ASSET_ID : str, optional
        Kobo asset/form ID
    API_KEY : str, optional
        Kobo API authentication token
    file_path : str, optional
        Path to CSV or Excel file (alternative to Kobo API)
    metadata_overrides : dict, optional
        Pre-filled metadata values
    interactive : bool, default True
        Prompt for missing metadata values
        
    Returns
    -------
    DataSet
        Prepared dataset with UUID and metadata, ready for aggregation
        
    Raises
    ------
    ValueError
        If neither file_path nor (BASE_URL, ASSET_ID, API_KEY) are provided,
        or if required metadata cannot be obtained
    """
    # If file_path is provided, import data from file. Otherwise, fetch data from Kobo API.
    if file_path:
        df = import_data(file_path)
        metadata = add_to_log(df, source='file', metadata_overrides=metadata_overrides, interactive=interactive)
        frame = df.copy()
        if '_submission_time' not in frame.columns:
            frame = frame.assign(_submission_time=metadata['last_submission'])
            frame['_submission_time'] = pd.to_datetime(frame['_submission_time'], format='%Y-%m-%d', errors='coerce').dt.floor('D')
        else:
            frame['_submission_time'] = frame['_submission_time'].fillna(metadata['last_submission'])
            frame['_submission_time'] = pd.to_datetime(frame['_submission_time'], format='%Y-%m-%d', errors='coerce').dt.floor('D')
        df = frame
        print("Data imported from file. Kobo metadata functions will be skipped (question dataframe and choices dataframe). Only basic metadata will be logged.")
        dataset = DataSet(df, None, None, metadata)
        dataset.df.columns = dataset.df.columns.str.split("/").str[-1]
        dataset = drop_child_name_cols(dataset)
        dataset = add_uuid(dataset)
        update_log(dataset)

        return dataset

    if not all([BASE_URL, ASSET_ID, API_KEY]):
        raise ValueError("BASE_URL, ASSET_ID, and API_KEY must be provided if file_path is not specified.")

    df, qdf, cdf = get_kobo_data(BASE_URL, ASSET_ID, API_KEY)
    metadata = add_to_log(df, source='kobo', metadata_overrides=metadata_overrides, interactive=interactive)
    print("Data fetched from Kobo API and metadata logged including question and choice dataframes (.qdf and .cdf).")
    dataset = DataSet(df, qdf, cdf, metadata)
    dataset.df.columns = dataset.df.columns.str.split("/").str[-1]
    dataset = drop_child_name_cols(dataset)
    dataset = add_uuid(dataset)
    update_log(dataset)

    return dataset
