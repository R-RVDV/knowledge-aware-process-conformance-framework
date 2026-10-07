"""
Computes succinctness metrics for the 9 SPARQL conformance queries and their SQL
equivalents (B1-B4, D4, D6, S1, S3, S5) and writes the results to succinctness_results/.
The queries are only measured as text, not executed.

Metrics, adapted from Vashistha and Jain (2016), with a SPARQL equivalent for each:
  qlength_loc / _chars : lines of code and characters (comments and whitespace stripped)
  n_operator           : SPARQL: triple patterns whose predicate is an OCEDD object-to-object
                         relation (the RDF equivalent of a join); SQL: JOIN clauses
  n_expression         : SPARQL: FILTER (NOT) EXISTS / OPTIONAL blocks; SQL: nested subqueries
  max_nesting_depth    : SPARQL: nested { } blocks; SQL: nested ( ) pairs, including
                         function calls such as CAST(...)
  n_column             : SPARQL: distinct ?variables; SQL: distinct table aliases
  n_table              : SPARQL: distinct ext: classes and properties; SQL: distinct source
                         tables. Reported descriptively: in Vashistha and Jain's regression
                         it carries little weight.

"""

import re
from pathlib import Path
import pandas as pd

OUTPUT_PATH = Path(__file__).resolve().parent / "succinctness_results"

# OCEDD object-to-object relation properties (Table 4.4). Only triples
# using one of these predicates are counted as join-equivalent operators.
RELATION_PROPERTIES = {
    "isConvertedTo",
    "isDeliveredBy",
    "isBilledBy",
    "matches",
    "generatesFinancialDoc",
    "reservedFor",
}


# ================================================================
# QUERY TEXT — SPARQL (from the verified query file) and SQL
# (from the verified run_sql_queries.py, post-fixes)
# ================================================================

SPARQL_QUERIES = {

"B1": """
SELECT ?gr ?grDate
WHERE {
  ?gr a ext:GoodsReceipt .

  ?grEvent a ext:RecordGoodsReceipt ;
           oced:observes ?gr ;
           oced:observed_at ?grDate .

  FILTER EXISTS {
    ?inv ext:matches ?gr .
  }

  FILTER NOT EXISTS {
    ?po a ext:PurchaseOrder ;
        ext:isDeliveredBy ?gr .
  }
}
ORDER BY ?grDate
""",

"B2": """
SELECT ?invoice ?po ?invoiceDate
WHERE {
  ?po a ext:PurchaseOrder ;
      ext:isBilledBy ?invoice .

  ?invEvent a ext:RecordInvoice ;
            oced:observes ?invoice ;
            oced:observed_at ?invoiceDate .

  FILTER NOT EXISTS {
    ?po ext:isDeliveredBy ?gr .

    ?grEvent a ext:RecordGoodsReceipt ;
             oced:observes ?gr ;
             oced:observed_at ?grDate .

    FILTER(?grDate <= ?invoiceDate)
  }
}
ORDER BY ?invoiceDate
""",

"B3": """
SELECT ?invoice ?fi
WHERE {
  ?invoice a ext:Invoice .
  ?invoice ext:generatesFinancialDoc ?fi .

  ?clearEvent a ext:ClearInvoice ;
              oced:observes ?fi .

  FILTER NOT EXISTS {
    ?invEvent a ext:RecordInvoice ;
              oced:observes ?invoice .
  }
}
""",

"B4": """
SELECT ?invoice ?po ?fi ?clearDate ?amount
WHERE {
  ?invoice a ext:Invoice .
  ?invoice ext:generatesFinancialDoc ?fi .
  ?po ext:isBilledBy ?invoice .

  ?clearEvent a ext:ClearInvoice ;
              oced:observes ?fi ;
              oced:observed_at ?clearDate .

  OPTIONAL { ?invoice ext:netAmount ?amount }

  FILTER NOT EXISTS {
    ?po ext:isDeliveredBy ?gr .
  }
}
ORDER BY DESC(?amount)
""",

"D4": """
SELECT ?invoice ?po ?invoiceVendor ?poVendor (MAX(?amt) AS ?amount)
WHERE {
  ?po a ext:PurchaseOrder ;
      ext:vendorId ?poVendor ;
      ext:isBilledBy ?invoice .

  ?invoice a ext:Invoice ;
           ext:vendorId ?invoiceVendor .

  OPTIONAL { ?invoice ext:netAmount ?amt }

  FILTER(?invoiceVendor != ?poVendor)
}
GROUP BY ?invoice ?po ?invoiceVendor ?poVendor
ORDER BY DESC(?amount)
""",

"D6": """
SELECT ?invoice ?po ?invoicedAmount ?poValue ?deviation
WHERE {
  ?po a ext:PurchaseOrder ;
      ext:netAmount ?poValue ;
      ext:isBilledBy ?invoice .

  ?invoice a ext:Invoice ;
           ext:netAmount ?invoicedAmount .

  BIND(?invoicedAmount - ?poValue AS ?deviation)

  FILTER(?invoicedAmount > ?poValue * 1.05)
}
ORDER BY DESC(?deviation)
""",

"S1": """
SELECT ?user ?po ?invoice ?poDate ?invDate
WHERE {
  ?poEvent a ext:CreatePurchaseOrder ;
           oced:observes ?po ;
           ext:userName ?user ;
           oced:observed_at ?poDate .

  ?invEvent a ext:RecordInvoice ;
            oced:observes ?invoice ;
            ext:userName ?user ;
            oced:observed_at ?invDate .

  ?po ext:isBilledBy ?invoice .
}
ORDER BY ?user ?poDate
""",

"S3": """
SELECT ?user ?invoice ?fi ?invDate ?clearDate
WHERE {
  ?invEvent a ext:RecordInvoice ;
            oced:observes ?invoice ;
            ext:userName ?user ;
            oced:observed_at ?invDate .

  ?invoice ext:generatesFinancialDoc ?fi .

  ?clearEvent a ext:ClearInvoice ;
              oced:observes ?fi ;
              ext:userName ?user ;
              oced:observed_at ?clearDate .
}
ORDER BY ?user ?invDate
""",

"S5": """
SELECT ?user ?po ?gr ?poDate ?grDate
WHERE {
  ?poEvent a ext:CreatePurchaseOrder ;
           oced:observes ?po ;
           ext:userName ?user ;
           oced:observed_at ?poDate .

  ?po ext:isDeliveredBy ?gr .

  ?grEvent a ext:RecordGoodsReceipt ;
           oced:observes ?gr ;
           ext:userName ?user ;
           oced:observed_at ?grDate .
}
ORDER BY ?user ?poDate
""",
}


