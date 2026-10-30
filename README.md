# SICOSIG

**Should I Come Or Should I Go**: a langgraph agent that tells you how to get
from A to B in Madrid public transport (metro and cercanías) as briefly as
possible, using real-time arrivals from the
[Madrid Transport MCP server](https://github.com/dieguezz/mcp-madrid-public-transport)
and a small chat model on [DeepInfra](https://deepinfra.com).

# Models

Same agent, two backends (configurable in `.env`, see `.env.example`):

- **DeepInfra** (default): `google/gemma-3-4b-it`, no install, needs
  `DEEPINFRA_API_KEY`.
- **Local via ollama**: `ollama pull gemma3:4b`, then set
  `SICOSIG_BASE_URL=http://localhost:11434/v1` and `SICOSIG_MODEL=gemma3:4b`.

# Setup

Clone and build the MCP server (only once, downloads ~200MB of GTFS data):

```
git clone https://github.com/dieguezz/mcp-madrid-public-transport.git
cd mcp-madrid-public-transport && npm install && npm run build && cd ..
```

Then the python side:

```
virtualenv -p python3 .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in DEEPINFRA_API_KEY
```

# Usage

One shot:

```
python sicosig.py ¿cómo llego de Sol a Getafe?
```

Interactive:

```
python sicosig.py
sicosig> de Atocha a Chamartín
```

Current state of the data sources:

- **Metro**: real-time arrivals, works out of the box ✅
- **Cercanías**: broken upstream (the shipped `gtfs-static.db` has no
  `par_5_*` stops and the repo no longer carries the train GTFS; the tool
  answers "Stop not found"). The agent says so instead of inventing times.
- **Bus EMT**: needs `EMT_CLIENT_ID` and `EMT_PASS_KEY`
  (free at https://openapi.emtmadrid.es) in `.env`; untested without them.

Note for node >= 25: the MCP pins `better-sqlite3@13` (patched in
`mcp-madrid-public-transport/package.json`, upstream `12.4.1` doesn't
compile on this node).

# Running the tests

```
python -m unittest discover tests
```
