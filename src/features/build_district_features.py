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

from pathlib import Path

import pandas as pd
from rapidfuzz import process, fuzz

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
}


def fuzzy_match_districts(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_col: str,
    right_col: str,
    threshold: int = 85,
) -> pd.DataFrame:
    """
    Match district names across two dataframes that likely spell/split
    districts differently. Returns `left` with a new column
    `{right_col}_matched` giving the best match from `right`, plus a
    `{right_col}_match_score` column so you can spot-check low-confidence
    matches by hand rather than trusting them blindly.
    """
    choices = right[right_col].dropna().unique().tolist()

    matched_names = []
    scores = []
    for name in left[left_col]:
        if pd.isna(name):
            matched_names.append(None)
            scores.append(0)
            continue
        result = process.extractOne(name, choices, scorer=fuzz.token_sort_ratio)
        if result and result[1] >= threshold:
            matched_names.append(result[0])
            scores.append(result[1])
        else:
            matched_names.append(None)
            scores.append(result[1] if result else 0)

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

    if uidai is None:
        raise SystemExit(
            "uidai_saturation is required as the base table -- run "
            "fetch_uidai_saturation.py first."
        )

    # Standardize the base table's district name column -- adjust to
    # whatever the real UIDAI CSV calls it once you've pulled it.
    base = uidai.rename(columns={"district": "district_name"})

    for name, df in [
        ("occupation", occupation),
        ("literacy", literacy),
        ("teledensity", teledensity),
        ("electrification", electrification),
    ]:
        if df is None:
            continue
        # Assumes each external source has a 'district' column -- rename
        # to match what's actually in your downloaded files.
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

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / "district_feature_table.csv"
    base.to_csv(out_path, index=False)
    print(f"Saved merged feature table ({len(base)} rows) to {out_path}")

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
