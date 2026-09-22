# VN Patch Manager - Decky Loader Plugin

Seamlessly check visual novel patch statuses and apply 18+ English patches directly from the **SteamOS Game Mode Quick Access Menu (QAM)** on your Steam Deck!

## Architecture

This plugin interacts with the local VNPM JSON-RPC daemon over UNIX domain socket (`~/.cache/vnpatchmanager/vnpm.sock`).

```
[ Steam Deck QAM ] <-> [ Decky Plugin (React) ]
                             |
                      [ Decky main.py ]
                             | (UNIX Domain Socket JSON-RPC)
                      [ vnpm --daemon ]
                             |
              [ SteamScanner & PatchExecutionEngine ]
```

## Installation & Development

1. Ensure VNPM is installed:
   ```bash
   pip install -e .
   ```
2. Symlink or copy `decky-plugin/` into your Decky plugins directory:
   ```bash
   ln -s "$(pwd)/decky-plugin" ~/homebrew/plugins/decky-vnpm
   ```
3. Run the background daemon (or enable systemd user service):
   ```bash
   vnpm --daemon
   ```
4. Build the plugin frontend:
   ```bash
   cd decky-plugin && pnpm install && pnpm run build
   ```
5. Press the `(...)` button on your Steam Deck to access VNPM right inside Game Mode!
