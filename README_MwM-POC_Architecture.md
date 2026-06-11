# MwM System Architecture Notes

> Purpose: living document to capture design decisions before and during system build

# **Overview of Structure for repo**

The below is the structure for the repo, including folders for datasets, and example .py files. This structure will be simpler than the final architecture but designed as a proof of concept for the approach. 

| Folder | Folder / File                | Purpose                         | Notes                                      |
|--------|-----------------------------|----------------------------------|--------------------------------------------|
|        | run_pipeline.py             | Main entry point                | Orchestrates the full pipeline             |
| notebooks |                          | Notebooks for testing and developing functions |                             |
| Config | config/                     | All configuration               | Keeps logic separate from code             |
| Config | config/config.json          | Indicator definitions           | Maps columns → indicators, types, aggregation |
| Data   | data/raw/                   | Input data                      | Kobo exports + .xls files                  |
| Data   | data/clean/                 | Clean tool-level tables         | One file per tool                          |
| Data   | data/combined/              | Joined datasets                 | Child-level, school-level tables           |
| Data   | data/output/                | Final outputs                   | Dashboard-ready + reports                  |
| Code   | code/                       | Core logic                      | All processing code lives here             |
| Code   | code/ingest.py              | Data loading & creation of dataset objects | Kobo + Excel → DataFrames → objects |
| Code   | code/transform.py           | Cleaning + standardisation      | Apply config, rename columns, fix types    |
| Code   | code/combine.py             | Table joins                     | Create child/school combined tables        |
| Code   | code/output.py              | Save + export                   | Write CSV/parquet + trigger reports        |
| Code   | code/report.py              | Report generation               | School / programme reports                 |
| Code   | code/dashboard.py (optional) | Simple dashboard                | e.g. Streamlit or export for Power BI      |
|        | README.md                   | Instructions                    | How to run + structure overview            |
|        | requirements.txt            | Dependencies                    | pandas, openpyxl, etc.                     |


# **Requirements for the Proof of Concept**

1. Ingest data from both Kobo and .xls files, prompting the user for metadata and creating a data object with tracked metadata
2. Recognise which config indicators are included in the data. It does this in reference to a config.json file which includes indicators and response options.
3. Create a clean base-table for that dataset, including calculated indicators and simple indicators. Option to create a summary table (calculated indicators only), and a full table (all raw data + calculated indicators)
4. Create a new child or school level table which combines data from more than one source table
5. Outputs all of these tables locally (as opposed to on OneLake)
6. Can thereafter output data to a) a dashboard, and b) one of two report types (based on a user input). 
7. Is all wrapped within a run_pipeline.py file

# **Process for working on Proof of Concept**

Our general pipeline will be to a) map out the overall architecture including framing and resolving core design questions (see core design questions below), b) map out specific functions for each .py file, c) use .ipynb notebooks (stored under notebooks/) to iteratively develop and test specific functions d) migrate functions to .py files which can be batch run through run_pipepline.py for testing 

Our aim will be to use AI to generate as much of the actual code as possible. However, human oversight is essential for ensuring the coherence of the overall design, and for ensuring consistency of the approach to coding. 

---

# **Core Design Questions**

## **Should MwM use an object-based approach for datasets?**

**Decision** : Use a **lightweight object-based structure** for datasets.

**Rationale**
- Ensures consistency across datasets
- Enables reuse across indicators and outputs
- Preserves traceability (critical for MwM credibility)
- Supports scaling into a system rather than one-off analyses

---

### **Overall System Model**

Dataset → Indicator → Output

Definitions

**Dataset** :  Data + metadata + processing history

**Indicator** : Defined calculation using one or more datasets

**Output** : Dashboard, report, or other user-facing product

---

### **Dataset Design**

**Structure (minimum viable)**:

This is an example list of the attributes/metadata that we could attach to the dataset objects, that could then be traced back all the way through the analysis process. 
- name
- source
- date_range
- level
- data
- cleaning_steps

**Design Principle**

Datasets are **structured containers with limited behaviour**.

Not full object-oriented systems.

---

### **Pipeline Design**

**Flow:**

Import → Dataset → Clean → Analyse → Output

**Key Rules:**

- Dataset created once at import
- Same dataset passed through pipeline
- Metadata updated at each step
- Dataset retained through to output stage (or at least metadata)

---

### **Functions vs Methods**

We may keep some methods that can be applied directly to the dataset object (e.g., dataset.summary()), but in the main functions will be used (e.g. func(dataset, params)). We can create a wrapper apply(dataset, func, params) which allows for the cleaning and processing steps to be logged for a dataset for transparency. 

This means that the dataset object has few (if any) method, but is more a way of storing metadata, configs, ogged steps - helping with consistency and scalability, and making writing functions more straightforward. 

---

