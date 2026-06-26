# MwM Proof of Concept V2 - Code Documentation

## Overview

This codebase implements a complete data pipeline for collecting, processing, and visualizing educational survey data from multiple countries. The system supports data ingestion from **Kobo Toolbox** (cloud-based survey platform) or local CSV/Excel files, with automatic deduplication, indicator/dimension aggregation, and interactive dashboards.

The architecture follows a **modular pipeline design** where data flows through distinct transformation stages, each handled by a separate module.

---

## System Architecture

### Data Flow Pipeline

```
INPUT
  ↓
[ingest.py] → Import from Kobo API or file, remove PII, generate UUIDs
  ↓
[aggregate.py] → Compute indicators/dimensions from config, create summary metadata
  ↓
[combine.py] → Merge into persistent combined files, deduplicate on UUID
  ↓
[app.py / dashdash.py] → Load combined data and display interactive dashboards
```

---

## Module Reference

### 1. **ingest.py** - Data Import & Preparation

**Purpose**: Import survey data from Kobo Toolbox API or local files, with metadata extraction and privacy protection.

**Key Classes & Functions**:

- **`build_dataset()`** - Main entry point for importing data
  - Accepts Kobo API credentials OR file path
  - Extracts metadata (form ID, submission dates, country, survey level)
  - Removes PII (child names) for privacy
  - Generates deterministic UUIDs for each row (for deduplication)
  - Logs import to `data/import_log.csv`
  - Returns: `DataSet` object ready for aggregation

- **`DataSet`** - Container class holding raw survey data
  - `.df` - Raw response dataframe
  - `.qdf` - Question metadata (from Kobo schema)
  - `.cdf` - Choice options metadata
  - `.metadata` - Form ID, submission dates, country, level, UUID columns
  - Methods:
    - `.split_multi()` - Expand select_multiple columns into binary columns
    - `.split_group_name()` - Clean column names from repeat groups

- **Helper Functions**:
  - `add_uuid()` - Generate row UUIDs using high-entropy column combinations
  - `drop_child_name_cols()` - Remove child name columns (PII protection)
  - `add_to_log()` - Parse and validate metadata, prompt for missing values
  - `update_log()` - Record final metadata to import log
  - `import_data()` - Read CSV/Excel files with delimiter detection
  - `get_kobo_data()` - Fetch data from Kobo API with repeat group handling
  - `split_multi()` - Expand space-separated multi-select values

**Example Usage**:
```python
from src.ingest import build_dataset

# From Kobo API
dataset = build_dataset(
    BASE_URL="https://kf.kobotoolbox.org/api/v2/assets/",
    ASSET_ID="abc123xyz",
    API_KEY="your_api_token",
    metadata_overrides={"country": "Kenya"}
)

# From CSV file
dataset = build_dataset(
    file_path="data/input/survey.csv",
    metadata_overrides={"level": "child", "country": "Uganda"}
)
```

---

### 2. **aggregate.py** - Indicator & Dimension Calculation

**Purpose**: Transform raw columns into indicators and dimensions using configuration files.

**Configuration-Driven Design**:
- Reads `config/<level>_config.json` (e.g., `child_config.json`)
- Reads `config/dimensions_config.json`
- Resolves which columns map to configured indicators/dimensions
- Computes derived dimensions (binning, transformations)
- Calculates indicators (sum, mean, divide, max operations)

**Key Function**:

- **`aggregates(dataset)`** - Main aggregation pipeline
  - Processes dimensions: maps columns, bins numeric values into categories
  - Processes indicators: resolves columns, computes based on agg_type
    - `simple` indicators: direct column mapping
    - `calculated` indicators: arithmetic operations (sum, mean, divide, max)
    - `aggregate` indicators: derived from multiple calculated indicators
  - Handles missing configurations gracefully (logs available/missing indicators)
  - Populates `dataset.df_short` (only indicator/dimension/UUID columns)
  - Populates `dataset.df_summary` (availability metadata)
  - Returns: Updated dataset ready for combining

**Config File Structure**:
```json
{
  "indicators": [
    {
      "id": "indicator_name",
      "type": "numeric|ordinal|categorical",
      "agg_type": "simple|calculated|aggregate",
      "columns": ["source_col"],
      "calc": {
        "op": "sum|mean|divide|max",
        "columns": ["col1", "col2"],
        "by": 5  // for divide operation
      }
    }
  ]
}
```

---

### 3. **combine.py** - Persistent Combined Datasets

**Purpose**: Merge processed datasets into persistent, deduplicated combined files for each level/country.

