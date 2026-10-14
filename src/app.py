import os
from supabase import create_client
from dotenv import load_dotenv
import streamlit as st

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

def login_screen():

    st.title("Measuring What Matters - Proof of Concept")
    st.text("Please sign in to continue. Note: all data presented is synthetic data for purpose of demonstration")

    email = st.text_input("Email")
    password = st.text_input("Password", type="password")

    if st.button("Sign in"):

        try:
            response = supabase.auth.sign_in_with_password(
                {
                    "email": email,
                    "password": password,
                }
            )

            st.session_state["user"] = response.user

            st.rerun()

        except Exception:
            st.error("Invalid email or password")


def logout():

    try:
        supabase.auth.sign_out()
    except:
        pass

    st.session_state.clear()
    st.rerun()

# Check authentication
if "user" not in st.session_state:
    login_screen()
    st.stop()

alldrivers = st.Page("pages/01_alldrivers.py", title="Data for all Drivers")
cios = st.Page("pages/02_cios.py", title="CIO Combinations")

pg = st.navigation([alldrivers, cios])

st.set_page_config(page_title="Measuring What Matters Data Hub")

pg.run()