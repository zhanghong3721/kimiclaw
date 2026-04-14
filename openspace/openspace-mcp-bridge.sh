#!/bin/bash
# OpenSpace MCP Server Launcher for OpenClaw
# Usage: openspace-mcp-bridge [--transport stdio|sse|streamable-http]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="/root/.openclaw/openspace/.venv"

if [ ! -d "$VENV_PATH" ]; then
    echo "Error: OpenSpace virtual environment not found at $VENV_PATH" >&2
    exit 1
fi

source "$VENV_PATH/bin/activate"

# Parse arguments
TRANSPORT="stdio"
while [[ $# -gt 0 ]]; do
    case $1 in
        --transport)
            TRANSPORT="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: openspace-mcp-bridge [--transport stdio|sse|streamable-http]"
            exit 0
            ;;
        *)
            shift
            ;;
    esac
done

exec openspace-mcp --transport "$TRANSPORT"