**Key Classes & Functions**:

- **`CombinedDataSet`** - Represents combined data for one level + country
  - `.df_short` - Deduplicated combined rows (indicators + dimensions + UUID)
  - `.df_summary` - Union of available/missing indicators and dimensions
  - `.metadata` - Level, country, row count, source form IDs, output path

- **`add_to_combined(dataset, output_dir)`** - Main function to merge a dataset
  - Reads existing combined CSV (if any) for this level/country
  - Merges with new data and deduplicates on UUID
  - Merges summaries (union of available, intersection of missing)
  - Tracks source form IDs
  - Returns: Updated `CombinedDataSet`

- **`school_combined(dataset, output_dir)`** - Aggregate to school level
  - Loads child and teacher combined data
  - Groups by school + month using configured aggregation methods
  - Merges child/teacher aggregates with school-level data
  - Returns: School-level `CombinedDataSet`

- **Helper Functions**:
  - `_load_summary()` / `_save_summary()` - Persistence helpers
  - `_merge_summaries()` - Union available, intersect missing indicators
  - `load_combined()` - Read combined CSV + summary JSON from disk

**Output Structure**:
```
output/<country>/tables/
  ├── combined_child_level.csv
  ├── combined_child_summary.json
  ├── combined_teacher_level.csv
  ├── combined_teacher_summary.json
  ├── combined_school_level.csv
  └── combined_school_summary.json
```

**Example Usage**:
```python
from src.combine import add_to_combined
from pathlib import Path

combined = add_to_combined(dataset, output_dir=Path("data/output"))
print(combined.df_short.shape)  # (rows, cols)
print(combined.df_summary["available_indicators"])
```

---

### 4. **output.py** - Raw Data Export

**Purpose**: Write processed datasets to timestamped CSV files with deduplication and version control.

**Key Functions**:

- **`output_df(dataset)`** - Export dataset to CSV
  - Writes to `output/<country>/<level>/<form_id>_<country>_<date>.csv`
  - Checks for existing file and compares UUIDs
  - If no data loss: overwrites with updated rows
  - If data loss detected: creates timestamped backup (e.g., `..._2024-06-26_15-30-45.csv`)
  - Prints warning about missing rows

- **`add_uuid(df, hash_cols)`** - Generate row UUIDs

---

### 5. **report.py** - Visualization & Analysis

**Purpose**: Generate charts and figures for dashboard display.

**Key Functions**:

- **`classify_series(col)`** - Infer data type (categorical, numeric, ordinal)
  - Uses name and cardinality heuristics
  - Returns category and range descriptor

- **`classify_from_config(col, level, config_dir)`** - Classify using config files
  - Reads indicator/dimension types from JSON config
  - More reliable than heuristics

- **`vars_from_df(df, config_dir)`** - Extract available indicators & dimensions
  - Filters configured indicators/dimensions to those present in df
  - Used by app.py to load data from combined CSV

- **`data_map(dataset)`** - Build metadata dataframe
  - Returns columns: name, ind_type, category, range

- **`plotter(kind, plot, df, dim, ind)`** - Render single chart
  - `kind`: "static" (matplotlib) or "dynamic" (plotly)
  - `plot`: "mean_bar", "stacked_bar", "line", "scatter"
  - Returns figure object

- **`fig_list(dataset, preferred_plot=None, max_figs=10)`** - Generate indicator/dimension pairs
  - Returns DataFrame of (indicator, dimension, plot_type) combinations
  - Filters to valid chart types based on data

---

### 6. **app.py** - Streamlit Dashboard

**Purpose**: Interactive web dashboard for exploring survey data by level (child/teacher/school) and filtering by dimensions.

**Features**:
- **Dashboard Page**:
  - Three tabs (Child, Teacher, School level data)
  - Sidebar filters for geographic/categorical dimensions (admin levels, school)
  - One tab per indicator with charts showing breakdown by dimensions
  - Date range filtering for time-series data
  - Automatic chart type selection (bar, line, scatter, stacked) based on data types

- **Input/Output Page**:
  - File upload interface (CSV/Excel)
  - Kobo API connection (with asset ID and API key)
  - Real-time metadata entry forms
  - Processing status feedback

**Key Functions**:
- `load_classification_maps()` - Load indicator/dimension type mappings
- `load_data(level, country)` - Load combined data for a level/country
- `render_tab(df, summary, level, label)` - Render tab with indicators and filters
- `render_school_tab(df, summary, level, label)` - School-specific renderer

**Run**:
```bash
streamlit run src/app.py
```

