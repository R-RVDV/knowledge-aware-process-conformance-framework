"""
Finds, per constraint, 4+ injectable process instances based
on the OCEDR (no baseline violations for that constraint).

Output: injection_config.json with the candidates per constraint.
Then fill in exactly 4 instances per constraint under 'selected'.

"""

import json
from pathlib import Path
from rdflib import Graph, Namespace
from rdflib.namespace import XSD

# ── Namespaces ────────────────────────────────────────────────────
EXT  = Namespace("http://emixa.nl/p2p/domain#")
OCED = Namespace("https://w3id.org/ocedo/core#")

# ── Load the original OCEDR ───────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent

g = Graph()
g.parse(str(REPO_ROOT / "emixa_p2p_ocedd.ttl"), format="turtle")
g.parse(str(REPO_ROOT / "ocedr_p2p_graph.ttl"),      format="turtle")
print(f"Loaded: {len(g)} triples\n")

candidates = {}

# ══════════════════════════════════════════════════════════════════
# B1 — GR requires PO
# Injection: remove ext:isDeliveredBy between PO and GR
# Candidate: GR with PO link AND ext:matches link (in scope)
# ══════════════════════════════════════════════════════════════════
rows = list(g.query("""
PREFIX ext:  <http://emixa.nl/p2p/domain#>
SELECT DISTINCT ?po ?gr WHERE {
  ?po  a ext:PurchaseOrder ;
       ext:isDeliveredBy ?gr .
  ?inv ext:matches ?gr .
}
LIMIT 20
"""))
candidates["B1"] = {
    "description": "Remove ext:isDeliveredBy triple between PO and GR",
    "injection_type": "remove_triple",
    "candidates": [{"po": str(r.po), "gr": str(r.gr)} for r in rows],
    "selected": []
}
print(f"B1 candidates: {len(rows)}")

# ══════════════════════════════════════════════════════════════════
# B2 — Invoice requires GR
# Injection: remove all ext:isDeliveredBy from PO
# Candidate: PO with both GR and Invoice (no existing B2 violation)
# ══════════════════════════════════════════════════════════════════
rows = list(g.query("""
PREFIX ext:  <http://emixa.nl/p2p/domain#>
PREFIX oced: <https://w3id.org/ocedo/core#>
SELECT DISTINCT ?po ?invoice ?gr WHERE {
  ?po a ext:PurchaseOrder ;
      ext:isDeliveredBy ?gr ;
      ext:isBilledBy ?invoice .
  ?invEv a ext:RecordInvoice ;
         oced:observes ?invoice .
}
LIMIT 20
"""))
candidates["B2"] = {
    "description": "Remove all ext:isDeliveredBy triples from the PO",
    "injection_type": "remove_all_isDeliveredBy",
    "candidates": [{"po": str(r.po), "invoice": str(r.invoice), "gr": str(r.gr)} for r in rows],
    "selected": []
}
print(f"B2 candidates: {len(rows)}")

# ══════════════════════════════════════════════════════════════════
# B3 — Payment requires invoice
# Injection: remove the RecordInvoice event (all triples)
# Candidate: Invoice with RecordInvoice event and generatesFinancialDoc link
# ══════════════════════════════════════════════════════════════════
rows = list(g.query("""
PREFIX ext:  <http://emixa.nl/p2p/domain#>
PREFIX oced: <https://w3id.org/ocedo/core#>
SELECT DISTINCT ?invoice ?fi ?invEvent WHERE {
  ?invoice  a ext:Invoice ;
            ext:generatesFinancialDoc ?fi .
  ?invEvent a ext:RecordInvoice ;
            oced:observes ?invoice .
  ?clrEvent a ext:ClearInvoice ;
            oced:observes ?fi .
}
LIMIT 20
"""))
candidates["B3"] = {
    "description": "Remove all triples of the RecordInvoice event",
    "injection_type": "remove_event",
    "candidates": [{"invoice": str(r.invoice), "fi": str(r.fi),
                    "inv_event": str(r.invEvent)} for r in rows],
    "selected": []
}
print(f"B3 candidates: {len(rows)}")

