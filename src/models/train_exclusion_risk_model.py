from __future__ import annotations

"""
Train a district-level exclusion risk model.

Target variable options, in order of preference:
  1. Actual authentication/transaction failure rate, where you were able
     to source it (a handful of states/districts from published studies).
  2. Aadhaar enrolment rejection rate as a weaker proxy, if (1) is too
     sparse to model on directly.

Whichever you use, say so explicitly and honestly in your write-up --
this is a modeling choice with real implications for what the model can
and can't claim.
"""

from pathlib import Path

import pandas as pd
import shap
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[2]
FEATURE_TABLE = ROOT / "data" / "processed" / "district_feature_table.csv"
MODEL_OUT = ROOT / "data" / "processed" / "exclusion_risk_model.json"
SHAP_OUT = ROOT / "data" / "processed" / "shap_values.csv"

# Update these once your feature table is finalized -- these are
# illustrative placeholders matching the sources in data_sources.md.
FEATURE_COLUMNS = [
    "aadhaar_saturation_pct",
    "pct_manual_labour_occupation",
    "literacy_rate",
    "teledensity",
    "pct_villages_electrified",
    "pct_elderly_population",
]
TARGET_COLUMN = "failure_rate"  # or "enrolment_rejection_rate" as fallback


def load_data() -> pd.DataFrame:
    if not FEATURE_TABLE.exists():
        raise SystemExit(
            f"{FEATURE_TABLE} not found -- run build_district_features.py first."
        )
    df = pd.read_csv(FEATURE_TABLE)
    missing = [c for c in FEATURE_COLUMNS + [TARGET_COLUMN] if c not in df.columns]
    if missing:
        raise SystemExit(
            f"Feature table is missing expected columns: {missing}. "
            "Update FEATURE_COLUMNS/TARGET_COLUMN to match your actual "
            "merged table, then re-run."
        )
    return df.dropna(subset=[TARGET_COLUMN])


def train():
    df = load_data()
    X = df[FEATURE_COLUMNS]
    y = df[TARGET_COLUMN]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    model = xgb.XGBRegressor(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    print(f"MAE: {mean_absolute_error(y_test, preds):.4f}")
    print(f"R^2: {r2_score(y_test, preds):.4f}")

    # With this few districts, treat these metrics as directional, not
    # definitive -- report cross-validation results too, not just a
    # single train/test split, once you have real data in hand.

    explainer = shap.TreeExplainer(model)
    shap_values = explainer(X)
    shap_df = pd.DataFrame(shap_values.values, columns=FEATURE_COLUMNS)
    shap_df["district_name"] = df["district_name"].values
    shap_df["predicted_risk"] = model.predict(X)
    shap_df.to_csv(SHAP_OUT, index=False)

    model.save_model(MODEL_OUT)
    print(f"Model saved to {MODEL_OUT}")
    print(f"SHAP values saved to {SHAP_OUT}")


if __name__ == "__main__":
    train()
