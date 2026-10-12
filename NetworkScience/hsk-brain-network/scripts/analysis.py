#!/usr/bin/env python3
"""Network-science analysis of the HSK 1-3 textbook language network.

Reads  network.json + communities.json  (same folder, or folder given as argv[1])
Writes analysis.json + analysis_summary.md.

The graph is treated as undirected and simple (multi-edges collapsed, self-loops
dropped).  Measures that need connectivity (path length, closeness, eigenvector,
Katz, betweenness) use the giant component.  Every random step has a fixed seed.
"""
import collections
import heapq
import json
import math
import sys
import time
import warnings
from pathlib import Path

import networkx as nx
import numpy as np
import scipy.sparse as sp
from scipy.sparse import csgraph
from scipy.sparse.linalg import eigsh, spsolve
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SEED = 42
PROJ = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
T0 = time.time()
PROV_RANK = {"text": 0, "match": 1, "llm": 2}          # most certain first


def log(msg):
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def clean(o):
    """Convert numpy scalars/arrays to plain python; NaN/inf become None."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return clean(o.tolist())
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return f if math.isfinite(f) else None
    return o


def r(x, d=4):
    return None if x is None or not math.isfinite(x) else round(float(x), d)


# ----------------------------------------------------------------------------- load
net = json.loads((PROJ / "network.json").read_text(encoding="utf-8"))
com = json.loads((PROJ / "communities.json").read_text(encoding="utf-8"))
nodes = net["nodes"]
ids = [n["id"] for n in nodes]
idx = {i: k for k, i in enumerate(ids)}
N = len(ids)
ntype = np.array([n["type"] for n in nodes])
label = [n.get("label") or n["id"] for n in nodes]
TYPES = sorted(set(ntype.tolist()))

pairs = collections.defaultdict(list)
self_loops = 0
for e in net["edges"]:
    a, b = idx[e["s"]], idx[e["t"]]
    if a == b:
        self_loops += 1
        continue
    pairs[(a, b) if a < b else (b, a)].append(e)
G = nx.Graph()
G.add_nodes_from(range(N))
G.add_edges_from(pairs)
L = G.number_of_edges()
A = nx.to_scipy_sparse_array(G, nodelist=range(N), weight=None, format="csr", dtype=float)
deg = np.asarray(A.sum(axis=1)).ravel()
log(f"loaded N={N} L={L} (raw edge records {len(net['edges'])}, self-loops {self_loops})")


def giant(Am):
    nc, lab = csgraph.connected_components(Am, directed=False)
    cnt = np.bincount(lab)
    return nc, cnt, np.where(lab == cnt.argmax())[0]


ncomp, comp_sizes, gc = giant(A)
gc_set = set(gc.tolist())
Agc = A[gc][:, gc].tocsr()
NG = len(gc)
log(f"components {ncomp}, giant {NG}")


def node_rec(i, **extra):
    d = {"id": ids[i], "label": label[i], "type": str(ntype[i]), "degree": int(deg[i])}
    d.update(extra)
    return d


def top_nodes(values, candidates, n, tiebreak=None):
    """top-n node records by value (desc); ties broken by degree then index."""
    cand = np.asarray(candidates)
    order = sorted(cand.tolist(), key=lambda i: (-values[i], -deg[i], i))[:n]
    return [node_rec(i, value=r(values[i], 6)) for i in order]


# ----------------------------------------------------------------------------- basic
raw_rel = collections.Counter(e["rel"] for e in net["edges"])
raw_prov = collections.Counter(e["prov"] for e in net["edges"])
simple_prov = collections.Counter(min((e["prov"] for e in es), key=PROV_RANK.get) for es in pairs.values())
k1, k2 = deg.mean(), (deg ** 2).mean()
basic = {
    "N": N, "L": L, "raw_edge_records": len(net["edges"]),
    "multi_edge_records_collapsed": len(net["edges"]) - self_loops - L, "self_loops_dropped": self_loops,
    "density": r(2 * L / (N * (N - 1)), 6), "mean_degree": r(k1), "k2": r(k2), "k2_over_k": r(k2 / k1),
    "kmax": int(deg.max()), "kmin": int(deg.min()), "median_degree": float(np.median(deg)),
    "isolated_nodes": int((deg == 0).sum()),
    "components": int(ncomp), "giant_size": int(NG), "giant_fraction": r(NG / N, 5),
    "largest_components": sorted(comp_sizes.tolist(), reverse=True)[:5],
    "giant_edges": int(Agc.nnz // 2),
    "node_types": {t: int((ntype == t).sum()) for t in TYPES},
    "edge_relations": dict(raw_rel.most_common()),
    "provenance_raw": dict(raw_prov),
    "provenance_raw_fraction": {k: r(v / len(net["edges"])) for k, v in raw_prov.items()},
    "provenance_simple_edges": dict(simple_prov),
    "provenance_simple_fraction": {k: r(v / L) for k, v in simple_prov.items()},
    "input_meta": net.get("meta", {}),
}

# ----------------------------------------------------------------------------- degree
dpos = deg[deg > 0].astype(int)
edges_ = [1]
while edges_[-1] <= dpos.max():
    edges_.append(max(edges_[-1] + 1, int(math.ceil(edges_[-1] * 1.5))))
logbins = []
for lo, hi in zip(edges_[:-1], edges_[1:]):
    c = int(((dpos >= lo) & (dpos < hi)).sum())
    if c:
        logbins.append([r(math.sqrt(lo * (hi - 1)), 4), c / (N * (hi - lo))])
uk = np.unique(dpos)
ccdf = [[int(k), r((dpos >= k).mean(), 6)] for k in uk]

import powerlaw  # noqa: E402

np.random.seed(SEED)
fit = powerlaw.Fit(dpos, discrete=True, verbose=False)
pl = fit.power_law
tail = dpos[dpos >= pl.xmin]


def compare(name):
    try:
        R, p = fit.distribution_compare("power_law", name)
        fav = "inconclusive" if p >= 0.1 else ("power_law" if R > 0 else name)
        return {"R": r(R), "p": r(p, 6), "favoured_at_p<0.1": fav}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:100]}


plaw = {
    "alpha": r(pl.alpha), "alpha_sigma": r(pl.sigma), "xmin": int(pl.xmin), "ks_distance": r(pl.D),
    "n_tail": int(len(tail)), "tail_fraction": r(len(tail) / len(dpos)),
    "vs_lognormal": compare("lognormal"), "vs_exponential": compare("exponential"),
    "vs_truncated_power_law": compare("truncated_power_law"),
    "vs_stretched_exponential": compare("stretched_exponential"),
    "lognormal_mu": r(getattr(fit.lognormal, "mu", None)), "lognormal_sigma": r(getattr(fit.lognormal, "sigma", None)),
    "exponential_lambda": r(getattr(fit.exponential, "Lambda", None), 6),
    "note": "discrete MLE fit (Clauset-Shalizi-Newman via the powerlaw package); R>0 favours the power law, p is the significance of R",
}
degree = {
    "log_binned": logbins, "ccdf": ccdf, "powerlaw": plaw,
    "hubs": [node_rec(i) for i in sorted(range(N), key=lambda i: (-deg[i], i))[:20]],
}
log(f"degree done: alpha={plaw['alpha']} xmin={plaw['xmin']}")


# ----------------------------------------------------------------------------- small world
def apsp(Am, want_sums=False):
    """Exact all-pairs BFS distances of a connected graph (chunked)."""
    n = Am.shape[0]
    sums, diam = np.zeros(n), 0.0
    for s in range(0, n, 400):
        D = csgraph.dijkstra(Am, directed=False, unweighted=True, indices=np.arange(s, min(n, s + 400)))
        sums[s:s + len(D)] = D.sum(axis=1)
        diam = max(diam, float(D.max()))
    return float(sums.sum() / (n * (n - 1))), diam, sums


def sw_stats(Gx):
    Ax = nx.to_scipy_sparse_array(Gx, nodelist=range(N), weight=None, format="csr", dtype=float)
    _, cnt, g = giant(Ax)
    sub = Ax[g][:, g].tocsr()
    l, d, _ = apsp(sub)
    return {"n": Gx.number_of_nodes(), "m": Gx.number_of_edges(),
            "avg_clustering": r(nx.average_clustering(Gx)), "transitivity": r(nx.transitivity(Gx)),
            "avg_path_giant": r(l), "diameter_giant": int(d), "giant_fraction": r(len(g) / N, 5)}


L_real, diam_real, dist_sums = apsp(Agc)
C_real, T_real = nx.average_clustering(G), nx.transitivity(G)
real = {"n": N, "m": L, "avg_clustering": r(C_real), "transitivity": r(T_real),
        "avg_path_giant": r(L_real), "diameter_giant": int(diam_real), "giant_fraction": r(NG / N, 5)}
log(f"real: C={C_real:.4f} L={L_real:.3f} diam={diam_real}")
er = []
for i in range(3):
    er.append(sw_stats(nx.gnm_random_graph(N, L, seed=SEED + i)))
log("ER done")
rew = []
for i in range(3):
    H = G.copy()
    nx.double_edge_swap(H, nswap=10 * L, max_tries=1000 * L, seed=SEED + 10 + i)
    rew.append(sw_stats(H))
log("rewired done")
mean = lambda lst, k: float(np.mean([x[k] for x in lst]))  # noqa: E731
C_lat = 3 * (k1 - 2) / (4 * (k1 - 1))                       # ring-lattice clustering, mean degree k1


def sigma_omega(ref):
    Cr, Lr = mean(ref, "avg_clustering"), mean(ref, "avg_path_giant")
    return {"sigma": r((C_real / Cr) / (L_real / Lr)), "omega": r(Lr / L_real - C_real / C_lat),
            "C_ratio": r(C_real / Cr), "L_ratio": r(L_real / Lr), "C_random_mean": r(Cr, 5), "L_random_mean": r(Lr)}


smallworld = {
    "real": real, "erdos_renyi": er, "rewired": rew,
    "vs_erdos_renyi": sigma_omega(er), "vs_rewired": sigma_omega(rew),
    "sigma": sigma_omega(er)["sigma"], "omega": sigma_omega(er)["omega"],
    "c_lattice_approx": r(C_lat), "l_theory_random": r(math.log(N) / math.log(k1)),
    "note": ("clustering over all nodes; path length and diameter exact on the giant component; sigma=(C/Cr)/(L/Lr); "
             "omega=Lr/L - C/Clattice with Clattice=3(k-2)/(4(k-1)) for a ring lattice of mean degree k "
             "(omega near 0 small-world, -1 lattice-like, +1 random-like); top-level sigma/omega use the ER baseline"),
}

# ----------------------------------------------------------------------------- centrality
Ggc = G.subgraph(gc.tolist()).copy()
closeness = np.full(N, np.nan)
closeness[gc] = (NG - 1) / dist_sums
lam, vec = eigsh(Agc, k=1, which="LA")
lam1 = float(lam[0])
v = np.abs(vec[:, 0]); v /= np.linalg.norm(v)
eig = np.full(N, np.nan); eig[gc] = v
alpha_katz = 0.85 / lam1
kz = spsolve((sp.identity(NG, format="csc") - alpha_katz * Agc.tocsc()), np.ones(NG))
kz = kz / np.linalg.norm(kz)
katz = np.full(N, np.nan); katz[gc] = kz
log("closeness/eigenvector/katz done")
bt = nx.betweenness_centrality(Ggc, k=300, seed=SEED)
betw = np.zeros(N)
for i, b in bt.items():
    betw[i] = b
log("betweenness done")
pr = nx.pagerank(G, alpha=0.85)
pagerank = np.array([pr[i] for i in range(N)])
cn = nx.core_number(G)
core = np.array([cn[i] for i in range(N)], dtype=float)
kmax_core = int(core.max())
log("pagerank/core done")

meas = {"degree": deg, "closeness": closeness, "betweenness": betw, "eigenvector": eig, "katz": katz,
        "pagerank": pagerank, "kcore": core}
X = np.column_stack([m[gc] for m in meas.values()])
rho = spearmanr(X).statistic
names = list(meas)
spearman = {a: {b: r(rho[i, j]) for j, b in enumerate(names)} for i, a in enumerate(names)}
centrality = {
    "top10": {
        "degree": top_nodes(deg, range(N), 10), "closeness": top_nodes(closeness, gc, 10),
        "betweenness_sampled_k300": top_nodes(betw, gc, 10), "eigenvector": top_nodes(eig, gc, 10),
        "pagerank": top_nodes(pagerank, range(N), 10), "kcore": top_nodes(core, range(N), 10),
        "katz": top_nodes(katz, gc, 10),
    },
    "spearman_giant_component": spearman,
    "top5_by_degree_per_type": {t: [node_rec(i) for i in
                                    sorted(np.where(ntype == t)[0].tolist(), key=lambda i: (-deg[i], i))[:5]]
                                for t in TYPES},
    "kcore": {"max_core": kmax_core, "main_core_size": int((core == kmax_core).sum()),
              "shell_sizes": [[int(k), int((core == k).sum())] for k in sorted(set(core.astype(int)))],
              "main_core_type_counts": {t: int(((core == kmax_core) & (ntype == t)).sum()) for t in TYPES
                                        if ((core == kmax_core) & (ntype == t)).any()},
              "tie_break": "k-core ranking ties are broken by degree, then node index"},
    "eigenvalue_lambda1": r(lam1), "katz_alpha": r(alpha_katz, 6),
    "note": ("closeness, eigenvector, Katz and betweenness are computed on the giant component; Spearman correlations use "
             "its nodes; closeness is exact, betweenness uses 300 sampled sources (seed 42); PageRank damping 0.85; "
             "Katz alpha = 0.85/lambda1"),
}

# ----------------------------------------------------------------------------- communities
major = np.array([com["major"].get(i, -1) for i in ids])
fine = np.array([com["fine"].get(i, -1) for i in ids])
ch_ids = [i for i in range(N) if ntype[i] == "chapter"]
ch_set = set(ch_ids)
ch_level = {i: (nodes[i].get("level") or (nodes[i]["lvs"][0] if nodes[i]["lvs"] else None)) for i in ch_ids}
# direct links node -> chapter (all relations); weight = summed edge weight
ch_link = collections.defaultdict(lambda: collections.defaultdict(float))
for e in net["edges"]:
    a, b = idx[e["s"]], idx[e["t"]]
    for x, y in ((a, b), (b, a)):
        if x in ch_set and y not in ch_set and ntype[y] != "book":
            ch_link[y][x] += e["w"]
node_chapter = np.full(N, -1)
for i, d in ch_link.items():
    node_chapter[i] = sorted(d.items(), key=lambda kv: (-kv[1], ids[kv[0]]))[0][0]


def nmi(a, b):
    a, b = np.unique(a, return_inverse=True)[1], np.unique(b, return_inverse=True)[1]
    n = len(a)
    M = sp.coo_matrix((np.ones(n), (a, b))).tocsr()
    pij = M.toarray() / n
    pi, pj = pij.sum(1), pij.sum(0)
    nz = pij > 0
    mi = float((pij[nz] * np.log(pij[nz] / np.outer(pi, pj)[nz])).sum())
    ha, hb = -float((pi * np.log(pi)).sum()), -float((pj * np.log(pj)).sum())
    return 0.0 if ha + hb == 0 else 2 * mi / (ha + hb)


level_single = np.array([nodes[i]["lvs"][0] if len(nodes[i]["lvs"]) == 1 else -1 for i in range(N)])
level_min = np.array([min(nodes[i]["lvs"]) if nodes[i]["lvs"] else -1 for i in range(N)])
m_ch = (node_chapter >= 0) & ~np.isin(ntype, ["chapter", "book"])
m_lv, m_lvmin = level_single > 0, level_min > 0
coo = A.tocoo()


def community_block(part, with_detail):
    same = part[coo.row] == part[coo.col]
    kin_p = np.bincount(coo.row, weights=same, minlength=N)
    kout_p = deg - kin_p
    out = []
    for c in sorted(set(part.tolist()) - {-1}):
        mem = np.where(part == c)[0]
        lin, bnd = kin_p[mem].sum() / 2, kout_p[mem].sum()
        strong = bool(np.all(kin_p[mem] > kout_p[mem]))
        weak = bool(kin_p[mem].sum() > kout_p[mem].sum())
        d = {"community": int(c), "size": int(len(mem)), "internal_edges": int(lin), "boundary_edges": int(bnd),
             "share_edges_inside": r(lin / (lin + bnd) if lin + bnd else 0),
             "mean_internal_degree": r(kin_p[mem].mean()), "mean_external_degree": r(kout_p[mem].mean()),
             "frac_nodes_kin_gt_kout": r((kin_p[mem] > kout_p[mem]).mean()),
             "status": "strong" if strong else ("weak" if weak else "neither")}
        if with_detail:
            tc = collections.Counter(ntype[mem].tolist())
            d["composition_by_type"] = {t: int(tc.get(t, 0)) for t in TYPES}
            d["composition_fraction"] = {t: r(tc.get(t, 0) / len(mem)) for t in TYPES}
            lv = collections.Counter()
            for i in mem:
                for l_ in nodes[i]["lvs"]:
                    lv[l_] += 1
            nl = sum(1 for i in mem if not nodes[i]["lvs"])
            nm = sum(1 for i in mem if len(nodes[i]["lvs"]) > 1)
            with_lv = len(mem) - nl
            d["levels"] = {"level_1": lv.get(1, 0), "level_2": lv.get(2, 0), "level_3": lv.get(3, 0),
                           "multi_level_nodes": nm, "no_level_nodes": nl}
            d["levels_fraction_of_levelled"] = {f"level_{k}": r(lv.get(k, 0) / with_lv) if with_lv else None
                                                for k in (1, 2, 3)}
            d["top_nodes"] = [node_rec(i) for i in sorted(mem.tolist(), key=lambda i: (-deg[i], i))[:5]]
            cc = collections.Counter(node_chapter[mem][node_chapter[mem] >= 0].tolist())
            d["top_chapters"] = [{"chapter": label[k], "nodes": int(v)} for k, v in cc.most_common(3)]
        out.append(d)
    return out


major_blocks = community_block(major, True)
fine_blocks = community_block(fine, False)
mj_parts = [set(np.where(major == c)[0].tolist()) for c in sorted(set(major.tolist()) - {-1})]
fn_parts = [set(np.where(fine == c)[0].tolist()) for c in sorted(set(fine.tolist()) - {-1})]
q_mj = nx.community.modularity(G, mj_parts)
q_fn = nx.community.modularity(G, fn_parts)
rerun = nx.community.louvain_communities(G, seed=SEED)
communities = {
    "louvain_fine": {"count": len(fn_parts), "Q_weighted_from_file": r(com.get("q_fine")), "Q_unweighted": r(q_fn),
                     "sizes": sorted([len(p) for p in fn_parts], reverse=True),
                     "n_strong": sum(b["status"] == "strong" for b in fine_blocks),
                     "n_weak": sum(b["status"] == "weak" for b in fine_blocks),
                     "n_neither": sum(b["status"] == "neither" for b in fine_blocks),
                     "louvain_rerun_unweighted": {"count": len(rerun), "Q": r(nx.community.modularity(G, rerun)),
                                                  "seed": SEED}},
    "major": {"count": len(mj_parts), "Q_weighted_from_file": r(com.get("q_major")), "Q_unweighted": r(q_mj),
              "communities": major_blocks,
              "n_strong": sum(b["status"] == "strong" for b in major_blocks),
              "n_weak": sum(b["status"] == "weak" for b in major_blocks)},
    "nmi": {
        "chapter_coverage_nodes": int(m_ch.sum()),
        "chapter_coverage_by_type": {t: int((m_ch & (ntype == t)).sum()) for t in TYPES if t not in ("chapter", "book")},
        "n_chapters": len(ch_ids),
        "major_vs_chapter": r(nmi(major[m_ch], node_chapter[m_ch])), "fine_vs_chapter": r(nmi(fine[m_ch], node_chapter[m_ch])),
        "level_single_nodes": int(m_lv.sum()),
        "major_vs_level": r(nmi(major[m_lv], level_single[m_lv])), "fine_vs_level": r(nmi(fine[m_lv], level_single[m_lv])),
        "major_vs_level_minlevel": r(nmi(major[m_lvmin], level_min[m_lvmin])),
        "fine_vs_level_minlevel": r(nmi(fine[m_lvmin], level_min[m_lvmin])),
        "note": ("NMI = 2I/(H1+H2). Chapter of a node = chapter node with the largest summed link weight (nodes without a "
                 "chapter link, chapter and book nodes are excluded); level NMI uses nodes with exactly one HSK level "
                 "(minlevel variant: lowest level of every levelled node). Louvain saw the chapter links, so chapter NMI is "
                 "partly built in"),
    },
    "definitions": "strong: k_in > k_out for every node; weak: sum k_in > sum k_out over the community (lecture 6)",
}
log("communities done")

# ----------------------------------------------------------------------------- overlap
sent = np.where(ntype == "sentence")[0]
direct = {i: set(d) for i, d in ch_link.items()}
ov_out = {}
ov_rank = {}
for t in ("char", "word"):
    members = np.where(ntype == t)[0]
    chs, rows = {}, []
    for i in members:
        s = set(direct.get(i, ()))
        ns = 0
        for j in G[i]:
            if ntype[j] == "sentence":
                ns += 1
                s |= direct.get(j, set())
        chs[i] = s
        lv = {ch_level[c] for c in s if ch_level.get(c)}
        rows.append((i, len(s), len(lv), ns))
    nch = np.array([x[1] for x in rows]); nlv = np.array([x[2] for x in rows])
    placed = nch > 0
    lvs_field = np.array([len(nodes[i]["lvs"]) for i in members])
    ov_out[t] = {
        "n": int(len(members)), "n_with_any_chapter": int(placed.sum()),
        "mean_chapters": r(nch.mean()), "median_chapters": float(np.median(nch)), "max_chapters": int(nch.max()),
        "mean_levels": r(nlv.mean()),
        "frac_ge2_chapters": r((nch >= 2).mean()), "frac_ge2_levels": r((nlv >= 2).mean()),
        "frac_all3_levels": r((nlv >= 3).mean()),
        "frac_ge2_chapters_among_placed": r((nch[placed] >= 2).mean()),
        "frac_ge2_levels_among_placed": r((nlv[placed] >= 2).mean()),
        "frac_ge2_levels_from_lvs_field": r((lvs_field >= 2).mean()),
        "top15_most_widely_used": [
            node_rec(i, n_chapters=int(c), n_levels=int(lv_), n_sentences=int(ns))
            for i, c, lv_, ns in sorted(rows, key=lambda x: (-x[1], -x[3], -deg[x[0]], x[0]))[:15]],
    }
# participation coefficient across the 8 major communities
cl = sorted(set(major.tolist()) - {-1})
Mm = sp.csr_matrix((np.ones(int((major >= 0).sum())), (np.where(major >= 0)[0], [cl.index(c) for c in major[major >= 0]])),
                   shape=(N, len(cl)))
Kic = (A @ Mm).toarray()
with np.errstate(divide="ignore", invalid="ignore"):
    P = 1 - ((Kic / deg[:, None]) ** 2).sum(axis=1)
P = np.where(deg > 0, P, 0.0)
MIN_DEG = 10
cand = np.where(deg >= MIN_DEG)[0]
bridge = [node_rec(i, participation=r(P[i], 4), home_community=int(major[i]))
          for i in sorted(cand.tolist(), key=lambda i: (-P[i], -deg[i], i))[:15]]
overlap = {
    "char": ov_out["char"], "word": ov_out["word"],
    "bridge_nodes": {"min_degree": MIN_DEG, "top15": bridge,
                     "mean_participation_all": r(P.mean()), "mean_participation_deg_ge_min": r(P[cand].mean()),
                     "n_deg_ge_min": int(len(cand)), "frac_participation_gt_0.5_deg_ge_min": r((P[cand] > 0.5).mean()),
                     "mean_participation_by_type": {t: r(P[ntype == t].mean()) for t in TYPES}},
    "note": ("chapters of a char/word = chapters it is linked to directly plus chapters of the sentences containing it; "
             "levels are the HSK levels of those chapters. Participation coefficient P=1-sum_c (k_ic/k_i)^2 over the 8 "
             "major communities, ranked among nodes with degree >= 10 (P is unreliable for tiny degrees)"),
}
log("overlap done")

# ----------------------------------------------------------------------------- robustness
fracs = [round(0.02 * k, 2) for k in range(16)]
steps = [int(round(f * N)) for f in fracs]


def gc_frac(removed):
    keep = np.ones(N, bool)
    keep[list(removed)] = False
    sub = A[keep][:, keep]
    return float(np.bincount(csgraph.connected_components(sub, directed=False)[1]).max() / N)


def curve(order):
    return [gc_frac(order[:m]) for m in steps]


rand_runs = np.array([curve(np.random.default_rng(SEED + k).permutation(N)) for k in range(5)])
order_deg = sorted(range(N), key=lambda i: (-deg[i], i))
order_btw = sorted(range(N), key=lambda i: (-betw[i], -deg[i], i))
# adaptive degree attack: always remove the currently best-connected node
dcur = deg.copy()
heap = [(-dcur[i], i) for i in range(N)]
heapq.heapify(heap)
gone, order_adapt = np.zeros(N, bool), []
while len(order_adapt) < steps[-1]:
    d_, i = heapq.heappop(heap)
    if gone[i] or -d_ != dcur[i]:
        continue
    gone[i] = True
    order_adapt.append(i)
    for j in G[i]:
        if not gone[j]:
            dcur[j] -= 1
            heapq.heappush(heap, (-dcur[j], j))
c_deg, c_btw, c_ada = curve(order_deg), curve(order_btw), curve(order_adapt)


def first_below(cv, thr=0.5):
    for f, x in zip(fracs, cv):
        if x < thr:
            return f
    return None


mr = k2 / k1
robustness = {
    "removed_fraction": fracs, "nodes_removed": steps,
    "random_failure_mean": [r(x) for x in rand_runs.mean(axis=0)], "random_failure_std": [r(x) for x in rand_runs.std(axis=0)],
    "random_runs": 5,
    "attack_degree_static": [r(x) for x in c_deg], "attack_betweenness_static": [r(x) for x in c_btw],
    "attack_degree_adaptive": [r(x) for x in c_ada],
    "first_removed_fraction_giant_below_half": {
        "random": first_below(rand_runs.mean(axis=0)), "degree": first_below(c_deg),
        "betweenness": first_below(c_btw), "degree_adaptive": first_below(c_ada)},
    "molloy_reed_kappa": r(mr), "random_failure_critical_fraction_theory": r(1 - 1 / (mr - 1)) if mr > 2 else 0.0,
    "top_removed_types": {k: dict(collections.Counter(ntype[o[:steps[3]]].tolist()))
                          for k, o in (("degree", order_deg), ("betweenness", order_btw))},
    "note": ("giant-component size as a fraction of the ORIGINAL N; static attacks rank nodes once on the intact graph "
             "(betweenness = sampled, k=300); adaptive attack recomputes degree after every removal; "
             "theory f_c = 1 - 1/(k2/k - 1) is the Molloy-Reed value for an uncorrelated graph"),
}
log("robustness done")

# ----------------------------------------------------------------------------- findings
tp = lambda i: str(ntype[i])  # noqa: E731
h0 = degree["hubs"][0]
ci = lambda k: smallworld["vs_erdos_renyi"][k]  # noqa: E731
ix = lambda f: fracs.index(f)  # noqa: E731
pw_vs = plaw["vs_lognormal"]
fav_ln = pw_vs.get("favoured_at_p<0.1")
if fav_ln == "lognormal":
    tail_txt = "the power law fit is beaten by a lognormal in a likelihood-ratio test, so the tail is heavy but not a clean power law"
elif fav_ln == "power_law":
    tail_txt = "a likelihood-ratio test prefers the power law over a lognormal"
else:
    tail_txt = "a likelihood-ratio test cannot separate the power law from a lognormal"
exp_txt = {"power_law": "and clearly beats an exponential", "exponential": "but an exponential fits better"}.get(
    plaw["vs_exponential"].get("favoured_at_p<0.1"), "but the test against an exponential is inconclusive")
big = max(major_blocks, key=lambda b: b["share_edges_inside"])
nmi_ = communities["nmi"]
fl = overlap["char"]["frac_ge2_chapters"]
top_char = overlap["char"]["top15_most_widely_used"][0]
f20 = ix(0.2)
sm_txt = ("a small-world network" if (ci("sigma") or 0) > 1 and abs(ci("omega") or 9) < 0.5 else
          "small-world by sigma but not by omega" if (ci("sigma") or 0) > 1 else "not clearly small-world")
findings = [
    f"The HSK 1-3 network has {N} nodes and {L} links (mean degree {basic['mean_degree']:.1f}, density "
    f"{basic['density']:.4f}) and {100 * basic['giant_fraction']:.1f}% of nodes lie in a single connected giant component.",
    f"Degrees are very uneven: the mean is {basic['mean_degree']:.1f} but the largest hub ({h0['type']} node '{h0['label']}') "
    f"has {h0['degree']} links, and k2/k = {basic['k2_over_k']:.1f}.",
    f"A discrete power law fits the tail above degree {plaw['xmin']} with exponent alpha = {plaw['alpha']:.2f}, "
    f"{exp_txt}, but {tail_txt} (p = {pw_vs.get('p')}).",
    f"Average clustering is {real['avg_clustering']:.3f}, about {ci('C_ratio'):.0f} times that of equal-size random graphs "
    f"({ci('C_random_mean'):.4f}), while the average path length of the giant component is {real['avg_path_giant']:.2f} "
    f"versus {ci('L_random_mean'):.2f} for random graphs, so the network is {sm_txt} "
    f"(sigma = {ci('sigma'):.1f}, omega = {ci('omega'):.2f}; diameter {real['diameter_giant']}).",
    f"The most central node is '{centrality['top10']['degree'][0]['label']}' by degree and "
    f"'{centrality['top10']['betweenness_sampled_k300'][0]['label']}' by sampled betweenness; "
    f"degree and PageRank agree closely (Spearman {spearman['degree']['pagerank']:.2f}) and the innermost k-shell is {kmax_core} "
    f"holding {centrality['kcore']['main_core_size']} nodes.",
    f"Louvain finds {communities['louvain_fine']['count']} fine communities (Q = {q_fn:.2f}), merged into 8 major ones "
    f"(Q = {q_mj:.2f}); {communities['major']['n_strong']} of the 8 are strong and {communities['major']['n_weak']} are weak, "
    f"and the strongest keeps {100 * big['share_edges_inside']:.0f}% of its links inside.",
    f"Major communities line up with the book structure: NMI is {nmi_['major_vs_chapter']:.2f} against chapters and "
    f"{nmi_['major_vs_level']:.2f} against HSK level, and {100 * fl:.0f}% of characters occur in two or more chapters "
    f"(most widespread: '{top_char['label']}' in {top_char['n_chapters']} chapters).",
    f"Removing 20% of nodes at random leaves {100 * robustness['random_failure_mean'][f20]:.0f}% of the network in the giant "
    f"component, but removing the top 20% by degree leaves {100 * c_deg[f20]:.0f}% and by sampled betweenness "
    f"{100 * c_btw[f20]:.0f}%, so the network resists failure better than targeted attack.",
]
log("findings built")

out = {
    "meta": {"seed": SEED, "input_N": N, "input_raw_edges": len(net["edges"]),
             "graph": "undirected, simple (multi-edges collapsed, self-loops dropped)",
             "runtime_seconds": None, "libraries": {"networkx": nx.__version__, "numpy": np.__version__,
                                                    "powerlaw": powerlaw.__version__}},
    "basic": basic, "degree": degree, "smallworld": smallworld, "centrality": centrality,
    "communities": communities, "overlap": overlap, "robustness": robustness, "findings": findings,
}
out["meta"]["runtime_seconds"] = round(time.time() - T0, 1)
(PROJ / "analysis.json").write_text(json.dumps(clean(out), ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
log("analysis.json written")

# ----------------------------------------------------------------------------- summary markdown
rel_top = ", ".join(f"{k} ({v})" for k, v in list(raw_rel.most_common(4)))
tcount = ", ".join(f"{v} {k}" for k, v in sorted(basic["node_types"].items(), key=lambda kv: -kv[1]))
summary = f"""# HSK 1-3 Language Network: key numbers

