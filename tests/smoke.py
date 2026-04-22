"""Smoke tests against the real OpenAlex API.

Run from project root:
    uv run python tests/smoke.py

Exercises all three tools end-to-end:
    - search_papers
    - get_paper_details
    - get_citation_graph (both directions)

Works without an API key using the free-credit tier, but OPENALEX_API_KEY
in your environment (or .env) is strongly recommended for real use.
"""
import asyncio
import os

from aletheia_mcp.sources import openalex

HAS_KEY = bool(os.getenv("OPENALEX_API_KEY"))


def _print_paper(i: int, p: dict) -> None:
    """Render a normalized paper dict for human-readable output."""
    authors = p.get("authors") or []
    author_names = ", ".join(authors[:3])
    if len(authors) > 3:
        author_names += " et al."
    if not author_names:
        author_names = "[no authors listed]"

    title = p.get("title", "[no title]")
    year = p.get("year", "?")
    citations = p.get("citation_count", 0) or 0

    print(f"{i}. {title}")
    print(f"   {author_names} ({year}) -- {citations:,} citations")
    if p.get("venue"):
        print(f"   Venue: {p['venue']}")
    if p.get("doi"):
        print(f"   DOI: {p['doi']}")


async def test_search() -> str:
    print("=" * 72)
    print("TEST 1: search_papers")
    print("=" * 72)
    result = await openalex.search_papers("CRISPR gene editing", limit=3)
    print("Total matches: {:,}".format(result["total"]))
    print("Returned: {} papers".format(len(result["papers"])))
    print()

    for i, p in enumerate(result["papers"], 1):
        _print_paper(i, p)
        print()

    first_id = result["papers"][0]["id"]
    print("-> Using paper 1's ID for downstream tests: {}".format(first_id))
    print()
    return first_id


async def test_details(paper_id: str) -> None:
    print("=" * 72)
    print("TEST 2: get_paper_details")
    print("=" * 72)
    paper = await openalex.get_paper_details(paper_id)
    if paper.get("error"):
        print("ERROR:", paper)
        return
    _print_paper(1, paper)
    abstract = paper.get("abstract")
    if abstract:
        preview = abstract[:200] + ("..." if len(abstract) > 200 else "")
        print(f"   Abstract preview: {preview}")
    print()


async def test_citations(paper_id: str) -> None:
    for direction in ("citations", "references"):
        print("=" * 72)
        print("TEST 3: get_citation_graph (direction={})".format(direction))
        print("=" * 72)
        result = await openalex.get_citation_graph(
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


async def main() -> None:
    print(f"Auth: {'API key present ✓' if HAS_KEY else 'No API key (free tier)'}")
    print()
    paper_id = await test_search()
    await test_details(paper_id)
    await test_citations(paper_id)
    print("=" * 72)
    print("ALL TESTS COMPLETED")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
