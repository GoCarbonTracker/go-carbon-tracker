---
description: Run GoCarbonTracker operations (update, serve, status) across workspaces and codebases
---

# /gct Slash Command

Use `/gct` to manage GoCarbonTracker pipelines, workspace updates, and viewer instances.

## Usage
- `/gct update [workspace]`: Pull latest GCT code, ensure build/install freshness, run incremental workspace update (`link` -> `infer` -> `match` -> `publish build`), and refresh live viewer.
- `/gct status [workspace]`: Report current data version, claim counts, and restatement pairs.
- `/gct serve [workspace]`: Launch or restart the local evidence viewer.

---

## `/gct update` Execution Workflow

When invoked with `update`:

1. **Synchronize Repositories**:
   Ensure both `gct-release` and `GTC RND/go-carbon-tracker` are synced with `main`:
   ```bash
   cd "/Users/varunmoka/GTC/gct-release" && git pull origin main
   cd "/Users/varunmoka/GTC/GTC RND/go-carbon-tracker" && git pull origin main
   ```

2. **Verify Python & Frontend Environment**:
   ```bash
   cd "/Users/varunmoka/GTC/GTC RND/go-carbon-tracker"
   .venv/bin/pip install -e .
   ```
   If frontend source files under `viewer/src/` changed without a dist rebuild:
   ```bash
   cd viewer && npm run build
   ```

3. **Execute Incremental Workspace Pipeline**:
   Target the workspace specified in `$ARGUMENTS` (defaults to current active workspace or `/Users/varunmoka/GTC/GTC RND/adidas-workspace`):
   ```bash
   gct update --workspace "$WORKSPACE"
   ```

4. **Refresh Live Viewer Daemon**:
   If a `gct serve` background task is active for this workspace, restart it on port 8765:
   ```bash
   gct serve --workspace "$WORKSPACE" --port 8765 --no-open
   ```

5. **Report Summary**:
   Output the updated version, number of documents, total claims, comparable pairs, and the direct clickable link to the viewer: `http://127.0.0.1:8765/?token=...`.
