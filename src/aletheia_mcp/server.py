"""aletheia-mcp server.

Defines the MCP server and registers tools that AI agents can call.
Each tool is a plain async Python function with a @mcp.tool() decorator.
FastMCP handles all JSON-RPC message passing, schema generation, and I/O.
"""
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from aletheia_mcp.sources import openalex

# Load environment variables from .env at project root (if present).
# Path walks: server.py → aletheia_mcp → src → project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# Create the MCP server. The name appears in MCP client UIs and logs.
mcp = FastMCP("aletheia-mcp")


# Shared description of the normalized paper shape, embedded in every tool
# docstring so the MCP client has consistent schema guidance.
_PAPER_SHAPE = """
    Each paper dict contains:
    - id: the source's native identifier (for OpenAlex: "W1234..." format)
    - title: paper title
    - abstract: full abstract text (null if none available)
    - authors: list of author names (strings)
    - year: publication year (integer) or null
    - citation_count: number of times this paper has been cited
    - venue: journal/conference name or null
    - doi: DOI string without URL prefix (e.g., "10.1038/nature12373")
    - url: canonical URL on the source platform
    - pdf_url: link to open-access PDF when available, null otherwise
    - source: always "openalex" in the current version
"""


@mcp.tool()
async def search_papers(query: str, limit: int = 10) -> dict:
    """Search scientific literature for papers matching a query.

    Searches the OpenAlex corpus (250M+ works from arXiv, PubMed, Crossref,
    and other sources). Good for finding papers by topic, author, or concept.

    Args:
        query: Natural language search terms. Examples:
            - "mitochondrial dysfunction Parkinson's disease"
            - "attention is all you need"
            - "CRISPR gene editing ethics"
        limit: Maximum papers to return (1-200, default 10).

    Returns:
        Dict with:
        - query: the search string used
        - total: total matching works in the corpus (may exceed limit)
        - papers: list of normalized paper dicts
    """ + _PAPER_SHAPE
    return await openalex.search_papers(query, limit)


@mcp.tool()
async def get_paper_details(paper_id: str) -> dict:
    """Fetch detailed information about a single paper by identifier.

    Use this when you have a specific paper ID and want its full metadata.
    Common sources of IDs: results from search_papers (use the id field),
    user-provided DOIs, PubMed IDs, or full OpenAlex URLs.

    Supported identifier formats:
    - OpenAlex ID: "W2741809807" (native, fastest)
    - DOI with prefix: "doi:10.1038/nature12373"
    - Plain DOI: "10.1038/nature12373" (auto-detected)
    - PubMed ID: "pmid:27889204"
    - Full OpenAlex URL: "https://openalex.org/W2741809807"

    Args:
        paper_id: Any supported identifier (see formats above).

    Returns:
        Normalized paper dict (see shape below), or an error dict with
        'error': 'not_found' if the identifier doesn't resolve.
    """ + _PAPER_SHAPE
    return await openalex.get_paper_details(paper_id)


@mcp.tool()
async def get_citation_graph(
    paper_id: str,
    direction: Literal["citations", "references"] = "citations",
    limit: int = 10,
) -> dict:
    """Traverse the citation graph forward or backward from a paper.

    Two directions answer different research questions:

    - direction="citations": Returns papers that CITE the given paper.
      Use for tracing influence forward in time. Good for questions like
      "what work built on this?" or "how has the field evolved since?"
      Results sorted by citation count (most influential first).

    - direction="references": Returns papers the given paper CITES.
      Use for tracing intellectual lineage backward. Good for questions
      like "what prior art informed this?" or "what are the canonical
      references?"

    Args:
        paper_id: Any supported identifier (see get_paper_details).
        direction: Either "citations" (papers citing this one) or
            "references" (papers this one cites). Default "citations".
        limit: Max related papers to return (1-200, default 10).

    Returns:
        Dict with:
        - paper_id: the source identifier (as given)
        - direction: the direction traversed
        - total: number of related papers returned
        - papers: list of normalized paper dicts (see shape below)
    """ + _PAPER_SHAPE
    return await openalex.get_citation_graph(paper_id, direction, limit)


@mcp.tool()
async def get_paper_full_text(paper_id: str) -> dict:
    """Fetch and return the full text of an open-access paper.

    Use this when abstracts aren't enough — when the user asks about specific
    methods, exact numbers, limitations, or wants to verify a claim against
    primary text. Only works for papers with an open-access PDF available.

    Typical flow: search_papers → pick a paper → get_paper_full_text(paper.id)
    to read the whole thing rather than just the abstract.

    Supported identifier formats: same as get_paper_details (OpenAlex IDs,
    DOIs with or without prefix, PubMed IDs, full OpenAlex URLs).

    Args:
        paper_id: Any supported identifier.

    Returns:
        On success, a dict with:
            - paper_id, title, authors, year, doi, pdf_url, source
            - text: full extracted text as a single string
            - char_count: length of the text

        On failure, a dict with an 'error' field. Possible error codes:
            - "not_found": paper_id didn't resolve
            - "no_open_access_version": paper exists but no OA PDF available
            - "download_failed": network error fetching the PDF
            - "not_a_pdf": URL returned HTML (likely paywall landing page)
            - "pdf_too_large": PDF exceeded 30MB safety cap
            - "extraction_failed": PDF parser error (encrypted/malformed)
            - "extraction_empty": PDF had no text layer (scanned image)

        When an error is returned, the response also includes 'message'
        with a human-readable explanation and (where relevant) the DOI so
        the user can access the paper through other means.
    """
    return await openalex.get_paper_full_text(paper_id)


def main() -> None:
    """Entry point — runs the MCP server using stdio transport.

    MCP clients (Claude Desktop, Cursor, Claude Code, etc.) launch this
    server as a subprocess and communicate over stdin/stdout using JSON-RPC.
    """
    mcp.run()


if __name__ == "__main__":
    main()
