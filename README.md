# aletheia-mcp

An MCP server that gives AI agents structured access to scientific literature — 250M+ papers indexed via OpenAlex, covering arXiv, PubMed, Crossref, and more — so they can do research, not just search.

## The gap this fills

Tools like Elicit, Consensus, and SciSpace are great but they're standalone chat apps. You ask one question, you get one answer. You can't chain operations.

With aletheia-mcp running in Claude or any MCP-compatible client, you can ask things like:

> "I'm reviewing literature on mitochondrial dysfunction in Parkinson's. Find the 20 most-cited papers from the last 5 years, cluster them by methodology, identify which methodologies are gaining traction vs. declining, and flag any that contradict the dominant view."

Under the hood, Claude chains multiple tool calls — search, fetch full metadata, walk citation graphs, compare — and synthesizes an answer. That's the difference between search and research.

## Tools in v0.2.0

- `search_papers(query, limit)` — unified search across the OpenAlex corpus
- `get_paper_details(paper_id)` — full metadata for any paper by OpenAlex ID, DOI, PubMed ID, or URL
- `get_citation_graph(paper_id, direction, limit)` — walk citations forward (`direction="citations"`) or references backward (`direction="references"`)

All tools return a normalized paper shape with: id, title, abstract, authors, year, citation_count, venue, doi, url, pdf_url, source.

## Why OpenAlex (not Semantic Scholar)

Earlier iterations used Semantic Scholar. The free API key there is gated and institution-preferred — independent developers face slow or rejected applications, which meant future users of this tool would hit the same wall.

[OpenAlex](https://openalex.org) is the open, CC0-licensed successor to Microsoft Academic Graph, with 250M+ works covering the same sources. As of February 2026, API keys are required but are free and self-serve — 30 seconds to sign up, no approval process.

## Install

Not yet on PyPI. To run locally:

```bash
git clone https://github.com/TechFusionData/aletheia-mcp
cd aletheia-mcp
uv sync
cp .env.example .env
# edit .env and paste your OpenAlex API key
```

Then register with Claude Code (or your MCP client of choice):

```bash
claude mcp add --scope user aletheia -- uv run --directory $(pwd) aletheia-mcp
```

Restart your MCP client and the tools become available.

## Why "aletheia"

ἀλήθεια — the Greek notion of truth as "unconcealment," the state of not being hidden. Research is the practice of bringing what's there into view.

## License

MIT. See [LICENSE](./LICENSE).
