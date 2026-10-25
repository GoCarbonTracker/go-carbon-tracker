---
name: gct-update
description: Pull latest GCT release code, update workspace pipeline (link, infer, match, publish build), and refresh live viewer. Usage: /gct update [workspace]
---

# GoCarbonTracker Update Skill (`/gct update`)

Use this skill when the user runs `/gct update`, `/gct-update`, or asks to update a GCT workspace with the latest pipeline and UI.

## Workflow

1. **Synchronize Repositories**:
   Pull latest commits for `gct-release` and `GTC RND/go-carbon-tracker`:
   ```bash
   cd "/Users/varunmoka/GTC/gct-release" && git pull origin main
   cd "/Users/varunmoka/GTC/GTC RND/go-carbon-tracker" && git pull origin main
   ```

2. **Ensure Build Freshness**:
   ```bash
   cd "/Users/varunmoka/GTC/GTC RND/go-carbon-tracker"
   .venv/bin/pip install -e .
   ```

3. **Run Incremental Workspace Update**:
   Execute the unified update command:
   ```bash
   gct update --workspace "$WORKSPACE"
   ```
   This automatically runs:
   - `gct link`: checks claims against source page readings
   - `gct infer`: proposes periods and reporting boundaries
   - `gct match`: links comparable multi-year series
   - `gct publish build`: publishes the updated data version

4. **Refresh Viewer**:
   Relaunch `gct serve` on port 8765 and report the tokenized access URL.
