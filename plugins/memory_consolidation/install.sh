#!/usr/bin/env bash
set -euo pipefail

# Memory Consolidation — one-line installer for OpenClaw
# Usage: bash install.sh
#
# Installs:
#   1. memory_consolidation.py + prompts/ → ~/.openclaw/workspace/memory_consolidation/
#   2. agent:bootstrap hook → ~/.openclaw/hooks/memory-stm-refresh/
#   3. Enables hooks.internal + hook entry in openclaw.json
#   4. Restarts gateway + runs initial memory generation

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OC_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
INSTALL_DIR="$OC_HOME/workspace/memory_consolidation"
HOOK_SRC="$SCRIPT_DIR/openclaw-hooks/memory-stm-refresh"
HOOK_DST="$OC_HOME/hooks/memory-stm-refresh"

# --- Preflight ---
if ! command -v openclaw &>/dev/null; then echo "Error: openclaw not found"; exit 1; fi
if [ ! -f "$OC_HOME/openclaw.json" ]; then echo "Error: $OC_HOME/openclaw.json not found"; exit 1; fi
if ! command -v python3 &>/dev/null; then echo "Error: python3 not found"; exit 1; fi

# --- Install script + prompts ---
echo "Installing memory_consolidation to $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR/prompts"
cp "$SCRIPT_DIR/memory_consolidation.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/prompts/"*.py "$INSTALL_DIR/prompts/"

cp "$SCRIPT_DIR/memory_consolidation.template.env" "$INSTALL_DIR/"
if [ ! -f "$INSTALL_DIR/memory_consolidation.env" ]; then
    cp "$SCRIPT_DIR/memory_consolidation.template.env" "$INSTALL_DIR/memory_consolidation.env"
    echo "  Created default memory_consolidation.env"
else
    echo "  Existing memory_consolidation.env preserved"
fi

# --- Install hooks ---
echo "Installing bootstrap hook (STM) to $HOOK_DST ..."
mkdir -p "$HOOK_DST"
cp "$HOOK_SRC/HOOK.md" "$HOOK_DST/"
cp "$HOOK_SRC/handler.ts" "$HOOK_DST/"

# --- Clean up old plugin + old hooks (replaced by single hook) ---
OLD_LTM_HOOK="$OC_HOME/hooks/memory-ltm-diary"
[ -d "$OLD_LTM_HOOK" ] && rm -rf "$OLD_LTM_HOOK" && echo "  Removed old hook: $OLD_LTM_HOOK"
OLD_PLUGIN="$OC_HOME/extensions/kimi-memory-consolidation"
OLD_PLUGIN2="$OC_HOME/extensions/memory-consolidation"
[ -d "$OLD_PLUGIN" ] && rm -rf "$OLD_PLUGIN" && echo "  Removed old plugin: $OLD_PLUGIN"
[ -d "$OLD_PLUGIN2" ] && rm -rf "$OLD_PLUGIN2" && echo "  Removed old plugin: $OLD_PLUGIN2"

# --- Update openclaw.json ---
echo "  Updating $OC_HOME/openclaw.json ..."
python3 - "$OC_HOME/openclaw.json" << 'PYEOF'
import json, sys, traceback
try:
    cfg_path = sys.argv[1]
    with open(cfg_path) as f:
        cfg = json.load(f)
    dirty = False

    # Enable internal hooks (required for agent:bootstrap)
    hooks = cfg.setdefault('hooks', {})
    internal = hooks.setdefault('internal', {})
    if not internal.get('enabled'):
        internal['enabled'] = True
        dirty = True
        print('  Enabled hooks.internal.')

    # Enable memory-stm-refresh hook entry
    entries = internal.setdefault('entries', {})
    for hook_id in ['memory-stm-refresh']:
        if entries.get(hook_id, {}).get('enabled') is not True:
            entries[hook_id] = {'enabled': True}
            dirty = True
            print(f'  Enabled {hook_id} hook.')

    # Clean up old plugin entries
    plugins = cfg.get('plugins', {})
    p_entries = plugins.get('entries', {})
    for old_id in ['kimi-memory-consolidation', 'memory-consolidation']:
        if old_id in p_entries:
            del p_entries[old_id]
            dirty = True
            print(f'  Removed old plugin entry: {old_id}')
    allow = plugins.get('allow')
    if isinstance(allow, list):
        for old_id in ['kimi-memory-consolidation', 'memory-consolidation']:
            if old_id in allow:
                allow.remove(old_id)
                dirty = True

    # Clean up legacy keys
    if 'roots' in plugins:
        del plugins['roots']
        dirty = True

    if dirty:
        with open(cfg_path, 'w') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write('\n')
        print('  Config updated.')
    else:
        print('  Config already up to date.')
except Exception:
    traceback.print_exc()
    sys.exit(1)
PYEOF

# --- Restart gateway ---
echo "Restarting gateway ..."
openclaw gateway stop 2>/dev/null || true
openclaw gateway start 2>/dev/null || {
    echo "Warning: could not restart gateway automatically."
    echo "  Run manually: openclaw gateway stop && openclaw gateway start"
}

# --- Initial memory generation ---
SESSION_COUNT=$(python3 "$INSTALL_DIR/memory_consolidation.py" stats 2>&1 | grep -oP '\d+(?= sessions)' | head -1 || echo "0")
if [ "${SESSION_COUNT:-0}" -ge 5 ]; then
    echo "Running initial compact ($SESSION_COUNT sessions) ..."
    python3 "$INSTALL_DIR/memory_consolidation.py" compact 2>&1 | sed 's/^/  /' || {
        python3 "$INSTALL_DIR/memory_consolidation.py" stm 2>&1 | sed 's/^/  /' || true
    }
else
    echo "Running initial STM ($SESSION_COUNT sessions, compact needs >= 5) ..."
    python3 "$INSTALL_DIR/memory_consolidation.py" stm 2>&1 | sed 's/^/  /' || true
fi

# Seed bootstrap hook state
python3 -c "
import json, os
sessions_path = os.path.join('$OC_HOME', 'agents', 'main', 'sessions', 'sessions.json')
try:
    with open(sessions_path) as f:
        store = json.load(f)
    for key, entry in store.items():
        if 'cron' in key: continue
        sid = entry.get('sessionId', '')
        if sid:
            with open('/tmp/memory-stm-last-session.json', 'w') as f:
                json.dump({'sessionId': sid}, f)
            break
except: pass
" 2>/dev/null

echo ""
echo "Done. Memory consolidation installed."
echo "  Script: $INSTALL_DIR/memory_consolidation.py"
echo "  Config: $INSTALL_DIR/memory_consolidation.env"
echo "  Hook:   $HOOK_DST (agent:bootstrap)"
echo ""
echo "To verify: python3 $INSTALL_DIR/memory_consolidation.py stats"
