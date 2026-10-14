import json
import os
import textwrap

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from datetime import datetime, timezone

from dotenv import load_dotenv
from matplotlib.colors import LinearSegmentedColormap
from openai import OpenAI
from supabase import create_client

from src.combine import fetch_all
from src.theme import Colors

# Build CMO visualisations. To build:
# 1. Master schools table for all CMO elements per driver
# 2. Table of typologies (i.e., quality high, quantity low etc.)
# 3. Narratives per CMO combination using Open AI API

load_dotenv()

supabase_client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY"),
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

NORMAL_AGGS = ["mean", "sum", "max", "min", "first", "last"]


#--------------------Aggregation helpers--------------------#

def calc_change_or_mean(g, column):
    vals = g[column].dropna()

    if len(vals) == 0:
        return np.nan

    if len(vals) == 1:
        return vals.iloc[0]

    temp = (
        g.loc[g[column].notna(), ["date_time", column]]
        .sort_values("date_time")
    )

    if temp["date_time"].nunique() <= 1:
        return temp[column].mean()

    return temp[column].iloc[-1] - temp[column].iloc[0]


def calc_change(g, column):
    vals = g[column].dropna()

    if len(vals) <= 1:
        return np.nan

    temp = (
        g.loc[g[column].notna(), ["date_time", column]]
        .sort_values("date_time")
    )

    if temp["date_time"].nunique() <= 1:
        return np.nan

    return temp[column].iloc[-1] - temp[column].iloc[0]


def end_minus_base(g, column):
    vals = g[column].dropna()

    if len(vals) == 0:
        return np.nan

    temp = (
        g.loc[g[column].notna(), ["round", column]]
        .sort_values("round")
    )

    if "baseline" not in temp["round"].values or "endline" not in temp["round"].values:
        return np.nan

    return (
        temp.loc[temp["round"] == "endline", column].mean()
        - temp.loc[temp["round"] == "baseline", column].mean()
    )


#--------------------Build CIO Tables--------------------#

def _split_pipe(value):
    if value is None or pd.isna(value):
        return []
    return [part.strip() for part in str(value).split("|") if part.strip()]


def _table_exists_with_rows(database, table):
    try:
        return bool(database.table(table).select("*").limit(1).execute().data)
    except Exception:
        return False


def list_drivers(database):
    """Driver ids from the drivers table (empty list if it is not populated)."""
    try:
        rows = database.table("drivers").select("driver_id").execute().data
    except Exception:
        return []
    return sorted(r["driver_id"] for r in rows if r.get("driver_id"))


def _indicator_metadata(driver_id, database):
    # driver_indicators is the source of truth; fall back to the pipe lists on indicators
    if _table_exists_with_rows(database, "driver_indicators"):
        links = pd.DataFrame(
            database.table("driver_indicators").select("*").eq("driver_id", driver_id).execute().data
        )
        if links.empty:
            raise ValueError(f"No indicators found for driver '{driver_id}'")
        links = links.drop(columns=["id"], errors="ignore").rename(
            columns={"indicator_id": "id", "role": "driver_level"}
        )
        return links[["id", "driver_level", "report_agg"]].reset_index(drop=True)

    all_indicators = pd.DataFrame(
        database.table("indicators")
        .select("*")
        .execute()
        .data
    )
    required = {"id", "driver_id", "driver_level", "report_agg"}
    missing = required.difference(all_indicators.columns)
    if missing:
        raise ValueError(f"Indicator metadata is missing required columns: {sorted(missing)}")

    # driver_id and driver_level are pipe-separated lists ("d_01|d_02") matched by position
    rows = []
    for row in all_indicators.itertuples(index=False):
        drivers = _split_pipe(row.driver_id)
        levels = _split_pipe(row.driver_level)
        if not drivers and not levels:
            continue
        if len(drivers) != len(levels):
            raise ValueError(
                f"Indicator '{row.id}' has {len(drivers)} driver_id value(s) "
                f"({row.driver_id!r}) but {len(levels)} driver_level value(s) ({row.driver_level!r})"
            )
        if driver_id in drivers:
            rows.append({
                "id": row.id,
                "driver_level": levels[drivers.index(driver_id)],
                "report_agg": row.report_agg,
            })

    if not rows:
        raise ValueError(f"No indicators found for driver '{driver_id}'")
    return pd.DataFrame(rows, columns=["id", "driver_level", "report_agg"])


