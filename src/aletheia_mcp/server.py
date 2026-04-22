"""aletheia-mcp server.

Defines the MCP server and registers tools that AI agents can call.
Each tool is a plain async Python function with a @mcp.tool() decorator.
FastMCP handles all JSON-RPC message passing, schema generation, and I/O.
"""
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from aletheia_mcp.sources import semantic_scholar

# Load environment variables from .env at project root (if present).
# Path walks: server.py → aletheia_mcp → src → project root.
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


@mcp.tool()
async def get_paper_details(paper_id: str) -> dict:
    """Fetch detailed information about a single paper by identifier.

    Use this when you have a specific paper ID and want its full metadata.
    Common sources of IDs: results from search_papers (use paperId field),
    or user-provided DOIs, arXiv IDs, PubMed IDs.

    Supported identifier formats:
    - Semantic Scholar ID: "649def34f8be52c8b66281af98ae884c09aef38b"
    - DOI (must include prefix): "DOI:10.1038/nature12373"
    - arXiv ID (must include prefix): "arXiv:2106.15928"
    - PubMed ID (must include prefix): "PMID:27889204"

    Args:
        paper_id: Any supported identifier (see formats above).

    Returns:
        Paper dict with paperId, title, abstract, authors, year,
        citationCount, venue, externalIds, url, openAccessPdf. Returns
        an error dict with 'error': 'not_found' if the identifier
        doesn't resolve to a known paper.
    """
    return await semantic_scholar.get_paper_details(paper_id)


@mcp.tool()
async def get_citation_graph(
    paper_id: str,
    direction: Literal["citations", "references"] = "citations",
    limit: int = 10,
) -> dict:
    """Traverse the citation graph forward or backward from a paper.

    Two directions answer different research questions:

    - direction="citations": Returns papers that CITE the given paper.
      Use this to trace a paper's influence forward in time. Good for
      questions like "what work built on this foundational paper?" or
      "how has the field evolved since this was published?"

    - direction="references": Returns papers that the given paper CITES.
      Use this to trace a paper's intellectual lineage backward. Good for
      questions like "what prior art informed this?" or "what are the
      canonical references in this area?"

    Args:
        paper_id: Any supported paper identifier (same formats as
            get_paper_details).
        direction: Either "citations" (papers citing this one) or
            "references" (papers this one cites). Default "citations".
        limit: Max related papers to return (1-100, default 10).

    Returns:
        Dict with:
        - paper_id: the source paper identifier
        - direction: the direction that was traversed
        - total: number of related papers returned
        - papers: list of paper dicts, same shape as search_papers returns.
    """
    return await semantic_scholar.get_citation_graph(paper_id, direction, limit)


def main() -> None:
    """Entry point — runs the MCP server using stdio transport.

    MCP clients (Claude Desktop, Cursor, Claude Code, etc.) launch this
    server as a subprocess and communicate over stdin/stdout using JSON-RPC.
    """
    mcp.run()


if __name__ == "__main__":
    main()
