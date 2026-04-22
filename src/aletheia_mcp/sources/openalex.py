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
import io
import os
from typing import Any, Literal

import httpx
import pymupdf

BASE_URL = "https://api.openalex.org"

# Retry config. Worst-case cumulative wait: 2+4+8+16+30 = 60 seconds.
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 30.0

# Full-text extraction config.
# Safety cap on PDF downloads — scientific papers are rarely >20MB; cap at 30MB
# to catch malformed URLs that return e.g. huge supplementary data bundles.
MAX_PDF_BYTES = 30 * 1024 * 1024
PDF_DOWNLOAD_TIMEOUT_SECONDS = 60.0


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


# ---------------------------------------------------------------------------
# Full-text extraction
# ---------------------------------------------------------------------------

async def _download_pdf(url: str) -> bytes:
    """Download a PDF from a URL, following redirects.

    Raises httpx.HTTPError on network problems or non-2xx responses.
    Raises ValueError if response exceeds MAX_PDF_BYTES.
    """
    # follow_redirects: publisher pdf_urls often redirect through CDNs.
    # User-Agent: some publishers 403 generic/default UAs.
    headers = {"User-Agent": "aletheia-mcp/0.3 (research tool; +github.com/TechFusionData/aletheia-mcp)"}
    async with httpx.AsyncClient(
        timeout=PDF_DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True
    ) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()

    if len(response.content) > MAX_PDF_BYTES:
        raise ValueError(
            f"PDF too large: {len(response.content):,} bytes "
            f"(cap: {MAX_PDF_BYTES:,})"
        )
    return response.content


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract plain text from PDF bytes using PyMuPDF.

    PyMuPDF (fitz) handles two-column scientific paper layouts noticeably
    better than pdfplumber — it preserves word boundaries and reading order
    on academic PDFs where pdfplumber tends to squash words together.

    Runs synchronously — caller should wrap in asyncio.to_thread to avoid
    blocking the event loop (PyMuPDF has no async API).

    Joins all pages with double newlines. Filters out empty pages silently.
    """
    text_parts: list[str] = []
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page in doc:
            page_text = page.get_text() or ""
            if page_text.strip():
                text_parts.append(page_text)
    finally:
        doc.close()
    return "\n\n".join(text_parts)


async def get_paper_full_text(paper_id: str) -> dict[str, Any]:
    """Fetch and extract the full text of an open-access paper.

    Flow:
        1. Resolve paper metadata via OpenAlex (to get pdf_url + title).
        2. If no pdf_url is known, return a structured error with DOI hint.
        3. Download the PDF.
        4. Verify magic bytes — pdf_urls sometimes return HTML landing pages
           rather than actual PDFs for paywalled content.
        5. Extract text via pdfplumber (wrapped in a thread).
        6. Return text + metadata, or a structured error dict.

    Errors are returned as dicts (not raised) so MCP clients get a clean
    structured response Claude can reason about:
        - "not_found": paper_id didn't resolve
        - "no_open_access_version": paper exists but no pdf_url available
        - "download_failed": network error or non-200 response
        - "not_a_pdf": URL returned HTML or other non-PDF content
        - "extraction_failed": pdfplumber couldn't parse (e.g., scanned PDF
          with no text layer, or encrypted/malformed PDF)
    """
    # Step 1: resolve paper
    paper = await get_paper_details(paper_id)
    if paper.get("error"):
        return paper  # already a structured not_found error

    pdf_url = paper.get("pdf_url")
    title = paper.get("title")
    doi = paper.get("doi")

    # Step 2: no OA version available
    if not pdf_url:
        return {
            "error": "no_open_access_version",
            "paper_id": paper_id,
            "title": title,
            "doi": doi,
            "message": (
                "No open-access PDF is available for this paper. "
                f"To read it, try the DOI{': ' + doi if doi else ''} "
                "through an institutional subscription."
            ),
        }

    # Step 3: download
    try:
        pdf_bytes = await _download_pdf(pdf_url)
    except ValueError as e:
        # Size cap exceeded
        return {
            "error": "pdf_too_large",
            "paper_id": paper_id,
            "title": title,
            "pdf_url": pdf_url,
            "message": str(e),
        }
    except httpx.HTTPError as e:
        return {
            "error": "download_failed",
            "paper_id": paper_id,
            "title": title,
            "pdf_url": pdf_url,
            "message": f"Could not download PDF: {type(e).__name__}: {e}",
        }

    # Step 4: verify it's a real PDF (not a paywall HTML page)
    if pdf_bytes[:4] != b"%PDF":
        return {
            "error": "not_a_pdf",
            "paper_id": paper_id,
            "title": title,
            "pdf_url": pdf_url,
            "message": (
                "The pdf_url returned non-PDF content (likely an HTML paywall "
                "or landing page). This paper may not have a truly open version."
            ),
        }

    # Step 5: extract text (runs in thread to avoid blocking event loop)
    try:
        text = await asyncio.to_thread(_extract_pdf_text, pdf_bytes)
    except Exception as e:
        return {
            "error": "extraction_failed",
            "paper_id": paper_id,
            "title": title,
            "pdf_url": pdf_url,
            "message": f"Failed to extract text: {type(e).__name__}: {e}",
        }

    if not text.strip():
        return {
            "error": "extraction_empty",
            "paper_id": paper_id,
            "title": title,
            "pdf_url": pdf_url,
            "message": (
                "PDF parsed but contained no extractable text. This usually "
                "means the PDF is a scanned image with no text layer; OCR "
                "would be needed."
            ),
        }

    # Step 6: success
    return {
        "paper_id": paper_id,
        "title": title,
        "authors": paper.get("authors"),
        "year": paper.get("year"),
        "doi": doi,
        "pdf_url": pdf_url,
        "text": text,
        "char_count": len(text),
        "source": "openalex",
    }
