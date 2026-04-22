"""aletheia-mcp server.

Defines the MCP server and registers tools that AI agents can call.
Each tool is a plain async Python function with a @mcp.tool() decorator.
FastMCP handles all JSON-RPC message passing, schema generation, and I/O.
"""
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from aletheia_mcp.sources import semantic_scholar

# Load environment variables from .env at project root (if present).
# Resolves symlinks so it works regardless of where the subprocess is launched
# from. Path walks: server.py → aletheia_mcp → src → project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# Create the MCP server. The name appears in MCP client UIs and logs.
mcp = FastMCP("aletheia-mcp")


@mcp.tool()
async def search_papers(query: str, limit: int = 10) -> dict:
    """Search scientific literature for papers matching a query.

    Searches across millions of papers indexed by Semantic Scholar, which
    aggregates content from arXiv, PubMed, PubMed Central, DBLP, and many
    other scientific sources. Good for finding papers by topic, author,
    or concept.

    Args:
        query: Natural language search terms. Examples:
            - "mitochondrial dysfunction Parkinson's disease"
            - "attention is all you need"
            - "CRISPR gene editing ethics"
        limit: Maximum papers to return (1-100, default 10).

    Returns:
        Dict with:
        - query: the search string that was used
        - total: total matches in the corpus (may exceed limit)
        - papers: list of paper objects. Each includes paperId, title,
          abstract, authors, year, citationCount, venue, externalIds
          (for linking to arXiv/PubMed/DOI), and openAccessPdf when available.
    """
    return await semantic_scholar.search_papers(query, limit)


def main() -> None:
    """Entry point — runs the MCP server using stdio transport.

    MCP clients (Claude Desktop, Cursor, Claude Code, etc.) launch this
    server as a subprocess and communicate over stdin/stdout using JSON-RPC.
    """
    mcp.run()


if __name__ == "__main__":
    main()
