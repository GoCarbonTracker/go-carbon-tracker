# Code origins

Code copied or adapted from `go-carbon-insights` is logged here. Nothing has been copied yet.

| Source path | Commit | What changed | Why |
|---|---|---|---|

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
