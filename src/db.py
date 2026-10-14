"""Shared Supabase client and cached data loader for the Streamlit app."""

import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

COUNTRY_TABLES = {"indicator_values", "driver_values", "school_values", "cio_table", "narratives"}


def new_client():
    """Uncached client for auth calls, so user sessions are never shared across users."""
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


@st.cache_resource
def get_client():
    """Shared client for read-only data queries."""
    return new_client()


@st.cache_data(ttl=900, show_spinner=False)
def load_data(table, country=None, columns="*", page_size=1000):
    """Fetch a table (optionally filtered by country) selecting only `columns`."""
    client = get_client()
    rows, start = [], 0

    while True:
        query = client.table(table).select(columns)
        if country is not None and table in COUNTRY_TABLES:
            query = query.ilike("country", country)

        page = query.range(start, start + page_size - 1).execute().data
        rows.extend(page)

        if len(page) < page_size:
            break
        start += page_size

    return pd.DataFrame(rows)
