---
description: Pull latest GCT code, sync workspace pipeline, rebuild published data version, and refresh viewer
---

# /gct-update Slash Command

Synchronize GoCarbonTracker codebase, update workspace data pipeline, and refresh the live viewer.

## Arguments
`$ARGUMENTS`: Optional workspace path. Defaults to active workspace or `/Users/varunmoka/GTC/GTC RND/adidas-workspace`.

## Execution Steps

1. **Pull & Sync Repos**:
   ```bash
   cd "/Users/varunmoka/GTC/gct-release" && git pull origin main
   cd "/Users/varunmoka/GTC/GTC RND/go-carbon-tracker" && git pull origin main
   ```

2. **Verify Package & UI**:
   ```bash
   cd "/Users/varunmoka/GTC/GTC RND/go-carbon-tracker"
   .venv/bin/pip install -e .
   ```

3. **Run Workspace Update**:
   ```bash
   gct update --workspace "${ARGUMENTS:-/Users/varunmoka/GTC/GTC RND/adidas-workspace}"
   ```

4. **Restart Viewer**:
   Relaunch `gct serve` on port 8765 if active and present the updated URL.