### **Cleaning Steps Logging**

We can include lines in functions to log datacleaning steps. so it would use a dataset._log_step() method to add a dictionary of "actions" completed at each step. For example if we are replacing missing data, it could record a list of dictionaries of actions (column:, method:, n-replaced:), which could then later be called to trace back decisions made. Example of encoding the _log_step() in the Dataset class is shown below. 

```python
  class Dataset:
      def __init__(self, data, metadata=None):
          self.data = data
          self.metadata = metadata or {}
          
          if "cleaning_steps" not in self.metadata:
              self.metadata["cleaning_steps"] = []

      def _log_step(self, step_name, params=None):
          entry = {
              "step": step_name
          }
          
          if params:
              entry["params"] = params
          
          self.metadata["cleaning_steps"].append(entry)
```
---

### Metadata Automation Strategy

Combine:

- Templates (config files) - these would allow for meta-data (source of data, country name, etc.) to be included for each dataset created. This would be kept to a minimum, with as much being auto-extracted from the dataset as possible. 
- Auto-extraction (e.g. date range, columns)
- Defaults
- Naming conventions

Automate repeatable metadata. Keep meaning human-defined. This would mean that when people are updloading datasets they would be prompted for key metadata such as name and source of the dataset, with others being automatically produced. The system would first automatically detect some fields, before prompting the user to validate and fill in gaps. 

## **02 How to handle simple and composite indicators?**

### Problem

MwM datasets may contain:

- **Simple indicators** (single column)
  - e.g. attendance
- **Composite indicators** (multiple columns combined)
  - e.g. HALDO (20+ items → one score)

These need to be:
- Identified clearly
- Calculated consistently
- Recombined into a unified dataset

---

### Decision

Use a **schema-driven approach** to define indicators, separating:

- Dataset (raw columns)
- Indicator definitions (logic + column mapping)
- Output datasets (final calculated values)

---

### Indicator Definition Structure

Define indicators in a config/schema layer:

- Simple indicators:
  - reference a single column

- Composite indicators:
  - reference a list of columns
  - apply a calculation function

This avoids relying solely on column names and keeps logic explicit.

---

### Processing Flow

1. **Load dataset**
   - Dataset contains all raw columns (including HALDO items)

2. **Parse using schema**
   - Extract relevant columns for each indicator
   - Separate dimensions (e.g. sex, age)

3. **Calculate indicators**
   - Simple: pass through or lightly transform
   - Composite: aggregate multiple columns → single value per row

4. **Recombine outputs**
   - Create new dataframe aligned on UID
   - Combine:
     - UID
     - Dimensions
     - Final indicator values

---

### Recombination Design

All outputs must:

- Preserve row-level alignment
- Use UID or index as the backbone
- Return one value per row per indicator

Two output datasets are produced:

#### 1. Full dataset (detailed)

Contains:
- All raw columns
- Calculated indicators

Used for:
- Validation
- Debugging
- Deep analysis

#### 2. Analytical dataset (clean)

Contains:
- UID
- Dimensions
- Final indicators only

Used for:
- Reporting
- Dashboards
- Modelling

---

### Object Model Integration

- Treat outputs as new dataset objects
- Record provenance:
  - source dataset
  - indicators applied

This preserves traceability across the pipeline

---

### Design Principles

- Dataset does not “know” indicator structure
- Indicator logic is defined externally (schema + functions)
- All indicators return row-aligned outputs
- Recombination is an explicit step

---

### Result

This approach enables:

- Clean handling of both simple and complex indicators
- Consistent processing pipeline
- Scalable system design
- Strong traceability for MwM outputs

---

### Note on Aggregation

Multi-level aggregation (e.g. school, region) can be handled simply using:

- `groupby()`
- aggregation dictionaries (`agg`)

No additional architectural complexity is required for this layer.

## **03 What goes into the config? How do we handle variance between countries/cases**

### Basic config design

Separate:

- **Logic (config)** → how the system works
- **Context (metadata)** → what this dataset is

> "Config defines behaviour; metadata defines context"

---

#### Base Config (Project-Level)

Stored in: `config/config.json`

**Purpose:** Defines stable system rules that apply across datasets.

*Example*

```json
{
  "indicators": {
    "attendance": {
      "type": "direct",
      "column": "attendance"
    },
    "haldo": {
      "type": "composite",
      "columns": ["haldo_q1", "haldo_q2", "haldo_q3"],
      "method": "mean"
    }
  },
  "aggregation": {
    "attendance": "mean",
    "haldo": "mean"
  }
}
```
**Key Characteristics:**

- Stable across datasets
- Defined once and reused
- Does not contain dataset-specific values

---

### Runtime Metadata (User Input)

**Purpose:** Captures information specific to a dataset instance. Collected at upload (CLI or Streamlit).

