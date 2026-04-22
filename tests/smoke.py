"""Smoke tests against the real Semantic Scholar API.

Run from project root:
    uv run python tests/smoke.py

Exercises all three tools end-to-end:
    - search_papers
    - get_paper_details
    - get_citation_graph (both directions)

Pauses between tests help when hitting the shared unauthenticated rate-limit
pool. Once SEMANTIC_SCHOLAR_API_KEY is set, the pauses are unnecessary.
"""
import asyncio
import os

from aletheia_mcp.sources import semantic_scholar

# Skip the pauses if we have an API key (we have dedicated quota then)
PAUSE_SECONDS = 0 if os.getenv("SEMANTIC_SCHOLAR_API_KEY") else 30


def _print_paper(i: int, p: dict) -> None:
    """Render a single paper row for human-readable output."""
    authors_list = p.get("authors") or []
    author_names = ", ".join(a["name"] for a in authors_list[:3])
    if len(authors_list) > 3:
        author_names += " et al."
    if not author_names:
        author_names = "[no authors listed]"

    title = p.get("title", "[no title]")
    year = p.get("year", "?")
    citations = p.get("citationCount", 0) or 0

    print(f"{i}. {title}")
    print(f"   {author_names} ({year}) -- {citations:,} citations")
    if p.get("venue"):
        print(f"   Venue: {p['venue']}")


async def _pause() -> None:
    if PAUSE_SECONDS > 0:
        print("... pausing {} seconds between tests (API key would remove this) ...".format(PAUSE_SECONDS))
        print()
        await asyncio.sleep(PAUSE_SECONDS)


async def test_search() -> str:
    print("=" * 72)
    print("TEST 1: search_papers")
    print("=" * 72)
    result = await semantic_scholar.search_papers("CRISPR gene editing", limit=3)
    print("Total matches: {:,}".format(result["total"]))
    print("Returned: {} papers".format(len(result["papers"])))
    print()

    for i, p in enumerate(result["papers"], 1):
        _print_paper(i, p)
        print()

    first_id = result["papers"][0]["paperId"]
    print("-> Using paper 1's ID for downstream tests: {}".format(first_id))
    print()
    return first_id


async def test_details(paper_id: str) -> None:
    print("=" * 72)
    print("TEST 2: get_paper_details")
    print("=" * 72)
    paper = await semantic_scholar.get_paper_details(paper_id)
    if paper.get("error"):
        print("ERROR:", paper)
        return
    _print_paper(1, paper)
    ext_ids = paper.get("externalIds") or {}
    if ext_ids:
        print("   External IDs:", ext_ids)
    print()


async def test_citations(paper_id: str) -> None:
    for direction in ("citations", "references"):
        print("=" * 72)
        print("TEST 3: get_citation_graph (direction={})".format(direction))
        print("=" * 72)
        result = await semantic_scholar.get_citation_graph(
            paper_id, direction=direction, limit=3
        )
        if result.get("error"):
            print("ERROR:", result)
            continue

        print("Returned {} papers".format(result["total"]))
        print()
        for i, p in enumerate(result["papers"], 1):
            if p:
                _print_paper(i, p)
                print()
        await _pause()


async def main() -> None:
    paper_id = await test_search()
    await _pause()
    await test_details(paper_id)
    await _pause()
    await test_citations(paper_id)
    print("=" * 72)
    print("ALL TESTS COMPLETED")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
