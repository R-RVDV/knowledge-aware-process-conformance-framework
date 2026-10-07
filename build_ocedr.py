"""
Builds the OCEDR layer from the anonymised SAP tables.
 
Input:  the 15 anonymised, tab-separated SAP tables in ./preprocessing/sap_data/02_processed/:
        EBAN, EKKO, EKPO, MKPF, MSEG, RBKP, RSEG, BKPF, BSEG, EKBE, EKET, RKPF, RESB, CDHDR, CDPOS.
Output: ./ocedr_p2p_graph.ttl.
 
How the tables are mapped:
  - every business object becomes a resource typed with its ext: class and oced:Object,
    with a URI built from the SAP key (e.g. res:PO_<EBELN> for a Purchase Order).
  - every process step becomes an event typed with its ext: class and oced:Event, linked to
    its object with oced:observes and dated with oced:observed_at.
  - relations between objects are direct ext: properties (e.g. ext:isDeliveredBy);
  - attributes are literals attached to the object or event.
 
"""


import pandas as pd
import os
from rdflib import Graph, Literal, RDF, Namespace
from rdflib.namespace import XSD

# =============================================================
# Namespaces — exactly identical to the OCEDD file
# =============================================================
OCED = Namespace("https://w3id.org/ocedo/core#")
EXT  = Namespace("http://emixa.nl/p2p/domain#")
RES  = Namespace("http://emixa.nl/p2p/resource/")

PROCESSED_PATH = './preprocessing/sap_data/02_processed/'
OUTPUT_FILE    = './ocedr_p2p_graph.ttl'




# =============================================================
# Helper functions
# =============================================================
def load(table_name):
    path = os.path.join(PROCESSED_PATH, f"{table_name}_anonymized.csv")
    if not os.path.exists(path):
        print(f"  ⚠️  Not found: {path}")
        return pd.DataFrame()
    df = pd.read_csv(path, sep='\t', dtype=str, on_bad_lines='skip')
    df.columns = [c.strip() for c in df.columns]
    df = df.map(lambda x: x.strip() if isinstance(x, str) else x)
    print(f"  ✅ {table_name}: {len(df)} rows | {list(df.columns)}")
    return df

def clean(val):
    if pd.isna(val) or str(val).strip().lower() in ['nan', 'none', '']:
        return None
    return str(val).strip()

def uri(prefix, *parts):
    key = '_'.join(str(p).strip() for p in parts if p and str(p).strip() not in ['nan', ''])
    key = key.replace(' ', '_').replace('/', '_').replace('\\', '_')
    return RES[prefix + key]

def add_literal(g, subject, predicate, value, datatype=XSD.string):
    v = clean(value)
    if v:
        g.add((subject, predicate, Literal(v, datatype=datatype)))

def add_date(g, subject, predicate, value):
    v = clean(value)
    if v and v != '1900-01-01' and v != 'NaT':
        g.add((subject, predicate, Literal(v, datatype=XSD.date)))


