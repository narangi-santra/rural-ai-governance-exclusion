# Data source catalog

| Source | What it gives you | Access | Notes |
|---|---|---|---|
| UIDAI Data / OGD India (`data.gov.in`) | District-wise Aadhaar enrolment saturation % | OGD India REST API with free API key (`api.data.gov.in`) or CSV export from `indiadataportal.com` / `uidai.gov.in` | Saturation ≠ authentication failure. Use as a base layer / proxy for digital-ID coverage, not as your main label. |
| Academic/policy briefs (ISB Bharti Institute, DIRI, IDEAS for India, LibTech India) | District/FPS-level PDS authentication failure rates for specific states (Jharkhand, AP, Haryana, Delhi) | Search + manual extraction from PDFs | These are your ground-truth validation points. Small in number — treat as gold-standard spot checks, not a training set by themselves. |
| State PDS transparency portals (e.g. Telangana, Chhattisgarh `khadya.cg.nic.in`, Andhra Pradesh `epds2.ap.gov.in`) | FPS or district-level monthly transaction/offtake data for that state | Varies by state — some have public dashboards, some need RTI | Coverage is inconsistent across states. Start with states known to publish (AP, Telangana, Chhattisgarh) rather than trying to be national from day one. |
| Census 2011 / SECC (Socio-Economic Caste Census) | District-level occupation mix (% manual labour), literacy, electrification, gender ratio | `censusindia.gov.in`, `secc.gov.in` | Data is from 2011 — note this explicitly as a limitation in your report; it's the best public granular socio-economic data available but it's dated. |
| TRAI district/circle-level telecom reports | Connectivity / teledensity proxy | `trai.gov.in` performance indicator reports (PDF/Excel, quarterly) | TRAI reports by "circle" (multi-district zones in some cases) — you may need to map circles to districts. |
| Saubhagya Dashboard | Village-level electrification data | `saubhagya.gov.in` | Useful for the "needs power + connectivity simultaneously" mechanism. |
| Right to Food Campaign / LibTech India documentation | Documented starvation deaths / exclusion case studies | Published reports, news coverage | Qualitative validation — use to sanity-check that your model's highest-risk districts overlap with real documented cases, not as numeric training data. |

## District name matching

Every one of these sources spells/splits districts slightly differently
(old vs. new district boundaries especially — India has created many new
districts since 2011 by splitting old ones). Recommended approach:

1. Pick ONE canonical district list (e.g. Census 2011's, since most other
   granular sources predate the newer district splits).
2. Build a manual mapping table for anything that doesn't match via fuzzy
   string matching (`thefuzz` / `rapidfuzz` in Python gets you most of the
   way, but always spot-check the output).
3. Keep the mapping table itself as a versioned file in `data/external/` —
   you'll need to explain and defend it in your methodology write-up.
