# Code origins

Code copied or adapted from `go-carbon-insights` is logged here.

| Source path | Verified source commit | What changed | Why |
|---|---|---|---|
| `services/hypergraph-rag/scripts/core/score_ground_truth.py` (scorer 1.1.0) | `64e80947d20a0d17e9f89f431245bfa0aedc15ef` | `normalize`, `number_tokens`, and their number-token expression were copied into `gct/measure/g2.py`. The two function bodies match this source snapshot. | Keep G2 text and number normalization consistent with the frozen scorer. |

The source commit above identifies a verified matching snapshot. The original copying-source commit was not recorded.
The copied code is licensed under MIT, copyright (c) 2025 GoCarbonTracker.
The MIT permission and warranty text is included in `LICENSE`; retain this copyright attribution with the copied code.

## Dependency notes

- reportlab (BSD licence, used for the PDF reports): its wheel also carries the DarkGarden font files
  (`reportlab/fonts/DarkGarden*`, GPL 2 or later with a font-embedding exception). GCT never registers or embeds
  them; it registers only reportlab's Vera fonts (Bitstream Vera licence), by path. `tests/test_licences.py` reads
  licence metadata, which cannot see font files inside a wheel, so this note records them;
  `tests/test_render_pdf.py` checks that no registered font name starts with DarkGarden.

## Third-party code in the committed viewer build

`gct/viewer_dist/assets/*.js` bundles these packages, minified by Vite, with their `@license` comments kept. Build-only packages are listed in `viewer/README.md`.

| Package | Version | Licence |
|---|---|---|
| react | 18.3.1 | MIT |
| react-dom | 18.3.1 | MIT |
| scheduler | 0.23.2 | MIT |
| Vite's module preload helper (part of vite) | 6.4.4 | MIT |
| cytoscape | 3.34.3 | MIT |

Cytoscape's own copyright notice is not kept in the minified bundle, so `gct/viewer_dist/NOTICES.txt` (copied from `viewer/public/NOTICES.txt`) carries its licence. Cytoscape's code embeds four further notices, kept in the bundle and repeated in `NOTICES.txt`: the Promises/A+ thenable (Ralf S. Engelschall), the Bezier curve function generator (Gaetan Renaudeau), the Runge-Kutta spring generator adapted from Framer.js (Koen Bok) and the event object based on jQuery events (MIT).