def _build_value_table(country, level, driver_id, indicators, database):
    if level == "school":
        indicator_ids = indicators["id"].tolist()
        source = pd.DataFrame(
            fetch_all(database, f"combined_{level}_level")
        )
        required_columns = {"country", "school_id", "round", "date_time", *indicator_ids}
        missing = required_columns.difference(source.columns)
        if missing:
            raise ValueError(
                f"Combined school data is missing required columns: {sorted(missing)}"
            )
        if source.empty:
            raise ValueError(f"No combined school data found for driver '{driver_id}'")

        source = source.loc[
            :, ["country", "school_id", "round", "date_time", *indicator_ids]
        ].copy()
        source["date_time"] = pd.to_datetime(source["date_time"], errors="coerce")
        source["country"] = source["country"].replace("unknown", country)
        source = source.loc[source["country"].astype(str).str.lower() == str(country).lower()].copy()
        source["country"] = str(country).lower()
        if source.empty:
            raise ValueError(f"No combined school data found for country '{country}'")

        aggregations = indicators.set_index("id")["report_agg"].to_dict()
        unsupported = {
            indicator: operation
            for indicator, operation in aggregations.items()
            if operation not in NORMAL_AGGS + ["change_from_baseline", "end_minus_base"]
        }
        if unsupported:
            raise ValueError(f"Unsupported CMO aggregation methods: {unsupported}")

        normal_aggs = {
            indicator: operation
            for indicator, operation in aggregations.items()
            if operation in NORMAL_AGGS
        }
        # first/last aggregations rely on chronological order
        source = source.sort_values("date_time", kind="stable")
        groups = source.groupby(["country", "school_id"])
        if normal_aggs:
            school_values = groups.agg(normal_aggs)
        else:
            school_values = groups.size().to_frame("_row_count").drop(columns="_row_count")

        for indicator, operation in aggregations.items():
            if operation == "change_from_baseline":
                school_values[indicator] = groups.apply(
                    lambda group: calc_change_or_mean(group, indicator)
                )
            elif operation == "end_minus_base":
                school_values[indicator] = groups.apply(
                    lambda group: end_minus_base(group, indicator)
                )

        school_values = school_values.reset_index()
        average_row = {"country": country, "school_id": "average"}
        for indicator in indicator_ids:
            average_row[indicator] = pd.to_numeric(
                school_values[indicator], errors="coerce"
            ).mean()
        school_values = pd.concat(
            [pd.DataFrame([average_row]), school_values],
            ignore_index=True,
        )
        school_values["driver"] = driver_id
        return school_values


def build_long_binary(country, level, driver_id, client=None):
    database = client or supabase_client
    indicators = _indicator_metadata(driver_id, database)
    levels = indicators.set_index("id")["driver_level"].to_dict()
    for required_level in ("implementation_quality", "implementation_quantity", "outcome"):
        if required_level not in levels.values():
            raise ValueError(f"Driver '{driver_id}' has no '{required_level}' indicators")

    values = _build_value_table(
        country, level, driver_id, indicators, database
    )
    long_table = values.melt(
        id_vars=["country", "school_id", "driver"],
        value_vars=indicators["id"].tolist(),
        var_name="variable",
        value_name="value",
    )
    long_table["variable_level"] = long_table["variable"].map(levels)

    outcome_rows = long_table["variable_level"] == "outcome"
    binary_rows = ~outcome_rows
    long_table["value_binary"] = long_table["value"].astype(object)

    schools = long_table["school_id"] != "average"
    binary_data = long_table.loc[binary_rows & schools, ["variable", "value"]].copy()
    binary_data["_numeric_value"] = pd.to_numeric(
        binary_data["value"], errors="coerce"
    )
    medians = (
        binary_data
        .groupby("variable")["_numeric_value"]
        .median()
    )
    to_bin = binary_rows & schools
    for index in long_table.index[to_bin]:
        value = pd.to_numeric(pd.Series([long_table.at[index, "value"]]), errors="coerce").iloc[0]
        median = medians.get(long_table.at[index, "variable"], np.nan)
        if pd.notna(value) and pd.notna(median):
            long_table.at[index, "value_binary"] = "High" if value > median else "Low"
        else:
            long_table.at[index, "value_binary"] = np.nan
    return long_table


