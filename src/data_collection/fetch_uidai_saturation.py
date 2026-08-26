from __future__ import annotations

"""
Fetch UIDAI's district-wise Aadhaar saturation data.

Supports:
1. Open Government Data (OGD) India API (data.gov.in):
   Requires an API key (pass --api-key or set DATA_GOV_IN_API_KEY environment variable).
   Endpoint: https://api.data.gov.in/resource/{resource_id}
   Supports pagination with --limit and --offset, or --all to fetch all records.

2. Legacy direct UIDAI REST feed:
   https://data.uidai.gov.in/uiddatacatalog/rest/{datasetcode}
   (No API key required, but subject to UIDAI portal availability and dataset code changes).

3. Realistic Mock Data Generator (--mock):
   Generates realistic, representative sample datasets of Indian districts across
   states with Aadhaar saturation metrics for offline testing, local prototyping,
   and development without requiring external network access or credentials.
"""

import argparse
import os
import sys
import warnings
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Any

# Suppress macOS LibreSSL vs urllib3 v2 non-fatal compatibility warning
warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")

import pandas as pd
import requests

# Open Government Data (OGD) India API defaults
OGD_BASE_URL = "https://api.data.gov.in/resource"
DEFAULT_OGD_RESOURCE_ID = "ecd49b12-3084-4521-8f7e-ca8bf72069ba"

# UIDAI Direct REST feed defaults
UIDAI_BASE_URL = "https://data.uidai.gov.in/uiddatacatalog/rest"
DISTRICT_SATURATION_DATASET_CODE = "aadhaarsaturationdistrict"

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


import time


ALL_INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
    "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Delhi", "Jammu and Kashmir", "Ladakh", "Puducherry", "Chandigarh",
    "Andaman and Nicobar Islands", "Dadra and Nagar Haveli and Daman and Diu",
    "Lakshadweep"
]


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "close",
}


