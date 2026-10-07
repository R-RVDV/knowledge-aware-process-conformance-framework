"""
Model-wide OCBC conformance check on the Knowledge Graph.

Tests the five ClaM relations (is the related object present?) and the five BCM constraints
C1-C5 (event order) against the OCEDR, aggregated per Purchase Order. The SPARQL queries are in
sparql_queries.py; this file runs them and aggregates the results.

Status: CONFORM, VIOLATION, MAVERICK (no requisition: not a deviation), N/A (the constraint does
not apply) or TIE (both events on the same day: dates have no time of day).
"""

import argparse
from collections import defaultdict
from pathlib import Path
from rdflib import Graph, Namespace

from sparql_queries import (
    Q_IS_CONVERTED_TO,
    Q_REQUISITIONS_WITHOUT_PO,
    make_downstream_query,
    Q_MATCHES,
    Q_PO_INVOICES,
    Q_TIME_REQ,
    Q_TIME_PO,
    Q_TIME_GR,
    Q_TIME_INV,
    Q_TIME_CLEAR,
)

# Default paths: see the layout in the module docstring
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "emixa_p2p_ocedd_v6_4.ttl"
DEFAULT_DATA_PATH = PROJECT_ROOT / "ocedr_p2p_graph.ttl"

EXT = Namespace("http://emixa.nl/p2p/domain#")
OCED = Namespace("https://w3id.org/ocedo/core#")

STATUS_CONFORM = "CONFORM"
STATUS_VIOLATION = "VIOLATION"
STATUS_MAVERICK = "MAVERICK"  # isConvertedTo only: the PO has no requisition (structural, not a deviation)
STATUS_NA = "N/A"  # BCM constraints only: the constraint does not apply to this PO
STATUS_TIE = "TIE"  # BCM constraints only: both events on the same day. Dates have no time of day,
                    # so the order cannot be established: neither CONFORM nor VIOLATION.

# Left out of the RESTRICTED verdict: they depend on the unreliable ClearInvoice event and
# FinancialDocument object. Their counts are still computed and printed.
UNRELIABLE_RELATIONS = {
    "invoiceChain",             # generatesFinancialDoc, rolled up to PO level
    "C4_Invoice_before_Clear",
    "C5_GR_before_Clear",
}


def load_graph(schema_path: str, data_path: str) -> Graph:
    g = Graph()
    g.parse(schema_path, format="turtle")
    g.parse(data_path, format="turtle")
    return g


# -------------------------------------------------------------------
# 1. isConvertedTo  (Requisition <-> PurchaseOrder), bidirectional OPTIONAL
# -------------------------------------------------------------------

def check_is_converted_to(g: Graph):
    """Returns a dict po_uri -> status (CONFORM / MAVERICK) and a separate list of Requisitions
    that never converted to a PO. Those requisitions have no PO, so they are reported separately
    and do not enter the per-PO verdict."""
    results = {}
    for row in g.query(Q_IS_CONVERTED_TO):
        results[row.po] = STATUS_CONFORM if row.req is not None else STATUS_MAVERICK

    orphan_requisitions = [row.req for row in g.query(Q_REQUISITIONS_WITHOUT_PO)]
    return results, orphan_requisitions


# -------------------------------------------------------------------
# 2-4. isDeliveredBy, isBilledBy, generatesFinancialDoc [unreliable]: does the source have at
# least one target? If not: VIOLATION. Only this lower bound is evaluated.
# -------------------------------------------------------------------

def check_downstream_relation(g: Graph, source_class, relation):
    """Generic check for isDeliveredBy / isBilledBy / generatesFinancialDoc."""
    q_counts = make_downstream_query(source_class, relation)
    counts = {row.source: int(row.n) for row in g.query(q_counts)}
    return {
        source: (STATUS_CONFORM if n > 0 else STATUS_VIOLATION)
        for source, n in counts.items()
    }


