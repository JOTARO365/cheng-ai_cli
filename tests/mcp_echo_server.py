"""A tiny stdio MCP server used by test_mcp_client (one 'echo' tool)."""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("echo-test")


@mcp.tool()
def echo(text: str) -> str:
    """Echo the given text back."""
    return f"echo: {text}"


if __name__ == "__main__":
    mcp.run()
