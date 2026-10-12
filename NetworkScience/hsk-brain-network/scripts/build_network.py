#!/usr/bin/env python3
"""Build the HSK language network:
characters -> words -> sentences -> grammar rules -> chapters -> books.
Inputs (all in --proj): graph.json export, classify_out_*.json, chapters_level*.json,
optional homograph_decisions.json and pattern_links.json.  Output: network.json."""
import json, re, sys, glob, collections, unicodedata
from pathlib import Path

REPO = Path(sys.argv[1]); PROJ = Path(sys.argv[2])
G = json.loads((REPO / 'graphify-out/graph.json').read_text(encoding='utf-8'))
EXT = json.loads((REPO / 'graphify-out/.graphify_extract_final.json').read_text(encoding='utf-8'))
kind0 = {n['id']: n.get('kind') for n in EXT['nodes']}
HZ = re.compile(r'[一-鿿]')

# ---------- chapters ----------
page_ch = {}   # (level, page) -> (chapter_id | None, section)
chapters = {}  # id -> dict
for L in (1, 2, 3):
    f = PROJ / f'chapters_level{L}.json'
    d = json.loads(f.read_text(encoding='utf-8'))
    for num, c in d['chapters'].items():
        cid = f'ch_{L}_{int(num):02d}'
        chapters[cid] = {'id': cid, 'type': 'chapter', 'level': L, 'num': int(num),
                         'label': f"HSK {L} Lesson {int(num)}: {c.get('title_en') or c.get('title_zh') or ''} {c.get('title_zh') or ''}".strip(),
                         'start': c.get('start_page'), 'end': c.get('end_page')}
    for p, v in d['pages'].items():
        ch = v['chapter']
        page_ch[(L, int(p))] = (f'ch_{L}_{int(ch):02d}' if isinstance(ch, int) and ch > 0 else None, v.get('section'))


def src_of(n):
    m = re.match(r'level(\d)/page_(\d+)', n.get('source_file') or '')
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


# ---------- typing ----------
cls = {}
for f in sorted(glob.glob(str(PROJ / 'classify_out_*.json'))):
    for r in json.loads(Path(f).read_text(encoding='utf-8')):
        cls[r['id']] = r
fmt = re.compile(r'^([一-鿿][一-鿿……～~]*)\s*[\(（]')
PYRE = re.compile(r'[\(（]([^)）]*)[\)）]')


def toneless(s):
    s = unicodedata.normalize('NFD', (s or '').lower())
    return re.sub(r'[^a-zü]', '', re.sub(r'[̀-ͯ]', '', s)).replace('ü', 'v')


info = {}
for n in G['nodes']:
    nid = n['id']; k = kind0.get(nid)
    t = None; head = ''; py = ''; proper = False
    if nid in cls:
        r = cls[nid]; t = r['type']; head = r.get('headword') or ''; py = r.get('pinyin') or ''; proper = bool(r.get('proper'))
    elif k == 'sentence':
        t = 'sentence'
    elif k == 'grammar':
        t = 'grammar'
    elif k == 'vocab':
        m = fmt.match(n['label'])
        t = 'word'; head = m.group(1) if m else ''
        mm = PYRE.search(n['label']); py = mm.group(1) if mm else ''
    else:
        t = 'other'
    info[nid] = {'type': t, 'head': head, 'py': py, 'proper': proper, 'node': n}

KEEP = {'word', 'character', 'sentence', 'grammar', 'dialogue', 'lesson', 'culture', 'radical_stroke', 'phonetics'}

# ---------- homograph decisions ----------
hom = {}
hf = PROJ / 'homograph_decisions.json'
if hf.exists():
    hom = json.loads(hf.read_text(encoding='utf-8'))   # {headword: {old_id: sense_key}}


def word_key(nid):
    i = info[nid]; h = i['head']
    if h in hom and nid in hom[h]:
        return f'{h}#{hom[h][nid]}'
    return h


# ---------- canonical nodes ----------
nodes = {}      # id -> dict
old2new = {}


