"""Entry point of the Claude Desktop extension: run the garmin-dynamic-mcp server over stdio."""

from garmin_dynamic_mcp.server import serve

if __name__ == "__main__":
    serve()
