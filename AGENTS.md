# SICOSIG

LangGraph proof-of-concept agent: brief A→B directions for Madrid public
transport. OpenAI-compatible chat model (DeepInfra by default, ollama for
local serving — same model `gemma-3-4b` on both) + Madrid Transport MCP
server (stdio).

## Structure

- `sicosig.py` — CLI entry point (one-shot query via argv or interactive REPL)
- `agent/__init__.py` — model, MCP client and langgraph agent (`SicosigAgent`)
- `tests/test_agent.py` — unittest, no API key needed
- `mcp-madrid-public-transport/` — third-party MCP server (TS, node, stdio)

## Conventions

Plain python, single quotes, two blank lines between top-level defs, no type
hints, unittest for tests. Config through `.env` (see `.env.example`).

## Commands

- install: `pip install -r requirements.txt` (venv), MCP: `npm install && npm run build` inside `mcp-madrid-public-transport/`
- tests: `python -m unittest discover tests`
- run: `python sicosig.py <pregunta>`

## Notes

The MCP server only exposes real-time arrivals (metro, cercanías, bus EMT),
not A→B routing; the model traces the route from its own knowledge of the
network and uses arrivals to decide "come now or wait".

Data source state: metro works live. Cercanías is broken upstream (shipped
`gtfs-static.db` lacks `par_5_*` GTFS stops → "Stop not found"); the prompt
tells the model to admit it instead of inventing times. Bus needs EMT
credentials. The server must run with `cwd` = its own dir (relative
`GTFS_DATA_PATH`); `better-sqlite3` was bumped to `^13.0.3` in its
`package.json` because `12.4.1` doesn't compile on node 26.

Model note: the agent requires tool calling, and `gemma-3-4b` can't do it
(DeepInfra returns tool calls with empty `{}` args; ollama `gemma3:4b`
reports "does not support tools" — empty replies either way). The deployed
`.env` overrides with `SICOSIG_MODEL=google/gemma-4-31B-it` (DeepInfra tool
calling verified). For fully local serving use a tool-capable ollama model
(e.g. `qwen3:4b`) via `SICOSIG_BASE_URL`/`SICOSIG_MODEL`, never gemma3.
