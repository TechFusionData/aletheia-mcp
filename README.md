# aletheia-mcp

An MCP server that gives AI agents structured access to scientific literature — PubMed, arXiv, bioRxiv, and Semantic Scholar — so they can do research, not just search.

## The gap this fills

Tools like Elicit, Consensus, and SciSpace are great but they're standalone chat apps. You ask one question, you get one answer. You can't chain operations.

With aletheia-mcp running in Claude or any MCP-compatible client, you can ask things like:

> "I'm reviewing literature on mitochondrial dysfunction in Parkinson's. Find the 20 most-cited papers from the last 5 years, cluster them by methodology, identify which methodologies are gaining traction vs. declining, and flag any that contradict the dominant view."

Under the hood, Claude chains multiple tool calls — search, fetch full text, analyze citations, compare — and synthesizes an answer. That's the difference between search and research.

## Status

**v0.1.0 — early, actively building.** Tools come online one at a time. Expect rough edges.

Tools planned for v0.1:
- `search_papers` — unified search across PubMed, arXiv, bioRxiv, Semantic Scholar
- `get_paper_metadata` — detailed info on a specific paper (authors, abstract, citations)
- `get_paper_full_text` — fetch full text where open-access available
- `find_related_papers` — semantic and citation-graph neighbors
- `get_citation_graph` — traverse who cites or is cited by a paper

## Install

Not yet on PyPI. To try it locally:

```bash
git clone https://github.com/TechFusionData/aletheia-mcp
cd aletheia-mcp
uv sync
```

Then configure your MCP client to point at the local server. Instructions per client coming once there's something worth installing.

## Why "aletheia"

ἀλήθεια — the Greek notion of truth as "unconcealment," the state of not being hidden. Research is the practice of bringing what's there into view.

## License

MIT. See [LICENSE](./LICENSE).
