"""
Creates a separate injected KG per constraint for isolated
precision/recall measurement. For each constraint a fresh copy of the
original OCEDR is used so that cross-contamination between constraints
is prevented.

Output per constraint:
    injected/ocedr_injected_B1.ttl
    injected/ocedr_injected_B2.ttl
    ... etc.

Combined injection (all 36 at once):
    injected/ocedr_injected_ALL.ttl

injection_log.json contains all executed injections per constraint.

"""

import json
import shutil
from pathlib import Path
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import XSD

# ── Namespaces ────────────────────────────────────────────────────
EXT  = Namespace("http://emixa.nl/p2p/domain#")
OCED = Namespace("https://w3id.org/ocedo/core#")

BASE      = Path(__file__).parent
REPO_ROOT = BASE.parent
SCHEMA    = str(REPO_ROOT / "emixa_p2p_ocedd_v6_4.ttl")
ORIGINAL  = str(REPO_ROOT / "ocedr_p2p_graph.ttl")
OUT_DIR   = BASE / "injected"
OUT_DIR.mkdir(exist_ok=True)

CONFIG_FILE = str(BASE / "injection_config.json")
LOG_FILE    = str(BASE / "injection_log.json")

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)

master_log = {}


def load_fresh_graph():
    """Load schema + original OCEDR as a fresh graph."""
    g = Graph()
    g.parse(SCHEMA,   format="turtle")
    g.parse(ORIGINAL, format="turtle")
    return g


def check_selected(constraint):
    selected = config[constraint]["selected"]
    if len(selected) != 4:
        raise ValueError(
            f"[{constraint}] Expected 4 selected instances, "
            f"but found: {len(selected)}."
        )
    return selected


def apply_b1(g, log):
    print("── B1: GR requires PO ─────────────────────────────────")
    for item in check_selected("B1"):
        po = URIRef(item["po"])
        gr = URIRef(item["gr"])
        triple = (po, EXT.isDeliveredBy, gr)
        if triple in g:
            g.remove(triple)
            print(f"  ✅ isDeliveredBy removed: {item['po'].split('/')[-1]}")
            log.append({"constraint": "B1", "action": "remove_triple",
                        "po": item["po"], "gr": item["gr"]})
        else:
            print(f"  ⚠️  Triple not found: {item['po'].split('/')[-1]}")


def apply_b2(g, log):
    print("── B2: Invoice requires GR ────────────────────────────")
    for item in check_selected("B2"):
        po = URIRef(item["po"])
        triples = list(g.triples((po, EXT.isDeliveredBy, None)))
        for t in triples:
            g.remove(t)
        print(f"  ✅ {len(triples)}x isDeliveredBy removed: {item['po'].split('/')[-1]}")
        log.append({"constraint": "B2", "action": "remove_all_isDeliveredBy",
                    "po": item["po"], "invoice": item["invoice"],
                    "removed_count": len(triples)})


def apply_b3(g, log):
    print("── B3: Payment requires invoice ──────────────────────")
    for item in check_selected("B3"):
        ev = URIRef(item["inv_event"])
        out = list(g.triples((ev, None, None)))
        inc = list(g.triples((None, None, ev)))
        for t in out + inc:
            g.remove(t)
        n = len(out) + len(inc)
        print(f"  ✅ RecordInvoice event removed: {item['inv_event'].split('/')[-1]} ({n} triples)")
        log.append({"constraint": "B3", "action": "remove_event",
                    "inv_event": item["inv_event"], "invoice": item["invoice"],
                    "triples_removed": n})


def apply_b4(g, log):
    print("── B4: Payment requires GR ───────────────────────────")
    for item in check_selected("B4"):
        po = URIRef(item["po"])
        triples = list(g.triples((po, EXT.isDeliveredBy, None)))
        for t in triples:
            g.remove(t)
        print(f"  ✅ {len(triples)}x isDeliveredBy removed: {item['po'].split('/')[-1]}")
        log.append({"constraint": "B4", "action": "remove_all_isDeliveredBy",
                    "po": item["po"], "invoice": item["invoice"],
                    "removed_count": len(triples)})


def apply_d4(g, log):
    print("── D4: Vendor mismatch ───────────────────────────────")
    for item in check_selected("D4"):
        inv = URIRef(item["invoice"])
        old = list(g.objects(inv, EXT.vendorId))
        g.remove((inv, EXT.vendorId, None))
        g.add((inv, EXT.vendorId, Literal("VENDOR_INJECTED", datatype=XSD.string)))
        print(f"  ✅ vendorId → VENDOR_INJECTED: {item['invoice'].split('/')[-1]}")
        log.append({"constraint": "D4", "action": "change_vendor_id",
                    "invoice": item["invoice"], "po": item["po"],
                    "old_vendor": [str(v) for v in old],
                    "new_vendor": "VENDOR_INJECTED"})