# ══════════════════════════════════════════════════════════════════
# B4 — Payment requires GR
# Injection: remove all ext:isDeliveredBy from PO
# Candidate: PO with GR + cleared Invoice (no existing B4 violation)
# Choose different POs than B2!
# ══════════════════════════════════════════════════════════════════
rows = list(g.query("""
PREFIX ext:  <http://emixa.nl/p2p/domain#>
PREFIX oced: <https://w3id.org/ocedo/core#>
SELECT DISTINCT ?po ?gr ?invoice ?fi WHERE {
  ?po a ext:PurchaseOrder ;
      ext:isDeliveredBy ?gr ;
      ext:isBilledBy ?invoice .
  ?invoice ext:generatesFinancialDoc ?fi .
  ?clrEvent a ext:ClearInvoice ;
            oced:observes ?fi .
}
LIMIT 20
"""))
candidates["B4"] = {
    "description": "Remove all ext:isDeliveredBy triples from the PO (choose different POs than B2!)",
    "injection_type": "remove_all_isDeliveredBy",
    "candidates": [{"po": str(r.po), "gr": str(r.gr), "invoice": str(r.invoice)} for r in rows],
    "selected": []
}
print(f"B4 candidates: {len(rows)}")

# ══════════════════════════════════════════════════════════════════
# D4 — Vendor invoice = vendor PO
# Injection: change ext:vendorId on Invoice to 'VENDOR_INJECTED'
# Candidate: Invoice-PO pair where vendors match
# ══════════════════════════════════════════════════════════════════
rows = list(g.query("""
PREFIX ext: <http://emixa.nl/p2p/domain#>
SELECT DISTINCT ?po ?invoice ?poVendor ?invVendor WHERE {
  ?po a ext:PurchaseOrder ;
      ext:vendorId ?poVendor ;
      ext:isBilledBy ?invoice .
  ?invoice a ext:Invoice ;
           ext:vendorId ?invVendor .
  FILTER(?poVendor = ?invVendor)
}
LIMIT 20
"""))
candidates["D4"] = {
    "description": "Change ext:vendorId on Invoice to 'VENDOR_INJECTED'",
    "injection_type": "change_vendor_id",
    "candidates": [{"po": str(r.po), "invoice": str(r.invoice),
                    "po_vendor": str(r.poVendor), "inv_vendor": str(r.invVendor)} for r in rows],
    "selected": []
}
print(f"D4 candidates: {len(rows)}")

# ══════════════════════════════════════════════════════════════════
# D6 — Invoice amount ≤ PO value + tolerance
# Injection: raise ext:netAmount on Invoice to poValue * 2.0
# Candidate: Invoice-PO pair without existing D6 violation (ratio ≤ 1.05)
# ══════════════════════════════════════════════════════════════════
rows = list(g.query("""
PREFIX ext: <http://emixa.nl/p2p/domain#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?po ?invoice ?poValue ?invAmount WHERE {
  ?po a ext:PurchaseOrder ;
      ext:netAmount ?poValue ;
      ext:isBilledBy ?invoice .
  ?invoice a ext:Invoice ;
           ext:netAmount ?invAmount .
  FILTER(xsd:decimal(?invAmount) <= xsd:decimal(?poValue) * 1.05)
  FILTER(xsd:decimal(?poValue) > 0)
}
LIMIT 20
"""))
candidates["D6"] = {
    "description": "Set ext:netAmount on Invoice to poValue * 2.0 (well above tolerance)",
    "injection_type": "change_net_amount",
    "candidates": [{"po": str(r.po), "invoice": str(r.invoice),
                    "po_value": str(r.poValue), "inv_amount": str(r.invAmount)} for r in rows],
    "selected": []
}
print(f"D6 candidates: {len(rows)}")

# ══════════════════════════════════════════════════════════════════
# S1 — PO creator ≠ invoice enterer
# Injection: set userName of RecordInvoice event = userName of PO creator
# Candidate: PO-Invoice pair where usernames are NOT equal
# ══════════════════════════════════════════════════════════════════
rows = list(g.query("""
PREFIX ext:  <http://emixa.nl/p2p/domain#>
PREFIX oced: <https://w3id.org/ocedo/core#>
SELECT DISTINCT ?po ?invoice ?poEvent ?invEvent ?poUser ?invUser WHERE {
  ?poEvent  a ext:CreatePurchaseOrder ;
            oced:observes ?po ;
            ext:userName ?poUser .
  ?invEvent a ext:RecordInvoice ;
            oced:observes ?invoice ;
            ext:userName ?invUser .
  ?po ext:isBilledBy ?invoice .
  FILTER(?poUser != ?invUser)
}
LIMIT 20
"""))
candidates["S1"] = {
    "description": "Set ext:userName of RecordInvoice event equal to poUser",
    "injection_type": "change_username",
    "target_event_key": "inv_event",
    "new_user_key": "po_user",
    "candidates": [{"po": str(r.po), "invoice": str(r.invoice),
                    "po_event": str(r.poEvent), "inv_event": str(r.invEvent),
                    "po_user": str(r.poUser), "inv_user": str(r.invUser)} for r in rows],
    "selected": []
}
print(f"S1 candidates: {len(rows)}")

