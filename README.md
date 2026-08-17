# Exclusion Risk Predictor + Fairness Audit for Welfare Authentication

> Predicting and auditing district-level exclusion risk in Aadhaar-authenticated welfare delivery (PDS), with a fairness audit and a governance dashboard for policy feedback.

## Motivation

India's Public Distribution System (PDS) serves ~800 million beneficiaries, with Aadhaar biometric authentication increasingly required for ration collection. Published research documents significant variation in authentication failure rates across districts:

- **Jharkhand**: Only 52% of ration card households successfully purchased rations in Ranchi district after biometric authentication became compulsory (August 2016), with digitized areas showing failure rates ~5× higher than offline areas.
- **Andhra Pradesh**: State-level failure averaged 2.5%, but YSR Kadapa and Vizianagaram ran >2× the state average; biometric mismatch accounted for 92% of failures.
- **Haryana**: Faridabad district had >2× the state's average failure rate.

These failures are **not random** — they correlate with structural factors (manual labour → worn fingerprints, poor connectivity, low electrification) that are both predictable and disproportionately concentrated in already-vulnerable populations. This project builds a predictive model and fairness audit to surface those patterns.

## Approach

### Unit of analysis: district-month

Individual-level authentication logs are not public (nor should they be — this is sensitive data about vulnerable people). What **is** public is district/state-level aggregates: UIDAI's saturation reports, Census socio-economic data, and published academic studies reporting district-level PDS transaction failure rates.

The unit of analysis is **district-month** (~700 districts × available months). This is a deliberate framing choice — it keeps the project honest about what public data supports and avoids building anything that scores individuals.

### Framing

This tool is positioned as a **diagnostic/audit system for administrators**, not as something that scores or flags individual beneficiaries. Given the real stakes (documented starvation deaths linked to wrongful exclusion), a district-level governance-monitoring framing is both more honest and more ethically sound.

## Pipeline

```
Data Collection → Feature Engineering → Risk Modeling → Fairness Audit → Dashboard
```

| Stage | What happens | Script |
|-------|-------------|--------|
| **Data collection** | Pull UIDAI district saturation feed + manually source Census, TRAI, Saubhagya data | `src/data_collection/fetch_uidai_saturation.py` |
| **Feature engineering** | Merge sources into a single district-level feature table with fuzzy district-name matching | `src/features/build_district_features.py` |
| **Risk modeling** | XGBoost regression on failure rate + SHAP feature attribution | `src/models/train_exclusion_risk_model.py` |
| **Fairness audit** | Fairlearn-based subgroup disparity analysis across structural exposure groups | `src/fairness/fairness_audit.py` |
| **Dashboard** | Streamlit app: district risk rankings, SHAP drivers, fairness results, policy feedback panel | `dashboard/app.py` |

## Project Structure

```
rural-ai-governance-exclusion/
├── data/
│   ├── raw/                 # Untouched downloads (UIDAI CSVs)
│   ├── external/            # Manually sourced files (Census, TRAI, state PDS dumps)
│   └── processed/           # Cleaned, merged district-month feature table
├── src/
│   ├── data_collection/
│   │   └── fetch_uidai_saturation.py
│   ├── features/
│   │   └── build_district_features.py
│   ├── models/
│   │   └── train_exclusion_risk_model.py
│   └── fairness/
│       └── fairness_audit.py
├── dashboard/
│   └── app.py
├── data_sources.md          # Catalog of every data source with URLs and access notes
├── requirements.txt
└── README.md
```

## Data Sources

| Source | What it provides | Access |
|--------|-----------------|--------|
| **UIDAI Public Data Portal** | District-wise Aadhaar enrolment saturation % (weekly) | REST API, no key needed |
| **Census 2011 / SECC** | Occupation mix, literacy, electrification, gender ratio | `censusindia.gov.in` |
| **TRAI Telecom Reports** | District/circle-level teledensity (connectivity proxy) | `trai.gov.in` quarterly reports |
| **Saubhagya Dashboard** | Village-level electrification | `saubhagya.gov.in` |
| **Published studies** (ISB, LibTech India, IDEAS for India) | District/FPS-level PDS failure rates (Jharkhand, AP, Haryana, Delhi) | Academic papers / policy briefs |

See [`data_sources.md`](data_sources.md) for the full catalog with exact URLs and access notes.

## Setup

```bash
# Clone the repository
git clone https://github.com/ayushsingh-22/rural-ai-governance-exclusion.git
cd rural-ai-governance-exclusion

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

Run the pipeline in order:

```bash
# 1. Fetch UIDAI district saturation data
python src/data_collection/fetch_uidai_saturation.py

# 2. Place Census, TRAI, Saubhagya files in data/external/ (see data_sources.md)

# 3. Build merged feature table
python src/features/build_district_features.py

# 4. Train exclusion risk model + generate SHAP values
python src/models/train_exclusion_risk_model.py

# 5. Run fairness audit
python src/fairness/fairness_audit.py

# 6. Launch dashboard
streamlit run dashboard/app.py
```

## Methodology Notes

- **Target variable**: Authentication/transaction failure rate where available from published studies; enrolment rejection rate as a weaker proxy where it isn't. The choice is stated explicitly — this is a modeling decision with real implications.
- **Model**: Gradient-boosted trees (XGBoost) with SHAP for feature attribution — the SHAP decomposition is the governance artifact, not just the predictions.
- **Fairness audit**: Districts are binned by structural factors (% manual labour, % elderly, connectivity) and compared for disparate impact using Fairlearn. This is district-level, not individual-level — a framing limitation noted explicitly.
- **Validation**: Model rankings are benchmarked against documented high-failure districts from published research (Jharkhand, AP, Haryana).

## Known Limitations

- **Ground truth scarcity**: Transaction failure rate is not centrally published at district level. Labeled data comes from a handful of academic studies, concentrated in Jharkhand, AP, Haryana, and Delhi.
- **Census data vintage**: Socio-economic features are from Census 2011 — the best available granular data, but dated.
- **District boundary changes**: India has created many new districts since 2011. Fuzzy matching handles most cases, but some manual reconciliation is always needed.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
