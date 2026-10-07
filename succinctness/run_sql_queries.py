"""
run_sql_queries.py
-------------------
Runs the 9 SQL equivalents of the SPARQL conformance queries (B1-B4, D4, D6,
S1, S3, S5) against the anonymized SAP CSV tables, for the succinctness
validation study (checking that the SQL translation returns sensible /
comparable results to the SPARQL versions on the OCEDR Knowledge Graph).

"""

from pathlib import Path
import duckdb
import pandas as pd

# ================================================================
# CONFIGURATION
# ================================================================

# Path to the folder containing the *_anonymized.csv files.
# Resolved relative to this script's own location (not the current working
# directory), so it works regardless of where you run `python` from.
# Adjust the relative part if your folder structure differs.
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_PATH = SCRIPT_DIR / "../preprocessing/sap_data/02_processed"

# Folder where the query results will be written (created if missing),
# also resolved relative to this script's location.
OUTPUT_PATH = SCRIPT_DIR / "query_results"

# Tables required by the 9 queries
TABLES = [
    "EKKO", "EKPO", "EBAN", "EKET",
    "MKPF", "MSEG",
    "RBKP", "RSEG",
    "BKPF", "BSEG",
    "EKBE",
]

# NOTE: previously used to filter BKPF for B3/B4, but removed — per the
# OCEDD schema every BKPF row is treated as a ClearInvoice event (no TCODE
# filter). Kept here only for the diagnostic printout below, in case you
# want to reintroduce a stricter definition of "payment posting".
CLEARING_TCODES = ("F-44", "F110")


# ================================================================
# LOAD TABLES
# ================================================================

def load_table(name: str, base_path: Path) -> pd.DataFrame:
    """Load a SAP 'Text with Tabs' export saved as .csv.

    Tries a couple of common delimiters since SE16N "Text with Tabs"
    exports are tab-separated despite the .csv extension.
    """
    file_path = base_path / f"{name}_anonymized.csv"
    if not file_path.exists():
        raise FileNotFoundError(f"Could not find {file_path}")

    # Auto-detect delimiter (tab, comma, semicolon) via the python engine.
    df = pd.read_csv(file_path, sep=None, engine="python", dtype=str)
    df.columns = [c.strip() for c in df.columns]
    return df


def load_all_tables(base_path: Path) -> dict:
    dfs = {}
    for name in TABLES:
        try:
            dfs[name] = load_table(name, base_path)
            print(f"Loaded {name:6s} — {len(dfs[name])} rows, "
                  f"columns: {list(dfs[name].columns)}")
        except FileNotFoundError as e:
            print(f"WARNING: {e} (queries needing {name} will fail)")
    return dfs


# ================================================================
# QUERIES
# ================================================================
# SQL translations of the 9 SPARQL queries. See p2p_sql_queries.sql
# for the full commented version with assumptions documented.