---

### 7. **dashdash.py** - Plotly Dash Dashboard (Alternative)

**Purpose**: Alternative dashboard using Plotly Dash framework (similar to app.py but with Dash). **This is just a test - not really fleshed out yet**

**Features**:
- Similar layout and functionality to app.py
- Useful for production deployments or non-Streamlit environments

---

### 8. **theme.py** - Branding & Visualization

**Purpose**: Centralized color schemes and matplotlib styling for Save the Children branding.

**Key Components**:

- **`Colors`** class - Brand color palette
  - Primary: red, purple, blue, green, yellow
  - Shades: light, medium, dark variants
  - Greys: grey_100 to grey_1000

- **`get_ordinal_colors(n)`** - Return color palette for n categories (3-7)
  - Ordinal palettes range from red (low) to green (high)

- **`sc_theme()`** - Apply Save the Children matplotlib theme
  - Sets fonts, colors, gridlines, figure format
  - Used by static plotting functions

---

### 9. **utils.py** - Shared Helpers

**Purpose**: Utility functions used across modules.

**Key Functions**:

- **`find_project_root(start_path, marker_file="path_config.json")`** - Locate project root
  - Searches up directory tree for `path_config.json`

- **`get_project_context(start_path, marker_file="path_config.json")`** - Get project paths
  - Reads `path_config.json`
  - Returns: dict with `project_root`, `config_dir`, `output_dir`, `data_dir`, `input_dir`

- **`find_hash_columns(df)`** - Select columns for UUID generation
  - Chooses 3-12 columns with high uniqueness and low missing data
  - Ensures deterministic UUIDs across imports

- **`make_uuid(row, hash_cols)`** - Generate MD5 hash-based UUID
  - Concatenates hash columns with '|' separator
  - Returns hex string

---

## Configuration Files

Located in `config/`:

### **`path_config.json`**
Maps logical directory names to relative paths:
```json
{
  "config_dir": "config",
  "data_dir": "data",
  "input_dir": "data/input",
  "output_dir": "data/output"
}
```

### **`child_config.json` / `teacher_config.json` / `school_config.json`**
Defines indicators for each survey level:
```json
{
  "indicators": [
    {
      "id": "indicator_id",
      "type": "numeric|ordinal|categorical",
      "level": "child|teacher|school",
      "agg_type": "simple|calculated|aggregate",
      "columns": ["source_column"],
      "calc": {
        "op": "sum|mean|divide|max",
        "columns": ["col1", "col2"],
        "by": 5
      },
      "agg_method": "mean|sum"
    }
  ]
}
```

### **`dimensions_config.json`**
Defines dimensions (breakdowns) across all levels:
```json
{
  "dimensions": [
    {
      "id": "dimension_id",
      "type": "categorical|ordinal|numeric|derived",
      "columns": ["source_column"],
      "agg_method": "first",
      "operation": "bin",  // for derived
      "bins": [
        {"min": 0, "max": 10, "label": "Very Low"},
        {"min": 11, "max": 20, "label": "Low"}
      ]
    }
  ]
}
```

---

## Data Model

### Import Log (`data/import_log.csv`)
Tracks all imported datasets:
- `form_id`: Unique form identifier (used to link repeat imports)
- `survey_name`: Human-readable survey name
- `level`: Survey level (child/teacher/school)
- `first_submission`: Earliest response timestamp
- `last_submission`: Latest response timestamp
- `rows`: Row count
- `country`: Country name
- `_uuid_cols`: Comma-separated column names used for UUID generation
- `logged_at`: Timestamp when imported

---

## Data Privacy

### PII Protection
- Child names automatically removed during import (`drop_child_name_cols()`)
- All personally identifiable information is stripped before aggregation
- Only UUIDs retained for deduplication

### UUID-Based Deduplication
- Deterministic hash-based UUIDs ensure rows are uniquely identified across imports
- Same raw data always produces same UUID
- Enables safe merging of multiple imports without manual deduplication

---

## Workflow Examples

### Example 1: Import Kobo Data, Aggregate, and Visualize

```python
from src.ingest import build_dataset
from src.aggregate import aggregates
from src.combine import add_to_combined
from pathlib import Path

# 1. Import from Kobo
dataset = build_dataset(
    BASE_URL="https://kf.kobotoolbox.org/api/v2/assets/",
    ASSET_ID="abc123xyz",
    API_KEY="your_token",
    metadata_overrides={"country": "Kenya"}
)

# 2. Compute indicators & dimensions
dataset = aggregates(dataset)

# 3. Merge into combined dataset for level/country
combined = add_to_combined(dataset, output_dir=Path("data/output"))

print(f"Combined dataset: {combined.metadata['row_count']} rows")
print(f"Available indicators: {combined.df_summary['available_indicators']}")

# 4. Open dashboard
# streamlit run src/app.py
```

