"""
Set of SPARQL queries for model wide conformance.
  1. Object-to-object relations (OCBC ClaM, lower half of Figure 2.1): isConvertedTo,
     isDeliveredBy, isBilledBy, matches, generatesFinancialDoc. Per source object, each query
     counts the related target objects.
  2. Event-event constraints (OCBC BCM, upper half of Figure 2.1):
       C1 Unary-Response(CreateRequisition, CreatePurchaseOrder)
       C2 Unary-Precedence(RecordGoodsReceipt, CreatePurchaseOrder)
       C3 Precedence(RecordInvoice, RecordGoodsReceipt)
       C4 Precedence(ClearInvoice, RecordInvoice)
       C5 Precedence(ClearInvoice, RecordGoodsReceipt)   (Three-Way Match order)
     Each constraint is evaluated from one MIN(?t) query per event type (Q_TIME_*), giving the
     earliest timestamp per Purchase Order. model_wide_conformance.py compares these pairwise
     to derive CONFORM / VIOLATION / TIE / N/A.

"""

# =====================================================================
# 1. Object-to-object relations
# =====================================================================

# ---------------------------------------------------------------------
# isConvertedTo (Requisition <-> PurchaseOrder), checked in both directions because
# neither side is mandatory (cardinality 0..1 : 0..1).
# ---------------------------------------------------------------------
Q_IS_CONVERTED_TO = """
PREFIX ext: <http://emixa.nl/p2p/domain#>
SELECT ?po ?req WHERE {
    ?po a ext:PurchaseOrder .
    OPTIONAL { ?req ext:isConvertedTo ?po }
}
"""

# The other direction: requisitions that never became a PO
Q_REQUISITIONS_WITHOUT_PO = """
PREFIX ext: <http://emixa.nl/p2p/domain#>
SELECT ?req WHERE {
    ?req a ext:PurchaseRequisition .
    FILTER NOT EXISTS { ?req ext:isConvertedTo ?po }
}
"""


# ---------------------------------------------------------------------
# isDeliveredBy (PurchaseOrder -> GoodsReceipt, 1:0..*), isBilledBy (PurchaseOrder -> Invoice,
# 1:0..*) and generatesFinancialDoc (Invoice -> FinancialDocument, 1:0..1).
# The same query shape serves all three, so it is a template: only the source class and the
# relation name differ.
# ---------------------------------------------------------------------
def make_downstream_query(source_class: str, relation: str, target_var: str = "target") -> str:
    """Returns a SPARQL query counting, per source instance, how many
    `relation`-linked target instances it has (0 if none)."""
    return f"""
    PREFIX ext: <http://emixa.nl/p2p/domain#>
    SELECT ?source (COUNT(?{target_var}) AS ?n) WHERE {{
        ?source a ext:{source_class} .
        OPTIONAL {{ ?source ext:{relation} ?{target_var} }}
    }} GROUP BY ?source
    """


# ---------------------------------------------------------------------
# matches (Invoice <-> GoodsReceipt), derived via the shared PurchaseOrder: the extraction has no
# direct key between the two. Reported as a separate Three-Way Match view and not summed into
# the per-PO deviation count (see model_wide_conformance.py).
# ---------------------------------------------------------------------
Q_MATCHES = """
PREFIX ext: <http://emixa.nl/p2p/domain#>
SELECT ?invoice (COUNT(?gr) AS ?n) WHERE {
    ?invoice a ext:Invoice ;
             ^ext:isBilledBy ?po .
    OPTIONAL { ?po ext:isDeliveredBy ?gr }
} GROUP BY ?invoice
"""


# Auxiliary: PO -> Invoice mapping, to roll invoice-level results up to the PO level.
Q_PO_INVOICES = """
PREFIX ext: <http://emixa.nl/p2p/domain#>
SELECT ?po ?invoice WHERE {
    ?po a ext:PurchaseOrder .
    OPTIONAL { ?po ext:isBilledBy ?invoice }
}
"""


# =====================================================================
# 2. Event-event (BCM) constraints
#
# Each query returns, per PurchaseOrder, the earliest observed_at timestamp of one event type
# among the PO and its related objects (goods receipts, invoices, financial documents,
# requisitions). There is one query per event type instead of one query with a variable event
# type, because rdflib has no query optimizer and a UNION over a variable event type forces a
# nested-loop join that is far too slow.
# =====================================================================

# CreateRequisition, per converted PO (used in C1).
Q_TIME_REQ = """
PREFIX ext: <http://emixa.nl/p2p/domain#>
PREFIX oced: <https://w3id.org/ocedo/core#>
SELECT ?po (MIN(?t) AS ?minT) WHERE {
    ?req a ext:PurchaseRequisition ; ext:isConvertedTo ?po .
    ?ev a ext:CreateRequisition ; oced:observes ?req ; oced:observed_at ?t .
} GROUP BY ?po
"""

# CreatePurchaseOrder, per PO (used in C1, C2).
Q_TIME_PO = """
PREFIX ext: <http://emixa.nl/p2p/domain#>
PREFIX oced: <https://w3id.org/ocedo/core#>
SELECT ?po (MIN(?t) AS ?minT) WHERE {
    ?po a ext:PurchaseOrder .
    ?ev a ext:CreatePurchaseOrder ; oced:observes ?po ; oced:observed_at ?t .
} GROUP BY ?po
"""

# RecordGoodsReceipt, per PO (used in C2, C3, C5).
Q_TIME_GR = """
PREFIX ext: <http://emixa.nl/p2p/domain#>
PREFIX oced: <https://w3id.org/ocedo/core#>
SELECT ?po (MIN(?t) AS ?minT) WHERE {
    ?po a ext:PurchaseOrder ; ext:isDeliveredBy ?gr .
    ?ev a ext:RecordGoodsReceipt ; oced:observes ?gr ; oced:observed_at ?t .
} GROUP BY ?po
"""

# RecordInvoice, per PO (used in C3, C4).
Q_TIME_INV = """
PREFIX ext: <http://emixa.nl/p2p/domain#>
PREFIX oced: <https://w3id.org/ocedo/core#>
SELECT ?po (MIN(?t) AS ?minT) WHERE {
    ?po a ext:PurchaseOrder ; ext:isBilledBy ?inv .
    ?ev a ext:RecordInvoice ; oced:observes ?inv ; oced:observed_at ?t .
} GROUP BY ?po
"""

# ClearInvoice, per PO (used in C4, C5).
Q_TIME_CLEAR = """
PREFIX ext: <http://emixa.nl/p2p/domain#>
PREFIX oced: <https://w3id.org/ocedo/core#>
SELECT ?po (MIN(?t) AS ?minT) WHERE {
    ?po a ext:PurchaseOrder ; ext:isBilledBy ?inv .
    ?inv ext:generatesFinancialDoc ?fd .
    ?ev a ext:ClearInvoice ; oced:observes ?fd ; oced:observed_at ?t .
} GROUP BY ?po
"""