QUERIES = {

    "B1_gr_without_po": """
        SELECT DISTINCT
            mk.MBLNR,
            mk.MJAHR,
            mk.BUDAT AS gr_date
        FROM MKPF mk
        JOIN MSEG ms
            ON mk.MBLNR = ms.MBLNR
           AND mk.MJAHR = ms.MJAHR
        WHERE EXISTS (
            SELECT 1 FROM RSEG rs WHERE rs.EBELN = ms.EBELN
        )
        AND NOT EXISTS (
            SELECT 1 FROM EKKO po WHERE po.EBELN = ms.EBELN
        )
        ORDER BY gr_date
    """,

    "B2_invoice_before_gr": """
        SELECT
            rb.BELNR AS invoice,
            rs.EBELN AS po,
            rb.BLDAT AS invoice_date
        FROM RBKP rb
        JOIN RSEG rs
            ON rb.BELNR = rs.BELNR
           AND rb.GJAHR = rs.GJAHR
        WHERE NOT EXISTS (
            SELECT 1
            FROM MSEG ms
            JOIN MKPF mk
                ON ms.MBLNR = mk.MBLNR
               AND ms.MJAHR = mk.MJAHR
            WHERE ms.EBELN = rs.EBELN
              AND mk.BUDAT <= rb.BLDAT
        )
        ORDER BY invoice_date
    """,

    "B3_payment_before_invoice": """
        SELECT DISTINCT
            rb.BELNR AS invoice,
            bk.BELNR AS fi_doc,
            bk.GJAHR
        FROM RBKP rb
        JOIN BKPF bk
            ON substr(bk.AWKEY, 1, 10) = rb.BELNR
        WHERE NOT EXISTS (
            SELECT 1
            FROM RBKP rb2
            WHERE rb2.BELNR = rb.BELNR
              AND rb2.GJAHR = rb.GJAHR
        )
    """,

    "B4_payment_without_gr": """
        SELECT
            rb.BELNR   AS invoice,
            ekko.EBELN AS po,
            MAX(bk.BUDAT) AS clear_date,
            MAX(CAST(rs.WRBTR AS DOUBLE)) AS amount
        FROM RBKP rb
        JOIN RSEG rs
            ON rb.BELNR = rs.BELNR
           AND rb.GJAHR = rs.GJAHR
        JOIN EKKO ekko
            ON rs.EBELN = ekko.EBELN
        JOIN BKPF bk
            ON substr(bk.AWKEY, 1, 10) = rb.BELNR
        WHERE NOT EXISTS (
            SELECT 1 FROM MSEG ms WHERE ms.EBELN = ekko.EBELN
        )
        GROUP BY rb.BELNR, ekko.EBELN
        ORDER BY amount DESC
    """,

    "D4_vendor_mismatch": """
        SELECT
            rb.BELNR   AS invoice,
            ekko.EBELN AS po,
            rb.LIFNR   AS invoice_vendor,
            ekko.LIFNR AS po_vendor,
            MAX(CAST(rs.WRBTR AS DOUBLE)) AS amount
        FROM RBKP rb
        JOIN RSEG rs
            ON rb.BELNR = rs.BELNR
           AND rb.GJAHR = rs.GJAHR
        JOIN EKKO ekko
            ON rs.EBELN = ekko.EBELN
        WHERE rb.LIFNR <> ekko.LIFNR
        GROUP BY rb.BELNR, ekko.EBELN, rb.LIFNR, ekko.LIFNR
        ORDER BY amount DESC
    """,

    "D6_amount_tolerance": """
        SELECT DISTINCT
            rb.BELNR   AS invoice,
            ekko.EBELN AS po,
            CAST(rs.WRBTR AS DOUBLE) AS invoiced_amount
        FROM RBKP rb
        JOIN RSEG rs
            ON rb.BELNR = rs.BELNR
           AND rb.GJAHR = rs.GJAHR
        JOIN EKKO ekko
            ON rs.EBELN = ekko.EBELN
        WHERE EXISTS (
            SELECT 1
            FROM EKPO ekpo
            WHERE ekpo.EBELN = ekko.EBELN
              AND CAST(rs.WRBTR AS DOUBLE) > CAST(ekpo.NETWR AS DOUBLE) * 1.05
        )
        ORDER BY invoice
    """,

    "S1_po_creator_is_invoice_enterer": """
        SELECT DISTINCT
            ekko.ERNAM AS user_name,
            ekko.EBELN AS po,
            rb.BELNR   AS invoice,
            ekko.BEDAT AS po_date,
            rb.BLDAT   AS invoice_date
        FROM EKKO ekko
        JOIN RSEG rs
            ON rs.EBELN = ekko.EBELN
        JOIN RBKP rb
            ON rb.BELNR = rs.BELNR
           AND rb.GJAHR = rs.GJAHR
        WHERE ekko.ERNAM = rb.USNAM
        ORDER BY user_name, po_date
    """,

    "S3_invoice_enterer_is_payment_poster": """
        SELECT
            rb.USNAM AS user_name,
            rb.BELNR AS invoice,
            bk.BELNR AS fi_doc,
            rb.BLDAT AS invoice_date,
            bk.BUDAT AS clear_date
        FROM RBKP rb
        JOIN BKPF bk
            ON substr(bk.AWKEY, 1, 10) = rb.BELNR
        WHERE rb.USNAM = bk.USNAM
        ORDER BY user_name, invoice_date
    """,

    "S5_po_creator_is_gr_poster": """
        SELECT DISTINCT
            ekko.ERNAM AS user_name,
            ekko.EBELN AS po,
            mk.MBLNR   AS gr,
            ekko.BEDAT AS po_date,
            mk.BUDAT   AS gr_date
        FROM EKKO ekko
        JOIN MSEG ms
            ON ms.EBELN = ekko.EBELN
        JOIN MKPF mk
            ON mk.MBLNR = ms.MBLNR
           AND mk.MJAHR = ms.MJAHR
        WHERE ekko.ERNAM = mk.USNAM
        ORDER BY user_name, po_date
    """,
}


# ================================================================
# MAIN
# ================================================================

def main():
    print(f"Loading tables from: {BASE_PATH.resolve()}\n")
    tables = load_all_tables(BASE_PATH)

    con = duckdb.connect(database=":memory:")
    for name, df in tables.items():
        con.register(name, df)

    # Diagnostic: show actual TCODE values present in BKPF, so
    # CLEARING_TCODES above can be calibrated correctly. B3/B4 depend
    # on this filter matching the real clearing transaction codes.
    if "BKPF" in tables:
        print("\n" + "=" * 60)
        print("DIAGNOSTIC: distinct BKPF.TCODE values (with counts)")
        print("=" * 60)
        tcode_counts = con.execute(
            "SELECT TCODE, COUNT(*) AS n FROM BKPF GROUP BY TCODE ORDER BY n DESC"
        ).df()
        print(tcode_counts.to_string(index=False))
        print(f"\nCurrently configured CLEARING_TCODES = {CLEARING_TCODES}")
        print("If none of the above match, update CLEARING_TCODES at the "
              "top of this script.\n")

    OUTPUT_PATH.mkdir(exist_ok=True)

    print("\n" + "=" * 60)
    print("RUNNING QUERIES")
    print("=" * 60)

    summary = []
    for query_id, sql in QUERIES.items():
        try:
            result = con.execute(sql).df()
            out_file = OUTPUT_PATH / f"{query_id}.csv"
            result.to_csv(out_file, index=False)
            print(f"{query_id:40s} -> {len(result):4d} violations "
                  f"(saved to {out_file})")
            summary.append((query_id, len(result), "OK"))
        except Exception as e:
            print(f"{query_id:40s} -> ERROR: {e}")
            summary.append((query_id, None, f"ERROR: {e}"))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    summary_df = pd.DataFrame(summary, columns=["query", "violation_count", "status"])
    print(summary_df.to_string(index=False))
    summary_df.to_csv(OUTPUT_PATH / "_summary.csv", index=False)
    print(f"\nSummary saved to {OUTPUT_PATH / '_summary.csv'}")


if __name__ == "__main__":
    main()