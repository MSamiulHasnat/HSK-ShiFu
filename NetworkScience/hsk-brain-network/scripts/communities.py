#!/usr/bin/env python3
"""Louvain communities on the HSK network (course lecture 7), folded into <= 8 major
communities for the colour channel.  Writes communities.json."""
import json, sys, collections, random
from pathlib import Path
import networkx as nx
from networkx.algorithms.community import louvain_communities, modularity

PROJ = Path(sys.argv[1]); MAJOR = int(sys.argv[2]) if len(sys.argv) > 2 else 8
NET = json.loads((PROJ / 'network.json').read_text(encoding='utf-8'))
nodes = {n['id']: n for n in NET['nodes']}
REL_W = {'char_in_word': 1.0, 'sentence_has_word': 1.0, 'sentence_has_char': 0.6, 'pattern_match': 0.8,
         'word_in_chapter': 0.8, 'sentence_in_chapter': 0.5, 'grammar_in_chapter': 0.8, 'content_in_chapter': 0.8, 'chapter_in_book': 0.2}
G = nx.Graph()
G.add_nodes_from(nodes)
for e in NET['edges']:
    w = REL_W.get(e['rel'], 1.0) * (1.0 + 0.15 * min(e['w'], 4))
    if G.has_edge(e['s'], e['t']):
        G[e['s']][e['t']]['weight'] += w
    else:
        G.add_edge(e['s'], e['t'], weight=w)
print('graph', G.number_of_nodes(), G.number_of_edges())

best = None
for res in (0.4, 0.6, 0.8, 1.0):
    for seed in range(6):
        parts = louvain_communities(G, weight='weight', resolution=res, seed=seed)
        q = modularity(G, parts, weight='weight')
        if best is None or q > best[0]:
            best = (q, res, seed, parts)
    print('resolution', res, 'best Q so far', round(best[0], 4))
q, res, seed, parts = best
parts = sorted(parts, key=len, reverse=True)
print('fine partition:', len(parts), 'communities, Q =', round(q, 4), 'resolution', res, 'seed', seed)

# fold into MAJOR communities by repeatedly merging the pair with the highest modularity gain
comm = {}
for i, p in enumerate(parts):
    for n in p:
        comm[n] = i
fine = {i: set(p) for i, p in enumerate(parts)}
m2 = sum(d.get('weight', 1.0) for _, _, d in G.edges(data=True))
deg = dict(G.degree(weight='weight'))


def merge_gain(ci, cj, ein, tot):
    e_ij = ein.get((min(ci, cj), max(ci, cj)), 0.0)
    return e_ij / m2 - (tot[ci] * tot[cj]) / (2 * m2 * m2)


tot = {i: sum(deg[n] for n in s) for i, s in fine.items()}
ein = collections.defaultdict(float)
for u, v, d in G.edges(data=True):
    a, b = comm[u], comm[v]
    if a != b:
        ein[(min(a, b), max(a, b))] += d.get('weight', 1.0)
groups = {i: {i} for i in fine}
alive = set(fine)
while len(alive) > MAJOR:
    best_pair = None
    for (a, b), w in ein.items():
        if a in alive and b in alive:
            g = merge_gain(a, b, ein, tot)
            if best_pair is None or g > best_pair[0]:
                best_pair = (g, a, b)
    if best_pair is None:
        break
    _, a, b = best_pair
    groups[a] |= groups.pop(b); alive.discard(b); tot[a] += tot.pop(b)
    new = collections.defaultdict(float)
    for (x, y), w in ein.items():
        x2 = a if x == b else x; y2 = a if y == b else y
        if x2 == y2:
            continue
        new[(min(x2, y2), max(x2, y2))] += w
    ein = new

order = sorted(alive, key=lambda i: -sum(len(fine[j]) for j in groups[i]))
major = {}
for rank, i in enumerate(order):
    for j in groups[i]:
        for n in fine[j]:
            major[n] = rank
sizes = collections.Counter(major.values())
Gm = {n: major[n] for n in G}
qm = modularity(G, [set(n for n in G if major[n] == r) for r in sorted(sizes)], weight='weight')
print('major communities:', dict(sorted(sizes.items())), 'Q =', round(qm, 4))
out = {'major': major, 'fine': {n: comm[n] for n in G}, 'q_fine': q, 'q_major': qm, 'resolution': res, 'seed': seed,
       'n_fine': len(parts), 'sizes_major': dict(sizes)}
(PROJ / 'communities.json').write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
