#!/usr/bin/env python3
"""Graph-driven brain layout.  No surface is ever drawn: the cortical surface (FreeSurfer fsaverage5,
bundled with nilearn) is only the domain the nodes may occupy.
  * hemispheres: balanced bisection of the community graph (hub links ignored)
  * each community gets a territory on the flattened cortex (balanced Voronoi, neighbours adjacent)
  * inside a territory a force-directed layout (springs along real edges) places the nodes, which are mapped
    back to the folded surface; edges are routed along the cortex
  * cerebellum: pronunciation and radical notes;  brainstem column: the ~30 hub characters/words
Output: brain_net.json for the viewer."""
import json, sys, math, base64, collections, time
import numpy as np
from pathlib import Path
from scipy.spatial import cKDTree

PROJ = Path(sys.argv[1]); PREVIEW = len(sys.argv) > 2 and sys.argv[2] == '--preview'
NET = json.loads((PROJ / 'network.json').read_text(encoding='utf-8'))
COM = json.loads((PROJ / 'communities.json').read_text(encoding='utf-8'))
S = np.load(PROJ / 'surf.npz')
rng = np.random.default_rng(7)
nodes = NET['nodes']; N = len(nodes); idx = {n['id']: i for i, n in enumerate(nodes)}
major = np.array([COM['major'].get(n['id'], 0) for n in nodes]); fine = np.array([COM['fine'].get(n['id'], 0) for n in nodes])
edges = [(idx[e['s']], idx[e['t']], e) for e in NET['edges'] if e['s'] in idx and e['t'] in idx]
deg = np.zeros(N, int)
for a, b, _ in edges:
    deg[a] += 1; deg[b] += 1
types = np.array([n['type'] for n in nodes])
CEN = np.array([0.0, -18.0, 12.0])


def to_world(p):
    q = p - CEN
    return np.stack([q[:, 0], q[:, 2], q[:, 1]], axis=1)


def normals(v, f):
    n = np.zeros_like(v); tri = v[f]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    for k in range(3):
        np.add.at(n, f[:, k], fn)
    n /= (np.linalg.norm(n, axis=1, keepdims=True) + 1e-9)
    if np.mean(np.sum(n * (v - v.mean(0)), axis=1)) < 0:
        n = -n
    return n


