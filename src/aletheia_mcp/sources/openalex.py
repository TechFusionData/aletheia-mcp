"""OpenAlex API wrapper.

OpenAlex is a free, CC0-licensed catalog of 250M+ academic works, 90M+ authors,
and 100K+ institutions. Successor to Microsoft Academic Graph. Indexes content
from arXiv, PubMed, Crossref, and many other sources.

Docs: https://docs.openalex.org/
As of Feb 2026, API key is required for all requests.
Sign up (free, instant, no approval process): https://openalex.org/settings/api

Auth: set OPENALEX_API_KEY in your environment (or .env file at project root)
and it will be sent as an `api_key` query parameter automatically.

Rate limits are credit-based. Singleton endpoints (GET /works/W123) cost 1
credit; list endpoints (GET /works?filter=...) cost 10 credits. Free tier
includes a generous daily allocation; check your usage at openalex.org/settings.
"""
import asyncio
import os
from typing import Any, Literal

import httpx

BASE_URL = "https://api.openalex.org"

# Retry config. Worst-case cumulative wait: 2+4+8+16+30 = 60 seconds.
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 30.0


# ---------------------------------------------------------------------------
# HTTP layer with retry
# ---------------------------------------------------------------------------

def _build_params(extra: dict | None = None) -> dict:
    """Build request params, injecting API key if available in environment."""
    params: dict = {}
    api_key = os.getenv("OPENALEX_API_KEY")
    if api_key:
        params["api_key"] = api_key
    if extra:
        params.update(extra)
    return params


async def _get_with_retry(
    client: httpx.AsyncClient, url: str, params: dict
) -> httpx.Response:
    """GET with exponential backoff on 429 and 5xx errors.

    Honors `Retry-After` header when present. Caps individual waits at
    MAX_BACKOFF_SECONDS. Non-retryable errors (4xx except 429) return
    immediately so callers see the original error.
    """
    backoff = INITIAL_BACKOFF_SECONDS

    for attempt in range(MAX_RETRIES):
        response = await client.get(url, params=params)

        is_retryable = response.status_code == 429 or 500 <= response.status_code < 600
        if not is_retryable:
            return response
        if attempt == MAX_RETRIES - 1:
            return response

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

    raise RuntimeError("exhausted retries without returning a response")


# ---------------------------------------------------------------------------
# Response normalization
# ---------------------------------------------------------------------------

def _decode_abstract(inverted: dict | None) -> str | None:
    """Reconstruct plain-text abstract from OpenAlex's inverted-index format.

    OpenAlex stores abstracts as {"word": [positions]} to respect copyright
    while still enabling search. Reverse the mapping to get readable text.
    """
    if not inverted:
        return None

    position_to_word: dict[int, str] = {}
    for word, positions in inverted.items():
        for pos in positions:
            position_to_word[pos] = word

    if not position_to_word:
        return None

    max_pos = max(position_to_word)
    words = [position_to_word.get(i, "") for i in range(max_pos + 1)]
    text = " ".join(w for w in words if w).strip()
    return text or None


def _strip_openalex_id(full_id: str | None) -> str | None:
    """Convert 'https://openalex.org/W1234' to just 'W1234'."""
    if not full_id:
        return None
    return full_id.rsplit("/", 1)[-1]


def _strip_doi_url(doi: str | None) -> str | None:
    """Convert 'https://doi.org/10.xxx/yyy' to '10.xxx/yyy'."""
    if not doi:
        return None
    prefix = "https://doi.org/"
    return doi[len(prefix):] if doi.startswith(prefix) else doi


def _normalize_work(work: dict) -> dict:
    """Convert an OpenAlex work object to our normalized paper shape.

    The normalized shape is stable across data sources so that tools can
    swap backends without tool-interface changes.
    """
    authorships = work.get("authorships") or []
    authors = [
        (a.get("author") or {}).get("display_name", "")
        for a in authorships
    ]
    authors = [a for a in authors if a]

    venue = None
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    if source:
        venue = source.get("display_name")

    # Prefer the best open-access location for a working PDF link.
    pdf_url = None
    best_oa = work.get("best_oa_location") or {}
    if best_oa:
        pdf_url = best_oa.get("pdf_url") or best_oa.get("landing_page_url")
    if not pdf_url:
        oa = work.get("open_access") or {}
        pdf_url = oa.get("oa_url")

    return {
        "id": _strip_openalex_id(work.get("id")),
        "title": work.get("title") or work.get("display_name"),
        "abstract": _decode_abstract(work.get("abstract_inverted_index")),
        "authors": authors,
        "year": work.get("publication_year"),
        "citation_count": work.get("cited_by_count", 0),
        "venue": venue,
        "doi": _strip_doi_url(work.get("doi")),
        "url": work.get("id"),
        "pdf_url": pdf_url,
        "source": "openalex",
    }


