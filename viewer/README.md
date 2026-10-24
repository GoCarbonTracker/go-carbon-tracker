# Evidence viewer (contributors only)

The viewer `gct serve` shows at `/`. Users never need Node: the built viewer is committed in `gct/viewer_dist/` and ships inside the `gct` package. This folder is its source, for contributors who change it.

React 18, TypeScript and Vite, with React state and one CSS file (`src/style.css`). Pages are rendered by the server as PNG (`/api/documents/{id}/pages/{n}.png`); the viewer draws the evidence boxes over them as SVG.

## Build

```
npm ci
npm run build
```

`npm ci` installs the exact versions in `package-lock.json`. `npm run build` type-checks (`tsc --noEmit`), builds into `../gct/viewer_dist/` and writes `../gct/viewer_dist/SOURCE.sha256`, the hash of the source files listed in `vite.config.ts`. Commit the source change and the new build together: `tests/test_viewer.py` fails when `SOURCE.sha256` does not match the source, and, when `node_modules/` is present, when a rebuild is not byte-identical to the committed build.

The pure viewer logic (`src/logic.ts`) has its own tests, run with Node's test runner and no framework:

```
node --test test/logic.test.ts
```

## Build provenance

The original viewer build used locally copied packages because downloads were not allowed. Cytoscape 3.34.3 was added from another local install. Its lockfile entry was written by hand using an integrity value from another project's lockfile. No registry install or package comparison was performed for that build.

The cached npm registry archives for React 18.3.1, React DOM 18.3.1, Scheduler 0.23.2, Cytoscape 3.34.3 and Vite 6.4.4 have since been checked against their lockfile integrity values. Each archive matched. The corresponding React, Vite and Cytoscape licence text accompanies the committed build in `NOTICES.txt`.

This offline archive check does not prove that the committed JavaScript was built from those packages. A rebuild with verified dependencies and a comparison against the committed assets remains pending. A clean dependency installation has not been demonstrated. Keep those checks separate from the source hash and the presence of licence notices.

## What ships

The built bundle contains react, react-dom and scheduler (MIT), and cytoscape (MIT) in its own chunk, loaded only when the Graphs tab is first shown; all are listed with their versions in `../ORIGINS.md`. `public/NOTICES.txt` is copied unchanged to `../gct/viewer_dist/NOTICES.txt` by each build and ships beside the bundle: it carries Cytoscape's licence, which its minified code does not keep, and the four notices embedded in its code. Everything else in `package-lock.json` is used only to build and is not shipped: vite, @vitejs/plugin-react (with Babel), typescript, @types/react, @types/react-dom and their dependencies.
