"""
This script anonymizes the raw SAP tables and creates 15 <TABLE>_anonymized.csv files to an output folder (tab-separated, UTF-8):
  - user names (ERNAM, AFNAM, USNAM, USERNAME) are replaced by User_001, User_002, ...
  - vendor numbers (LIFNR) are replaced by VND_0001, VND_0002, ...
  - the same name or number gets the same pseudonym in every table, so the relations
    between tables are preserved;
  - tables without such columns are copied unchanged under the new name.

Pseudonym numbers are assigned in order of first appearance while the files are read. That
order follows glob.glob(), which is not guaranteed to be the same on every machine, so
re-running the script on the raw data may give different numbers.
"""


import pandas as pd
import glob
import os
import shutil
import io


def read_sap_file(file_path, nrows=None):
    fname = os.path.basename(file_path)
    encoding = 'utf-8' if file_path.endswith('_anonymized.csv') else 'latin-1'

    with open(file_path, 'r', encoding=encoding, errors='replace') as f:
        lines = f.readlines()

    if nrows is not None:
        lines = lines[:nrows + 1]

    # Strip outer quotes per line
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        if line.startswith('"') and line.endswith('"'):
            line = line[1:-1]
        cleaned_lines.append(line)

    content = '\n'.join(cleaned_lines)

    # All tables via tab separator — this works for all SAP SE16N exports
    df = pd.read_csv(
        io.StringIO(content),
        sep='\t',
        dtype=str,
        on_bad_lines='skip'
    )

    # Clean up columns
    df.columns = [str(c).strip().replace('"', '') for c in df.columns]
    df = df.loc[:, ~df.columns.str.contains(r'^Unnamed|^$', case=False, regex=True)]
    df = df.map(lambda x: str(x).replace('"', '').strip()
                if pd.notna(x) and str(x).lower() not in ['nan', 'none'] else x)
    return df


def anonymize_sap_folder(input_folder, output_folder):
    user_mapping = {}
    next_user_id = 1
    vendor_mapping = {}
    next_vendor_id = 1

    user_columns = ['ERNAM', 'AFNAM', 'USNAM', 'USERNAME']
    vendor_columns = ['LIFNR']
    all_target_cols = user_columns + vendor_columns

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    def get_user_pseudonym(real_name):
        nonlocal next_user_id
        if pd.isna(real_name) or str(real_name).strip() == "" or str(real_name).lower() in ['nan', 'none', '0']:
            return real_name
        real_name = str(real_name).upper().strip()
        if real_name not in user_mapping:
            user_mapping[real_name] = f"User_{next_user_id:03d}"
            next_user_id += 1
        return user_mapping[real_name]

    def get_vendor_pseudonym(real_id):
        nonlocal next_vendor_id
        if pd.isna(real_id) or str(real_id).strip() == "" or str(real_id).lower() in ['nan', 'none', '0']:
            return real_id
        real_id = str(real_id).strip()
        if real_id not in vendor_mapping:
            vendor_mapping[real_id] = f"VND_{next_vendor_id:04d}"
            next_vendor_id += 1
        return vendor_mapping[real_id]

    search_path = os.path.join(input_folder, "*_extract.csv")
    files = glob.glob(search_path)

    print("Round 1: Inventorying...")
    for file_path in files:
        fname = os.path.basename(file_path)
        try:
            df = read_sap_file(file_path)
            has_targets = any(col in df.columns for col in all_target_cols)
            if has_targets:
                for col in [c for c in user_columns if c in df.columns]:
                    df[col].dropna().apply(get_user_pseudonym)
                for col in [c for c in vendor_columns if c in df.columns]:
                    df[col].dropna().apply(get_vendor_pseudonym)
                print(f"  > {fname}: Names collected. Columns: {list(df.columns)}")
            else:
                print(f"  . {fname}: No target columns found (will be copied later).")
        except Exception as e:
            print(f"  ! Error while reading {fname}: {e}")

    print("\nRound 2: Processing or Copying...")
    for file_path in files:
        fname = os.path.basename(file_path)
        output_name = fname.replace('_extract', '_anonymized')
        dest_path = os.path.join(output_folder, output_name)
        try:
            df = read_sap_file(file_path)
            has_targets = any(col in df.columns for col in all_target_cols)
            if has_targets:
                for col in [c for c in user_columns if c in df.columns]:
                    df[col] = df[col].apply(get_user_pseudonym)
                for col in [c for c in vendor_columns if c in df.columns]:
                    df[col] = df[col].apply(get_vendor_pseudonym)
                df.to_csv(dest_path, sep='\t', index=False, encoding='utf-8')
                print(f"  Success (Anonymized): {fname} -> {output_name}")
            else:
                shutil.copy2(file_path, dest_path)
                print(f"  Success (Copied): {fname} -> {output_name}")
        except Exception as e:
            print(f"  ! Error while processing {fname}: {e}")

    print(f"\nTotal unique users: {next_user_id - 1}")
    print(f"Total unique vendors: {next_vendor_id - 1}")
    return {"users": user_mapping, "vendors": vendor_mapping}