### Example 2: Import CSV File

```python
from src.ingest import build_dataset
from src.aggregate import aggregates
from src.combine import add_to_combined
from pathlib import Path

dataset = build_dataset(
    file_path="data/input/my_survey.csv",
    metadata_overrides={
        "form_id": "myform01",
        "survey_name": "School Survey Round 1",
        "level": "school",
        "country": "Uganda"
    }
)

dataset = aggregates(dataset)
combined = add_to_combined(dataset, output_dir=Path("data/output"))
```

---

## Troubleshooting & Common Tasks

### Add New Indicator
1. Edit `config/<level>_config.json`
2. Add entry to `indicators` array with `id`, `type`, `agg_type`, and `calc` rule
3. Re-run `aggregates()` - new indicator will be computed automatically

### Add New Dimension
1. Edit `config/dimensions_config.json`
2. Add entry to `dimensions` array with `id`, `type`, and `columns`
3. For derived dimensions (e.g., age groups), set `type: "derived"` and `operation: "bin"` with `bins` rules

### Check Data Quality
```python
from src.combine import load_combined

combined = load_combined(Path("data/output"), country="Kenya", level="child")
print(combined.df_summary)  # See available/missing indicators/dimensions
print(combined.df_short.isna().sum())  # Missing data per column
```

### Detect & Resolve Duplicates
- The UUID system handles duplicates automatically
- Check `data/import_log.csv` to see if same form was imported multiple times
- Each import creates new rows with same UUID if data unchanged (deduplication merges them)

### Change Aggregation Method
1. Edit `config/<level>_config.json` or `config/dimensions_config.json`
2. Change `agg_method` (e.g., "mean" → "sum")
3. Re-aggregate and re-combine data

---

## File Structure Quick Reference

```
MwM Proof of Concept V2/
├── src/                          # Python modules
│   ├── __init__.py
│   ├── app.py                    # Streamlit dashboard
│   ├── dashdash.py               # Plotly Dash dashboard
│   ├── ingest.py                 # Data import & preparation
│   ├── aggregate.py              # Indicator/dimension calculation
│   ├── combine.py                # Merge into persistent files
│   ├── output.py                 # Raw data export
│   ├── report.py                 # Visualization helpers
│   ├── theme.py                  # Branding & colors
│   └── utils.py                  # Shared utilities
├── config/                       # Configuration files
│   ├── child_config.json         # Child-level indicators
│   ├── teacher_config.json       # Teacher-level indicators
│   ├── school_config.json        # School-level indicators
│   └── dimensions_config.json    # Dimension definitions
├── data/                         # Data directory
│   ├── input/                    # Raw input files
│   │   ├── aser_sample.csv
│   │   └── school_sample.csv
│   ├── output/                   # Processed output
│   │   └── <country>/tables/
│   │       ├── combined_child_level.csv
│   │       ├── combined_teacher_level.csv
│   │       ├── combined_school_level.csv
│   │       └── *_summary.json
│   └── import_log.csv            # Import tracking log
├── notebooks/                    # Jupyter notebooks
│   └── test_notebook.ipynb
├── path_config.json              # Path mappings
├── requirements.txt              # Python dependencies
├── README_MwM-POC_Architecture.md # Architecture overview
└── README.md                     # This file
```

---

## Dependencies

See `requirements.txt` for full list. Key packages:
- `pandas` - Data manipulation
- `streamlit` - Web dashboard
- `plotly` / `plotly-express` - Interactive charts
- `matplotlib` / `seaborn` - Static charts
- `requests` - HTTP client for Kobo API
- `openpyxl` / `xlrd` - Excel file support

---

## Next Steps for New Team Member

1. **Understand the pipeline**: Read this README and review the architecture diagram in `README_MwM-POC_Architecture.md`
2. **Explore sample data**: Check `data/input/` for example CSVs
3. **Run a test import**: Use `build_dataset()` with a sample file
4. **Review configs**: Edit a small config file to understand the structure
5. **Start the dashboard**: Run `streamlit run src/app.py`
6. **Trace code**: Follow a value through the pipeline (ingest → aggregate → combine → app)

---

## Contact & Support

For questions about specific functions, see docstrings in the source code. Each function has detailed parameter descriptions and usage notes.