# ══════════════════════════════════════════════════════════════════
# S3 — Invoice enterer ≠ payment poster
# Injection: set userName of RecordInvoice event to a different user
#           (not the payment poster) so that a NEW violation arises.
#
# Reason for the reversed approach:
#   The baseline already shows 53 S3 violations because nearly all
#   Invoice-FI pairs have the same userName. There are hardly any pairs
#   without an existing violation to inject on. Solution: look for pairs
#   where users ARE equal and change the inv_user to a
#   unique injection value 'User_INJECTED_S3', so that it becomes a
#   new detectable violation on top of the baseline.
# ══════════════════════════════════════════════════════════════════
rows = list(g.query("""
PREFIX ext:  <http://emixa.nl/p2p/domain#>
PREFIX oced: <https://w3id.org/ocedo/core#>
SELECT DISTINCT ?invoice ?fi ?invEvent ?clrEvent ?invUser ?clrUser WHERE {
  ?invEvent a ext:RecordInvoice ;
            oced:observes ?invoice ;
            ext:userName ?invUser .
  ?invoice ext:generatesFinancialDoc ?fi .
  ?clrEvent a ext:ClearInvoice ;
            oced:observes ?fi ;
            ext:userName ?clrUser .
  FILTER(?invUser = ?clrUser)
}
LIMIT 20
"""))
candidates["S3"] = {
    "description": (
        "Set ext:userName of RecordInvoice event to 'User_INJECTED_S3'. "
        "This creates a new violation on top of the existing baseline: "
        "the ClearInvoice user remains unchanged, but the RecordInvoice user "
        "now differs — so that S3 detects the injection as a new pair."
    ),
    "injection_type": "change_username_to_injected",
    "target_event_key": "inv_event",
    "new_user": "User_INJECTED_S3",
    "candidates": [{"invoice": str(r.invoice), "fi": str(r.fi),
                    "inv_event": str(r.invEvent), "clr_event": str(r.clrEvent),
                    "inv_user": str(r.invUser), "clr_user": str(r.clrUser)} for r in rows],
    "selected": []
}
print(f"S3 candidates: {len(rows)}")

# ══════════════════════════════════════════════════════════════════
# S5 — GR poster ≠ PO creator
# Injection: set userName of RecordGoodsReceipt event = userName of PO creator
# Candidate: PO-GR pair where usernames are NOT equal
# ══════════════════════════════════════════════════════════════════
rows = list(g.query("""
PREFIX ext:  <http://emixa.nl/p2p/domain#>
PREFIX oced: <https://w3id.org/ocedo/core#>
SELECT DISTINCT ?po ?gr ?poEvent ?grEvent ?poUser ?grUser WHERE {
  ?poEvent a ext:CreatePurchaseOrder ;
           oced:observes ?po ;
           ext:userName ?poUser .
  ?po ext:isDeliveredBy ?gr .
  ?grEvent a ext:RecordGoodsReceipt ;
           oced:observes ?gr ;
           ext:userName ?grUser .
  FILTER(?poUser != ?grUser)
}
LIMIT 20
"""))
candidates["S5"] = {
    "description": "Set ext:userName of RecordGoodsReceipt event equal to poUser",
    "injection_type": "change_username",
    "target_event_key": "gr_event",
    "new_user_key": "po_user",
    "candidates": [{"po": str(r.po), "gr": str(r.gr),
                    "po_event": str(r.poEvent), "gr_event": str(r.grEvent),
                    "po_user": str(r.poUser), "gr_user": str(r.grUser)} for r in rows],
    "selected": []
}
print(f"S5 candidates: {len(rows)}")

# ── Save candidate list ────────────────────────────────────────
config_path = Path(__file__).parent / "injection_config.json"
with open(config_path, "w", encoding="utf-8") as f:
    json.dump(candidates, f, indent=2, ensure_ascii=False)

print(f"\n✅ injection_config.json created in {config_path}")
print("Fill in exactly 4 instances per constraint under 'selected'.")
print("Then use inject.py to inject the violations.")