def apply_d6(g, log):
    print("── D6: Amount tolerance ─────────────────────────────")
    for item in check_selected("D6"):
        inv = URIRef(item["invoice"])
        po_value   = float(item["po_value"])
        new_amount = round(po_value * 2.0, 2)
        old = list(g.objects(inv, EXT.netAmount))
        g.remove((inv, EXT.netAmount, None))
        g.add((inv, EXT.netAmount, Literal(new_amount, datatype=XSD.decimal)))
        print(f"  ✅ netAmount → {new_amount} (ratio 2.0): {item['invoice'].split('/')[-1]}")
        log.append({"constraint": "D6", "action": "change_net_amount",
                    "invoice": item["invoice"], "po": item["po"],
                    "po_value": po_value, "new_amount": new_amount})


def apply_s1(g, log):
    print("── S1: PO creator ≠ invoice enterer ─────────────────")
    for item in check_selected("S1"):
        ev  = URIRef(item["inv_event"])
        old = list(g.objects(ev, EXT.userName))
        g.remove((ev, EXT.userName, None))
        g.add((ev, EXT.userName, Literal(item["po_user"], datatype=XSD.string)))
        print(f"  ✅ userName RecordInvoice → {item['po_user']}: {item['inv_event'].split('/')[-1]}")
        log.append({"constraint": "S1", "action": "change_username",
                    "event": item["inv_event"], "po": item["po"],
                    "old_user": [str(v) for v in old],
                    "new_user": item["po_user"]})


def apply_s3(g, log):
    print("── S3: Invoice enterer ≠ payment poster ─────────────")
    for item in check_selected("S3"):
        # Inject a NEW pair by:
        # 1. changing inv_user to a unique value
        # 2. changing clr_user to that same unique value
        # Result: new pair with inv_user = clr_user = User_INJ_S3_[n]
        new_user = f"User_INJ_S3_{item['invoice'].split('5105600')[1]}"
        inv_ev  = URIRef(item["inv_event"])
        clr_ev  = URIRef(item["clr_event"])
        g.remove((inv_ev, EXT.userName, None))
        g.add((inv_ev, EXT.userName, Literal(new_user, datatype=XSD.string)))
        g.remove((clr_ev, EXT.userName, None))
        g.add((clr_ev, EXT.userName, Literal(new_user, datatype=XSD.string)))
        print(f"  ✅ inv + clr userName → {new_user}: {item['invoice'].split('/')[-1]}")
        log.append({"constraint": "S3", "action": "sync_inv_clr_username",
                    "inv_event": item["inv_event"], "clr_event": item["clr_event"],
                    "new_user": new_user})


def apply_s5(g, log):
    print("── S5: GR poster ≠ PO creator ───────────────────────")
    for item in check_selected("S5"):
        ev  = URIRef(item["gr_event"])
        old = list(g.objects(ev, EXT.userName))
        g.remove((ev, EXT.userName, None))
        g.add((ev, EXT.userName, Literal(item["po_user"], datatype=XSD.string)))
        print(f"  ✅ userName RecordGR → {item['po_user']}: {item['gr_event'].split('/')[-1]}")
        log.append({"constraint": "S5", "action": "change_username",
                    "event": item["gr_event"], "po": item["po"],
                    "old_user": [str(v) for v in old],
                    "new_user": item["po_user"]})


APPLIERS = {
    "B1": apply_b1, "B2": apply_b2, "B3": apply_b3, "B4": apply_b4,
    "D4": apply_d4, "D6": apply_d6,
    "S1": apply_s1, "S3": apply_s3, "S5": apply_s5,
}

# ══════════════════════════════════════════════════════════════════
# Isolated injection per constraint
# ══════════════════════════════════════════════════════════════════
print("=" * 60)
print("ISOLATED INJECTION PER CONSTRAINT")
print("=" * 60)

for constraint, apply_fn in APPLIERS.items():
    print(f"\n[{constraint}] Loading fresh graph...")
    g   = load_fresh_graph()
    log = []
    apply_fn(g, log)
    out_path = str(OUT_DIR / f"ocedr_injected_{constraint}.ttl")
    g.serialize(out_path, format="turtle")
    master_log[constraint] = log
    print(f"  📁 Saved: injected/ocedr_injected_{constraint}.ttl")

# ══════════════════════════════════════════════════════════════════
# Combined injection (all 36 at once) — for supplementary analysis
# ══════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("COMBINED INJECTION (all 36 violations)")
print("=" * 60)

g_all = load_fresh_graph()
log_all = []
for apply_fn in APPLIERS.values():
    apply_fn(g_all, log_all)

out_all = str(OUT_DIR / "ocedr_injected_ALL.ttl")
g_all.serialize(out_all, format="turtle")
master_log["ALL"] = log_all
print(f"\n  📁 Saved: injected/ocedr_injected_ALL.ttl")

# ── Save log ────────────────────────────────────────────────────
with open(LOG_FILE, "w", encoding="utf-8") as f:
    json.dump(master_log, f, indent=2, ensure_ascii=False)

print(f"\n{'=' * 60}")
print(f"✅ Done — 10 files created in injected/")
print(f"   9 isolated files (one per constraint)")
print(f"   1 combined file (all 36 violations)")
print(f"📋 Log saved: injection_log.json")
