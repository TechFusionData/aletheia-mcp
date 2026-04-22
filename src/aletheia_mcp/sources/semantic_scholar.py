"""Semantic Scholar API wrapper.

Semantic Scholar aggregates papers from arXiv, PubMed, PubMed Central, DBLP,
and many other sources into a single searchable corpus. We use it as our
primary search backend because it gives us broad coverage with one API.

Docs: https://api.semanticscholar.org/api-docs/
Without an API key: ~100 requests per 5 minutes, SHARED across all anonymous
traffic globally. Throttles quickly in practice.
With an API key (free): much higher limits and dedicated quota.
Request one at: https://www.semanticscholar.org/product/api

Auth: set SEMANTIC_SCHOLAR_API_KEY in your environment (or .env file at the
project root) and it will be sent as the `x-api-key` header automatically.
"""
import asyncio
import os
from typing import Any, Literal

import httpx

BASE_URL = "https://api.semanticscholar.org/graph/v1"

# Fields for paper search and details responses.
# Fewer fields = faster responses. These cover everything our tools expose.
DEFAULT_PAPER_FIELDS = (
    "paperId,title,abstract,authors,year,"
    "citationCount,venue,externalIds,url,openAccessPdf"
)

# Retry config. Worst-case cumulative wait: 2+4+8+16+30 = 60 seconds.
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 30.0


def _get_headers() -> dict[str, str]:
    """Build request headers, including API key if available in environment."""
    headers = {"Accept": "application/json"}
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    return headers


async def _get_with_retry(
    client: httpx.AsyncClient, url: str, params: dict
) -> httpx.Response:
    """GET with exponential backoff on 429 and 5xx errors.

    Honors `Retry-After` header when present. Caps individual waits at
    MAX_BACKOFF_SECONDS so we don't hang forever. Other errors (4xx except
    429) return immediately — those are bugs in our request, not transient.
    """
    backoff = INITIAL_BACKOFF_SECONDS

    for attempt in range(MAX_RETRIES):
        response = await client.get(url, params=params, headers=_get_headers())

        # Success or non-retryable client error: return now.
        is_retryable = response.status_code == 429 or 500 <= response.status_code < 600
        if not is_retryable:
            return response

        # Out of retries — return the last response, caller decides what to do.
        if attempt == MAX_RETRIES - 1:
            return response

        # Transient failure: figure out how long to wait.
        # Prefer server's Retry-After hint if present and sane.
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                wait = min(float(retry_after), MAX_BACKOFF_SECONDS)
            except ValueError:
                wait = backoff
        else:
            wait = backoff

        await asyncio.sleep(wait)
        backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    # Unreachable (loop always returns or sleeps-and-continues), but keeps
    # the type checker happy.
    raise RuntimeError("exhausted retries without returning a response")


async def search_papers(query: str, limit: int = 10) -> dict[str, Any]:
    """Search for papers matching a natural language query.

    Args:
        query: Search terms — topic, author name, paper title, or any
            natural language description.
        limit: Maximum number of results to return. Clamped to [1, 100].

    Returns:
        Dict with keys:
            - query: the query string that was searched
            - total: total matching papers in the corpus (may exceed limit)
            - papers: list of paper dicts with fields from DEFAULT_PAPER_FIELDS
    """
    limit = max(1, min(100, limit))

    url = f"{BASE_URL}/paper/search"
    params = {
        "query": query,
        "limit": limit,
        "fields": DEFAULT_PAPER_FIELDS,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await _get_with_retry(client, url, params)
        response.raise_for_status()
        data = response.json()

    return {
        "query": query,
        "total": data.get("total", 0),
        "papers": data.get("data", []),
    }


async def get_paper_details(paper_id: str) -> dict[str, Any]:
    """Fetch detailed information about a single paper.

    Accepts any of Semantic Scholar's supported paper identifiers:
    - Semantic Scholar paper ID (e.g., "649def34f8be52c8b66281af98ae884c09aef38b")
    - DOI with prefix (e.g., "DOI:10.1038/nature12373")
    - arXiv ID with prefix (e.g., "arXiv:2106.15928")
    - PubMed ID with prefix (e.g., "PMID:27889204")
    - MAG ID with prefix (e.g., "MAG:2741809807")

    Args:
        paper_id: Any supported identifier (see above).

    Returns:
        Paper dict with all fields from DEFAULT_PAPER_FIELDS, or an error
        structure if the paper isn't found.
    """
    url = f"{BASE_URL}/paper/{paper_id}"
    params = {"fields": DEFAULT_PAPER_FIELDS}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await _get_with_retry(client, url, params)
        if response.status_code == 404:
            return {
                "error": "not_found",
                "paper_id": paper_id,
                "message": f"No paper found for identifier '{paper_id}'.",
            }
        response.raise_for_status()
        return response.json()


async def get_citation_graph(
    paper_id: str,
    direction: Literal["citations", "references"] = "citations",
    limit: int = 10,
) -> dict[str, Any]:
    """Traverse the citation graph for a paper.

    Two directions:
    - "citations": papers that CITE the given paper (forward in time —
      use for "what work built on this?" or "how influential was this?")
    - "references": papers that the given paper CITES (backward in time —
      use for "what did this build on?" or "what's the prior art?")

    Args:
        paper_id: Any supported paper identifier (see get_paper_details).
        direction: Either "citations" or "references".
        limit: Max related papers to return. Clamped to [1, 100].

    Returns:
        Dict with keys:
            - paper_id: the source paper identifier
            - direction: the direction traversed
            - total: number of related papers (may exceed limit)
            - papers: list of paper dicts
    """
    if direction not in ("citations", "references"):
        raise ValueError(
            f"direction must be 'citations' or 'references', got {direction!r}"
        )

    limit = max(1, min(100, limit))

    url = f"{BASE_URL}/paper/{paper_id}/{direction}"
    params = {
        "limit": limit,
        # For citations/references, the papers are nested under a wrapper.
        # We request 'citedPaper' for references and 'citingPaper' for citations,
        # but asking for DEFAULT_PAPER_FIELDS directly also works with prefixes.
        "fields": DEFAULT_PAPER_FIELDS,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await _get_with_retry(client, url, params)
        if response.status_code == 404:
            return {
                "error": "not_found",
                "paper_id": paper_id,
                "direction": direction,
                "message": f"No paper found for identifier '{paper_id}'.",
            }
        response.raise_for_status()
        data = response.json()

    # The API wraps each entry under 'citingPaper' or 'citedPaper' depending
    # on direction. Flatten to a plain list of paper dicts.
    wrapper_key = "citingPaper" if direction == "citations" else "citedPaper"
    raw_items = data.get("data", [])
    papers = [item.get(wrapper_key, item) for item in raw_items]

    return {
        "paper_id": paper_id,
        "direction": direction,
        "total": len(papers),  # API returns batches; this is the batch size
        "papers": papers,
    }