def build_cio_table(long_table):
    required = {
        "country", "school_id", "driver", "variable", "variable_level", "value", "value_binary"
    }
    missing = required.difference(long_table.columns)
    if missing:
        raise ValueError(f"Long indicator table is missing required columns: {sorted(missing)}")

    variable_levels = long_table.groupby("variable")["variable_level"].first().to_dict()
    quality_variables = [
        variable for variable, level in variable_levels.items()
        if level == "implementation_quality"
    ]
    quantity_variables = [
        variable for variable, level in variable_levels.items()
        if level == "implementation_quantity"
    ]
    outcome_variables = [
        variable for variable, level in variable_levels.items() if level == "outcome"
    ]
    if not quality_variables or not quantity_variables or not outcome_variables:
        raise ValueError("Long indicator table must include quality, quantity, and outcome indicators")

    wide = long_table.pivot(
        index=["country", "school_id", "driver"],
        columns="variable",
        values="value_binary",
    ).reset_index()
    wide.columns.name = None
    wide["implementation_quality"] = wide[quality_variables[0]]
    wide["implementation_quantity"] = wide[quantity_variables[0]]
    outcomes = (
        long_table.loc[long_table["variable_level"] == "outcome"]
        .groupby(["country", "school_id", "driver"], as_index=False)["value"]
        .mean()
        .rename(columns={"value": "outcome"})
    )
    wide = wide.merge(outcomes, on=["country", "school_id", "driver"], how="left")

    context_columns = [
        variable for variable, level in variable_levels.items() if level == "context"
    ]
    # Schools with no quality or quantity classification cannot be placed in a CIO cell
    schools = wide.loc[
        (wide["school_id"] != "average")
        & wide["implementation_quality"].notna()
        & wide["implementation_quantity"].notna()
    ]

    grouped_tables = []
    base = (
        schools.groupby(
            ["country", "driver", "implementation_quality", "implementation_quantity"],
            dropna=False,
        )
        .agg(outcome=("outcome", "mean"), schools=("school_id", "count"))
        .reset_index()
    )
    base["context"] = "None"
    grouped_tables.append(base)

    for variable in context_columns:
        context_rows = schools.loc[schools[variable].isin(["High", "Low"])].copy()
        context_rows["context"] = context_rows.apply(
            lambda row: f"{variable}_{str(row[variable]).lower()}",
            axis=1,
        )
        grouped = (
            context_rows.groupby(
                [
                    "country", "driver", "context",
                    "implementation_quality", "implementation_quantity",
                ],
                dropna=False,
            )
            .agg(outcome=("outcome", "mean"), schools=("school_id", "count"))
            .reset_index()
        )
        grouped_tables.append(grouped)

    columns = [
        "country", "driver", "context", "implementation_quality",
        "implementation_quantity", "outcome", "schools",
    ]
    return pd.concat(grouped_tables, ignore_index=True).loc[:, columns]


#--------------------Narratives--------------------#

