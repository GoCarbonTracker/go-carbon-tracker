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

Known limits of this setup: for the story that added the viewer, `node_modules/` was filled from a local copy of the same locked packages, because no download was allowed. The registry install with `npm ci` was not run, and no check of the installed packages against the registry tarballs was made.

## What ships

The built bundle contains react, react-dom and scheduler (MIT), listed with their versions in `../ORIGINS.md`. Everything else in `package-lock.json` is used only to build and is not shipped: vite, @vitejs/plugin-react (with Babel), typescript, @types/react, @types/react-dom and their dependencies.
