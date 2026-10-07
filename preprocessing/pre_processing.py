"""
Preprocessing of the raw SAP extracts into the anonymised, cleaned tables that are the
input of build_ocedr.py.

Step 1  Anonymise: user names and vendor numbers in ./preprocessing/sap_data/01_raw/
        (<TABLE>_extract.csv) are replaced by pseudonyms (see user_anonymizer.py) and the
        tables are written to ./preprocessing/sap_data/02_processed/ (<TABLE>_anonymized.csv).
Step 2  Clean (in place): dates to ISO (YYYY-MM-DD), amounts and quantities to numbers, and
        a readable label for the EKBE transaction type (VGABE).

The raw extracts contain real user names and vendor numbers and are therefore not part of
the replication package. This script documents how the processed tables were produced.

WARNING: step 2 is not idempotent. It must only run directly after step 1, on freshly
anonymised tables. Running this script on tables in 02_processed that are already cleaned
corrupts them (e.g. 1234.5 becomes 12345 and 2020-03-05 becomes 2020-05-03).

"""


import os
import pandas as pd
import glob
from user_anonymizer import anonymize_sap_folder, read_sap_file


def post_process_fixes(folder_path):
    print("\n--- Start Post-Processing Fixes ---")
    files = glob.glob(os.path.join(folder_path, "*_anonymized.csv"))

    for file_path in files:
        fname = os.path.basename(file_path)
        try:
            df = read_sap_file(file_path)

            if df.empty:
                continue

            # Dates to ISO
            date_cols = ['BEDAT', 'BLDAT', 'BUDAT', 'CPUDT', 'ERDAT', 'EINDT', 'SLFDT', 'UDATE']
            for col in [c for c in date_cols if c in df.columns]:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce').dt.strftime('%Y-%m-%d')

            # Amounts & quantities
            amount_cols = ['NETWR', 'BRTWR', 'WRBTR', 'DMBTR', 'MENGE', 'NETPR', 'BPMNG']
            for col in [c for c in amount_cols if c in df.columns]:
                df[col] = df[col].str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                if col in ['MENGE', 'BPMNG']:
                    df[col] = df[col].str.extract(r'(\d+\.?\d*)')[0]
                df[col] = pd.to_numeric(df[col], errors='coerce')

            # VGABE Labels
            if 'VGABE' in df.columns:
                vgabe_map = {'1': 'Goods Receipt', '2': 'Invoice Receipt'}
                df['VGABE_LABEL'] = df['VGABE'].map(vgabe_map).fillna('Other')

            df.to_csv(file_path, sep='\t', index=False, encoding='utf-8')
            print(f"  Successfully cleaned: {fname}")

        except Exception as e:
            print(f"  ! Error during post-processing {fname}: {e}")

    print("--- Post-Processing Completed ---")


def main_preprocessing():
    RAW_DATA_PATH = './preprocessing/sap_data/01_raw/'
    CLEAN_DATA_PATH = './preprocessing/sap_data/02_processed/'

    if not os.path.exists(CLEAN_DATA_PATH):
        os.makedirs(CLEAN_DATA_PATH)

    print("--- START PRE-PROCESSING WORKFLOW ---")

    print("Step 1: Applying privacy masks...")
    mappings = anonymize_sap_folder(RAW_DATA_PATH, CLEAN_DATA_PATH)
    print(f"  > {len(mappings['users'])} unique users and {len(mappings['vendors'])} vendors mapped.")

    print("Step 2: Optimizing data integrity and structure...")
    post_process_fixes(CLEAN_DATA_PATH)

    print("\n--- FULL PROCESS COMPLETED ---")
    print(f"The data in {CLEAN_DATA_PATH} is now ready for Triplification.")

if __name__ == "__main__":
    main_preprocessing()