# -------------------------------------------------------------------
# 5. matches (Invoice <-> GoodsReceipt), derived via the shared PO. Same condition as
# isDeliveredBy, seen from the Invoice side: reported as a Three-Way Match view, not added to the
# per-PO deviation count (it would count the same missing goods receipt twice).
# -------------------------------------------------------------------

def check_matches(g: Graph):
    """Reported separately (see note above) - not folded into the
    per-PO conformance aggregation."""
    return {
        row.invoice: (STATUS_CONFORM if int(row.n) > 0 else STATUS_VIOLATION)
        for row in g.query(Q_MATCHES)
    }


# -------------------------------------------------------------------
# BCM layer (event-event), top half of Figure 2.1. Per PO, the earliest timestamps from the five
# Q_TIME_* queries are compared here:
#   C1 Unary-Response(CreateRequisition, CreatePurchaseOrder)
#   C2 Unary-Precedence(RecordGoodsReceipt, CreatePurchaseOrder)
#   C3 Precedence(RecordInvoice, RecordGoodsReceipt)
#   C4 Precedence(ClearInvoice, RecordInvoice)               [unreliable]
#   C5 Precedence(ClearInvoice, RecordGoodsReceipt)          [unreliable]
# Status: N/A if the triggering event does not occur (the requisition for C1, the later event for
# C2-C5; that absence is already flagged elsewhere); VIOLATION if it occurs without the other
# required event; otherwise the dates are compared (TIE on the same day).
# -------------------------------------------------------------------

def _run_min_time_query(g: Graph, query: str):
    """Executes a MIN(?t)-per-PO SPARQL query, returns dict po -> time (str)."""
    return {row.po: str(row.minT) for row in g.query(query) if row.minT is not None}


def get_event_times(g: Graph):
    """Runs the five SPARQL time-aggregation queries and returns five
    dicts (po -> earliest timestamp of that event type), one per BCM
    event type."""
    return {
        "req": _run_min_time_query(g, Q_TIME_REQ),
        "po": _run_min_time_query(g, Q_TIME_PO),
        "gr": _run_min_time_query(g, Q_TIME_GR),
        "inv": _run_min_time_query(g, Q_TIME_INV),
        "clear": _run_min_time_query(g, Q_TIME_CLEAR),
    }


def _order_status(t_early, t_late):
    """Compares two timestamps for a precedence check. Returns CONFORM,
    VIOLATION, or TIE (same calendar day - see STATUS_TIE)."""
    if t_early == t_late:
        return STATUS_TIE
    return STATUS_CONFORM if t_early < t_late else STATUS_VIOLATION


