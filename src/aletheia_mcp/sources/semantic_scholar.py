"""Semantic Scholar API wrapper.

Semantic Scholar aggregates papers from arXiv, PubMed, PubMed Central, DBLP,
and many other sources into a single searchable corpus. We use it as our
primary search backend because it gives us broad coverage with one API.

Docs: https://api.semanticscholar.org/api-docs/
Without an API key: 100 requests per 5 minutes, shared with all anonymous
traffic from your IP. In practice this gets throttled quickly.
With an API key (free): much higher limits, dedicated quota.
Request one at: https://www.semanticscholar.org/product/api

Auth: set SEMANTIC_SCHOLAR_API_KEY in your environment (or .env file)
and it will be sent as the `x-api-key` header automatically.
"""
import asyncio
import os
from typing import Any

import httpx

BASE_URL = "https://api.semanticscholar.org/graph/v1"

DEFAULT_SEARCH_FIELDS = (
    "paperId,title,abstract,authors,year,"
    "citationCount,venue,externalIds,url,openAccessPdf"
)

# Retry config for transient failures (429, 5xx)
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0


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

    Retries up to MAX_RETRIES times, doubling the backoff each attempt.
    Other errors (4xx except 429) raise immediately — those are bugs in
    our request, not transient failures.
    """
    backoff = INITIAL_BACKOFF_SECONDS
    last_response: httpx.Response | None = None

    for attempt in range(MAX_RETRIES):
        response = await client.get(url, params=params, headers=_get_headers())
        last_response = response

        # Transient errors: retry
        if response.status_code == 429 or 500 <= response.status_code < 600:
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(backoff)
                backoff *= 2
                continue

        # Success or non-retryable error: return and let caller decide
        return response

    # Should be unreachable, but satisfies the type checker
    assert last_response is not None
    return last_response


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
            - papers: list of paper dicts with fields from DEFAULT_SEARCH_FIELDS

    Raises:
        httpx.HTTPStatusError: if the API returns a persistent 4xx/5xx response
            after retries are exhausted.
        httpx.RequestError: on network errors or timeouts.
    """
    limit = max(1, min(100, limit))

    url = f"{BASE_URL}/paper/search"
    params = {
        "query": query,
        "limit": limit,
        "fields": DEFAULT_SEARCH_FIELDS,
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
