"""
Streamlit dashboard: district exclusion-risk map + policy feedback panel.

This is intentionally a prototype of the feedback loop that currently
doesn't exist -- authentication failure data isn't fed back into welfare
monitoring anywhere today. Frame it in your write-up as "what a
monitoring system could look like", not as a production tool.

Run with: streamlit run dashboard/app.py
"""

from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SHAP_OUT = ROOT / "data" / "processed" / "shap_values.csv"
AUDIT_OUT = ROOT / "data" / "processed" / "fairness_audit_results.csv"

st.set_page_config(page_title="Welfare Authentication Exclusion Risk", layout="wide")
st.title("District Exclusion Risk — Welfare Authentication")
st.caption(
    "Prototype governance dashboard. District-level predicted risk of "
    "Aadhaar authentication failure in welfare delivery, with a fairness "
    "audit across structural exposure groups. Not a production system — "
    "a proof of concept for the feedback loop that doesn't currently exist."
)

if not SHAP_OUT.exists():
    st.warning(
        "No model output found yet. Run the data collection, feature "
        "building, and model training scripts first (see README.md)."
    )
    st.stop()

df = pd.read_csv(SHAP_OUT)

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Districts ranked by predicted exclusion risk")
    top_n = st.slider("Show top N highest-risk districts", 5, 50, 20)
    ranked = df.sort_values("predicted_risk", ascending=False).head(top_n)
    st.dataframe(
        ranked[["district_name", "predicted_risk"]].reset_index(drop=True),
        use_container_width=True,
    )

with col2:
    st.subheader("What's driving risk")
    selected_district = st.selectbox("Select a district", df["district_name"].unique())
    row = df[df["district_name"] == selected_district].iloc[0]
    feature_cols = [c for c in df.columns if c not in ("district_name", "predicted_risk")]
    shap_row = row[feature_cols].sort_values(key=abs, ascending=False)
    st.bar_chart(shap_row)
    st.caption("SHAP contribution to this district's predicted risk (higher = more risk)")

st.divider()
st.subheader("Fairness audit: who bears the exclusion risk")

if AUDIT_OUT.exists():
    audit_df = pd.read_csv(AUDIT_OUT)
    st.dataframe(audit_df, use_container_width=True)
    st.caption(
        "Demographic parity difference compares the rate at which each "
        "group is flagged 'high risk'. Values far from 0 indicate the "
        "predicted risk is concentrated in one group over another."
    )
else:
    st.info("Run src/fairness/fairness_audit.py to populate this section.")

st.divider()
st.subheader("Policy feedback gap")
st.markdown(
    """
    Authentication failure data is generated at scale (billions of
    transactions monthly) but is not currently integrated into welfare
    monitoring or policy feedback. This dashboard is a prototype of what
    that feedback loop could look like: districts ranked by risk, the
    structural factors driving it, and which groups are disproportionately
    exposed — updated as new district data comes in, rather than
    discovered years later through starvation-death investigations.
    """
)