*Example*

```python
metadata = {
  "dataset_type": "assessment",
  "level": "student",
  "source": "Kenya national system",
  "country": "Kenya",
  "year": 2025
}
```

**Key Characteristics:**

- Varies by dataset
- May be partly auto-generated (e.g. country, date range)
- Stored on dataset object

---

### Combining Config and Metadata

**Approach:**

- Load base config from file
- Collect user inputs
- Keep them separate, but use both in pipeline

---

*Example Process*

```python
base_config = load_json("config/config.json")

metadata = collect_user_input()

dataset = Dataset(data=df, metadata=metadata)
```

Then downstream:

```python
run_pipeline(dataset, base_config)
```

---

### Usage in Pipeline

Config drives logic

```python
for indicator, spec in config["indicators"].items():
    calculate_indicator(dataset, spec)
```

Metadata drives behaviour selection

```python
if dataset.metadata["level"] == "student":
    run_student_pipeline(dataset)
```

---

### Dimensions (Disaggregation Variables)

These are stored in the global 

```json
{
  "dimensions": {
    "sex": {"column": "sex"},
    "age": {"column": "age"}
  }
}
```

✅ Apply across all countries/projects

In the future, we may want to adapt this to be able to handle dimensions which are defined differently in different places, or even to create dictionaries of all possible responses, to be able to map where there are no responses by a certain group. 

---

### Final Combined View

At runtime, your system effectively uses:

**Config (logic):**
- indicators
- aggregation
- global dimensions

**Metadata (context):**
- level
- dataset_type
- source
- country

---

## **04 How to call the right data from the kobo API?**

This is a simpler question. Our aim for getting data out of the kobo API, is that it arrives:
1. With names rather than labels across the board
2. Without group names included
3. With seperate columns for any select multiple options

This means we would append our API call with:

    /data.json?hierarchy=False&split_select_multiples=True 

This will give us the right data. 

API keys stored in .env which is not pushed to Github (logged under .gitignore)

## **05 How will we ensure consistent formatting in Plotly/Streamlit**

For our dashboards we will use streamlit, hosting plotly figures. We will use plotly for interactivity - though for static reports we have a preference for pylot figures and seaborn axes for better formatting and cleaner syntax. 

To make sure that our app.py is as clean as possible, as well as giving us a way to centrally manage and edit formatting choices - we will create a series of config .json files in our /config folder. 

**Formatting Configs**

*process*
- Create dictionaries for different style elements to be passed in plotly, including base_configs, axis_configs, and other configs that can be used by plotly
- Add these seperately under fig.update_layout.
- Additional seperate updates can be layered on top
- to do this we would need a simple load_config function that would sit under utils

**Hover Configs**

*Process*
- Store a fields.json which has a dictionary for possible fields we would have in a figure (e.g., score, progress, date, school_id etc.). This dictionary captures; "label" i.e., human readable name, and "format" e.g., how we would like the number displayed. 
- build a get_field function and a build_hover function which can combine the data pulled from the .json file into a string which is passed to fig.update_traces(hovertemplate= )

*Example of build_hover*

```python

def build_hover(fields):
    parts = []

    for f in fields:
        field = get_field(f)
        label = field["label"]
        fmt = field["format"]

        if fmt:
            parts.append(f"{label}: %{{y:{fmt}}}")
        else:
            parts.append(f"{label}: %{{y}}")

    parts.append("<extra></extra>")
    return "<br>".join(parts

```
---


## **05. Dataset Versioning Strategy**

To ensure reliable dataset versioning during ingestion, a hybrid approach combining automatic detection and manual input will be used.

#### Principles
- Prefer automatic version linking where a stable external identifier exists.
- Support explicit manual linking to avoid ambiguity.
- Avoid relying solely on inference for versioning decisions.

#### Ingestion Logic

if parent_dataset_id is provided:
  link as a new version of the specified dataset
elif source contains a stable external_id (e.g. Kobo form_id):
  match to existing dataset using external_id
else:
  create a new dataset

#### Source-Specific Behaviour
- **KoBo / API ingestion**
  - Use survey or form `_id` as `external_id`
  - Automatically group datasets into a single version lineage

- **Manual uploads**
  - Allow optional `parent_dataset_id` parameter
  - If not provided, treat as new dataset unless a high-confidence match is found

#### Data Model Requirements
- `dataset_id` (unique per version)
- `dataset_group_id` (shared across versions)
- `version_number`
- `source_type` (e.g. manual, kobo, api)
- `external_id` (nullable; used for API sources)
- `parent_dataset_id` (optional; user-provided override)

#### UX Consideration
For manual uploads, the system may suggest a potential match:

"This appears to be an update to dataset X — confirm?"

Users should always be able to confirm or override this suggestion.

---


