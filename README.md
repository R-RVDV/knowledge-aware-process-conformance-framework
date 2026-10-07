# Knowledge-Aware Conformance Checking: Replication Package
 
Replication package of the master thesis *Knowledge-Aware Conformance Checking: Leveraging
Object-Centric Event Data (OCED) for Process Diagnosis in SAP Environments* (Utrecht University,
2026, in cooperation with Emixa).
 
It contains the code to rebuild the Knowledge Graph (KG) from the anonymised SAP tables, to run
the conformance checks (model-wide OCBC conformance) and to repeat the evaluation (synthetic injection, succinctness analysis).

For the associated Proof-of-Concept tool navigate to: https://github.com/R-RVDV/p2p-poc
 
## Repository layout
 
The scripts use relative paths and expect this layout. Run the scripts marked "root" from the
repository root; the other scripts find their files relative to their own location.
 
```
.
├── emixa_p2p_ocedd.ttl                
├── ocedr_p2p_graph.ttl               
├── requirements.txt
├── build_ocedr.py                     
├── automated_constraint_discovery.py
├── ocedr_diagnostics.py
├── ocedr_statistics.py
├── preprocessing/
│   ├── pre_processing.py
│   ├── user_anonymizer.py
│   └── sap_data/02_processed/
├── model_wide_conformance/
│   ├── model_wide_conformance.py
│   └── sparql_queries.py
├── synthetic_injection/            
│   ├── find_candidates.py                              
│   ├── inject.py
│   ├── injection_config.json
│   ├── injection_log.json
│   └── injected/
└── succinctness/
    ├── run_sql_queries.py
    └── compute_succinctness_metrics.py                    
```
 
## Requirements
 
Python 3.11 or newer.
 
```
pip install -r requirements.txt
```
 
 
## Expected results
 
Use these numbers to check that your run matches the thesis.
 
| Check | Expected |
|---|---|
| Triples in OCEDD / OCEDR | 238 / 64,724 |
| Baseline violations B1, B2, B3, B4, D4, D6, S1, S3, S5 | 0, 5, 0, 5, 0, 5, 50, 53, 193 |
| Total after injection (same order) | 4, 9, 4, 9, 4, 9, 54, 53, 197 |
| Model-wide conformance, all 390 Purchase Orders (restricted) | 33 fully conformant (8.5%) |
| Model-wide conformance, the 44 POs with an invoice (restricted) | 33 fully conformant (75.0%) |
 
 
## Warnings
 
- **Do not run `pre_processing.py` on the provided tables.** Its second step is not idempotent:
  on tables that are already cleaned it corrupts amounts (1234.5 becomes 12345) and swaps day
  and month in dates. The script documents how the processed tables were produced; it only
  works on raw SAP extracts.
- **Do not re-run `find_candidates.py` unless you want to redo the selection.** It overwrites
  `injection_config.json` and empties the selected instances.
- **Pseudonym numbers are not reproducible.** The anonymisation mapping is not stored, and the
  numbering (`User_001`, ...) follows the order in which the raw files are read. Re-running on
  the raw data may give different numbers, and `injection_config.json` refers to the current ones.
- **generatesFinancialDoc, C4 and C5 are unreliable.** They depend on the ClearInvoice event and
  the FinancialDocument object, which are derived via `BKPF.AWKEY` (see Threats to Validity in
  the thesis). `model_wide_conformance.py` therefore reports a restricted and a full result.

## Data availability
 
The raw SAP extracts are not distributed, as they contain real user names and vendor numbers and
come from a test system (VD9) of Emixa. The set of anonymised tables are presented in `preprocessing/sap_data/02_processed/` and `ocedr_p2p_graph.ttl`.
 
## Use of generative AI
 
The code was developed with the help of generative AI (Claude, Anthropic). The scripts were
generated and debugged iteratively, and comments and code were reviewed by the author. The query
layer was verified independently, through synthetic injection and through SQL equivalents run on
the flat tables, and changes to the schema encoding were checked by confirming that triple
counts and conformance results stayed identical.