def generate_narrative(cio_table):
    if cio_table.empty or "outcome" not in cio_table:
        raise ValueError("CIO table must contain outcome rows before generating narratives")

    baseline = cio_table.loc[cio_table["context"] == "None"]
    if baseline.empty:
        raise ValueError("CIO table must contain the base context 'None'")

    combination_means = {}
    for quality in ("High", "Low"):
        for quantity in ("High", "Low"):
            rows = baseline.loc[
                (baseline["implementation_quality"] == quality)
                & (baseline["implementation_quantity"] == quantity),
                "outcome",
            ]
            combination_means[f"{quality} Quality + {quantity} Quantity"] = rows.mean()

    prompt = f"""
    You are analysing Context-Implementation-Outcome (CIO) data for an education dashboard.
    Write one narrative for every context value in the provided records. Each narrative must
    contain at most two sentences, use cautious non-causal language, avoid exact averages,
    and mention small subgroup sizes (one or two schools) as unreliable patterns.
    Compare outcomes with the overall averages for the four implementation combinations.
    The value "None" is the base case with no context variable considered.

    Overall outcome average: {baseline["outcome"].mean()}
    Implementation-combination averages: {combination_means}
    Data: {cio_table.to_dict(orient="records")}

    Return a JSON object in exactly this shape:
    {{"narratives": [{{"table_name": "context_name", "narrative": "..."}}]}}
    Use each context value lowercased as table_name (for example, "None" becomes "none").
    """
    response = client.responses.create(
        model="gpt-5-mini",
        input=prompt,
        text={"format": {"type": "json_object"}},
    )
    if not response.output_text:
        raise ValueError("Narrative generation returned an empty response")
    return response.output_text


def narrative_table(cio_table, driver):
    data = json.loads(generate_narrative(cio_table))
    narratives = data.get("narratives") if isinstance(data, dict) else None
    if not isinstance(narratives, list):
        raise ValueError("Narrative response must contain a 'narratives' list")
    result = pd.DataFrame(narratives)
    if not {"table_name", "narrative"}.issubset(result.columns):
        raise ValueError("Each narrative must contain 'table_name' and 'narrative'")

    result["table_name"] = result["table_name"].astype(str).str.lower()
    expected = set(cio_table["context"].astype(str).str.lower().unique())
    actual = set(result["table_name"])
    if actual != expected:
        raise ValueError(
            "Narrative contexts do not match the CIO table "
            f"(missing: {sorted(expected - actual)}, unexpected: {sorted(actual - expected)})"
        )
    if result["table_name"].duplicated().any():
        raise ValueError("Narrative response contains duplicate context names")

    countries = cio_table["country"].dropna().unique()
    if len(countries) != 1:
        raise ValueError("CIO table must contain exactly one country for narrative generation")
    result["driver"] = driver
    result["country"] = countries[0]
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    return result



#--------------------Run end to end--------------------#

def _upsert_records(table):
    records = table.astype(object).where(pd.notna(table), None)
    return records.to_dict(orient="records")


def upsert_tables(supabase_client, long_table, cio_table, narratives):
    supabase_client.table("indicator_values").upsert(
        _upsert_records(long_table)
    ).execute()
    supabase_client.table("cio_table").upsert(
        _upsert_records(cio_table)
    ).execute()
    supabase_client.table("narratives").upsert(
        _upsert_records(narratives)
    ).execute()


def build_cmos(country="kenya", level="school", driver_id="d_01", client=None, regenerate_narratives=False):
    database = client or supabase_client
    long_table = build_long_binary(country, level, driver_id, client=database)
    cio_table = build_cio_table(long_table)

    existing = pd.DataFrame(
        database.table("narratives").select("*")
        .eq("country", cio_table["country"].iloc[0]).eq("driver", driver_id)
        .execute().data
    )
    if not existing.empty and not regenerate_narratives:
        print(f"Narratives already exist for {driver_id}; skipping generation.")
        narratives = existing
        database.table("indicator_values").upsert(_upsert_records(long_table)).execute()
        database.table("cio_table").upsert(_upsert_records(cio_table)).execute()
    else:
        narratives = narrative_table(cio_table, driver_id)
        upsert_tables(database, long_table, cio_table, narratives)
    return long_table, cio_table, narratives


if __name__ == "__main__":
    load_dotenv()
    supabase_client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    build_cmos(client=supabase_client)
