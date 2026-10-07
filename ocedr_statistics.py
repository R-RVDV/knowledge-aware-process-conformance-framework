"""
Descriptive statistics of the OCEDR Knowledge Graph (the data layer).

Reports:
  1. The number of instances per class.
  2. The number of Purchase Order -> Invoice links (ext:isBilledBy).

"""

import rdflib

g = rdflib.Graph()
g.parse("ocedr_p2p_graph.ttl", format="turtle")


# Query 1: Actual counts per type
query_counts = """
PREFIX oced: <https://w3id.org/ocedo/core#>
PREFIX ext: <http://emixa.nl/p2p/domain#>

SELECT ?type (COUNT(?s) AS ?total)
WHERE {
    ?s a ?type .
}
GROUP BY ?type
ORDER BY DESC(?total)
"""

# Query 2: Connectivity (P2P chain)
query_links = """
PREFIX ext: <http://emixa.nl/p2p/domain#>
SELECT (COUNT(*) AS ?links)
WHERE {
    ?po a ext:PurchaseOrder .
    ?po ext:isBilledBy ?inv .
}
"""

print("📊 DESCRIPTIVE STATISTICS:")
for row in g.query(query_counts):
    # .total retrieves the value from COUNT()
    print(f"{row.type.split('#')[-1].split('/')[-1]:<25} | {row.total}")

print("\n🔗 KNOWLEDGE GRAPH CONNECTIVITY:")
for row in g.query(query_links):
    print(f"Number of links (Order -> Invoice): {row.links}")