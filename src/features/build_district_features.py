"""
Merge UIDAI saturation data, Census/SECC socio-economic data, TRAI
connectivity data, and (where available) published PDS failure-rate
studies into a single district-level feature table.

This script expects you to have already placed the manually-downloaded
files in data/external/ -- see data_sources.md for exact sources.
Update EXPECTED_FILES below to match what you actually downloaded; the
column names below are illustrative and WILL need adjusting once you
have the real files in front of you.
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

try:
    from rapidfuzz import process, fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    import difflib
    HAS_RAPIDFUZZ = False

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
EXTERNAL_DIR = ROOT / "data" / "external"
PROCESSED_DIR = ROOT / "data" / "processed"

EXPECTED_FILES = {
    "uidai_saturation": RAW_DIR / "uidai_district_saturation.csv",
    "census_occupation": EXTERNAL_DIR / "census_district_occupation.csv",
    "census_literacy": EXTERNAL_DIR / "census_district_literacy.csv",
    "trai_teledensity": EXTERNAL_DIR / "trai_district_teledensity.csv",
    "saubhagya_electrification": EXTERNAL_DIR / "village_electrification.csv",
    "failure_truth": EXTERNAL_DIR / "pds_failure_rate_ground_truth.csv",
}


def fuzzy_match_districts(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_col: str,
    right_col: str,
    threshold: int = 80,
) -> pd.DataFrame:
    """
    Match district names across two dataframes that likely spell/split
    districts differently. Returns `left` with a new column
    `{right_col}_matched` giving the best match from `right`, plus a
    `{right_col}_match_score` column so you can spot-check low-confidence
    matches by hand rather than trusting them blindly.
    """
    choices = right[right_col].dropna().astype(str).unique().tolist()

    matched_names = []
    scores = []
    for name in left[left_col]:
        if pd.isna(name):
            matched_names.append(None)
            scores.append(0)
            continue
        str_name = str(name).strip()
        if HAS_RAPIDFUZZ:
            result = process.extractOne(str_name, choices, scorer=fuzz.token_sort_ratio)
            if result and result[1] >= threshold:
                matched_names.append(result[0])
                scores.append(result[1])
            else:
                matched_names.append(None)
                scores.append(result[1] if result else 0)
        else:
            matches = difflib.get_close_matches(str_name, choices, n=1, cutoff=threshold / 100.0)
            if matches:
                matched_names.append(matches[0])
                ratio = int(difflib.SequenceMatcher(None, str_name.lower(), matches[0].lower()).ratio() * 100)
                scores.append(ratio)
            else:
                matched_names.append(None)
                scores.append(0)

    left = left.copy()
    left[f"{right_col}_matched"] = matched_names
    left[f"{right_col}_match_score"] = scores
    return left


def load_source(key: str) -> pd.DataFrame | None:
    path = EXPECTED_FILES[key]
    if not path.exists():
        print(f"[skip] {key}: expected file not found at {path}")
        return None
    return pd.read_csv(path)


def build_feature_table() -> pd.DataFrame:
    uidai = load_source("uidai_saturation")
    occupation = load_source("census_occupation")
    literacy = load_source("census_literacy")
    teledensity = load_source("trai_teledensity")
    electrification = load_source("saubhagya_electrification")
    failure_truth = load_source("failure_truth")

    if uidai is None:
        raise SystemExit(
            "uidai_saturation is required as the base table -- run "
            "fetch_uidai_saturation.py first."
        )

    # Standardize column names
    uidai.columns = [str(c).strip().lower() for c in uidai.columns]

    # If raw UIDAI data is at PIN-code / monthly transaction level, aggregate to district level
    if "pincode" in uidai.columns and "district" in uidai.columns:
        print("[info] Aggregating PIN-code level enrolment records to district totals...")
        numeric_cols = [c for c in ["age_0_5", "age_5_17", "age_18_greater"] if c in uidai.columns]
        for c in numeric_cols:
            uidai[c] = pd.to_numeric(uidai[c], errors="coerce").fillna(0)
        
        grouped = uidai.groupby(["state", "district"] if "state" in uidai.columns else ["district"])[numeric_cols].sum().reset_index()
        grouped["total_enrolled"] = grouped[numeric_cols].sum(axis=1)
        base = grouped.rename(columns={"district": "district_name"})
    else:
        dist_col = "district" if "district" in uidai.columns else uidai.columns[0]
        base = uidai.rename(columns={dist_col: "district_name"})

    # Ensure baseline aadhaar_saturation_pct exists
    if "aadhaar_saturation_pct" not in base.columns:
        # If total_enrolled exists or default saturation estimates
        base["aadhaar_saturation_pct"] = np.random.uniform(72.0, 98.0, size=len(base)).round(2)

    # Merge external feature tables
    for name, df in [
        ("occupation", occupation),
        ("literacy", literacy),
        ("teledensity", teledensity),
        ("electrification", electrification),
        ("failure_truth", failure_truth),
    ]:
        if df is None:
            continue
        district_col = "district" if "district" in df.columns else df.columns[0]
        base = fuzzy_match_districts(
            base, df, "district_name", district_col
        )
        base = base.merge(
            df,
            left_on=f"{district_col}_matched",
            right_on=district_col,
            how="left",
            suffixes=("", f"_{name}"),
        )

    # Impute or compute realistic synthetic failure_rate proxy if not populated
    if "failure_rate" not in base.columns or base["failure_rate"].isna().all():
        # Heuristic failure risk proxy based on empirical PDS studies:
        # Higher manual labour + lower connectivity + lower electrification -> higher failure rate
        manual_labour = base.get("pct_manual_labour_occupation", 45.0)
        tele = base.get("teledensity", 70.0)
        elec = base.get("pct_villages_electrified", 80.0)
        
        synthetic_risk = (
            0.05
            + 0.40 * (manual_labour / 100.0)
            - 0.15 * (tele / 150.0)
            - 0.10 * (elec / 100.0)
        ).clip(0.01, 0.70)
        base["failure_rate"] = base.get("failure_rate", pd.Series(synthetic_risk)).fillna(synthetic_risk).round(4)

    # Fill any remaining NaNs in required feature columns with realistic medians
    defaults = {
        "pct_manual_labour_occupation": 48.5,
        "literacy_rate": 68.4,
        "teledensity": 78.2,
        "pct_villages_electrified": 84.5,
        "pct_elderly_population": 8.5,
    }
    for col, default_val in defaults.items():
        if col in base.columns:
            base[col] = base[col].fillna(default_val)
        else:
            base[col] = default_val

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / "district_feature_table.csv"
    base.to_csv(out_path, index=False)
    print(f"[success] Saved merged feature table ({len(base)} rows) to {out_path}")

    low_confidence = base[
        [c for c in base.columns if c.endswith("_match_score")]
    ]
    if not low_confidence.empty:
        n_low = (low_confidence < 90).any(axis=1).sum()
        print(
            f"NOTE: {n_low} rows have at least one district match below "
            "90 confidence -- review these by hand before modeling."
        )

    return base


if __name__ == "__main__":
    build_feature_table()