# =============================================================
# Triplification
# =============================================================
def build_graph():
    # Empty graph — data triples only, no schema
    g = Graph()

    g.bind("oced", OCED)
    g.bind("ext",  EXT)
    g.bind("res",  RES)

    print("\n📋 Loading tables...")
    eban  = load("EBAN")
    ekko  = load("EKKO")
    ekpo  = load("EKPO")
    mkpf  = load("MKPF")
    mseg  = load("MSEG")
    rbkp  = load("RBKP")
    rseg  = load("RSEG")
    bkpf  = load("BKPF")
    bseg  = load("BSEG")
    ekbe  = load("EKBE")
    eket  = load("EKET")
    rkpf  = load("RKPF")
    resb  = load("RESB")
    cdhdr = load("CDHDR")
    cdpos = load("CDPOS")

    print("\n🔨 Starting triplification...\n")

    # ---------------------------------------------------------
    # 1. PURCHASE REQUISITION (EBAN)
    #    Object: ext:PurchaseRequisition
    #    Event:  ext:CreateRequisition
    # ---------------------------------------------------------
    if not eban.empty and 'BANFN' in eban.columns:
        for _, row in eban.iterrows():
            banfn = clean(row.get('BANFN'))
            bnfpo = clean(row.get('BNFPO'))
            if not banfn:
                continue

            req_uri = uri("Req_", banfn, bnfpo)
            g.add((req_uri, RDF.type, EXT.PurchaseRequisition))
            g.add((req_uri, RDF.type, OCED.Object))

            ev_uri = uri("Ev_CreateReq_", banfn, bnfpo)
            g.add((ev_uri, RDF.type, EXT.CreateRequisition))
            g.add((ev_uri, RDF.type, OCED.Event))
            g.add((ev_uri, OCED.observes, req_uri))
            add_date(g, ev_uri, OCED.observed_at, row.get('ERDAT'))
            add_literal(g, ev_uri, EXT.userName, row.get('ERNAM'))

            # Relation: isConvertedTo PurchaseOrder
            ebeln = clean(row.get('EBELN'))
            if ebeln and ebeln not in ['0000000000', '']:
                g.add((req_uri, EXT.isConvertedTo, uri("PO_", ebeln)))

        print(f"  ✅ EBAN processed ({len(eban)} rows)")

    # ---------------------------------------------------------
    # 2. PURCHASE ORDER (EKKO)
    #    Object: ext:PurchaseOrder
    #    Event:  ext:CreatePurchaseOrder
    # ---------------------------------------------------------
    if not ekko.empty and 'EBELN' in ekko.columns:
        for _, row in ekko.iterrows():
            ebeln = clean(row.get('EBELN'))
            if not ebeln:
                continue

            po_uri = uri("PO_", ebeln)
            g.add((po_uri, RDF.type, EXT.PurchaseOrder))
            g.add((po_uri, RDF.type, OCED.Object))
            add_literal(g, po_uri, EXT.vendorId, row.get('LIFNR'))

            ev_uri = uri("Ev_CreatePO_", ebeln)
            g.add((ev_uri, RDF.type, EXT.CreatePurchaseOrder))
            g.add((ev_uri, RDF.type, OCED.Event))
            g.add((ev_uri, OCED.observes, po_uri))
            add_date(g, ev_uri, OCED.observed_at, row.get('BEDAT'))
            add_literal(g, ev_uri, EXT.userName, row.get('ERNAM'))

        print(f"  ✅ EKKO processed ({len(ekko)} rows)")

    # EKPO: attributes on PurchaseOrder
    # Note: multiple EKPO rows per EBELN write to the same PO URI;
    # the last row wins. This is a deliberate limitation of the schema
    # (one PurchaseOrder object per EBELN). See thesis §5.6.
    if not ekpo.empty and 'EBELN' in ekpo.columns:
        for _, row in ekpo.iterrows():
            ebeln = clean(row.get('EBELN'))
            if not ebeln:
                continue
            po_uri = uri("PO_", ebeln)
            add_literal(g, po_uri, EXT.materialNumber, row.get('MATNR') or row.get('TXZ01'))
            if clean(row.get('NETWR')):
                add_literal(g, po_uri, EXT.netAmount, row.get('NETWR'), datatype=XSD.decimal)
            if clean(row.get('MENGE')):
                add_literal(g, po_uri, EXT.quantity, row.get('MENGE'), datatype=XSD.decimal)

        print(f"  ✅ EKPO processed ({len(ekpo)} rows)")

    # ---------------------------------------------------------
    # 3. GOODS RECEIPT (MKPF + MSEG)
    #    Object: ext:GoodsReceipt
    #    Event:  ext:RecordGoodsReceipt
    # ---------------------------------------------------------
    if not mkpf.empty and 'MBLNR' in mkpf.columns:
        for _, row in mkpf.iterrows():
            mblnr = clean(row.get('MBLNR'))
            mjahr = clean(row.get('MJAHR'))
            if not mblnr:
                continue

            gr_uri = uri("GR_", mblnr, mjahr)
            g.add((gr_uri, RDF.type, EXT.GoodsReceipt))
            g.add((gr_uri, RDF.type, OCED.Object))

            ev_uri = uri("Ev_RecordGR_", mblnr, mjahr)
            g.add((ev_uri, RDF.type, EXT.RecordGoodsReceipt))
            g.add((ev_uri, RDF.type, OCED.Event))
            g.add((ev_uri, OCED.observes, gr_uri))
            add_date(g, ev_uri, OCED.observed_at, row.get('BUDAT'))
            add_literal(g, ev_uri, EXT.userName, row.get('USNAM'))

        print(f"  ✅ MKPF processed ({len(mkpf)} rows)")

    # MSEG: relation GoodsReceipt → PurchaseOrder
    # Note: multiple MSEG rows per MBLNR write quantity to the same
    # GR URI; the last row wins. See the EKPO note above.
    if not mseg.empty and 'MBLNR' in mseg.columns:
        for _, row in mseg.iterrows():
            mblnr = clean(row.get('MBLNR'))
            mjahr = clean(row.get('MJAHR'))
            ebeln = clean(row.get('EBELN'))
            if not mblnr or not ebeln or ebeln == '0000000000':
                continue
            gr_uri = uri("GR_", mblnr, mjahr)
            g.add((uri("PO_", ebeln), EXT.isDeliveredBy, gr_uri))
            if clean(row.get('MENGE')):
                add_literal(g, gr_uri, EXT.quantity, row.get('MENGE'), datatype=XSD.decimal)

        print(f"  ✅ MSEG processed ({len(mseg)} rows)")

    # ---------------------------------------------------------
    # 4. INVOICE (RBKP + RSEG)
    #    Object: ext:Invoice
    #    Event:  ext:RecordInvoice
    # ---------------------------------------------------------
    if not rbkp.empty and 'BELNR' in rbkp.columns:
        for _, row in rbkp.iterrows():
            belnr = clean(row.get('BELNR'))
            gjahr = clean(row.get('GJAHR'))
            if not belnr:
                continue

            inv_uri = uri("Inv_", gjahr, belnr)
            g.add((inv_uri, RDF.type, EXT.Invoice))
            g.add((inv_uri, RDF.type, OCED.Object))
            # ext:vendorId on Invoice (RBKP.LIFNR) — D4 Three-Way Match vendor check
            # Possible thanks to v6.1: rdfs:domain broadened to ext:P2PObject
            add_literal(g, inv_uri, EXT.vendorId, row.get('LIFNR'))

            ev_uri = uri("Ev_RecordInv_", gjahr, belnr)
            g.add((ev_uri, RDF.type, EXT.RecordInvoice))
            g.add((ev_uri, RDF.type, OCED.Event))
            g.add((ev_uri, OCED.observes, inv_uri))
            add_date(g, ev_uri, OCED.observed_at, row.get('BLDAT'))
            add_literal(g, ev_uri, EXT.userName, row.get('USNAM'))

        print(f"  ✅ RBKP processed ({len(rbkp)} rows)")

    # RSEG: relations Invoice → PurchaseOrder and Three-Way Match
    # [PERF] Pre-build MSEG lookup dictionary to avoid an O(n×m) loop
    mseg_by_ebeln = {}
    if not mseg.empty and 'EBELN' in mseg.columns:
        for _, row in mseg[['EBELN', 'MBLNR', 'MJAHR']].dropna(subset=['EBELN']).iterrows():
            ebeln_key = clean(row.get('EBELN'))
            mblnr_val = clean(row.get('MBLNR'))
            mjahr_val = clean(row.get('MJAHR'))
            if ebeln_key and mblnr_val:
                mseg_by_ebeln.setdefault(ebeln_key, set()).add((mblnr_val, mjahr_val))

    if not rseg.empty and 'BELNR' in rseg.columns:
        for _, row in rseg.iterrows():
            belnr = clean(row.get('BELNR'))
            gjahr = clean(row.get('GJAHR'))
            ebeln = clean(row.get('EBELN'))
            if not belnr:
                continue

            inv_uri = uri("Inv_", gjahr, belnr)
            if clean(row.get('WRBTR')):
                add_literal(g, inv_uri, EXT.netAmount, row.get('WRBTR'), datatype=XSD.decimal)
            if clean(row.get('MENGE')):
                add_literal(g, inv_uri, EXT.quantity, row.get('MENGE'), datatype=XSD.decimal)

            if ebeln and ebeln != '0000000000':
                g.add((uri("PO_", ebeln), EXT.isBilledBy, inv_uri))

                # matches: indirect via shared PO (RSEG.EBELN = MSEG.EBELN)
                # LFBNR not available; Three-Way Match derived via shared EBELN
                for mblnr_val, mjahr_val in mseg_by_ebeln.get(ebeln, set()):
                    g.add((inv_uri, EXT.matches, uri("GR_", mblnr_val, mjahr_val)))

        print(f"  ✅ RSEG processed ({len(rseg)} rows)")

    # ---------------------------------------------------------
    # 5. FINANCIAL DOCUMENT (BKPF + BSEG)
    #    Object: ext:FinancialDocument
    #    Event:  ext:ClearInvoice
    # ---------------------------------------------------------
    if not bkpf.empty and 'BELNR' in bkpf.columns:
        for _, row in bkpf.iterrows():
            belnr = clean(row.get('BELNR'))
            gjahr = clean(row.get('GJAHR'))
            bukrs = clean(row.get('BUKRS'))
            if not belnr:
                continue

            fi_uri = uri("FI_", bukrs, gjahr, belnr)
            g.add((fi_uri, RDF.type, EXT.FinancialDocument))
            g.add((fi_uri, RDF.type, OCED.Object))

            ev_uri = uri("Ev_ClearInv_", bukrs, gjahr, belnr)
            g.add((ev_uri, RDF.type, EXT.ClearInvoice))
            g.add((ev_uri, RDF.type, OCED.Event))
            g.add((ev_uri, OCED.observes, fi_uri))
            add_date(g, ev_uri, OCED.observed_at, row.get('BUDAT'))
            add_literal(g, ev_uri, EXT.userName, row.get('USNAM'))
            add_literal(g, ev_uri, EXT.transactionCode, row.get('TCODE'))

            # [FIX bug 3] generatesFinancialDoc: Invoice → FinancialDocument via AWKEY
            # AWKEY structure: characters 1-10 = invoice BELNR, characters 11-14 = invoice GJAHR
            awkey = clean(row.get('AWKEY'))
            if awkey and len(awkey) >= 14:
                inv_belnr = awkey[:10].strip()
                inv_gjahr = awkey[10:14].strip()
                g.add((uri("Inv_", inv_gjahr, inv_belnr),
                       EXT.generatesFinancialDoc, fi_uri))
            elif awkey and len(awkey) >= 10:
                g.add((uri("Inv_", gjahr, awkey[:10].strip()),
                       EXT.generatesFinancialDoc, fi_uri))

        print(f"  ✅ BKPF processed ({len(bkpf)} rows)")

    # BSEG: generic relation FinancialDocument → PurchaseOrder (BSEG.EBELN).
    # Deliberately oced:object_relation (OCEDO Core) without its own ext: subproperty:
    # none of the six OCEDD relations covers this link, and no conformance query uses it.
    if not bseg.empty and 'EBELN' in bseg.columns:
        for _, row in bseg.iterrows():
            belnr = clean(row.get('BELNR'))
            gjahr = clean(row.get('GJAHR'))
            bukrs = clean(row.get('BUKRS'))
            ebeln = clean(row.get('EBELN'))
            if not belnr or not ebeln or ebeln == '0000000000':
                continue
            g.add((uri("FI_", bukrs, gjahr, belnr), OCED.object_relation, uri("PO_", ebeln)))

        print(f"  ✅ BSEG processed ({len(bseg)} rows)")

    # ---------------------------------------------------------
    # 6. EKBE: PO History events
    # ---------------------------------------------------------
    if not ekbe.empty and 'EBELN' in ekbe.columns:
        for i, row in ekbe.iterrows():
            ebeln = clean(row.get('EBELN'))
            if not ebeln or ebeln == '0000000000':
                continue
            label  = clean(row.get('VGABE_LABEL')) or 'Other'
            ev_uri = uri(f"Ev_EKBE_{label.replace(' ', '')}_", ebeln, str(i))
            g.add((ev_uri, RDF.type, EXT.P2PEvent))
            g.add((ev_uri, RDF.type, OCED.Event))
            g.add((ev_uri, OCED.observes, uri("PO_", ebeln)))
            add_date(g, ev_uri, OCED.observed_at, row.get('BUDAT'))
            if clean(row.get('WRBTR')):
                add_literal(g, ev_uri, EXT.poHistoryAmount, row.get('WRBTR'), datatype=XSD.decimal)
        print(f"  ✅ EKBE processed ({len(ekbe)} rows)")

    # ---------------------------------------------------------
    # 7. EKET: Delivery schedule
    # ---------------------------------------------------------
    if not eket.empty and 'EBELN' in eket.columns:
        for _, row in eket.iterrows():
            ebeln = clean(row.get('EBELN'))
            if not ebeln or ebeln == '0000000000':
                continue
            add_date(g, uri("PO_", ebeln), EXT.scheduledDeliveryDate, row.get('EINDT'))
        print(f"  ✅ EKET processed ({len(eket)} rows)")

    # ---------------------------------------------------------
    # 8. RKPF: Reservation headers
    # ---------------------------------------------------------
    if not rkpf.empty and 'RSNUM' in rkpf.columns:
        for _, row in rkpf.iterrows():
            rsnum = clean(row.get('RSNUM'))
            if not rsnum:
                continue
            res_uri = uri("Res_", rsnum)
            g.add((res_uri, RDF.type, EXT.Reservation))
            g.add((res_uri, RDF.type, OCED.Object))
            add_literal(g, res_uri, EXT.userName, row.get('USNAM'))
        print(f"  ✅ RKPF processed ({len(rkpf)} rows)")

    # ---------------------------------------------------------
    # 9. RESB: Reservation items
    # ---------------------------------------------------------
    if not resb.empty and 'EBELN' in resb.columns:
        for _, row in resb.iterrows():
            rsnum = clean(row.get('RSNUM'))
            ebeln = clean(row.get('EBELN'))
            if not rsnum or not ebeln or ebeln == '0000000000':
                continue
            res_uri = uri("Res_", rsnum)
            g.add((res_uri, RDF.type, EXT.Reservation))
            g.add((res_uri, RDF.type, OCED.Object))
            g.add((res_uri, EXT.reservedFor, uri("PO_", ebeln)))
        print(f"  ✅ RESB processed ({len(resb)} rows)")

    # ---------------------------------------------------------
    # 10. CHANGE EVENTS (CDHDR + CDPOS)
    # ---------------------------------------------------------
    cdhdr_index = {}
    if not cdhdr.empty and 'CHANGENR' in cdhdr.columns:
        for _, row in cdhdr.iterrows():
            changenr = clean(row.get('CHANGENR'))
            if changenr:
                cdhdr_index[changenr] = row
        print(f"  ✅ CDHDR processed ({len(cdhdr)} rows, as lookup index for CDPOS)")

    if not cdpos.empty and 'CHANGENR' in cdpos.columns:
        for i, row in cdpos.iterrows():
            changenr = clean(row.get('CHANGENR'))
            fname    = clean(row.get('FNAME'))
            if not changenr:
                continue
            ev_uri = uri("Ev_Change_", changenr, str(i))
            g.add((ev_uri, RDF.type, EXT.ChangeEvent))
            g.add((ev_uri, RDF.type, OCED.Event))
            hdr = cdhdr_index.get(changenr)
            if hdr is not None:
                add_date(g, ev_uri, OCED.observed_at, hdr.get('UDATE'))
                add_literal(g, ev_uri, EXT.userName,        hdr.get('USERNAME'))
                add_literal(g, ev_uri, EXT.transactionCode, hdr.get('TCODE'))
                objectclas = clean(hdr.get('OBJECTCLAS'))
                objectid   = clean(hdr.get('OBJECTID'))
                if objectid and objectclas == 'EINKBELEG':
                    g.add((ev_uri, OCED.observes, uri("PO_", objectid)))
            add_literal(g, ev_uri, EXT.changedFieldName, fname)
            add_literal(g, ev_uri, EXT.oldValue,         row.get('VALUE_OLD'))
            add_literal(g, ev_uri, EXT.newValue,         row.get('VALUE_NEW'))
        print(f"  ✅ CDPOS processed ({len(cdpos)} rows, one node per field change)")

    # ---------------------------------------------------------
    # 11. Export — data triples only (no schema)
    # ---------------------------------------------------------
    g.serialize(destination=OUTPUT_FILE, format="turtle")
    print(f"\n🚀 SUCCESS! OCEDR graph saved as '{OUTPUT_FILE}'")
    print(f"📊 Total number of data triples: {len(g)}")
    print(f"   (schema triples are in emixa_p2p_ocedd.ttl, not in this file)")


if __name__ == "__main__":
    build_graph()