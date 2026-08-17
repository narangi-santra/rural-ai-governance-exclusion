"""
Fetch UIDAI's district-wise Aadhaar saturation report.

UIDAI publishes this as a free REST feed, no API key required:
    https://data.uidai.gov.in/uiddatacatalog/rest/{datasetcode}
    https://data.uidai.gov.in/uiddatacatalog/rest/{datasetcode}/{date}
    https://data.uidai.gov.in/uiddatacatalog/rest/{datasetcode}/{fromdate}/{todate}

Dates are in yyyymmdd format. The dataset code for the district-wise
saturation report changes occasionally on UIDAI's end, so if this returns
an error, check data.uidai.gov.in for the current code before assuming
your network/environment is broken.

This script needs real network access — run it locally, not inside a
network-sandboxed environment.
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://data.uidai.gov.in/uiddatacatalog/rest"

# NOTE: verify this against the current listing at data.uidai.gov.in before
# your first run -- UIDAI has changed dataset codes before without notice.
DISTRICT_SATURATION_DATASET_CODE = "aadhaarsaturationdistrict"

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


def fetch_saturation_report(target_date: str | None = None) -> pd.DataFrame:
    """
    Fetch the district-wise saturation report for a given date
    (yyyymmdd). Defaults to the most recent available date if not given.
    """
    if target_date:
        url = f"{BASE_URL}/{DISTRICT_SATURATION_DATASET_CODE}/{target_date}"
    else:
        url = f"{BASE_URL}/{DISTRICT_SATURATION_DATASET_CODE}"

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    # UIDAI's feed has returned both JSON and CSV historically depending on
    # the dataset -- handle both.
    content_type = resp.headers.get("Content-Type", "")
    if "json" in content_type:
        df = pd.DataFrame(resp.json())
    else:
        from io import StringIO
        df = pd.read_csv(StringIO(resp.text))

    return df


def fetch_date_range(from_date: str, to_date: str) -> pd.DataFrame:
    url = f"{BASE_URL}/{DISTRICT_SATURATION_DATASET_CODE}/{from_date}/{to_date}"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "")
    if "json" in content_type:
        return pd.DataFrame(resp.json())
    from io import StringIO
    return pd.read_csv(StringIO(resp.text))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="yyyymmdd, defaults to latest available")
    parser.add_argument("--from-date", help="yyyymmdd start of range")
    parser.add_argument("--to-date", help="yyyymmdd end of range")
    parser.add_argument(
        "--out",
        default=str(RAW_DIR / "uidai_district_saturation.csv"),
        help="output CSV path",
    )
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if args.from_date and args.to_date:
            df = fetch_date_range(args.from_date, args.to_date)
        else:
            df = fetch_saturation_report(args.date)
    except requests.HTTPError as e:
        print(f"Request failed: {e}", file=sys.stderr)
        print(
            "Check data.uidai.gov.in for the current dataset code -- "
            f"this script assumes '{DISTRICT_SATURATION_DATASET_CODE}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    df.to_csv(args.out, index=False)
    print(f"Saved {len(df)} rows to {args.out}")


if __name__ == "__main__":
    main()
