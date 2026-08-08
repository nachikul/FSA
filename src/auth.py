"""Optional shared-password gate for the whole app.

Controlled entirely by the APP_PASSWORD environment variable (set as a Fly
secret for a public deployment, or locally too if you want it): if it's
unset, the app is wide open — this is meant for a personal deployment
that's reachable on the public internet, not a substitute for real
multi-user auth with individual accounts, rate limiting, or audit logs.
"""
from __future__ import annotations

import hmac
import os

import streamlit as st


def require_password() -> None:
    password = os.environ.get("APP_PASSWORD")
    if not password:
        return  # gate disabled -- no password configured

    if st.session_state.get("authenticated"):
        return

    st.title("🔒 Financial Statement Analyser")
    st.caption("Enter the password to continue.")
    with st.form("password_gate"):
        entered = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="Password")
        submitted = st.form_submit_button("Enter")

    if submitted:
        if hmac.compare_digest(entered, password):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")

    st.stop()
