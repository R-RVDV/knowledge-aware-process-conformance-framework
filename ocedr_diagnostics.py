"""

Diagnostic queries to validate the KG and detect unusual patterns.
Gives an overview of the KG structure and potential data problems.

"""

from rdflib import Graph, Namespace
from rdflib.plugins.sparql import prepareQuery

EXT  = Namespace("http://emixa.nl/p2p/domain#")
OCED = Namespace("https://w3id.org/ocedo/core#")
RES  = Namespace("http://emixa.nl/p2p/resource/")

KG_FILE = './ocedr_p2p_graph.ttl'

print("Loading KG...")
g = Graph()
g.parse(KG_FILE, format='turtle')
print(f"   {len(g)} triples loaded\n")

PREFIXES = """
    PREFIX ext:  <http://emixa.nl/p2p/domain#>
    PREFIX oced: <https://w3id.org/ocedo/core#>
    PREFIX res:  <http://emixa.nl/p2p/resource/>
    PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
"""

def run(title, query, limit=10):
    print(f"{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    results = list(g.query(PREFIXES + query))
    if not results:
        print("  ✅ No results (all in order)\n")
        return results
    for i, row in enumerate(results[:limit]):
        print("  " + "  |  ".join(str(v).split('/')[-1] for v in row))
    if len(results) > limit:
        print(f"  ... and {len(results) - limit} more")
    print(f"  → Total: {len(results)} results\n")
    return results


# ============================================================
# 1. OVERVIEW — how many instances per object type?
# ============================================================
run("1. Number of instances per object type", """
    SELECT ?type (COUNT(?obj) AS ?total)
    WHERE {
        ?obj rdf:type ?type .
        FILTER(STRSTARTS(STR(?type), "http://emixa.nl/p2p/domain#"))
    }
    GROUP BY ?type
    ORDER BY DESC(?total)
""", limit=20)

# ============================================================
# 2. OVERVIEW — how many relations per type?
# ============================================================
run("2. Number of relations per type", """
    SELECT ?pred (COUNT(*) AS ?total)
    WHERE {
        ?s ?pred ?o .
        FILTER(STRSTARTS(STR(?pred), "http://emixa.nl/p2p/domain#"))
    }
    GROUP BY ?pred
    ORDER BY DESC(?total)
""", limit=20)

# ============================================================
# 3. STRUCTURE CHECK — POs without GoodsReceipt
# ============================================================
run("3. POs without GoodsReceipt (possibly open orders)", """
    SELECT ?po
    WHERE {
        ?po rdf:type ext:PurchaseOrder .
        FILTER NOT EXISTS { ?po ext:isDeliveredBy ?gr }
    }
""")

# ============================================================
# 4. STRUCTURE CHECK — POs without Invoice
# ============================================================
run("4. POs without Invoice (delivered but not invoiced?)", """
    SELECT ?po
    WHERE {
        ?po rdf:type ext:PurchaseOrder .
        ?po ext:isDeliveredBy ?gr .
        FILTER NOT EXISTS { ?po ext:isBilledBy ?inv }
    }
""")

# ============================================================
# 5. STRUCTURE CHECK — Invoices without FinancialDocument
# ============================================================
run("5. Invoices without FinancialDocument (not paid?)", """
    SELECT ?inv
    WHERE {
        ?inv rdf:type ext:Invoice .
        FILTER NOT EXISTS { ?inv ext:generatesFinancialDoc ?fi }
    }
""")

# ============================================================
# 6. STRUCTURE CHECK — Invoices without GoodsReceipt match
#    (core of the Three-Way Match)
# ============================================================
run("6. Invoices without a matches relation to a GoodsReceipt", """
    SELECT ?inv
    WHERE {
        ?inv rdf:type ext:Invoice .
        FILTER NOT EXISTS { ?inv ext:matches ?gr }
    }
""")

# ============================================================
# 7. DATA QUALITY — POs without vendor (LIFNR)
# ============================================================
run("7. POs without vendorId (missing LIFNR)", """
    SELECT ?po
    WHERE {
        ?po rdf:type ext:PurchaseOrder .
        FILTER NOT EXISTS { ?po ext:vendorId ?v }
    }
""")

# ============================================================
# 8. DATA QUALITY — Events without timestamp
# ============================================================
run("8. Events without timestamp", """
    SELECT ?ev ?type
    WHERE {
        ?ev rdf:type ?type .
        FILTER(?type IN (
            ext:CreateRequisition,
            ext:CreatePurchaseOrder,
            ext:RecordGoodsReceipt,
            ext:RecordInvoice,
            ext:ClearInvoice
        ))
        FILTER NOT EXISTS { ?ev oced:observed_at ?t }
    }
""")

# ============================================================
# 9. DATA QUALITY — Events without userName
# ============================================================
run("9. Events without userName (SoD checks become difficult)", """
    SELECT ?ev ?type
    WHERE {
        ?ev rdf:type ?type .
        FILTER(?type IN (
            ext:CreatePurchaseOrder,
            ext:RecordGoodsReceipt,
            ext:RecordInvoice,
            ext:ClearInvoice
        ))
        FILTER NOT EXISTS { ?ev ext:userName ?u }
    }
""")

# ============================================================
# 10. COMPLETENESS CHECK — Complete P2P cycles
#     (all 5 object types present)
# ============================================================
run("10. Fully completed P2P cycles (Req→PO→GR→Inv→FinDoc)", """
    SELECT ?po ?req ?gr ?inv ?fi
    WHERE {
        ?req ext:isConvertedTo ?po .
        ?po  ext:isDeliveredBy ?gr .
        ?po  ext:isBilledBy    ?inv .
        ?inv ext:generatesFinancialDoc ?fi .
    }
""")

print("✅ Diagnostics completed.")