"""
Exploratory mining of behavioural constraints from the OCEDR,
used to find candidate constraints for the OCBC model.

Idea: for every Purchase Order (PO) a trace is built from the process events of the PO and of
the objects related to it (Goods Receipts, Invoices, Financial Documents, Requisitions),
ordered by date. For every pair of event types (A, B) the script then measures how often an
occurrence of B is preceded by an occurrence of A in the same trace. Pairs that reach the
confidence threshold (90%) are printed as precedence constraints. These constraints were than validated
during the expert interview.

Input:  ocedr_p2p_graph.ttl.
Output: the discovered precedence pairs, with their confidence
        and the number of conforming / total occurrences.

"""



import rdflib
from rdflib import URIRef, RDF
from collections import defaultdict
import time

EXT  = "http://emixa.nl/p2p/domain#"
OCED = "https://w3id.org/ocedo/core#"

PO_TYPE      = URIRef(f"{EXT}PurchaseOrder")
IS_DELIVERED = URIRef(f"{EXT}isDeliveredBy")
IS_BILLED    = URIRef(f"{EXT}isBilledBy")
IS_CONVERTED = URIRef(f"{EXT}isConvertedTo")
GEN_FIN      = URIRef(f"{EXT}generatesFinancialDoc")
OBSERVES     = URIRef(f"{OCED}observes")
OBS_AT       = URIRef(f"{OCED}observed_at")

# Superclasses and auxiliary events that we do not want to include as an activity
EXCLUDE_TYPES = {
    f"{OCED}Event",
    f"{EXT}P2PEvent",
    f"{EXT}ChangeEvent",
}

print("⏳ Loading Knowledge Graph...")
t0 = time.time()
g = rdflib.Graph()
g.parse("ocedr_p2p_graph.ttl", format="turtle")
print(f"✅ Loaded {len(g)} triples in {time.time()-t0:.1f}s.\n")

# ── Step 1: index all events with their type + timestamp (single scan) ──────────
print("🔧 Indexing events (type + timestamp)...")
t0 = time.time()
event_info = {}  # event_uri -> (type_str, time_str)

for ev, t in g.subject_objects(OBS_AT):
    ev_types = [str(o) for o in g.objects(ev, RDF.type)]
    ev_type = next((et for et in ev_types if et not in EXCLUDE_TYPES), None)
    if ev_type:
        event_info[ev] = (ev_type, str(t))

print(f"   {len(event_info)} events indexed in {time.time()-t0:.1f}s.\n")

# ── Step 2: index which events observe which object (single scan) ──────────
print("🔧 Indexing observers (object -> events)...")
t0 = time.time()
observers = defaultdict(list)

for ev, obj in g.subject_objects(OBSERVES):
    if ev in event_info:
        observers[obj].append(ev)

print(f"   {len(observers)} observed objects indexed in {time.time()-t0:.1f}s.\n")

# ── Step 3: build traces per PO via direct graph navigation ─────────────────
print("🔍 Building process traces per Purchase Order (root object)...")
t0 = time.time()
traces = defaultdict(list)

for po in g.subjects(RDF.type, PO_TYPE):
    related_objects = [po]

    for gr in g.objects(po, IS_DELIVERED):
        related_objects.append(gr)

    for inv in g.objects(po, IS_BILLED):
        related_objects.append(inv)
        for fi in g.objects(inv, GEN_FIN):
            related_objects.append(fi)

    for req in g.subjects(IS_CONVERTED, po):
        related_objects.append(req)

    events = []
    for obj in related_objects:
        for ev in observers.get(obj, []):
            ev_type, ev_time = event_info[ev]
            events.append((ev_time, ev_type))

    events.sort(key=lambda x: x[0])
    traces[str(po)] = [ev_type for _, ev_type in events]

print(f"   Traces built in {time.time()-t0:.1f}s.\n")

# Filter: only POs with at least 2 events
active_traces = {k: v for k, v in traces.items() if len(v) > 1}
print(f"📊 Traces built for {len(active_traces)} active Purchase Orders (with >1 event).\n")

# ── Step 4: constraint mining (unchanged logic) ────────────────────────
print("🤖 Mining Behavioral Constraints (Confidence Threshold: 90%)...")
print("-" * 90)

unique_events = set(ev for t in active_traces.values() for ev in t)
discovered_constraints = []

MIN_CONFIDENCE = 0.90

for b in unique_events:
    for a in unique_events:
        if a == b:
            continue
        total_b = 0
        valid   = 0
        for trace in active_traces.values():
            for idx, event in enumerate(trace):
                if event == b:
                    total_b += 1
                    if a in trace[:idx]:
                        valid += 1
        if total_b > 5:
            confidence = valid / total_b
            if confidence >= MIN_CONFIDENCE:
                discovered_constraints.append((a, b, confidence, valid, total_b))

print(f"🎉 DISCOVERED OCBC CONSTRAINTS (>= {MIN_CONFIDENCE*100:.0f}%):")
print(f"{'Event A':<30} -> {'Event B':<30} | {'Confidence':<10} | Conform / Total")
print("-" * 90)

for a, b, conf, valid, total in sorted(
        discovered_constraints, key=lambda x: x[2], reverse=True):
    a_short = a.split('#')[-1].split('/')[-1]
    b_short = b.split('#')[-1].split('/')[-1]
    print(f"Precedence: {a_short:<18} -> {b_short:<30} | {conf*100:6.1f}%   | {valid} / {total}")

print("-" * 90)