def _normalize_id_for_openalex(paper_id: str) -> str:
    """Convert various identifier formats into what OpenAlex URLs expect.

    Handled formats:
    - "W1234..." → passed through (native OpenAlex)
    - "https://openalex.org/W1234..." → stripped to "W1234"
    - "DOI:10.xxx/..." or "doi:10.xxx/..." → "doi:10.xxx/..."
    - Plain "10.xxx/yyy" (looks like DOI) → "doi:10.xxx/yyy"
    - "PMID:12345" or "pmid:12345" → "pmid:12345"

    Unsupported inputs are passed through (OpenAlex may still resolve them,
    e.g. via URL-encoded DOIs).
    """
    pid = paper_id.strip()

    # Native OpenAlex URL → extract the ID
    if pid.startswith("https://openalex.org/"):
        return pid.rsplit("/", 1)[-1]

    # Native OpenAlex ID (W, A, I, S, etc prefix then digits)
    if len(pid) >= 2 and pid[0] in "WAISCPF" and pid[1:].isdigit():
        return pid

    # DOI variants
    if pid.lower().startswith("doi:"):
        return "doi:" + pid[4:]
    if pid.startswith("10."):
        return "doi:" + pid

    # PubMed variants
    if pid.lower().startswith("pmid:"):
        return "pmid:" + pid[5:]

    # arXiv: OpenAlex doesn't accept arXiv-prefixed URLs directly,
    # but many arXiv papers have DOIs. Return as-is; caller handles failure.
    return pid


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search_papers(query: str, limit: int = 10) -> dict[str, Any]:
    """Search for papers matching a natural language query.

    Args:
        query: Free-text search terms.
        limit: Maximum number of results to return. Clamped to [1, 200].

    Returns:
        Dict with keys:
            - query: the query string that was searched
            - total: total matching works in the corpus (may exceed limit)
            - papers: list of normalized paper dicts (see _normalize_work)
    """
    limit = max(1, min(200, limit))

    url = f"{BASE_URL}/works"
    params = _build_params({"search": query, "per_page": limit})

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await _get_with_retry(client, url, params)
        response.raise_for_status()
        data = response.json()

    papers = [_normalize_work(w) for w in data.get("results", [])]
    return {
        "query": query,
        "total": (data.get("meta") or {}).get("count", 0),
        "papers": papers,
    }


async def get_paper_details(paper_id: str) -> dict[str, Any]:
    """Fetch a single paper by identifier.

    Accepts OpenAlex IDs (W1234...), DOIs (with or without 'doi:' prefix),
    PubMed IDs (with 'pmid:' prefix), or full OpenAlex URLs.

    Args:
        paper_id: Any supported identifier.

    Returns:
        Normalized paper dict, or an error dict with 'error': 'not_found'
        if the identifier doesn't resolve to a known work.
    """
    normalized_id = _normalize_id_for_openalex(paper_id)
    url = f"{BASE_URL}/works/{normalized_id}"
    params = _build_params()

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await _get_with_retry(client, url, params)
        if response.status_code == 404:
            return {
                "error": "not_found",
                "paper_id": paper_id,
                "message": f"No paper found for identifier '{paper_id}'.",
            }
        response.raise_for_status()
        return _normalize_work(response.json())


async def get_citation_graph(
    paper_id: str,
    direction: Literal["citations", "references"] = "citations",
    limit: int = 10,
) -> dict[str, Any]:
    """Traverse the citation graph for a paper.

    - direction="citations": papers that CITE the given paper (forward in time)
    - direction="references": papers the given paper CITES (backward in time)

    For references, OpenAlex exposes the list of IDs directly on the source
    work and we batch-fetch their details. For citations, we use a filter
    query against the /works endpoint.

    Args:
        paper_id: Any supported identifier (see get_paper_details).
        direction: Either "citations" or "references".
        limit: Max papers to return. Clamped to [1, 200].

    Returns:
        Dict with keys:
            - paper_id: the source paper identifier (as given)
            - direction: the direction traversed
            - total: number of related papers returned
            - papers: list of normalized paper dicts
    """
    if direction not in ("citations", "references"):
        raise ValueError(
            f"direction must be 'citations' or 'references', got {direction!r}"
        )

    limit = max(1, min(200, limit))
    normalized_id = _normalize_id_for_openalex(paper_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        if direction == "citations":
            # Papers that cite this one: filter works where cites matches.
            url = f"{BASE_URL}/works"
            params = _build_params({
                "filter": f"cites:{normalized_id}",
                "per_page": limit,
                "sort": "cited_by_count:desc",
            })
            response = await _get_with_retry(client, url, params)
            if response.status_code == 404:
                return _not_found(paper_id, direction)
            response.raise_for_status()
            data = response.json()
            papers = [_normalize_work(w) for w in data.get("results", [])]

        else:  # references
            # Two-step: fetch the source paper, then batch-fetch its references.
            source_url = f"{BASE_URL}/works/{normalized_id}"
            source_response = await _get_with_retry(
                client, source_url, _build_params()
            )
            if source_response.status_code == 404:
                return _not_found(paper_id, direction)
            source_response.raise_for_status()
            source_work = source_response.json()

            ref_ids = source_work.get("referenced_works") or []
            # Strip to short IDs and take only what we need.
            short_ref_ids = [
                _strip_openalex_id(rid) for rid in ref_ids[:limit] if rid
            ]

            if not short_ref_ids:
                papers = []
            else:
                # Batch fetch using OR filter (pipe-separated).
                batch_url = f"{BASE_URL}/works"
                batch_params = _build_params({
                    "filter": f"openalex_id:{'|'.join(short_ref_ids)}",
                    "per_page": limit,
                })
                batch_response = await _get_with_retry(
                    client, batch_url, batch_params
                )
                batch_response.raise_for_status()
                batch_data = batch_response.json()
                papers = [_normalize_work(w) for w in batch_data.get("results", [])]

    return {
        "paper_id": paper_id,
        "direction": direction,
        "total": len(papers),
        "papers": papers,
    }


def _not_found(paper_id: str, direction: str) -> dict[str, Any]:
    return {
        "error": "not_found",
        "paper_id": paper_id,
        "direction": direction,
        "message": f"No paper found for identifier '{paper_id}'.",
    }
