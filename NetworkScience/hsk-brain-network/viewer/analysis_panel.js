'use strict';
// Analysis tab: key numbers, three small charts, findings, caveats. All values come from analysis.json.
const AnalysisPanel = (function () {
  const NS = 'http://www.w3.org/2000/svg';
  const S = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.append(e); return e; };
  const H = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
  const f = (x, d = 2) => (x == null ? 'n/a' : Number(x).toFixed(d));
  const pct = (x) => Math.round(x * 100) + '%';

  // Generic line chart on a 320x170 canvas. series: [{name,color,pts:[[x,y]],dash}]
  function chart(box, title, series, o) {
    const wrap = H('div', 'chart'); wrap.append(H('div', 'cap', title));
    const W = 320, Ht = 170, m = { l: 36, r: 8, t: 8, b: 26 };
    const svg = S('svg', { viewBox: `0 0 ${W} ${Ht}`, role: 'img', 'aria-label': title }, wrap);
    const all = series.flatMap((s) => s.pts);
    const tx = o.logx ? Math.log10 : (v) => v, ty = o.logy ? Math.log10 : (v) => v;
    const xs = all.map((p) => tx(p[0])), ys = all.map((p) => ty(p[1]));
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = o.logy ? Math.min(...ys) : 0, y1 = o.logy ? 0 : Math.max(...ys);
    const X = (v) => m.l + ((tx(v) - x0) / (x1 - x0)) * (W - m.l - m.r), Y = (v) => Ht - m.b - ((ty(v) - y0) / (y1 - y0)) * (Ht - m.t - m.b);
    const grid = '#262d3b', ink = '#7c8699';
    S('line', { x1: m.l, x2: m.l, y1: m.t, y2: Ht - m.b, stroke: ink }, svg);
    S('line', { x1: m.l, x2: W - m.r, y1: Ht - m.b, y2: Ht - m.b, stroke: ink }, svg);
    (o.yticks || []).forEach((v) => {
      S('line', { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), stroke: grid }, svg);
      const t = S('text', { x: m.l - 4, y: Y(v) + 3, 'text-anchor': 'end', fill: ink, 'font-size': 9 }, svg); t.textContent = o.yfmt ? o.yfmt(v) : v;
    });
    (o.xticks || []).forEach((v) => {
      const t = S('text', { x: X(v), y: Ht - m.b + 12, 'text-anchor': 'middle', fill: ink, 'font-size': 9 }, svg); t.textContent = o.xfmt ? o.xfmt(v) : v;
    });
    const xl = S('text', { x: (W + m.l) / 2, y: Ht - 3, 'text-anchor': 'middle', fill: ink, 'font-size': 9.5 }, svg); xl.textContent = o.xlabel;
    series.forEach((s) => {
      S('path', {
        d: s.pts.map((p, i) => (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join(''),
        fill: 'none', stroke: s.color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-dasharray': s.dash || ''
      }, svg);
    });
    const leg = H('div', 'note');
    series.forEach((s, i) => {
      const sp = H('span', null, (i ? '   ' : '') + '— ' + s.name); sp.style.color = s.color; sp.style.filter = 'brightness(1.15)'; leg.append(sp);
    });
    wrap.append(leg); box.append(wrap);
  }

  function render(box, A, PAL, NAMES) {
    const b = A.basic, sw = A.smallworld, cm = A.communities, ro = A.robustness, dg = A.degree, ov = A.overlap, ct = A.centrality;
    box.replaceChildren();
    box.append(H('h2', null, 'Key numbers'));
    const rows = [
      ['Nodes / links', `${b.N.toLocaleString()} / ${b.L.toLocaleString()}`],
      ['Mean degree', f(b.mean_degree, 1)],
      ['Largest hub', `${dg.hubs[0].label.split(' ')[0]} (${dg.hubs[0].degree} links)`],
      ['Connected', pct(sw.real.giant_fraction) + ' in one component'],
      ['Degree tail exponent', `${f(dg.powerlaw.alpha)} (degree ≥ ${dg.powerlaw.xmin})`],
      ['Clustering vs random', `${f(sw.real.avg_clustering, 3)} vs ${f(sw.vs_erdos_renyi.C_random_mean, 4)}`],
      ['Average path / diameter', `${f(sw.real.avg_path_giant)} / ${sw.real.diameter_giant}`],
      ['Small-world σ / ω', `${f(sw.sigma, 1)} / ${f(sw.omega)}`],
      ['Communities (fine, Q)', `${cm.louvain_fine.count}, ${f(cm.louvain_fine.Q_weighted_from_file)}`],
      ['Colour groups (Q)', `${cm.major.count}, ${f(cm.major.Q_weighted_from_file)}`],
      ['Innermost k-shell', `${ct.kcore.max_core} (${ct.kcore.main_core_size} nodes)`],
      ['Chars in 2+ chapters', pct(ov.char.frac_ge2_chapters)]
    ];
    const tb = H('table'); rows.forEach(([k, v]) => { const tr = H('tr'); tr.append(H('td', null, k), H('td', null, v)); tb.append(tr); }); box.append(tb);
    box.append(H('p', 'note', 'The two Q values are weighted, as the colour layout uses. The unweighted values are ' + f(cm.louvain_fine.Q_unweighted, 2) + ' and ' + f(cm.major.Q_unweighted, 2) + '.'));

    box.append(H('h2', null, 'Charts'));
    chart(box, 'Share of nodes with at least this many links', [{ name: 'real network', color: PAL[0], pts: dg.ccdf.filter((p) => p[1] > 0) }],
      { logx: true, logy: true, xticks: [1, 10, 100, 700], yticks: [1, 0.1, 0.01, 0.001], yfmt: (v) => v * 100 + '%', xlabel: 'links (log scale)' });
    const xs = ro.removed_fraction, zip = (ys) => xs.map((x, i) => [x, ys[i]]);
    chart(box, 'Share of network still connected after removing nodes', [
      { name: 'random', color: PAL[2], pts: zip(ro.random_failure_mean) },
      { name: 'busiest first', color: PAL[1], pts: zip(ro.attack_degree_static) },
      { name: 'most between', color: PAL[3], pts: zip(ro.attack_betweenness_static), dash: '4 3' }],
    { xticks: [0, 0.1, 0.2, 0.3], yticks: [0, 0.5, 1], xfmt: (v) => pct(v), yfmt: (v) => pct(v), xlabel: 'nodes removed' });
    const sh = ct.kcore.shell_sizes;
    chart(box, 'Nodes in each k-shell (higher shell = more tightly knit)', [{ name: 'nodes', color: PAL[6], pts: sh.map((p) => [p[0], p[1]]) }],
      { xticks: [1, 3, 5, 7, 9], yticks: [0, 500, 1000, 1500], xlabel: 'k-shell' });

    box.append(H('h2', null, 'Findings'));
    const ol = H('ol', 'find'); A.findings.forEach((t) => ol.append(H('li', null, t))); box.append(ol);
    box.append(H('h2', null, 'Caveats'));
    box.append(H('p', 'note', 'Sparks and the textbook chat use the real links. Path length, closeness, eigenvector and Katz centrality use the giant component, which here is every node. Betweenness is sampled from 300 sources. Community agreement with chapters is partly built in, because chapter links were part of the weighting. Grammar-to-sentence links are only the ones found in the book text or by string match, so grammar nodes are probably under-linked. Random steps use seed 42.'));
  }
  return { render };
})();
