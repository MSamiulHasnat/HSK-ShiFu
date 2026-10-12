# HSK 1-3 Language Network: key numbers

**Nodes** are the teaching units of the three HSK Standard Course textbooks: 2850 sentence, 932 char, 651 word, 311 grammar, 197 phonetics, 190 text, 122 radical, 73 culture, 50 chapter, 3 book.
**Links** are relations stated or implied by the books: a character occurs in a word, a word or character occurs in a sentence,
a sentence illustrates a grammar rule, and a lesson contains a sentence, word or rule (most common relations: sentence_has_char (14057), sentence_has_word (6651), contains_word (3415), sentence_in_chapter (2845)).
The graph is treated as undirected and simple. Link provenance: 78% read directly from the text,
18% found by string matching, 3% extracted by a language model.

## Size
| Quantity | Value |
|---|---|
| Nodes N / links L | 5379 / 32076 |
| Mean degree, density | 11.93, 0.0022 |
| Largest degree, k2/k | 745, 72.6 |
| Connected components, giant fraction | 1, 100.0% |
| Power-law tail (degree >= 8) | alpha = 2.75, KS distance 0.041 |
| Average clustering / transitivity | 0.164 / 0.015 |
| Average shortest path / diameter (giant) | 3.45 / 8 |
| Random graph clustering / path (mean of 3) | 0.0021 / 3.73 |
| Small-world sigma / omega | 85.8 / 0.84 |
| Louvain fine communities, Q | 32, 0.383 |
| Major communities, Q | 8, 0.357 (0 strong, 2 weak) |
| NMI major vs chapter / vs HSK level | 0.39 / 0.10 |
| Giant fraction after 20% removed: random / degree / betweenness | 78% / 44% / 62% |

## Key findings
1. The HSK 1-3 network has 5379 nodes and 32076 links (mean degree 11.9, density 0.0022) and 100.0% of nodes lie in a single connected giant component.
2. Degrees are very uneven: the mean is 11.9 but the largest hub (char node '我 wǒ (character, I/me)') has 745 links, and k2/k = 72.6.
3. A discrete power law fits the tail above degree 8 with exponent alpha = 2.75, and clearly beats an exponential, but a likelihood-ratio test cannot separate the power law from a lognormal (p = 0.320962).
4. Average clustering is 0.164, about 79 times that of equal-size random graphs (0.0021), while the average path length of the giant component is 3.45 versus 3.73 for random graphs, so the network is small-world by sigma but not by omega (sigma = 85.8, omega = 0.84; diameter 8).
5. The most central node is '我 wǒ (character, I/me)' by degree and '的 (de) - attributive particle' by sampled betweenness; degree and PageRank agree closely (Spearman 0.97) and the innermost k-shell is 9 holding 1398 nodes.
6. Louvain finds 32 fine communities (Q = 0.38), merged into 8 major ones (Q = 0.36); 0 of the 8 are strong and 2 are weak, and the strongest keeps 36% of its links inside.
7. Major communities line up with the book structure: NMI is 0.39 against chapters and 0.10 against HSK level, and 39% of characters occur in two or more chapters (most widespread: '你 (nǐ) — you' in 50 chapters).
8. Removing 20% of nodes at random leaves 78% of the network in the giant component, but removing the top 20% by degree leaves 44% and by sampled betweenness 62%, so the network resists failure better than targeted attack.

## Caveats
Path length, closeness, eigenvector, Katz and betweenness use the giant component; betweenness is sampled from 300 source nodes;
the lattice reference for omega is the analytic ring-lattice clustering; the Louvain partitions were computed with edge weights
that include chapter links, so agreement with chapters is partly built in. All random steps use seed 42.
