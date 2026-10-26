'use strict';
// Validated categorical palette, dark-surface steps (slots 1-8).
const PAL = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];
// Provisional names from each group's busiest members (to be replaced by agent-written names).
const NAMES = ['Pointing and wanting', 'Negation and goodness', 'Having and wanting more', 'Linking and contrast',
  'Asking and going', 'Comparing and degree', 'Core pronouns and "is"', 'Place and ongoing action'];
const TYPE_LABEL = { book: 'Book', chapter: 'Chapter', char: 'Character', culture: 'Culture', grammar: 'Grammar', phonetics: 'Pronunciation', radical: 'Radical', sentence: 'Sentence', text: 'Text', word: 'Word' };
const $ = (s) => document.querySelector(s);
const b64 = (s, T) => { const bin = atob(s), u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return new T(u.buffer); };
const norm = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };

async function load(name) {
  if (window['__' + name]) return window['__' + name];
  const r = await fetch('../data/' + (name === 'BRAIN' ? 'brain_net.json' : 'analysis.json'));
  return r.json();
}

(async function main() {
  const [B, A] = await Promise.all([load('BRAIN'), load('ANALYSIS')]);
  const nN = B.nN, nE = B.nE, K = B.K, nodes = B.nodes;
  const pos = b64(B.pos, Int16Array), nrm = b64(B.nrm, Int8Array), poly = b64(B.poly, Int16Array), pnrm = b64(B.pnrm, Int8Array);
  const ea = b64(B.ea, Uint8Array), es = b64(B.es, Uint32Array), er = b64(B.er, Uint8Array);
  $('#status').remove();
  $('#cnt').textContent = nN.toLocaleString() + ' nodes · ' + nE.toLocaleString() + ' links';

  // centre and scale
  const c0 = [0, 0, 0];
  for (let i = 0; i < nN; i++) for (let k = 0; k < 3; k++) c0[k] += pos[i * 3 + k] / 16 / nN;
  let R = 0;
  for (let i = 0; i < nN; i++) { let d = 0; for (let k = 0; k < 3; k++) d += (pos[i * 3 + k] / 16 - c0[k]) ** 2; R = Math.max(R, Math.sqrt(d)); }
  const P = (a, i, k) => a[i * 3 + k] / 16 - c0[k];

  // adjacency
  const inc = Array.from({ length: nN }, () => []);
  for (let e = 0; e < nE; e++) { inc[es[2 * e]].push(e); inc[es[2 * e + 1]].push(e); }
  const other = (e, n) => (es[2 * e] === n ? es[2 * e + 1] : es[2 * e]);

  // state
  const typeOn = new Set(B.types.map((_, i) => i)), commOn = new Set(PAL.map((_, i) => i)), lvOn = new Set([1, 2, 3]);
  let sel = -1, hits = new Set();
  const nodeVis = new Uint8Array(nN).fill(1);

  // renderer
  const canvas = $('#gl');
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, R * 0.05, R * 20);
  camera.up.set(0, 1, 0);
  const controls = new THREE.OrbitControls(camera, canvas);
  controls.enableDamping = true; controls.dampingFactor = 0.08; controls.autoRotateSpeed = 0.6;
  // drag = rotate, right/middle drag or shift+drag = pan the whole network; wheel zooms toward the pointer
  controls.enablePan = true; controls.screenSpacePanning = true; controls.enableZoom = false;
  controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.PAN };
  canvas.addEventListener('contextmenu', (e) => e.preventDefault());
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect(), nx = ((e.clientX - rect.left) / rect.width) * 2 - 1, ny = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    const dist = camera.position.distanceTo(controls.target);
    const s = Math.min(Math.max(Math.exp(e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.0015)), 0.5), 2);
    const nd = Math.min(Math.max(dist * s, R * 0.15), R * 12), k = nd / dist;
    const ray = new THREE.Vector3(nx, ny, 0.5).unproject(camera).sub(camera.position).normalize();
    const fwd = camera.getWorldDirection(new THREE.Vector3());
    const t = dist / Math.max(ray.dot(fwd), 1e-3), p = camera.position.clone().addScaledVector(ray, t); // point under cursor on the target plane
    camera.position.copy(p).addScaledVector(camera.position.clone().sub(p), k);
    controls.target.copy(p).addScaledVector(controls.target.clone().sub(p), k);
    controls.update();
  }, { passive: false });
  function setView(v) {
    // data axes: x = left-right, y = up, z = back-to-front (see layout.py previews)
    const d = R * 3.0, p = { side: [-d, 0, 0], top: [0, d, 0], front: [0, 0, d] }[v];
    camera.up.set(...(v === 'top' ? [0, 0, 1] : [0, 1, 0]));
    camera.position.set(...p); controls.target.set(0, 0, 0); controls.update();
  }
  setView('side');
  function resize() { renderer.setSize(innerWidth, innerHeight, false); camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); }
  addEventListener('resize', resize); resize();

  // colours
  const col = PAL.map((h) => new THREE.Color(h));
  const gray = new THREE.Color('#8a93a8');

  const FACING = `
    float facing(vec3 n){ vec3 nv = normalize(normalMatrix * n); return mix(0.10, 1.0, smoothstep(-0.15, 0.45, nv.z)); }`;

  // ----- nodes
  const nPos = new Float32Array(nN * 3), nNrm = new Float32Array(nN * 3), nCol = new Float32Array(nN * 3), nSize = new Float32Array(nN), nSt = new Float32Array(nN * 2);
  for (let i = 0; i < nN; i++) {
    for (let k = 0; k < 3; k++) { nPos[i * 3 + k] = P(pos, i, k); nNrm[i * 3 + k] = nrm[i * 3 + k] / 127; }
    const c = col[nodes[i].c]; nCol.set([c.r, c.g, c.b], i * 3);
    nSize[i] = 1.3 + 1.5 * Math.log10(1 + nodes[i].d);
    nSt[i * 2] = 1;
  }
  const ng = new THREE.BufferGeometry();
  ng.setAttribute('position', new THREE.BufferAttribute(nPos, 3)); ng.setAttribute('normal', new THREE.BufferAttribute(nNrm, 3));
  ng.setAttribute('aCol', new THREE.BufferAttribute(nCol, 3)); ng.setAttribute('aSize', new THREE.BufferAttribute(nSize, 1));
  const nStA = new THREE.BufferAttribute(nSt, 2); ng.setAttribute('aSt', nStA);
  const U = { uScale: { value: 1 }, uDim: { value: 0 } };
  const nodeMat = new THREE.ShaderMaterial({
    uniforms: U, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `attribute vec3 aCol; attribute float aSize; attribute vec2 aSt; uniform float uScale; uniform float uDim;
      varying vec3 vC; varying float vA; ${FACING}
      void main(){ vec4 mv = modelViewMatrix * vec4(position,1.0); gl_Position = projectionMatrix * mv;
        float f = facing(normal); float hl = aSt.y;
        float dim = hl > 0.5 ? 1.0 : 1.0 - uDim * 0.75;
        float sz = aSize * (hl > 1.5 ? 2.4 : hl > 0.5 ? 1.5 : 1.0);
        gl_PointSize = sz * uScale / -mv.z;
        vC = hl > 1.5 ? vec3(1.0) : mix(aCol, vec3(1.0), hl > 0.5 ? 0.35 : 0.0);
        vA = aSt.x * f * dim; if(hl > 0.5) vA = aSt.x * max(f, 0.55); }`,
    fragmentShader: `varying vec3 vC; varying float vA;
      void main(){ vec2 p = gl_PointCoord - 0.5; float r = length(p); if(r > 0.5) discard;
        float a = smoothstep(0.5, 0.25, r); gl_FragColor = vec4(vC * vA * a * 1.0, 1.0); }`
  });
  scene.add(new THREE.Points(ng, nodeMat));

  // ----- links: K segments per polyline
  const SV = K * 2, nV = nE * SV;
  const lPos = new Float32Array(nV * 3), lNrm = new Float32Array(nV * 3), lCol = new Float32Array(nV * 3), lAl = new Float32Array(nV), lSt = new Float32Array(nV);
  for (let e = 0; e < nE; e++) {
    const a = es[2 * e], b = es[2 * e + 1], c = nodes[a].c === nodes[b].c ? col[nodes[a].c] : gray;
    for (let j = 0; j < K; j++) for (let s = 0; s < 2; s++) {
      const v = e * SV + j * 2 + s, q = (e * (K + 1) + j + s) * 3;
      for (let k = 0; k < 3; k++) { lPos[v * 3 + k] = poly[q + k] / 16 - c0[k]; lNrm[v * 3 + k] = pnrm[q + k] / 127; }
      lCol.set([c.r, c.g, c.b], v * 3); lAl[v] = ea[e] / 255; lSt[v] = 1;
    }
  }
  const lg = new THREE.BufferGeometry();
  lg.setAttribute('position', new THREE.BufferAttribute(lPos, 3)); lg.setAttribute('normal', new THREE.BufferAttribute(lNrm, 3));
  lg.setAttribute('aCol', new THREE.BufferAttribute(lCol, 3)); lg.setAttribute('aAl', new THREE.BufferAttribute(lAl, 1));
  const lStA = new THREE.BufferAttribute(lSt, 1); lg.setAttribute('aSt', lStA);
  const linkMat = new THREE.ShaderMaterial({
    uniforms: U, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `attribute vec3 aCol; attribute float aAl; attribute float aSt; uniform float uDim; varying vec3 vC; varying float vA; ${FACING}
      void main(){ gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0);
        float f = facing(normal); bool on = aSt > 1.05; bool vis = aSt > 0.5;
        float base = on ? (aSt - 1.0) : aAl * 0.13 * (1.0 - uDim * 0.8);
        vC = on ? mix(aCol, vec3(1.0), 0.5) : aCol; vA = vis ? base * (on ? max(f, 0.5) : f) : 0.0; }`,
    fragmentShader: `varying vec3 vC; varying float vA; void main(){ gl_FragColor = vec4(vC * vA, 1.0); }`
  });
  scene.add(new THREE.LineSegments(lg, linkMat));

  // ----- sparks
  const NS = 220, sPos = new Float32Array(NS * 3), sNrm = new Float32Array(NS * 3);
  const sg = new THREE.BufferGeometry();
  sg.setAttribute('position', new THREE.BufferAttribute(sPos, 3)); sg.setAttribute('normal', new THREE.BufferAttribute(sNrm, 3));
  const sparkMat = new THREE.ShaderMaterial({
    uniforms: U, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `uniform float uScale; varying float vA; ${FACING}
      void main(){ vec4 mv = modelViewMatrix * vec4(position,1.0); gl_Position = projectionMatrix * mv; gl_PointSize = 5.0 * uScale / -mv.z; vA = max(facing(normal), 0.4); }`,
    fragmentShader: `varying float vA; void main(){ float r = length(gl_PointCoord - 0.5); if(r > 0.5) discard; gl_FragColor = vec4(vec3(1.0,0.85,0.5) * vA * smoothstep(0.5,0.0,r) * 1.6, 1.0); }`
  });
  const sparkPts = new THREE.Points(sg, sparkMat); sparkPts.frustumCulled = false; scene.add(sparkPts);
  const sparks = Array.from({ length: NS }, () => ({ e: -1, t: 0, v: 0.5, dir: 1 }));
  let sparkEdges = [], sparkFrom = -1;
  function pickAmbient() {
    for (let t = 0; t < 8; t++) { const e = Math.floor(Math.random() * nE); if (ea[e] > 120) return e; }
    return Math.floor(Math.random() * nE);
  }
  function respawn(s, ambient) {
    const live = sparkEdges.length && !ambient;
    s.e = live ? sparkEdges[Math.floor(Math.random() * sparkEdges.length)] : pickAmbient();
    s.t = Math.random() * (live ? 0.2 : 1); s.v = 0.35 + Math.random() * 0.5;
    s.dir = sparkFrom >= 0 && live ? (es[2 * s.e] === sparkFrom ? 1 : -1) : (Math.random() < 0.5 ? 1 : -1);
  }
  sparks.forEach((s) => respawn(s, true));

  function stepSparks(dt) {
    const nLive = sparkEdges.length ? NS : 24;
    for (let i = 0; i < NS; i++) {
      const s = sparks[i];
      if (i >= nLive) { sPos[i * 3] = sPos[i * 3 + 1] = sPos[i * 3 + 2] = 1e6; continue; }
      s.t += dt * s.v;
      if (s.t >= 1 || s.e < 0) respawn(s, !sparkEdges.length);
      const u = (s.dir > 0 ? s.t : 1 - s.t) * K, j = Math.min(K - 1, Math.floor(u)), f = u - j, q0 = (s.e * (K + 1) + j) * 3, q1 = q0 + 3;
      for (let k = 0; k < 3; k++) {
        sPos[i * 3 + k] = (poly[q0 + k] * (1 - f) + poly[q1 + k] * f) / 16 - c0[k];
        sNrm[i * 3 + k] = (pnrm[q0 + k] * (1 - f) + pnrm[q1 + k] * f) / 127;
      }
    }
    sg.attributes.position.needsUpdate = true; sg.attributes.normal.needsUpdate = true;
  }

  // ----- state refresh
  function refresh() {
    for (let i = 0; i < nN; i++) {
      const n = nodes[i];
      nodeVis[i] = typeOn.has(n.t) && commOn.has(n.c) && n.lv.some((l) => lvOn.has(l)) ? 1 : 0;
    }
    const nb = new Set();
    if (sel >= 0) for (const e of inc[sel]) nb.add(other(e, sel));
    for (let i = 0; i < nN; i++) {
      nSt[i * 2] = nodeVis[i];
      nSt[i * 2 + 1] = i === sel ? 2 : (nb.has(i) || hits.has(i)) ? 1 : 0;
    }
    nStA.needsUpdate = true;
    const focus = sel >= 0 || hits.size > 0;
    const flag = new Uint8Array(nE); let nOn = 0;
    for (let e = 0; e < nE; e++) {
      const a = es[2 * e], b = es[2 * e + 1];
      if (!(nodeVis[a] && nodeVis[b])) continue;
      flag[e] = 1;
      if ((sel >= 0 && (a === sel || b === sel)) || (sel < 0 && hits.size > 0 && (hits.has(a) || hits.has(b)))) { flag[e] = 2; nOn++; }
    }
    const strength = Math.min(0.9, 0.9 * Math.sqrt(30 / Math.max(nOn, 1)));  // many highlighted links share the light
    for (let e = 0; e < nE; e++) lSt.fill(flag[e] === 2 ? 1 + strength : flag[e], e * SV, (e + 1) * SV);
    lStA.needsUpdate = true;
    U.uDim.value = focus ? 1 : 0;
  }

  // ----- legend, filters
  const sizes = {}; nodes.forEach((n) => { sizes[n.c] = (sizes[n.c] || 0) + 1; });
  const legend = $('#legend');
  PAL.forEach((h, i) => {
    const r = el('div', 'row'); const sw = el('span', 'sw'); sw.style.background = h;
    r.append(sw, el('span', null, NAMES[i]), el('span', 'n', sizes[i])); r.title = 'Click to show or hide; double-click to show only this';
    r.onclick = () => { commOn.has(i) ? commOn.delete(i) : commOn.add(i); r.classList.toggle('off', !commOn.has(i)); refresh(); };
    r.ondblclick = () => { commOn.clear(); commOn.add(i); [...legend.children].forEach((x, k) => x.classList.toggle('off', k !== i)); refresh(); };
    legend.append(r);
  });
  function chips(box, items, set) {
    items.forEach(([key, txt]) => {
      const c = el('span', 'chip on', txt);
      c.onclick = () => { set.has(key) ? set.delete(key) : set.add(key); c.classList.toggle('on', set.has(key)); refresh(); };
      box.append(c);
    });
  }
  chips($('#types'), B.types.map((t, i) => [i, TYPE_LABEL[t] || t]), typeOn);
  chips($('#levels'), [[1, 'HSK 1'], [2, 'HSK 2'], [3, 'HSK 3']], lvOn);
  document.querySelectorAll('[data-v]').forEach((b) => (b.onclick = () => setView(b.dataset.v)));
  $('#spin').onclick = () => { controls.autoRotate = !controls.autoRotate; };
  $('#clear').onclick = () => { hits = new Set(); sparkEdges = []; sparkFrom = -1; select(-1); };
  document.querySelectorAll('.tab').forEach((t) => (t.onclick = () => showTab(t.dataset.t)));
  function showTab(n) {
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('on', t.dataset.t === n));
    document.querySelectorAll('.pane').forEach((p) => p.classList.toggle('on', p.id === 'p-' + n));
  }

  // ----- selection
  const nodeName = (i) => nodes[i].l;
  function select(i) {
    sel = i;
    const box = $('#p-sel'); box.replaceChildren();
    if (i < 0) { box.append(el('p', 'sub', 'Click a dot to see what it connects to.')); refresh(); return; }
    hits = new Set();
    const n = nodes[i];
    box.append(el('h1', null, n.l));
    box.append(el('p', 'sub', `${TYPE_LABEL[B.types[n.t]]} · HSK ${n.lv.join(', ') || '?'} · ${NAMES[n.c]}` + (n.pg && n.pg.length ? ' · ' + n.pg.slice(0, 4).join(', ') : '')));
    box.append(el('p', 'sub', `${inc[i].length} links`));
    const byType = {};
    for (const e of inc[i]) { const o = other(e, i), t = B.types[nodes[o].t]; (byType[t] = byType[t] || []).push([o, e]); }
    Object.keys(byType).sort((a, b) => byType[b].length - byType[a].length).forEach((t) => {
      box.append(el('h2', null, `${TYPE_LABEL[t]} (${byType[t].length})`));
      byType[t].sort((x, y) => nodes[y[0]].d - nodes[x[0]].d).slice(0, 8).forEach(([o, e]) => {
        const b = el('button', 'hit', nodes[o].l); b.title = B.rels[er[e]].replace(/_/g, ' '); b.onclick = () => select(o); box.append(b);
      });
    });
    sparkEdges = inc[i].slice(); sparkFrom = i;
    refresh(); showTab('sel');
  }

  // ----- picking
  const v3 = new THREE.Vector3(), nz3 = new THREE.Vector3();
  function pick(mx, my) {
    camera.updateMatrixWorld(); let best = -1, bd = 14 * 14;
    const m = new THREE.Matrix3().getNormalMatrix(camera.matrixWorldInverse);
    for (let i = 0; i < nN; i++) {
      if (!nodeVis[i]) continue;
      v3.set(nPos[i * 3], nPos[i * 3 + 1], nPos[i * 3 + 2]);
      nz3.set(nNrm[i * 3], nNrm[i * 3 + 1], nNrm[i * 3 + 2]).applyMatrix3(m);
      if (nz3.z < -0.1 && i !== sel) continue;
      v3.project(camera); if (v3.z > 1) continue;
      const dx = (v3.x * 0.5 + 0.5) * innerWidth - mx, dy = (-v3.y * 0.5 + 0.5) * innerHeight - my, d = dx * dx + dy * dy - nodes[i].d * 0.02;
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }
  const tip = $('#tip'); let down = null;
  canvas.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
  canvas.addEventListener('pointerup', (e) => {
    if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 4) select(pick(e.clientX, e.clientY));
    down = null;
  });
  canvas.addEventListener('pointermove', (e) => {
    if (e.buttons) { tip.style.display = 'none'; return; }
    const i = pick(e.clientX, e.clientY);
    if (i < 0) { tip.style.display = 'none'; return; }
    tip.textContent = nodes[i].l; tip.style.display = 'block'; tip.style.left = e.clientX + 12 + 'px'; tip.style.top = e.clientY + 12 + 'px';
  });

  // ----- textbook chat
  const normLab = nodes.map((n) => norm(n.l));
  const log = $('#chatlog');
  function say(txt, me) { const m = el('div', 'msg' + (me ? ' me' : ''), txt); log.append(m); $('#right').scrollTop = 1e6; return m; }
  say('Ask about a character, word, or grammar point and I will find it in the textbook network. Sparks run along its real links.');
  $('#cf').onsubmit = (ev) => {
    ev.preventDefault(); const q = $('#ci').value.trim(); if (!q) return; $('#ci').value = ''; say(q, true);
    const nq = norm(q), sc = [];
    nodes.forEach((n, i) => {
      const k = normLab[i].indexOf(nq); if (k < 0) return;
      const t = B.types[n.t];
      sc.push([i, (k === 0 ? 3 : 1) + Math.log10(1 + n.d) * 0.6 - (t === 'sentence' || t === 'text' ? 0.8 : 0) + (t === 'word' || t === 'char' || t === 'grammar' ? 0.6 : 0)]);
    });
    sc.sort((a, b) => b[1] - a[1]);
    if (!sc.length) { say(`Nothing in the textbooks matches "${q}". Try a character, a pinyin syllable, or an English gloss.`); return; }
    const top = sc.slice(0, 6).map((x) => x[0]), b = top[0], nb = nodes[b];
    const chap = inc[b].map((e) => other(e, b)).filter((o) => B.types[nodes[o].t] === 'chapter').map(nodeName).filter((x, k, a) => a.indexOf(x) === k);
    const m = say(`${sc.length} matches for "${q}". Best match: ${nb.l} (${TYPE_LABEL[B.types[nb.t]].toLowerCase()}, HSK ${nb.lv.join('/') || '?'}), ${inc[b].length} links` +
      (chap.length ? `, taught in ${chap.slice(0, 3).join('; ')}${chap.length > 3 ? ` and ${chap.length - 3} more` : ''}.` : '.'));
    top.forEach((i) => { const h = el('button', 'hit', nodes[i].l); h.onclick = () => select(i); m.append(h); });
    sel = -1; hits = new Set(top);
    sparkEdges = []; top.forEach((i) => inc[i].slice(0, 40).forEach((e) => sparkEdges.push(e))); sparkFrom = b;
    refresh();
    // look at the best match from outside the brain
    const p = new THREE.Vector3(nPos[b * 3], nPos[b * 3 + 1], nPos[b * 3 + 2]);
    const dir = new THREE.Vector3(nNrm[b * 3], nNrm[b * 3 + 1], nNrm[b * 3 + 2]).normalize();
    controls.target.copy(p.clone().multiplyScalar(0.3));
    camera.position.copy(p.clone().add(dir.multiplyScalar(R * 2.8)));
  };

  AnalysisPanel.render($('#p-ana'), A, PAL, NAMES);
  refresh();

  // ----- loop
  let last = performance.now();
  renderer.setClearColor(0x07090e);
  (function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    U.uScale.value = renderer.domElement.height * 0.9;
    controls.update(); stepSparks(dt); renderer.render(scene, camera); requestAnimationFrame(frame);
  })(last);
  window.__viewer = { setView, select, camera, controls, nodes, R };
})().catch((e) => { const s = $('#status'); if (s) s.textContent = 'Failed to load: ' + e.message; console.error(e); });
