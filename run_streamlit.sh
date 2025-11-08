#!/bin/bash
# Helper script to run Streamlit app
cd "$(dirname "$0")"
uv run streamlit run streamlit_app.py
