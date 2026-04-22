"""Quick smoke test: can we search Semantic Scholar and get real data?

Run from project root:
    uv run python tests/smoke.py
"""
import asyncio

from aletheia_mcp.sources import semantic_scholar


async def main() -> None:
    result = await semantic_scholar.search_papers("CRISPR gene editing", limit=3)

    print(f"Total matches in corpus: {result['total']:,}")
    print(f"Returned: {len(result['papers'])} papers")
    print()

    for i, p in enumerate(result["papers"], 1):
        authors_list = p.get("authors", [])
        author_names = ", ".join(a["name"] for a in authors_list[:3])
        if len(authors_list) > 3:
            author_names += " et al."

        print(f"{i}. {p.get('title', '[no title]')}")
        print(
            f"   {author_names} ({p.get('year', '?')}) — "
            f"{p.get('citationCount', 0):,} citations"
        )
        if p.get("venue"):
            print(f"   Venue: {p['venue']}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
