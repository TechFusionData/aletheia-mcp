# aletheia-mcp

[![PyPI version](https://img.shields.io/pypi/v/aletheia-mcp.svg)](https://pypi.org/project/aletheia-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/aletheia-mcp.svg)](https://pypi.org/project/aletheia-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

An MCP server that gives AI agents structured access to scientific literature — 250M+ papers indexed via OpenAlex, covering arXiv, PubMed, Crossref, and more — so they can do research, not just search.

## The gap this fills

Tools like Elicit, Consensus, and SciSpace are great but they're standalone chat apps. You ask one question, you get one answer. You can't chain operations.

With aletheia-mcp running in Claude or any MCP-compatible client, you can ask things like:

> "I'm reviewing literature on mitochondrial dysfunction in Parkinson's. Find the 20 most-cited papers from the last 5 years, pull the full text of the three most influential, identify the exact mechanisms they propose, and flag any that contradict each other."

Under the hood, Claude chains multiple tool calls — search, fetch metadata, walk citations, download and parse full PDFs — and synthesizes. That's the difference between search and research.

## Tools in v0.3.0

- `search_papers(query, limit)` — unified search across the OpenAlex corpus
- `get_paper_details(paper_id)` — full metadata for any paper by OpenAlex ID, DOI, PubMed ID, or URL
- `get_citation_graph(paper_id, direction, limit)` — walk citations forward (`direction="citations"`) or references backward (`direction="references"`)
- `get_paper_full_text(paper_id)` — **new in v0.3** — fetches and extracts the full text of any open-access paper. Handles arXiv, PubMed Central, and direct publisher PDFs. Falls back gracefully when no OA version is available.

All paper-returning tools use a normalized shape: `{id, title, abstract, authors, year, citation_count, venue, doi, url, pdf_url, source}`. The full-text tool adds `text` and `char_count`.

## Why OpenAlex (not Semantic Scholar)

Earlier iterations used Semantic Scholar. The free API key there is gated and institution-preferred — independent developers face slow or rejected applications, which meant future users of this tool would hit the same wall.

[OpenAlex](https://openalex.org) is the open, CC0-licensed successor to Microsoft Academic Graph, with 250M+ works covering the same sources. As of February 2026, API keys are required but are free and self-serve — 30 seconds to sign up, no approval process.

## Install

Available on PyPI:

```bash
uv add aletheia-mcp
```

Or as a one-line registration directly with Claude Code:

```bash
claude mcp add --scope user aletheia \
  --env OPENALEX_API_KEY=your-key-here \
  -- uvx aletheia-mcp
```

(Grab a free OpenAlex API key in 30 seconds at <https://openalex.org/settings/api>.)

### From source (for contributors)

```bash
git clone https://github.com/TechFusionData/aletheia-mcp
cd aletheia-mcp
uv sync
cp .env.example .env
# edit .env and paste your OpenAlex API key
claude mcp add --scope user aletheia -- uv run --directory $(pwd) aletheia-mcp
```

Restart your MCP client and the tools become available.

## Dependencies worth noting

- **PyMuPDF** (AGPL-3.0) — used for full-text PDF extraction because it handles two-column scientific layouts far better than alternatives. If AGPL is a concern for your use case, you can swap in `pypdfium2` (Apache-2.0) in `sources/openalex.py:_extract_pdf_text` at the cost of somewhat messier text output.

## Why "aletheia"

ἀλήθεια — the Greek notion of truth as "unconcealment," the state of not being hidden. Research is the practice of bringing what's there into view.

## License

MIT. See [LICENSE](./LICENSE).
