"""Allow `python -m neuro_ghost.mcp_server` to work."""
from neuro_ghost.mcp_server import mcp

if __name__ == "__main__":
    mcp.run()