def fetch_ogd_saturation(
    api_key: str,
    resource_id: str = DEFAULT_OGD_RESOURCE_ID,
    state: str | None = None,
    district: str | None = None,
    limit: int = 100,
    offset: int = 0,
    fetch_all: bool = False,
    batch_size: int = 250,
    timeout: int = 60,
    max_retries: int = 5,
    delay: float = 0.4,
    out_path: Path | None = None,
    resume: bool = True,
) -> pd.DataFrame:
    """
    Fetch district saturation/enrolment data from data.gov.in (OGD India API).
    Streams batches directly to disk in append mode, automatically resumes from last
    saved offset if interrupted, and handles HTTP 429 rate limiting with progressive backoff.
    """
    url = f"{OGD_BASE_URL}/{resource_id}"
    records: list[dict[str, Any]] = []
    current_offset = offset
    page_size = min(limit, batch_size) if not fetch_all else batch_size

    # Automatic resume check if output file exists
    if out_path and out_path.exists() and resume and offset == 0:
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                existing_lines = sum(1 for _ in f)
            if existing_lines > 1:
                current_offset = existing_lines - 1
                print(f"[resume] Found existing file at {out_path} with {current_offset} rows.", flush=True)
                print(f"[resume] Resuming download starting from offset {current_offset}...", flush=True)
        except Exception as e:
            print(f"[warning] Could not determine resume offset from {out_path}: {e}", file=sys.stderr, flush=True)

    state_info = f" for state='{state}'" if state else " (all states)"
    print(f"[info] Querying data.gov.in (resource: {resource_id}){state_info} with batch_size={page_size}...", flush=True)

    total_fetched = 0
    while True:
        cur_limit = page_size if (fetch_all or max_retries) else min(page_size, limit - total_fetched)
        if not fetch_all and total_fetched >= limit:
            break

        params: dict[str, Any] = {
            "api-key": api_key,
            "format": "json",
            "offset": current_offset,
            "limit": cur_limit,
        }
        if state:
            params["filters[state]"] = state
        if district:
            params["filters[district]"] = district

        # Robust retry loop handling timeouts, 429 rate limits, and 502/504 gateway errors
        resp = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.get(url, params=params, headers=DEFAULT_HEADERS, timeout=timeout)
                if resp.status_code == 429:
                    wait_time = max(6 * attempt, 10)
                    print(
                        f"[warning] HTTP 429 Rate Limit at offset {current_offset} (attempt {attempt}/{max_retries}). "
                        f"Cooling down for {wait_time}s before retrying...",
                        file=sys.stderr,
                        flush=True,
                    )
                    time.sleep(wait_time)
                    continue
                elif resp.status_code in (502, 503, 504):
                    wait_time = 3 * attempt
                    print(
                        f"[warning] HTTP {resp.status_code} Gateway error at offset {current_offset} (attempt {attempt}/{max_retries}). "
                        f"Retrying in {wait_time}s...",
                        file=sys.stderr,
                        flush=True,
                    )
                    time.sleep(wait_time)
                    continue

                resp.raise_for_status()
                break
            except (requests.Timeout, requests.ConnectionError) as req_err:
                if attempt < max_retries:
                    wait_time = attempt * 3
                    print(
                        f"[warning] Network timeout/error at offset {current_offset} (attempt {attempt}/{max_retries}). "
                        f"Retrying in {wait_time}s...",
                        file=sys.stderr,
                        flush=True,
                    )
                    time.sleep(wait_time)
                else:
                    raise req_err

        if resp is None or resp.status_code != 200:
            print(f"[warning] Stopping fetch at offset {current_offset} due to unsuccessful response.", file=sys.stderr, flush=True)
            break

        data = resp.json()

        # OGD API sometimes returns 200 with status="error" in json body
        if isinstance(data, dict) and data.get("status") == "error":
            msg = data.get("message") or data.get("title") or "Unknown OGD API error"
            raise requests.HTTPError(f"OGD API returned error: {msg}", response=resp)

        batch_records = data.get("records", [])
        if not batch_records and isinstance(data, list):
            batch_records = data

        if not batch_records:
            print(f"[info] No more records returned at offset {current_offset}. Reached end of partition.", flush=True)
            break

        # Convert batch to DataFrame and normalize columns
        batch_df = pd.DataFrame(batch_records)
        batch_df.columns = [
            str(c).strip().lower().replace(" ", "_").replace("-", "_") for c in batch_df.columns
        ]

        # Stream directly to disk in append mode so progress is never lost
        if out_path:
            write_header = not out_path.exists() or out_path.stat().st_size == 0
            batch_df.to_csv(out_path, mode="a", index=False, header=write_header)

        records.extend(batch_records)
        total_fetched += len(batch_records)
        current_offset += len(batch_records)

        total_available = data.get("total", 0)
        try:
            total_available = int(total_available)
        except (ValueError, TypeError):
            total_available = 0

        total_str = f"/{total_available}" if total_available else ""
        print(f"[progress] Offset {current_offset:6d} | Batch {len(batch_records):3d} recs (Total state fetched: {total_fetched}{total_str}) [SAVED TO DISK]", flush=True)

        # Stop if we reached requested limit or fetched all available records
        if not fetch_all and total_fetched >= limit:
            break

        if total_available and current_offset >= total_available:
            break

        if len(batch_records) < cur_limit:
            break

        # Courteous pacing to avoid hitting rate limits
        if delay > 0:
            time.sleep(delay)

    if out_path and out_path.exists():
        return pd.read_csv(out_path)
    return pd.DataFrame(records)