def add_node(nid, **kw):
    if nid not in nodes:
        nodes[nid] = {'id': nid, 'pages': [], 'lvs': [], 'old': []}
    d = nodes[nid]
    for k, v in kw.items():
        if k in ('pages', 'lvs', 'old'):
            for x in v:
                if x not in d[k]:
                    d[k].append(x)
        elif v and not d.get(k):
            d[k] = v
    return d


for nid, i in info.items():
    t = i['type']
    if t not in KEEP:
        continue
    L, P = src_of(i['node'])
    pg = [f'L{L}p{P}'] if L else []
    lv = [L] if L else []
    lab = i['node']['label']
    if t == 'sentence':
        add_node(nid, type='sentence', label=lab, pages=pg, lvs=lv, old=[nid]); old2new[nid] = nid
    elif t == 'grammar':
        add_node(nid, type='grammar', label=lab, pages=pg, lvs=lv, old=[nid]); old2new[nid] = nid
    elif t == 'word' and i['head']:
        h = i['head']
        if len(re.sub(r'[^一-鿿]', '', h)) == 1 and h == re.sub(r'[^一-鿿]', '', h):
            cid = f'c_{h}'
            add_node(cid, type='char', head=h, pages=pg, lvs=lv, old=[nid], is_word=True, pinyin=i['py'], label=lab)
            old2new[nid] = cid
        else:
            wk = word_key(nid); wid = f'w_{wk}'
            add_node(wid, type='word', head=h, pages=pg, lvs=lv, old=[nid], pinyin=i['py'], label=lab, proper=i['proper'])
            old2new[nid] = wid
    elif t == 'character' and i['head'] and len(re.sub(r'[^一-鿿]', '', i['head'])) == 1:
        h = re.sub(r'[^一-鿿]', '', i['head']); cid = f'c_{h}'
        add_node(cid, type='char', head=h, pages=pg, lvs=lv, old=[nid], label=lab); old2new[nid] = cid
    elif t == 'lesson':
        m = re.match(r'^\s*(?:Lesson|Unit|第)\s*(\d+)', lab)
        if m and L and f'ch_{L}_{int(m.group(1)):02d}' in chapters:
            old2new[nid] = f'ch_{L}_{int(m.group(1)):02d}'
    else:
        ty = {'dialogue': 'text', 'culture': 'culture', 'radical_stroke': 'radical', 'phonetics': 'phonetics'}.get(t)
        if ty:
            add_node(nid, type=ty, label=lab, pages=pg, lvs=lv, old=[nid]); old2new[nid] = nid

# chapter and book nodes
for cid, c in chapters.items():
    nodes[cid] = {'id': cid, 'type': 'chapter', 'label': c['label'], 'pages': [], 'lvs': [c['level']], 'old': [], 'level': c['level']}
for L in (1, 2, 3):
    nodes[f'book_{L}'] = {'id': f'book_{L}', 'type': 'book', 'label': f'HSK Standard Course {L}', 'pages': [], 'lvs': [L], 'old': []}

# ---------- characters from word headwords ----------
EDGES = collections.OrderedDict()   # (a,b,rel) -> dict


def add_edge(a, b, rel, prov, w=1.0):
    if a == b or a not in nodes or b not in nodes:
        return
    key = (a, b, rel) if a < b else (b, a, rel)
    e = EDGES.get(key)
    if e is None:
        EDGES[key] = {'s': key[0], 't': key[1], 'rel': rel, 'prov': prov, 'w': w}
    else:
        e['w'] += w
        order = {'text': 0, 'match': 1, 'llm': 2}
        if order.get(prov, 2) < order.get(e['prov'], 2):
            e['prov'] = prov


def ensure_char(c):
    cid = f'c_{c}'
    if cid not in nodes:
        nodes[cid] = {'id': cid, 'type': 'char', 'head': c, 'label': c, 'pages': [], 'lvs': [], 'old': []}
    return cid


for wid in [k for k, v in nodes.items() if v['type'] == 'word']:
    h = nodes[wid]['head']
    for c in HZ.findall(h):
        add_edge(ensure_char(c), wid, 'char_in_word', 'text')

# ---------- old edges remapped ----------
for e in G['links']:
    a = old2new.get(e['source']); b = old2new.get(e['target'])
    if not a or not b or a == b:
        continue
    prov = 'text' if e.get('confidence') == 'EXTRACTED' else 'llm'
    add_edge(a, b, e.get('relation') or 'related', prov)

