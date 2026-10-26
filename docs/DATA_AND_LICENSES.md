# Data sources, cleaning decisions and licences

## Forensic Reconciliation: 13,630 vs 21,029 Row Discrepancy

A central audit objective is explaining the difference between the **13,630** and **21,029** clean dataset counts:

1. **The 21,029-row dataset** was generated when all five raw training sources were ingested together, including `Used_Car_Price_Prediction.csv` (`third_listings`). Raw input: 23,652 rows across 5 sources $\rightarrow$ 2,623 rejected $\rightarrow$ 21,029 clean rows.
2. **The 13,630-row dataset** is the trusted release dataset produced when `third_listings` is excluded. Raw input: 16,252 rows across the four approved sources $\rightarrow$ 2,622 rejected $\rightarrow$ **13,630 clean rows**.
3. **Forensic breakdown by source:**
   - `cardekho_v3`: 8,128 raw $\rightarrow$ 6,843 clean (in release) / 6,846 (when third_listings present due to cross-source deduplication order)
   - `cardekho_old`: 4,340 raw $\rightarrow$ 3,452 clean (in release) / 3,457
   - `cardekho_v4`: 2,059 raw $\rightarrow$ 2,046 clean
   - `city_listings`: 1,725 raw $\rightarrow$ 1,289 clean
   - `third_listings`: 7,400 raw $\rightarrow$ 7,391 clean (**EXCLUDED from release**)
4. **Resolution Decision:** Because `third_listings` contains web-scraped fields with marketplace terms-of-service caveats, it is **excluded from the release pipeline**. The released model and all companion metadata are trained strictly on the **13,630 clean records** from approved open sources.

## Raw Source Inventory and Forensic Audit

| File | SHA-256 Digest | Raw Rows | Verified Unit | Stated Licence | Release Status |
|---|---|---|---|---|---|
| `Car details v3.csv` | `1b2a30b2f36fd246366773fe5375399692f1a113890ad2a6d464b8c8deaadadb` | 8,128 | INR (₹4,50,000 median) | DbCL v1.0 | **Approved & Used** |
| `CAR DETAILS FROM CAR DEKHO.csv` | `454fe4ea4f6d2af973493287abf0631006a32bd4f462103e4dfcffa75d721edf` | 4,340 | INR (₹3,50,000 median) | DbCL v1.0 | **Approved & Used** |
| `car details v4.csv` | `6841a81165c2a390d84b361555489e123f739f0e4b2bfe7915e759746b3efe59` | 2,059 | INR (₹8,25,000 median) | DbCL v1.0 | **Approved & Used** |
| `UsedCars_Combined.csv` | `e59c070d80bbe2745b99e84e52e006560667221e6942a283d1012dcaefb66816` | 1,725 | INR (₹8,75,000 median) | CC0: Public Domain | **Approved & Used** |
| `car data.csv` | `00b477def120548e583c638b00146982956b80646817901245ef78da9c4b3063` | 301 | Lakhs (3.6L median) | DbCL v1.0 | **Unit reference only** (not trained; target leak `Present_Price`) |
| `Used_Car_Price_Prediction.csv` | `6da5cbb18dce65901513840439f7f23791e28d8695a6a1c50dbfdd7e65865766` | 7,400 | INR (₹3,82,449 median) | Kaggle CC0 (unverified scraping terms) | **EXCLUDED FROM RELEASE** |
| `Dataset.csv` | `6d8d8546de6d5a215d95d8e030b42a9be3cd8232055ab45d6f68afb9be02e20b` | 1,725 | INR | Derived | **Excluded** (target leakage `inv_car_price`, `best_buy*`) |
| `UsedCars_<city>.csv` ×7 | (per-city files) | – | INR | CC0 | **Excluded** (subsets of `UsedCars_Combined.csv`) |

## Cleaning Outcome (Release Pipeline, from `cleaning_report.json`)
* Loaded 16,252 rows from the four approved sources $\rightarrow$ **13,630 clean rows**.
  - 2,391 duplicate listings within source removed
  - 213 duplicate listings across sources removed
  - 11 implausible km/year (> 100,000 km/yr) rejected
  - 3 impossible km values (> 1,000,000 km) rejected
  - 2 implausible odometers for vehicle age rejected
  - 2 implausible prices below ₹25,000 rejected
  - Every rejected record is logged with its reason in `rejected_records.csv`.
* **Price units verified, not assumed**: Each source's median price was compared with the CarDekho v3 INR benchmark; all four approved training sources were verified as numeric INR without scaling.
* **Outliers reviewed, not deleted**: High prices are legitimate luxury vehicles (Mercedes-Benz, BMW, Audi, Land Rover).
* **Owner counts**: Capped at 4 ("4 or more"). `Test Drive Car` and `UnRegistered Car` values are treated as unknown.
* **Transmission**: Derived from model names for city listings only when explicit tokens (MT, AT, AMT, CVT, DCT, DSG) are present; otherwise treated as missing.
* **Snapshot year**: Assumed to be the newest model year in each approved file (v3/old: 2020, city listings: 2021, v4: 2022). Historical listing prices are not inflation-adjusted.
* Targets are **historical listing (asking) prices**, not guaranteed transaction prices.

## Verified Provenance and Licences

1. **CarDekho Vehicle Dataset** (`Car details v3.csv`, `CAR DETAILS FROM CAR DEKHO.csv`, `car details v4.csv`):
   - Source: Kaggle [`nehalbirla/vehicle-dataset-from-cardekho`](https://www.kaggle.com/datasets/nehalbirla/vehicle-dataset-from-cardekho)
   - Stated Licence: **Database Contents License (DbCL) v1.0** (Open Database, Contents: Database Contents).
   - Verification Evidence: The dataset is licensed under DbCL v1.0, permitting extraction, transformation, model training, and redistribution with attribution.

2. **City Listings** (`UsedCars_Combined.csv`):
   - Source: Kaggle [`sanjeetsinghnaik/used-car-information`](https://www.kaggle.com/datasets/sanjeetsinghnaik/used-car-information)
   - Stated Licence: **Creative Commons CC0: Public Domain Dedication**.
   - Verification Evidence: Dedication to public domain with no copyright restrictions.

3. **Third-Party Listings (`Used_Car_Price_Prediction.csv`) — Excluded**:
   - Source: Kaggle *True Value Cars Dataset* by user *Nandeesh* ([`Nandeesh/true-value-cars-dataset`](https://www.kaggle.com/datasets/Nandeesh/true-value-cars-dataset)).
   - Stated Licence on Kaggle: CC0: Public Domain.
   - **Unresolved Concerns:** Features including `broker_quote`, `ad_created_on`, `booking_down_pymnt`, and inspection identifiers establish that this data was originally extracted via web-scraping from commercial Indian portal listings (Cars24 / True Value network). Because original portal terms may restrict automated collection and commercial redistribution, the dataset cannot be verified as legally risk-free.
   - **Action Taken:** Permanently excluded from the release training pipeline via:
     ```bash
     python ml/scripts/ingest.py --raw-dir ml/data/raw --exclude-source third_listings
     ```

## Raw Data Policy
Raw datasets are excluded from version control (`.gitignore`) and are **not redistributed** in this repository. All artifacts, models, and analytics are derived, transformed representations.