def check_bcm_constraints(g: Graph, all_pos):
    """Returns dict: po_uri -> {constraint_name: status}, with status in CONFORM / VIOLATION /
    TIE / N/A. Timestamps come from the five Q_TIME_* queries. C4 and C5 are unreliable: they are
    still computed, but left out of the RESTRICTED verdict."""
    times = get_event_times(g)
    report = {}
    for po in all_pos:
        t_req = times["req"].get(po)
        t_po = times["po"].get(po)
        t_gr = times["gr"].get(po)
        t_inv = times["inv"].get(po)
        t_clear = times["clear"].get(po)

        statuses = {}

        # C1: N/A without requisition (maverick PO, flagged by isConvertedTo).
        if t_req is None:
            statuses["C1_Req_before_PO"] = STATUS_NA
        elif t_po is None:
            statuses["C1_Req_before_PO"] = STATUS_VIOLATION
        else:
            statuses["C1_Req_before_PO"] = _order_status(t_req, t_po)

        # C2: PO -> GR. N/A if no GR yet (already flagged by isDeliveredBy).
        if t_gr is None:
            statuses["C2_PO_before_GR"] = STATUS_NA
        elif t_po is None:
            statuses["C2_PO_before_GR"] = STATUS_VIOLATION
        else:
            statuses["C2_PO_before_GR"] = _order_status(t_po, t_gr)

        # C3: GR -> Invoice. N/A if no Invoice yet (already flagged by isBilledBy).
        if t_inv is None:
            statuses["C3_GR_before_Invoice"] = STATUS_NA
        elif t_gr is None:
            statuses["C3_GR_before_Invoice"] = STATUS_VIOLATION
        else:
            statuses["C3_GR_before_Invoice"] = _order_status(t_gr, t_inv)

        # C4: Invoice -> Clear. [UNRELIABLE] N/A if never cleared (already flagged by invoiceChain).
        if t_clear is None:
            statuses["C4_Invoice_before_Clear"] = STATUS_NA
        elif t_inv is None:
            statuses["C4_Invoice_before_Clear"] = STATUS_VIOLATION
        else:
            statuses["C4_Invoice_before_Clear"] = _order_status(t_inv, t_clear)

        # C5: GR -> Clear (Three-Way Match order). [UNRELIABLE] N/A if never cleared.
        if t_clear is None:
            statuses["C5_GR_before_Clear"] = STATUS_NA
        elif t_gr is None:
            statuses["C5_GR_before_Clear"] = STATUS_VIOLATION
        else:
            statuses["C5_GR_before_Clear"] = _order_status(t_gr, t_clear)

        report[po] = statuses
    return report


# -------------------------------------------------------------------
# Aggregation per Purchase Order
# -------------------------------------------------------------------

def get_po_related_objects(g: Graph):
    """Map each PO to its downstream Invoice(s), for rolling up matches/
    generatesFinancialDoc results to the PO level."""
    mapping = defaultdict(list)
    for row in g.query(Q_PO_INVOICES):
        if row.invoice is not None:
            mapping[row.po].append(row.invoice)
    return mapping


def aggregate(g: Graph):
    conv_results, orphan_reqs = check_is_converted_to(g)
    deliv_results = check_downstream_relation(g, "PurchaseOrder", "isDeliveredBy")
    bill_results = check_downstream_relation(g, "PurchaseOrder", "isBilledBy")
    fin_results = check_downstream_relation(g, "Invoice", "generatesFinancialDoc")  # UNRELIABLE, see docstring
    match_results = check_matches(g)  # reported separately, see check_matches()
    po_invoices = get_po_related_objects(g)

    all_pos = set(conv_results) | set(deliv_results) | set(bill_results)

    # BCM layer (event-event timing), via SPARQL time-aggregation queries
    bcm_results = check_bcm_constraints(g, all_pos)

    report = {}
    for po in all_pos:
        statuses = {
            "isConvertedTo": conv_results.get(po, STATUS_VIOLATION),
            "isDeliveredBy": deliv_results.get(po, STATUS_VIOLATION),
            "isBilledBy": bill_results.get(po, STATUS_VIOLATION),
        }
        # Roll invoice-level generatesFinancialDoc up to PO level (worst status). Unreliable: left out
        # of the RESTRICTED verdict. matches is not added: it duplicates the isDeliveredBy gap.
        invoice_statuses = [
            fin_results.get(inv, STATUS_VIOLATION) for inv in po_invoices.get(po, [])
        ]
        if invoice_statuses:
            statuses["invoiceChain"] = (
                STATUS_VIOLATION if STATUS_VIOLATION in invoice_statuses else STATUS_CONFORM
            )
        else:
            statuses["invoiceChain"] = STATUS_CONFORM  # no invoice yet = handled by isBilledBy

        # Merge the BCM statuses (N/A does not affect the verdict)
        statuses.update(bcm_results.get(po, {}))

        report[po] = statuses

    return report, orphan_reqs, match_results, po_invoices