# ---------- sentence segmentation ----------
words_by_head = collections.defaultdict(list)
for k, v in nodes.items():
    if v['type'] == 'word':
        words_by_head[v['head']].append(k)
HEADS = set(h for h in words_by_head if 2 <= len(re.sub(r'[^一-鿿]', '', h)) and h == re.sub(r'[^一-鿿]', '', h))
MAXL = max(len(h) for h in HEADS)
SPLIT = re.compile(r'^(.*?)\s*\((?=[A-Za-zÀ-ɏ])')


def sent_text(label):
    m = SPLIT.match(label); return (m.group(1) if m else label)


seg_stats = collections.Counter()
for sid in [k for k, v in nodes.items() if v['type'] == 'sentence']:
    t = sent_text(nodes[sid]['label']); i = 0
    runs = []
    while i < len(t):
        if not HZ.match(t[i]):
            i += 1; continue
        j = i
        while j < len(t) and HZ.match(t[j]):
            j += 1
        run = t[i:j]; p = 0
        while p < len(run):
            for L in range(min(MAXL, len(run) - p), 1, -1):
                if run[p:p + L] in HEADS:
                    for wid in words_by_head[run[p:p + L]][:1]:
                        add_edge(sid, wid, 'sentence_has_word', 'match'); seg_stats['word'] += 1
                    m_ = run[p:p + L]
                    for a2 in range(len(m_)):
                        for b2 in range(a2 + 2, len(m_) + 1):
                            if (a2, b2) != (0, len(m_)) and m_[a2:b2] in HEADS:
                                add_edge(sid, words_by_head[m_[a2:b2]][0], 'sentence_has_word', 'match'); seg_stats['inner'] += 1
                    p += L; break
            else:
                add_edge(sid, ensure_char(run[p]), 'sentence_has_char', 'text'); seg_stats['char'] += 1
                p += 1
        i = j
print('segmentation links', dict(seg_stats))

# ---------- chapter membership by page ----------
cnt = collections.Counter()
for nid, v in list(nodes.items()):
    if v['type'] in ('chapter', 'book', 'char') and not (v['type'] == 'char' and v.get('is_word')):
        continue
    for pg in v['pages']:
        m = re.match(r'L(\d)p(\d+)', pg)
        ch = page_ch.get((int(m.group(1)), int(m.group(2))), (None, None))[0]
        if ch:
            rel = {'sentence': 'sentence_in_chapter', 'word': 'word_in_chapter', 'char': 'word_in_chapter', 'grammar': 'grammar_in_chapter'}.get(v['type'], 'content_in_chapter')
            add_edge(nid, ch, rel, 'text'); cnt[rel] += 1
for cid, c in chapters.items():
    add_edge(cid, f"book_{c['level']}", 'chapter_in_book', 'text')
print('chapter links', dict(cnt))

# ---------- grammar -> sentence pattern links ----------
pf = PROJ / 'pattern_links.json'
if pf.exists():
    for r in json.loads(pf.read_text(encoding='utf-8')):
        add_edge(r['grammar'], r['sentence'], 'pattern_match', 'match', r.get('score', 1.0))

# ---------- finalise ----------
deg = collections.Counter()
for e in EDGES.values():
    deg[e['s']] += 1; deg[e['t']] += 1
drop = [k for k, v in nodes.items() if deg[k] == 0 and v['type'] not in ('book',)]
for k in drop:
    del nodes[k]
for k, v in nodes.items():
    v['lvs'] = sorted(set(v['lvs']))
out = {'nodes': list(nodes.values()), 'edges': list(EDGES.values()),
       'meta': {'dropped_isolates': len(drop), 'types': dict(collections.Counter(v['type'] for v in nodes.values())),
                'edge_types': dict(collections.Counter(e['rel'] for e in EDGES.values())),
                'prov': dict(collections.Counter(e['prov'] for e in EDGES.values()))}}
(PROJ / 'network.json').write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
print('nodes', len(nodes), 'edges', len(EDGES)); print(out['meta'])