def fetch_uidai_direct(
    target_date: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    dataset_code: str = DISTRICT_SATURATION_DATASET_CODE,
    timeout: int = 30,
) -> pd.DataFrame:
    """
    Fetch district saturation report from UIDAI's legacy REST feed.
    Dates are expected in yyyymmdd format.
    """
    if from_date and to_date:
        url = f"{UIDAI_BASE_URL}/{dataset_code}/{from_date}/{to_date}"
    elif target_date:
        url = f"{UIDAI_BASE_URL}/{dataset_code}/{target_date}"
    else:
        url = f"{UIDAI_BASE_URL}/{dataset_code}"

    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if "json" in content_type:
        df = pd.DataFrame(resp.json())
    else:
        df = pd.read_csv(StringIO(resp.text))

    return df


def generate_mock_saturation_data(seed: int = 42) -> pd.DataFrame:
    """
    Generate a realistic, comprehensive mock dataset of district-level Aadhaar saturation
    across major Indian states. Used for offline testing and development.
    """
    import numpy as np

    np.random.seed(seed)

    districts_by_state = {
        "Bihar": [
            ("Patna", 5838465, 96.4),
            ("Gaya", 4391418, 88.2),
            ("Muzaffarpur", 4801062, 89.7),
            ("Bhagalpur", 3037766, 87.5),
            ("Purnia", 3264619, 81.3),
            ("Darbhanga", 3937385, 86.8),
            ("Rohtas", 2959918, 91.2),
            ("Kishanganj", 1690400, 77.4),
            ("Madhubani", 4487379, 83.6),
            ("Samastipur", 4261566, 88.0),
        ],
        "Jharkhand": [
            ("Ranchi", 2914253, 94.8),
            ("Dhanbad", 2684487, 92.1),
            ("Purbi Singhbhum", 2293919, 93.4),
            ("Bokaro", 2062330, 91.0),
            ("Palamu", 1939869, 82.5),
            ("Gumla", 1025213, 71.8),
            ("Dumka", 1321442, 76.2),
            ("Khunti", 531885, 69.4),
            ("West Singhbhum", 1502338, 73.5),
            ("Garhwa", 1322784, 78.9),
        ],
        "Uttar Pradesh": [
            ("Lucknow", 4589838, 97.8),
            ("Varanasi", 3676841, 95.2),
            ("Kanpur Nagar", 4581268, 96.5),
            ("Prayagraj", 5954391, 93.1),
            ("Gorakhpur", 4440895, 90.4),
            ("Agra", 4418797, 94.6),
            ("Bareilly", 4448359, 89.8),
            ("Meerut", 3443689, 95.7),
            ("Sonbhadra", 1862559, 79.3),
            ("Bahraich", 3487731, 76.8),
            ("Sitapur", 4483992, 84.1),
            ("Hardoi", 4092845, 85.3),
        ],
        "Madhya Pradesh": [
            ("Bhopal", 2371061, 97.2),
            ("Indore", 3276697, 98.1),
            ("Jabalpur", 2463289, 93.5),
            ("Gwalior", 2032036, 94.0),
            ("Rewa", 2365106, 88.6),
            ("Balaghat", 1701698, 86.4),
            ("Jhabua", 1025048, 72.1),
            ("Mandla", 1054905, 75.8),
            ("Barwani", 1385881, 74.2),
            ("Chhindwara", 2090922, 89.1),
        ],
        "Rajasthan": [
            ("Jaipur", 6626178, 98.4),
            ("Jodhpur", 3687002, 93.8),
            ("Udaipur", 3068420, 89.2),
            ("Kota", 1951014, 95.6),
            ("Bikaner", 2363937, 91.5),
            ("Barmer", 2603751, 80.4),
            ("Jaisalmer", 669919, 78.6),
            ("Dungarpur", 1388552, 76.9),
            ("Banswara", 1797485, 75.3),
            ("Alwar", 3674179, 92.7),
        ],
        "Odisha": [
            ("Khordha", 2251673, 96.8),
            ("Cuttack", 2624470, 95.1),
            ("Ganjam", 3529031, 91.4),
            ("Sambalpur", 1041099, 92.0),
            ("Koraput", 1379647, 74.8),
            ("Malkangiri", 613192, 68.5),
            ("Mayurbhanj", 2519738, 77.2),
            ("Rayagada", 967911, 73.1),
            ("Kandhamal", 733110, 75.6),
            ("Balasore", 2317419, 90.3),
        ],
        "West Bengal": [
            ("Kolkata", 4496694, 98.5),
            ("North 24 Parganas", 10009781, 96.1),
            ("South 24 Parganas", 8161961, 92.4),
            ("Murshidabad", 7103807, 85.6),
            ("Darjeeling", 1846823, 91.8),
            ("Purulia", 2930115, 82.3),
            ("Bankura", 3596674, 86.7),
            ("Birbhum", 3502404, 87.9),
        ],
        "Maharashtra": [
            ("Mumbai", 3085411, 99.2),
            ("Pune", 9429408, 98.7),
            ("Nagpur", 4653570, 96.4),
            ("Nashik", 6107187, 95.0),
            ("Aurangabad", 3701282, 93.2),
            ("Gadchiroli", 1072942, 78.4),
            ("Nandurbar", 1648295, 77.1),
            ("Thane", 11060148, 97.9),
            ("Solapur", 4317756, 92.8),
            ("Amravati", 2888445, 93.6),
        ],
        "Andhra Pradesh": [
            ("Visakhapatnam", 4290589, 97.5),
            ("Krishna", 4517398, 96.8),
            ("Guntur", 4887813, 96.2),
            ("Chittoor", 4174064, 95.4),
            ("Kurnool", 4053463, 91.7),
            ("Anantapur", 4081148, 90.9),
            ("Srikakulam", 2703114, 88.5),
            ("East Godavari", 5154296, 96.0),
        ],
        "Telangana": [
            ("Hyderabad", 3943323, 99.1),
            ("Ranga Reddy", 2446265, 97.9),
            ("Medchal-Malkajgiri", 2440073, 98.2),
            ("Warangal", 759594, 94.6),
            ("Adilabad", 708972, 83.4),
            ("Mahabubnagar", 919903, 87.8),
            ("Khammam", 1401639, 93.1),
            ("Nizamabad", 1571022, 94.0),
        ],
        "Tamil Nadu": [
            ("Chennai", 4646732, 98.9),
            ("Coimbatore", 3458045, 98.2),
            ("Madurai", 3038252, 96.7),
            ("Tiruchirappalli", 2722290, 96.5),
            ("Salem", 3482056, 95.8),
            ("Dharmapuri", 1506843, 91.2),
            ("Nilgiris", 735394, 94.1),
            ("Ramanathapuram", 1353445, 92.4),
        ],
        "Karnataka": [
            ("Bengaluru Urban", 9621551, 99.0),
            ("Mysuru", 3001127, 96.8),
            ("Belagavi", 4779661, 94.2),
            ("Kalaburagi", 2566326, 88.7),
            ("Raichur", 1928812, 82.4),
            ("Ballari", 2452595, 90.1),
            ("Dakshina Kannada", 2089649, 97.4),
            ("Yadgir", 1174271, 79.6),
        ],
        "Kerala": [
            ("Thiruvananthapuram", 3301427, 98.4),
            ("Ernakulam", 3282388, 98.7),
            ("Kozhikode", 3086293, 97.9),
            ("Wayanad", 817420, 92.3),
            ("Malappuram", 4112920, 96.1),
            ("Idukki", 1108974, 93.5),
            ("Palakkad", 2809934, 96.8),
        ],
        "Assam": [
            ("Kamrup Metropolitan", 1253938, 93.2),
            ("Dibrugarh", 1326335, 87.5),
            ("Cachar", 1736617, 82.1),
            ("Karbi Anglong", 956313, 72.4),
            ("Dhubri", 1949258, 76.8),
            ("Kokrajhar", 887142, 74.9),
            ("Nagaon", 2823768, 84.6),
        ],
        "Gujarat": [
            ("Ahmedabad", 7214225, 98.6),
            ("Surat", 6081322, 98.0),
            ("Vadodara", 4165626, 97.3),
            ("Rajkot", 3804558, 96.9),
            ("Dahod", 2127086, 73.4),
            ("The Dangs", 228291, 69.8),
            ("Banaskantha", 3120506, 89.2),
            ("Kutch", 2092371, 91.0),
        ],
        "Chhattisgarh": [
            ("Raipur", 4063872, 96.5),
            ("Bilaspur", 2664029, 93.1),
            ("Bastar", 1413199, 74.5),
            ("Dantewada", 533638, 70.2),
            ("Surguja", 2359886, 79.4),
            ("Korba", 1206640, 89.8),
        ],
        "Haryana": [
            ("Gurugram", 1514432, 98.5),
            ("Faridabad", 1809733, 97.8),
            ("Hisar", 1743931, 95.2),
            ("Mewat", 1089263, 74.2),
            ("Karnal", 1505324, 96.1),
        ],
        "Punjab": [
            ("Ludhiana", 3498739, 98.2),
            ("Amritsar", 2490656, 97.1),
            ("Jalandhar", 2193590, 97.5),
            ("Bathinda", 1388525, 95.8),
            ("Firozpur", 2029074, 92.3),
        ],
    }

    records = []
    as_of = date.today().strftime("%Y-%m-%d")

    for state_name, district_list in districts_by_state.items():
        for dist_name, base_pop, base_sat in district_list:
            # Slight noise for realistic variation
            noise = np.random.normal(0, 0.4)
            sat_pct = round(float(np.clip(base_sat + noise, 50.0, 99.9)), 2)
            enrolled = int(base_pop * (sat_pct / 100.0))

            records.append(
                {
                    "state": state_name,
                    "district": dist_name,
                    "total_population": base_pop,
                    "enrolled_population": enrolled,
                    "aadhaar_saturation_pct": sat_pct,
                    "as_of_date": as_of,
                }
            )

    return pd.DataFrame(records)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch district-wise Aadhaar saturation data from OGD India (data.gov.in) or UIDAI portal.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    source_group = parser.add_argument_group("Data Source Options")
    source_group.add_argument(
        "--source",
        choices=["datagov", "uidai"],
        default="datagov",
        help="Data source: 'datagov' (OGD India API) or 'uidai' (legacy REST feed)",
    )
    source_group.add_argument(
        "--mock",
        action="store_true",
        help="Generate realistic mock district saturation dataset offline (no API key or network required)",
    )

    ogd_group = parser.add_argument_group("OGD India API (data.gov.in) Options")
    ogd_group.add_argument(
        "--api-key",
        default=os.getenv("DATA_GOV_IN_API_KEY"),
        help="API key for data.gov.in (defaults to DATA_GOV_IN_API_KEY environment variable)",
    )
    ogd_group.add_argument(
        "--resource-id",
        default=DEFAULT_OGD_RESOURCE_ID,
        help="Resource ID of the dataset on data.gov.in",
    )
    ogd_group.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of records to fetch",
    )
    ogd_group.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Pagination offset index for records",
    )
    ogd_group.add_argument(
        "--state",
        help="State filter (e.g. 'Jharkhand', 'Bihar', or 'all' to fetch across states). OGD requires state filtering to avoid 502 Bad Gateway on 7M+ record datasets.",
    )
    ogd_group.add_argument(
        "--district",
        help="District filter (e.g. 'Ranchi')",
    )
    ogd_group.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="HTTP request timeout in seconds (default: 60)",
    )
    ogd_group.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of records to fetch per page request (default: 100)",
    )
    ogd_group.add_argument(
        "--delay",
        type=float,
        default=0.4,
        help="Inter-request delay in seconds to avoid HTTP 429 rate limit (default: 0.4)",
    )
    ogd_group.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not auto-resume from existing CSV file; restart fetching from offset 0",
    )
    ogd_group.add_argument(
        "--all",
        dest="fetch_all",
        action="store_true",
        help="Fetch all available records via pagination",
    )

    uidai_group = parser.add_argument_group("Legacy UIDAI REST Feed Options")
    uidai_group.add_argument(
        "--date",
        help="yyyymmdd target date (defaults to latest available)",
    )
    uidai_group.add_argument(
        "--from-date",
        help="yyyymmdd start date for date range query",
    )
    uidai_group.add_argument(
        "--to-date",
        help="yyyymmdd end date for date range query",
    )
    uidai_group.add_argument(
        "--dataset-code",
        default=DISTRICT_SATURATION_DATASET_CODE,
        help="UIDAI dataset code",
    )

    parser.add_argument(
        "--out",
        default=str(RAW_DIR / "uidai_district_saturation.csv"),
        help="Output CSV file path",
    )

    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.mock:
        print("[info] Generating realistic mock Aadhaar saturation dataset...")
        df = generate_mock_saturation_data()
        df.to_csv(out_path, index=False)
        print(f"[success] Generated {len(df)} district records across {df['state'].nunique()} states.")
        print(f"[success] Saved to {out_path}")
        return

    # If querying data.gov.in
    if args.source == "datagov":
        api_key = args.api_key
        if not api_key:
            print(
                "[ERROR] An API key is required to query data.gov.in (OGD India).\n"
                "  Please provide an API key using --api-key <KEY> or set the\n"
                "  DATA_GOV_IN_API_KEY environment variable.\n\n"
                "  Get a free API key at: https://data.gov.in\n\n"
                "  Tip: For offline development and testing, run with the --mock flag:\n"
                "      python src/data_collection/fetch_uidai_saturation.py --mock",
                file=sys.stderr,
            )
            sys.exit(1)

        states_to_fetch = []
        if args.state and args.state.lower() == "all":
            states_to_fetch = ALL_INDIAN_STATES
        elif args.state:
            states_to_fetch = [args.state]
        else:
            # Default to focal states for PDS exclusion if not specified
            states_to_fetch = ["Jharkhand", "Andhra Pradesh", "Bihar", "Uttar Pradesh", "Rajasthan", "Odisha", "Haryana"]
            print(f"[info] No --state specified. Defaulting to key focus states: {', '.join(states_to_fetch)}")
            print("  (Pass --state 'StateName' or --state all to customize)\n")

        print(
            f"[info] Fetching saturation data from data.gov.in (resource: {args.resource_id})..."
        )
        try:
            frames = []
            for st_name in states_to_fetch:
                # If downloading a single state, write directly to out_path
                # If downloading multiple states, write to separate state partitions
                if len(states_to_fetch) == 1:
                    state_out_path = out_path
                else:
                    state_slug = st_name.lower().replace(" ", "_")
                    state_out_path = out_path.parent / f"uidai_saturation_{state_slug}.csv"

                state_df = fetch_ogd_saturation(
                    api_key=api_key,
                    resource_id=args.resource_id,
                    state=st_name,
                    district=args.district,
                    limit=args.limit,
                    offset=args.offset,
                    fetch_all=args.fetch_all,
                    batch_size=args.batch_size,
                    timeout=args.timeout,
                    delay=args.delay,
                    out_path=state_out_path,
                    resume=not args.no_resume,
                )
                if not state_df.empty:
                    frames.append(state_df)

            if len(states_to_fetch) > 1 and frames:
                df = pd.concat(frames, ignore_index=True)
                df.to_csv(out_path, index=False)
                print(f"[success] Combined {len(df)} total rows across {len(states_to_fetch)} states into {out_path}")
            elif out_path.exists():
                df = pd.read_csv(out_path)
            else:
                df = pd.DataFrame()
        except requests.ConnectionError as e:
            print(
                f"\n[ERROR] Connection failed: Unable to connect to data.gov.in.\n"
                f"Details: {e}\n\n"
                "Guidance:\n"
                "  - Check your internet connection and proxy settings.\n"
                "  - Run with --mock for offline development without internet access:\n"
                "      python src/data_collection/fetch_uidai_saturation.py --mock\n",
                file=sys.stderr,
            )
            sys.exit(1)
        except requests.Timeout as e:
            print(
                f"\n[ERROR] Request timed out while querying data.gov.in.\n"
                f"Details: {e}\n\n"
                "Guidance: Try again or use --mock for local offline testing.\n",
                file=sys.stderr,
            )
            sys.exit(1)
        except requests.HTTPError as e:
            status_code = getattr(e.response, "status_code", None)
            print(
                f"\n[ERROR] HTTP Error {status_code or ''}: {e}\n\n"
                "Guidance:\n",
                file=sys.stderr,
            )
            if status_code in (401, 403):
                print(
                    "  - Authentication failed. Verify that your API key is valid.\n"
                    "  - Obtain or renew your API key at: https://data.gov.in\n",
                    file=sys.stderr,
                )
            elif status_code == 404:
                print(
                    f"  - Resource ID '{args.resource_id}' was not found on data.gov.in.\n"
                    "  - Verify the resource ID at https://data.gov.in\n",
                    file=sys.stderr,
                )
            print(
                "  - Run with --mock for offline development without an API key:\n"
                "      python src/data_collection/fetch_uidai_saturation.py --mock\n",
                file=sys.stderr,
            )
            sys.exit(1)
        except requests.RequestException as e:
            print(
                f"\n[ERROR] Request error: {e}\n\n"
                "Guidance: For offline development, run with --mock:\n"
                "      python src/data_collection/fetch_uidai_saturation.py --mock\n",
                file=sys.stderr,
            )
            sys.exit(1)

    # If querying legacy UIDAI portal
    else:
        print("[info] Fetching saturation data from UIDAI portal...")
        try:
            if args.from_date and args.to_date:
                df = fetch_uidai_direct(
                    from_date=args.from_date,
                    to_date=args.to_date,
                    dataset_code=args.dataset_code,
                )
            else:
                df = fetch_uidai_direct(
                    target_date=args.date,
                    dataset_code=args.dataset_code,
                )
        except requests.ConnectionError as e:
            print(
                f"\n[ERROR] Connection failed: Unable to connect to data.uidai.gov.in.\n"
                f"Details: {e}\n\n"
                "Guidance:\n"
                "  - Check your internet connection.\n"
                "  - Run with --mock for offline development:\n"
                "      python src/data_collection/fetch_uidai_saturation.py --mock\n",
                file=sys.stderr,
            )
            sys.exit(1)
        except requests.Timeout as e:
            print(
                f"\n[ERROR] Request timed out while connecting to data.uidai.gov.in.\n"
                f"Details: {e}\n",
                file=sys.stderr,
            )
            sys.exit(1)
        except requests.HTTPError as e:
            print(
                f"\n[ERROR] HTTP Error: {e}\n\n"
                "Guidance:\n"
                f"  - Check data.uidai.gov.in for the current dataset code (used '{args.dataset_code}').\n"
                "  - Run with --mock for offline development:\n"
                "      python src/data_collection/fetch_uidai_saturation.py --mock\n",
                file=sys.stderr,
            )
            sys.exit(1)
        except requests.RequestException as e:
            print(
                f"\n[ERROR] Request error: {e}\n\n"
                "Guidance: Run with --mock for offline development:\n"
                "      python src/data_collection/fetch_uidai_saturation.py --mock\n",
                file=sys.stderr,
            )
            sys.exit(1)

    if df.empty:
        print("[warning] No records returned from the query.", file=sys.stderr)
    else:
        df.to_csv(out_path, index=False)
        print(f"[success] Saved {len(df)} rows to {out_path}")


if __name__ == "__main__":
    main()