def _is_fully_conformant(statuses, restricted: bool):
    """A PO is fully conformant if no status is VIOLATION. With restricted=True the
    UNRELIABLE_RELATIONS are skipped (the primary definition); with restricted=False all count
    (the original ten-relation figure, for reference only)."""
    ok_statuses = (STATUS_CONFORM, STATUS_MAVERICK, STATUS_NA, STATUS_TIE)
    relevant = (
        (rel, s) for rel, s in statuses.items()
        if not (restricted and rel in UNRELIABLE_RELATIONS)
    )
    return all(s in ok_statuses for _, s in relevant)


def summarize(report, orphan_reqs, match_results):
    n_total = len(report)

    n_conform_restricted = sum(
        1 for statuses in report.values() if _is_fully_conformant(statuses, restricted=True)
    )
    n_conform_full = sum(
        1 for statuses in report.values() if _is_fully_conformant(statuses, restricted=False)
    )
    n_violation_restricted = n_total - n_conform_restricted
    n_violation_full = n_total - n_conform_full

    per_relation_violations = defaultdict(int)
    per_relation_ties = defaultdict(int)
    for statuses in report.values():
        for relation, status in statuses.items():
            if status == STATUS_VIOLATION:
                per_relation_violations[relation] += 1
            elif status == STATUS_TIE:
                per_relation_ties[relation] += 1

    n_maverick = sum(
        1 for statuses in report.values() if statuses["isConvertedTo"] == STATUS_MAVERICK
    )

    # Conditional metric: of the invoices that were billed, what share completes the chain
    # correctly? (separates "never reached this stage" from "reached it and failed")
    n_invoices = len(match_results)
    n_matches_violation = sum(1 for s in match_results.values() if s == STATUS_VIOLATION)

    print(f"Total Purchase Orders evaluated: {n_total}")
    print()
    print("Conformance under two definitions (thesis Section 6.4):")
    print(f"  RESTRICTED (7 reliable relations, excludes generatesFinancialDoc/C4/C5):")
    print(f"    Fully conformant : {n_conform_restricted} ({n_conform_restricted/n_total:.1%})")
    print(f"    Deviating        : {n_violation_restricted} ({n_violation_restricted/n_total:.1%})")
    print(f"  FULL (all 10 relations/constraints, original definition - reference only):")
    print(f"    Fully conformant : {n_conform_full} ({n_conform_full/n_total:.1%})")
    print(f"    Deviating        : {n_violation_full} ({n_violation_full/n_total:.1%})")
    print(f"  of which maverick procurement (no PR, not a deviation): {n_maverick}")
    print()
    print("Deviations by relation (share of all POs; matches excluded - see below):")
    print("  (generatesFinancialDoc/invoiceChain, C4, C5 marked UNRELIABLE - see thesis 6.4)")
    for relation, count in sorted(per_relation_violations.items(), key=lambda x: -x[1]):
        flag = "  [UNRELIABLE]" if relation in UNRELIABLE_RELATIONS else ""
        print(f"  {relation:<24s}: {count} ({count/n_total:.1%}){flag}")
    if per_relation_ties:
        print()
        print("Same-day ties (date-only granularity, order undecidable - not counted as violation):")
        for relation, count in sorted(per_relation_ties.items(), key=lambda x: -x[1]):
            flag = "  [UNRELIABLE]" if relation in UNRELIABLE_RELATIONS else ""
            print(f"  {relation:<24s}: {count} ({count/n_total:.1%}){flag}")
    print()
    print(f"Requisitions that never converted to a PO: {len(orphan_reqs)}")
    print()
    print("Three-Way Match view (matches relation, reported separately - ")
    print("identical underlying condition to isDeliveredBy/potential_c5, not summed above):")
    if n_invoices:
        print(f"  Invoices without a matching GoodsReceipt: {n_matches_violation} / {n_invoices} "
              f"({n_matches_violation/n_invoices:.1%})")
        n_matches_conform = n_invoices - n_matches_violation
        print(f"  Conditional on being billed, chain completed correctly: "
              f"{n_matches_conform}/{n_invoices} ({n_matches_conform/n_invoices:.1%})")
    else:
        print("  No invoices found in the graph.")