SQL_QUERIES = {

"B1": """
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

"B2": """
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

"B3": """
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

"B4": """
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

"D4": """
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

"D6": """
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

"S1": """
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

"S3": """
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

"S5": """
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
# METRIC FUNCTIONS
# ================================================================

def strip_sparql_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        line = re.sub(r"#.*$", "", line)
        lines.append(line)
    return "\n".join(lines)


def strip_sql_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        line = re.sub(r"--.*$", "", line)
        lines.append(line)
    return "\n".join(lines)


def loc(text: str) -> int:
    return len([l for l in text.splitlines() if l.strip()])


def qlength_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def count_all_sparql_triples(text: str) -> int:
    # All triple patterns in the WHERE clause (internal helper only;
    # not reported directly).
    body = text
    body = re.sub(r"FILTER\s*\([^)]*\)", "", body)
    body = re.sub(r"BIND\s*\([^)]*\)", "", body)
    count = 0
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith(("SELECT", "WHERE", "ORDER", "GROUP",
                                   "FILTER", "OPTIONAL", "}", "{")):
            continue
        if "?" in s and (s.endswith(".") or s.endswith(";")):
            count += 1
    return count


def n_operator_sparql(text: str) -> int:
    # Join-equivalent operators: triples using an OCEDD object-to-object
    # relation property (Table 4.4). These are the only SPARQL
    # constructs that traverse from one business object to a related
    # one, making them the RDF analogue of an SQL JOIN.
    count = 0
    for prop in RELATION_PROPERTIES:
        count += len(re.findall(rf"\bext:{prop}\b", text))
    return count


def n_attribute_sparql(text: str) -> int:
    # Internal only: remaining triples (type assertions, attribute
    # access, event-observes-object patterns) not counted as operators.
    # Computed for internal consistency checks; not reported as an
    # output column (see thesis 4.6.3).
    total = count_all_sparql_triples(text)
    relation = n_operator_sparql(text)
    return max(0, total - relation)


def n_operator_sql(text: str) -> int:
    # SQL "number of operators": JOIN clauses, following [16].
    return len(re.findall(r"\bJOIN\b", text, flags=re.IGNORECASE))


def n_expression_sparql(text: str) -> int:
    return len(re.findall(r"FILTER\s+(NOT\s+)?EXISTS\s*\{", text)) \
        + len(re.findall(r"OPTIONAL\s*\{", text))


def n_expression_sql(text: str) -> int:
    depth = 0
    subq_count = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif text[i:i+6].upper() == "SELECT" and depth > 0:
            subq_count += 1
            i += 6
            continue
        i += 1
    return subq_count


def max_brace_depth(text: str) -> int:
    depth = 0
    max_depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch == "}":
            depth = max(0, depth - 1)
    return max_depth


def max_paren_depth(text: str) -> int:
    depth = 0
    max_depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch == ")":
            depth = max(0, depth - 1)
    return max_depth


def n_column_sparql(text: str) -> int:
    return len(set(re.findall(r"\?[A-Za-z_][A-Za-z0-9_]*", text)))


def n_column_sql(text: str) -> int:
    aliases = re.findall(
        r"(?:FROM|JOIN)\s+[A-Za-z_][A-Za-z0-9_]*\s+([A-Za-z_][A-Za-z0-9_]*)",
        text, flags=re.IGNORECASE
    )
    keywords = {"ON", "AS", "WHERE", "SELECT"}
    aliases = [a for a in aliases if a.upper() not in keywords]
    return len(set(a.lower() for a in aliases))


def n_table_sparql(text: str) -> int:
    return len(set(re.findall(r"ext:[A-Za-z_][A-Za-z0-9_]*", text)))


def n_table_sql(text: str) -> int:
    tables = re.findall(
        r"(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)",
        text, flags=re.IGNORECASE
    )
    return len(set(t.upper() for t in tables))


# ================================================================
# MAIN
# ================================================================

def main():
    rows = []
    for constraint in SPARQL_QUERIES:
        sp_raw = SPARQL_QUERIES[constraint]
        sql_raw = SQL_QUERIES[constraint]

        sp = strip_sparql_comments(sp_raw).strip()
        sql = strip_sql_comments(sql_raw).strip()

        # Internal consistency check: relation + attribute triples
        # should sum to the total triple count. Not part of the
        # reported output.
        assert n_operator_sparql(sp) + n_attribute_sparql(sp) == \
            count_all_sparql_triples(sp), \
            f"Triple count mismatch for {constraint}"

        rows.append({
            "constraint": constraint,
            # Query length (Vashistha & Jain: Qlength)
            "sparql_qlength_loc": loc(sp),
            "sql_qlength_loc": loc(sql),
            "sparql_qlength_chars": qlength_chars(sp),
            "sql_qlength_chars": qlength_chars(sql),
            # Number of operators (join-equivalents only; relation
            # triples for SPARQL, JOIN clauses for SQL)
            "sparql_n_operator": n_operator_sparql(sp),
            "sql_n_operator": n_operator_sql(sql),
            # Number of expression operators (Vashistha & Jain: Nexpression)
            "sparql_n_expression": n_expression_sparql(sp),
            "sql_n_expression": n_expression_sql(sql),
            "sparql_max_nesting_depth": max_brace_depth(sp),
            "sql_max_nesting_depth": max_paren_depth(sql),
            # Number of columns (Vashistha & Jain: Ncolumn)
            "sparql_n_column": n_column_sparql(sp),
            "sql_n_column": n_column_sql(sql),
            # Number of tables (Vashistha & Jain: Ntable)
            "sparql_n_table": n_table_sparql(sp),
            "sql_n_table": n_table_sql(sql),
        })

    df = pd.DataFrame(rows)

    numeric_cols = [c for c in df.columns if c != "constraint"]
    avg_row = {"constraint": "AVERAGE"}
    avg_row.update({c: round(df[c].mean(), 2) for c in numeric_cols})
    df = pd.concat([df, pd.DataFrame([avg_row])], ignore_index=True)

    print(df.to_string(index=False))

    OUTPUT_PATH.mkdir(exist_ok=True)
    csv_path = OUTPUT_PATH / "succinctness_metrics.csv"
    df.to_csv(csv_path, index=False)
    print(f"\nSaved to {csv_path}")

    md_path = OUTPUT_PATH / "succinctness_metrics.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(df.to_markdown(index=False))
    print(f"Saved to {md_path}")


if __name__ == "__main__":
    main()