def poisson(P, n_target, seed):
    r_ = np.random.default_rng(seed); order = r_.permutation(len(P)); lo, hi = 0.6, 14.0; best = None
    for _ in range(13):
        rad = (lo + hi) / 2; cell = {}; chosen = []
        for i in order:
            q = P[i]; key = (int(q[0] // rad), int(q[1] // rad), int(q[2] // rad)); good = True
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for j in cell.get((key[0] + dx, key[1] + dy, key[2] + dz), ()):
                            if np.sum((P[j] - q) ** 2) < rad * rad:
                                good = False; break
                        if not good: break
                    if not good: break
                if not good: break
            if good:
                cell.setdefault(key, []).append(i); chosen.append(i)
        if len(chosen) >= n_target:
            best = chosen; lo = rad
        else:
            hi = rad
    return np.array(best[:n_target] if best else [])


def fr_layout(dom, edges_ij, n, w_ij, groups, iters=170, seed=1):
    """Force layout of n nodes constrained to the point set `dom` (M x d). Returns continuous positions."""
    r_ = np.random.default_rng(seed); tree = cKDTree(dom)
    d_nn = tree.query(dom, k=2)[0][:, 1].mean(); k = d_nn * math.sqrt(len(dom) / max(n, 1)) * 1.05
    pos = dom[r_.choice(len(dom), n, replace=n > len(dom))].copy().astype(float)
    ei = np.array(edges_ij) if len(edges_ij) else np.zeros((0, 2), int); w = np.array(w_ij) if len(w_ij) else np.zeros(0)
    dg = np.bincount(ei.ravel(), minlength=n).astype(float) + 1.0 if len(ei) else np.ones(n)
    wn = w / np.power(dg[ei[:, 0]] * dg[ei[:, 1]], 0.25) if len(ei) else w
    for it in range(iters):
        t = k * (1.6 * (1 - it / iters) + 0.15); disp = np.zeros_like(pos)
        tr = cKDTree(pos); pr = tr.query_pairs(r=3.0 * k, output_type='ndarray')
        if len(pr):
            v = pos[pr[:, 0]] - pos[pr[:, 1]]; d = np.linalg.norm(v, axis=1) + 1e-6
            f = (k * k / d)[:, None] * (v / d[:, None]); np.add.at(disp, pr[:, 0], f); np.add.at(disp, pr[:, 1], -f)
        if len(ei):
            v = pos[ei[:, 0]] - pos[ei[:, 1]]; d = np.linalg.norm(v, axis=1) + 1e-6
            f = (d * d / k * wn)[:, None] * (v / d[:, None]) * 0.35; np.add.at(disp, ei[:, 0], -f); np.add.at(disp, ei[:, 1], f)
        cs = {g: pos[groups == g].mean(0) for g in np.unique(groups)}
        cen = np.array([cs[g] for g in groups]); disp += (cen - pos) * 0.35 * (1 - 0.6 * it / iters)
        L = np.linalg.norm(disp, axis=1) + 1e-9; pos += disp / L[:, None] * np.minimum(L, t)[:, None]
        _, ix = tree.query(pos); pos = dom[ix].astype(float)
    return pos


def assign(pos, dom, order):
    tree = cKDTree(dom); used = np.zeros(len(dom), bool); res = np.zeros(len(pos), int)
    for i in order:
        kq = 24
        while True:
            _, ix = tree.query(pos[i], k=min(kq, len(dom))); ix = np.atleast_1d(ix); free = [j for j in ix if not used[j]]
            if free:
                res[i] = free[0]; used[free[0]] = True; break
            kq *= 3
    return res


# ---------------- region assignment ----------------
HUB_N = 30
cand = [i for i in range(N) if types[i] in ('char', 'word')]
hubs = set(sorted(cand, key=lambda i: -deg[i])[:HUB_N])
phon = np.isin(types, ['phonetics', 'radical'])
region = np.zeros(N, int)  # 0 left, 1 right, 2 cerebellum, 3 brainstem (hub relay column)
for i in range(N):
    if i in hubs: region[i] = 3
    elif phon[i]: region[i] = 2
rest_idx = np.where(region <= 1)[0]
fc = np.unique(fine[rest_idx]); fi = {c: i for i, c in enumerate(fc)}
A = np.zeros((len(fc), len(fc))); sz = np.zeros(len(fc))
for i in rest_idx: sz[fi[fine[i]]] += 1
DEGCAP = 150
for a_, b_, e in edges:
    if region[a_] <= 1 and region[b_] <= 1 and fine[a_] != fine[b_] and deg[a_] < DEGCAP and deg[b_] < DEGCAP:
        A[fi[fine[a_]], fi[fine[b_]]] += 1; A[fi[fine[b_]], fi[fine[a_]]] += 1
Lp = np.diag(A.sum(1)) - A
vals, vecs = np.linalg.eigh(Lp + 1e-9 * np.eye(len(fc)))
order = np.argsort(vecs[:, 1]); cum = np.cumsum(sz[order]); tot = cum[-1]; best = None
for s_ in range(len(order)):
    if 0.40 * tot <= cum[s_] <= 0.60 * tot:
        left = set(order[:s_ + 1]); cut = sum(A[i, j] for i in left for j in range(len(fc)) if j not in left)
        if best is None or cut < best[0]: best = (cut, s_)
left = set(order[:best[1] + 1])
for i in rest_idx: region[i] = 0 if fi[fine[i]] in left else 1
cross = sum(1 for a_, b_, e in edges if region[a_] in (0, 1) and region[b_] in (0, 1) and region[a_] != region[b_])
print('regions (L,R,CB,stem):', np.bincount(region, minlength=4).tolist(), '| community-level cut', int(best[0]), '| L/R cross edges', cross, 'of', len(edges))

# ---------------- hemisphere surfaces ----------------
t0 = time.time(); pos3 = np.zeros((N, 3)); nrm3 = np.zeros((N, 3)); HEMI = {}


def build_hemi(h, side):
    pv = S[h + '_pv'].astype(float); fv = S[h + '_fv'][:, :2].astype(float); F = S[h + '_pf'].astype(int); sulc = S[h + '_s'].astype(float)
    nr = normals(pv, F)
    e = np.unique(np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1), axis=0)
    lp = np.linalg.norm(pv[e[:, 0]] - pv[e[:, 1]], axis=1); lf = np.linalg.norm(fv[e[:, 0]] - fv[e[:, 1]], axis=1)
    torn_e = lf > 3.0 * lp + 3.0; tset = set(map(tuple, e[torn_e])); ok_e = ~torn_e
    P = [pv]; Fl = [fv]; Nn = [nr]; Ss = [sulc]
    P.append((pv[e[ok_e, 0]] + pv[e[ok_e, 1]]) / 2); Fl.append((fv[e[ok_e, 0]] + fv[e[ok_e, 1]]) / 2)
    nm = nr[e[ok_e, 0]] + nr[e[ok_e, 1]]; Nn.append(nm / (np.linalg.norm(nm, axis=1, keepdims=True) + 1e-9)); Ss.append((sulc[e[ok_e, 0]] + sulc[e[ok_e, 1]]) / 2)
    tri_ok = np.array([not (tuple(sorted((f[0], f[1]))) in tset or tuple(sorted((f[1], f[2]))) in tset or tuple(sorted((f[0], f[2]))) in tset) for f in F])
    Fk = F[tri_ok]; P.append(pv[Fk].mean(1)); Fl.append(fv[Fk].mean(1)); nm = nr[Fk].sum(1)
    Nn.append(nm / (np.linalg.norm(nm, axis=1, keepdims=True) + 1e-9)); Ss.append(sulc[Fk].mean(1))
    P = np.concatenate(P); Fl = np.concatenate(Fl); Nn = np.concatenate(Nn); Ss = np.concatenate(Ss)
    valid = ((side * Nn[:, 0]) > -0.55) & (Ss < 0.25)
    P = P[valid]; Fl = Fl[valid]; Nn = Nn[valid]
    W = to_world(P + Nn * 0.7); Wn = np.stack([Nn[:, 0], Nn[:, 2], Nn[:, 1]], axis=1); W[:, 0] += side * 2.0
    return W, Wn, Fl


def balanced_territories(dom, centres, sizes, iters=80):
    M = len(dom); K = len(centres); target = sizes / sizes.sum() * M; w = np.zeros(K); c = centres.copy()
    spacing2 = (dom.max(0) - dom.min(0)).prod() / M
    for it in range(iters):
        d2 = ((dom[:, None, :] - c[None, :, :]) ** 2).sum(-1) - w[None, :]
        a = d2.argmin(1); cnt = np.bincount(a, minlength=K)
        w += 0.35 * (target - cnt) / np.maximum(target, 1) * spacing2 * 6
        for k_ in range(K):
            m = a == k_
            if m.any(): c[k_] = 0.6 * c[k_] + 0.4 * dom[m].mean(0)
    d2 = ((dom[:, None, :] - c[None, :, :]) ** 2).sum(-1) - w[None, :]
    return d2.argmin(1), c


def place_region(r, W, Wn, Fl):
    members = np.where(region == r)[0]
    thin = poisson(W, int(len(members) * 1.3), 11 + r)
    dom = Fl[thin]; comms = np.unique(fine[members]); K = len(comms); ci = {c: i for i, c in enumerate(comms)}
    sizes = np.array([(fine[members] == c).sum() for c in comms], float)
    CW = np.zeros((K, K))
    for a_, b_, e in edges:
        if region[a_] == r and region[b_] == r and fine[a_] != fine[b_] and deg[a_] < DEGCAP and deg[b_] < DEGCAP:
            CW[ci[fine[a_]], ci[fine[b_]]] += 1; CW[ci[fine[b_]], ci[fine[a_]]] += 1
    cw_edges = [(i, j) for i in range(K) for j in range(i + 1, K) if CW[i, j] > 0]
    cw_w = [min(3.0, CW[i, j] / (np.sqrt(sizes[i] * sizes[j]) * 0.5)) for i, j in cw_edges]
    cc = fr_layout(dom, cw_edges, K, cw_w, np.arange(K), iters=120, seed=5 + r)
    terr, cc = balanced_territories(dom, cc, sizes)
    pos_local = {}
    for k_, c in enumerate(comms):
        mem = members[fine[members] == c]; pidx = np.where(terr == k_)[0]
        if len(pidx) < len(mem):
            d2 = ((dom - cc[k_]) ** 2).sum(1); pidx = np.argsort(d2)[:int(len(mem) * 1.15)]
        loc = {g: i for i, g in enumerate(mem)}
        ee = [(loc[a_], loc[b_]) for a_, b_, e in edges if a_ in loc and b_ in loc]
        ww = [min(e['w'], 3.0) for a_, b_, e in edges if a_ in loc and b_ in loc]
        p = fr_layout(dom[pidx], ee, len(mem), ww, np.zeros(len(mem), int), iters=140, seed=17 + k_)
        asg = assign(p, dom[pidx], np.argsort(-deg[mem])); sel = thin[pidx[asg]]
        pos3[mem] = W[sel]; nrm3[mem] = Wn[sel]
        pos_local.update({g: Fl[sel[i]] for i, g in enumerate(mem)})
    return pos_local


for r, h, side in ((0, 'left', -1.0), (1, 'right', 1.0)):
    W, Wn, Fl = build_hemi(h, side)
    fl = place_region(r, W, Wn, Fl)
    HEMI[h] = {'W': W, 'N': Wn, 'F': Fl, 'tree': cKDTree(Fl), 'flat_of_node': fl}
    print(h, 'laid out', int((region == r).sum()), f'nodes ({time.time() - t0:.0f}s)')

# ---------------- cerebellum ----------------
CB_C = np.array([0.0, -66.0, -34.0]); CB_R = np.array([50.0, 31.0, 22.0])
cbm = np.where(region == 2)[0]
th = np.linspace(0.05, math.pi - 0.05, 90); ph = np.linspace(0, 2 * math.pi, 150, endpoint=False)
T, Ph = np.meshgrid(th, ph, indexing='ij'); d = np.stack([np.sin(T) * np.cos(Ph), np.sin(T) * np.sin(Ph), np.cos(T)], axis=-1).reshape(-1, 3)
rr = 1 - 0.06 * np.abs(np.sin(34.0 * d[:, 2])) ** 2; pts = CB_C + d * CB_R * rr[:, None]
nn_ = d / CB_R; nn_ /= np.linalg.norm(nn_, axis=1, keepdims=True)
keep = (nn_[:, 2] < 0.55) & (pts[:, 1] < -50)
Wc = to_world(pts[keep] + nn_[keep] * 0.7); Wcn = np.stack([nn_[keep][:, 0], nn_[keep][:, 2], nn_[keep][:, 1]], axis=1)
if len(cbm):
    thin = poisson(Wc, int(len(cbm) * 1.25), 21); local = {g: i for i, g in enumerate(cbm)}
    ee = [(local[a_], local[b_]) for a_, b_, x in edges if a_ in local and b_ in local]; ww = [min(x['w'], 3.0) for a_, b_, x in edges if a_ in local and b_ in local]
    p = fr_layout(Wc[thin], ee, len(cbm), ww, major[cbm], seed=9)
    asg = assign(p, Wc[thin], np.argsort(-deg[cbm])); sel = thin[asg]; pos3[cbm] = Wc[sel]; nrm3[cbm] = Wcn[sel]
HEMI['cb'] = {'W': Wc, 'N': Wcn, 'tree': cKDTree(Wc)}
print('cerebellum laid out', len(cbm))

# ---------------- brainstem: hub relay column ----------------
hl = sorted(hubs, key=lambda i: -deg[i]); ns = len(hl)
for j, i in enumerate(hl):
    t = (j + 0.5) / ns; ang = j * 2.399963
    c = to_world(np.array([[0.0, -22.0 - 14.0 * t, -14.0 - 34.0 * t + 3 * math.sin(3 * t)]]))[0]
    rad = 6.0 - 2.0 * t; pos3[i] = c + np.array([math.cos(ang) * rad, 0.0, math.sin(ang) * rad * 0.9]); nrm3[i] = np.array([math.cos(ang), 0, math.sin(ang)])
print('brainstem hubs', ns)

# ---------------- edge routing ----------------
K = 8; poly = np.zeros((len(edges), K + 1, 3), np.float32); pnrm = np.zeros((len(edges), K + 1, 3), np.float32); kinds = collections.Counter()
CORE = np.array([0.0, 4.0, -4.0])
for ei_, (a, b, e) in enumerate(edges):
    A_, B_ = pos3[a], pos3[b]; ra, rb = region[a], region[b]; ts = np.linspace(0, 1, K + 1)
    if ra == rb and ra in (0, 1):
        H = HEMI['left' if ra == 0 else 'right']; fa, fb = H['flat_of_node'][a], H['flat_of_node'][b]
        samp = fa[None, :] * (1 - ts[:, None]) + fb[None, :] * ts[:, None]
        _, ix = H['tree'].query(samp); P_ = H['W'][ix].copy(); N_ = H['N'][ix].copy(); P_[0], P_[-1] = A_, B_; N_[0], N_[-1] = nrm3[a], nrm3[b]
        if np.max(np.linalg.norm(np.diff(P_, axis=0), axis=1)) > 30.0:
            dist = np.linalg.norm(B_ - A_); ctl = (A_ + B_) / 2 + (nrm3[a] + nrm3[b]) * (0.14 * dist + 3)
            P_ = ((1 - ts) ** 2)[:, None] * A_ + (2 * (1 - ts) * ts)[:, None] * ctl + (ts ** 2)[:, None] * B_; N_ = np.tile((nrm3[a] + nrm3[b]) / 2, (K + 1, 1)); kinds['tear'] += 1
        else: kinds['surface'] += 1
    elif ra == rb == 2:
        samp = A_[None, :] * (1 - ts[:, None]) + B_[None, :] * ts[:, None]; _, ix = HEMI['cb']['tree'].query(samp)
        P_ = HEMI['cb']['W'][ix].copy(); N_ = HEMI['cb']['N'][ix].copy(); P_[0], P_[-1] = A_, B_; N_[0], N_[-1] = nrm3[a], nrm3[b]; kinds['cb'] += 1
    elif ra == 3 or rb == 3:
        mid = (A_ + B_) / 2; ctl = mid + (CORE - mid) * 0.2
        P_ = ((1 - ts) ** 2)[:, None] * A_ + (2 * (1 - ts) * ts)[:, None] * ctl + (ts ** 2)[:, None] * B_; N_ = np.zeros((K + 1, 3)); kinds['fibre'] += 1
    else:
        dist = np.linalg.norm(B_ - A_); mid = (A_ + B_) / 2; ctl = mid + np.array([0.0, 0.10 * dist + 4.0, 0.0])
        P_ = ((1 - ts) ** 2)[:, None] * A_ + (2 * (1 - ts) * ts)[:, None] * ctl + (ts ** 2)[:, None] * B_; N_ = np.zeros((K + 1, 3)); kinds['long'] += 1
    poly[ei_] = P_; pnrm[ei_] = N_
print('edge routing', dict(kinds))


# ---------------- export ----------------
def b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


rels = sorted(set(e['rel'] for _, _, e in edges)); ridx = {r: i for i, r in enumerate(rels)}
provs = ['text', 'match', 'llm']
types_l = sorted(set(types)); tidx = {t: i for i, t in enumerate(types_l)}
meta = [{'id': n['id'], 'l': (n.get('label') or n.get('head') or n['id'])[:260], 't': tidx[n['type']], 'c': int(major[i]), 'f': int(fine[i]),
         'd': int(deg[i]), 'lv': n.get('lvs', []), 'r': int(region[i]), 'pg': n.get('pages', [])[:6]} for i, n in enumerate(nodes)]
ea = np.array([min(255, int(255 * min(1.0, 20.0 / max(deg[a_], deg[b_])) ** 0.8)) for a_, b_, _ in edges], np.uint8)
out = {'types': types_l, 'rels': rels, 'provs': provs, 'nodes': meta,
       'pos': b64(np.round(pos3 * 16).astype(np.int16)), 'nrm': b64(np.round(nrm3 * 127).astype(np.int8)),
       'ea': b64(ea), 'es': b64(np.array([[a, b] for a, b, _ in edges], np.uint32)), 'er': b64(np.array([ridx[e['rel']] for _, _, e in edges], np.uint8)),
       'ep': b64(np.array([provs.index(e['prov']) for _, _, e in edges], np.uint8)), 'ew': b64(np.array([min(e['w'], 255) for _, _, e in edges], np.uint8)),
       'poly': b64(np.round(poly * 16).astype(np.int16)), 'pnrm': b64(np.round(pnrm * 127).astype(np.int8)), 'K': K, 'nE': len(edges), 'nN': N,
       'q': COM.get('q_major'), 'sizes': COM.get('sizes_major')}
(PROJ / 'brain_net.json').write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print('wrote brain_net.json', round((PROJ / 'brain_net.json').stat().st_size / 1e6, 2), 'MB')

if PREVIEW:
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    pal = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#00a000', '#9085e9', '#e66767', '#888888']
    for name, (hx, hy) in (('side', (2, 1)), ('top', (0, 2))):
        fig, ax = plt.subplots(figsize=(11, 8), facecolor='#080c16'); ax.set_facecolor('#080c16')
        sel_e = np.argsort(-ea.astype(int))[:12000]
        for i in sel_e:
            a_, b_ = edges[i][0], edges[i][1]
            ax.plot(poly[i][:, hx], poly[i][:, hy], lw=0.3, alpha=0.05 + 0.25 * ea[i] / 255, color=pal[min(major[a_], 8)] if major[a_] == major[b_] else '#7f8aa3')
        ax.scatter(pos3[:, hx], pos3[:, hy], s=np.where(region == 3, 40, 3 + 0.01 * deg), c=[pal[min(m, 8)] for m in major], zorder=3); ax.set_aspect('equal'); ax.axis('off')
        plt.savefig(PROJ / f'preview_{name}.png', dpi=80, facecolor='#080c16'); plt.close()
