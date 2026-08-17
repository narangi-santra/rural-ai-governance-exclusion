"""
Fairness audit for the exclusion risk model.

The question this answers is NOT "is the model accurate" -- it's "does the
model's predicted risk (and the real-world pattern it's modeling) fall
disproportionately on specific groups". This is the part that makes the
project a governance audit rather than a plain regression exercise.

Since your data is district-level, "subgroup" here means splitting
districts into bins by a sensitive/structural feature (e.g. above vs.
below median % manual-labour occupation, above vs. below median % elderly
population) rather than individual-level protected attributes -- be
explicit about that framing limitation in your write-up.
"""

from pathlib import Path

import pandas as pd
from fairlearn.metrics import MetricFrame, demographic_parity_difference

ROOT = Path(__file__).resolve().parents[2]
SHAP_OUT = ROOT / "data" / "processed" / "shap_values.csv"
FEATURE_TABLE = ROOT / "data" / "processed" / "district_feature_table.csv"
AUDIT_OUT = ROOT / "data" / "processed" / "fairness_audit_results.csv"

# Districts above the median on these get treated as the "high exposure"
# group for that dimension -- adjust to match your final feature names.
SENSITIVE_DIMENSIONS = [
    "pct_manual_labour_occupation",
    "pct_elderly_population",
    "teledensity",  # lower connectivity = higher exposure, so invert this one
]

RISK_THRESHOLD_PERCENTILE = 0.75  # top quartile predicted risk = "high risk"


def load_data() -> pd.DataFrame:
    preds = pd.read_csv(SHAP_OUT)
    features = pd.read_csv(FEATURE_TABLE)
    return preds.merge(features, on="district_name", how="left", suffixes=("", "_feat"))


def audit():
    df = load_data()

    risk_cutoff = df["predicted_risk"].quantile(RISK_THRESHOLD_PERCENTILE)
    df["high_risk"] = (df["predicted_risk"] >= risk_cutoff).astype(int)

    results = []
    for dim in SENSITIVE_DIMENSIONS:
        if dim not in df.columns:
            print(f"[skip] {dim} not found in merged table")
            continue

        median = df[dim].median()
        # invert direction for connectivity -- lower connectivity = higher exposure
        if dim == "teledensity":
            df["group"] = (df[dim] < median).map({True: "high_exposure", False: "low_exposure"})
        else:
            df["group"] = (df[dim] >= median).map({True: "high_exposure", False: "low_exposure"})

        mf = MetricFrame(
            metrics={"mean_predicted_risk": lambda yt, yp: yp.mean()},
            y_true=df["high_risk"],
            y_pred=df["predicted_risk"],
            sensitive_features=df["group"],
        )

        dp_diff = demographic_parity_difference(
            y_true=df["high_risk"],
            y_pred=df["high_risk"],  # using the binarized flag itself
            sensitive_features=df["group"],
        )

        print(f"\n--- {dim} ---")
        print(mf.by_group)
        print(f"Demographic parity difference (high-risk flag rate): {dp_diff:.4f}")

        results.append(
            {
                "dimension": dim,
                "demographic_parity_difference": dp_diff,
                "high_exposure_mean_risk": mf.by_group.loc["high_exposure", "mean_predicted_risk"]
                if "high_exposure" in mf.by_group.index
                else None,
                "low_exposure_mean_risk": mf.by_group.loc["low_exposure", "mean_predicted_risk"]
                if "low_exposure" in mf.by_group.index
                else None,
            }
        )

    results_df = pd.DataFrame(results)
    results_df.to_csv(AUDIT_OUT, index=False)
    print(f"\nSaved audit results to {AUDIT_OUT}")


if __name__ == "__main__":
    audit()