def summarize_subset(report, po_invoices):
    """Conformance for the POs with at least one Invoice (those that went beyond PO creation).
    Reports the RESTRICTED and FULL definitions, as summarize() does."""
    billed_pos = {po for po, invs in po_invoices.items() if invs}
    subset = {po: statuses for po, statuses in report.items() if po in billed_pos}

    n_total = len(subset)
    if n_total == 0:
        print("No Purchase Orders with an Invoice found - subset is empty.")
        return

    n_conform_restricted = sum(
        1 for statuses in subset.values() if _is_fully_conformant(statuses, restricted=True)
    )
    n_conform_full = sum(
        1 for statuses in subset.values() if _is_fully_conformant(statuses, restricted=False)
    )
    n_violation_restricted = n_total - n_conform_restricted
    n_violation_full = n_total - n_conform_full

    per_relation_violations = defaultdict(int)
    per_relation_ties = defaultdict(int)
    for statuses in subset.values():
        for relation, status in statuses.items():
            if status == STATUS_VIOLATION:
                per_relation_violations[relation] += 1
            elif status == STATUS_TIE:
                per_relation_ties[relation] += 1

    print(f"Total Purchase Orders with >=1 Invoice: {n_total} (of {len(report)} total)")
    print()
    print("Conformance under two definitions (thesis Section 6.4):")
    print(f"  RESTRICTED (7 reliable relations, excludes generatesFinancialDoc/C4/C5):")
    print(f"    Fully conformant : {n_conform_restricted} ({n_conform_restricted/n_total:.1%})")
    print(f"    Deviating        : {n_violation_restricted} ({n_violation_restricted/n_total:.1%})")
    print(f"  FULL (all 10 relations/constraints, original definition - reference only):")
    print(f"    Fully conformant : {n_conform_full} ({n_conform_full/n_total:.1%})")
    print(f"    Deviating        : {n_violation_full} ({n_violation_full/n_total:.1%})")
    print()
    print("Deviations by relation, within this subset:")
    print("  (generatesFinancialDoc/invoiceChain, C4, C5 marked UNRELIABLE - see thesis 6.4)")
    for relation, count in sorted(per_relation_violations.items(), key=lambda x: -x[1]):
        flag = "  [UNRELIABLE]" if relation in UNRELIABLE_RELATIONS else ""
        print(f"  {relation:<24s}: {count} ({count/n_total:.1%}){flag}")
    if per_relation_ties:
        print()
        print("Same-day ties within this subset (not counted as violation):")
        for relation, count in sorted(per_relation_ties.items(), key=lambda x: -x[1]):
            flag = "  [UNRELIABLE]" if relation in UNRELIABLE_RELATIONS else ""
            print(f"  {relation:<24s}: {count} ({count/n_total:.1%}){flag}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--schema", default=str(DEFAULT_SCHEMA_PATH),
        help=f"Path to OCEDD schema ttl (default: {DEFAULT_SCHEMA_PATH})")
    parser.add_argument(
        "--data", default=str(DEFAULT_DATA_PATH),
        help=f"Path to OCEDR data graph ttl (default: {DEFAULT_DATA_PATH})")
    args = parser.parse_args()

    for label, path in [("schema", args.schema), ("data", args.data)]:
        if not Path(path).is_file():
            raise FileNotFoundError(
                f"Could not find the {label} file at: {path}\n"
                f"Pass an explicit path with --{label} if your project layout differs."
            )

    g = load_graph(args.schema, args.data)
    report, orphan_reqs, match_results, po_invoices = aggregate(g)
    summarize(report, orphan_reqs, match_results)
    print()
    print("=" * 70)
    print("SUBSET ANALYSIS: Purchase Orders that reached invoicing")
    print("=" * 70)
    summarize_subset(report, po_invoices)