**Nodes** are the teaching units of the three HSK Standard Course textbooks: {tcount}.
**Links** are relations stated or implied by the books: a character occurs in a word, a word or character occurs in a sentence,
a sentence illustrates a grammar rule, and a lesson contains a sentence, word or rule (most common relations: {rel_top}).
The graph is treated as undirected and simple. Link provenance: {100 * basic['provenance_raw_fraction']['text']:.0f}% read directly from the text,
{100 * basic['provenance_raw_fraction']['match']:.0f}% found by string matching, {100 * basic['provenance_raw_fraction']['llm']:.0f}% extracted by a language model.

## Size
| Quantity | Value |
|---|---|
| Nodes N / links L | {N} / {L} |
| Mean degree, density | {basic['mean_degree']:.2f}, {basic['density']:.4f} |
| Largest degree, k2/k | {basic['kmax']}, {basic['k2_over_k']:.1f} |
| Connected components, giant fraction | {ncomp}, {100 * basic['giant_fraction']:.1f}% |
| Power-law tail (degree >= {plaw['xmin']}) | alpha = {plaw['alpha']:.2f}, KS distance {plaw['ks_distance']:.3f} |
| Average clustering / transitivity | {real['avg_clustering']:.3f} / {real['transitivity']:.3f} |
| Average shortest path / diameter (giant) | {real['avg_path_giant']:.2f} / {real['diameter_giant']} |
| Random graph clustering / path (mean of 3) | {ci('C_random_mean'):.4f} / {ci('L_random_mean'):.2f} |
| Small-world sigma / omega | {ci('sigma'):.1f} / {ci('omega'):.2f} |
| Louvain fine communities, Q | {communities['louvain_fine']['count']}, {q_fn:.3f} |
| Major communities, Q | 8, {q_mj:.3f} ({communities['major']['n_strong']} strong, {communities['major']['n_weak']} weak) |
| NMI major vs chapter / vs HSK level | {nmi_['major_vs_chapter']:.2f} / {nmi_['major_vs_level']:.2f} |
| Giant fraction after 20% removed: random / degree / betweenness | {100 * robustness['random_failure_mean'][f20]:.0f}% / {100 * c_deg[f20]:.0f}% / {100 * c_btw[f20]:.0f}% |

## Key findings
""" + "\n".join(f"{k + 1}. {s}" for k, s in enumerate(findings)) + f"""

## Caveats
Path length, closeness, eigenvector, Katz and betweenness use the giant component; betweenness is sampled from 300 source nodes;
the lattice reference for omega is the analytic ring-lattice clustering; the Louvain partitions were computed with edge weights
that include chapter links, so agreement with chapters is partly built in. All random steps use seed {SEED}.
"""
(PROJ / "analysis_summary.md").write_text(summary, encoding="utf-8")
log("summary written")
