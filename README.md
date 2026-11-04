# SICOSIG

![LLM agent](https://img.shields.io/badge/LLM-tool_calling_agent-8B5CF6)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-agent_loop-1C3C3C?logo=langchain&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-data_contracts-E92063?logo=pydantic&logoColor=white)
![TDD](https://img.shields.io/badge/TDD-unittest-2EA44F)

**Should I Come Or Should I Go**: a langgraph agent that tells you how to get
from A to B in Madrid public transport (metro and cercanías) as briefly as
possible, using real-time arrivals from the
[Madrid Transport MCP server](https://github.com/dieguezz/mcp-madrid-public-transport)
and a small chat model on [DeepInfra](https://deepinfra.com).

# Models

Same agent, two backends (configurable in `.env`, see `.env.example`):

- **DeepInfra** (default): `google/gemma-3-4b-it`, no install, needs
  `DEEPINFRA_API_KEY`.
- **Local via ollama** (tool calling verified): `ollama pull qwen3.5:4b`,
  then set `SICOSIG_BASE_URL=http://localhost:11434/v1` and
  `SICOSIG_MODEL=qwen3.5:4b`. Do not use gemma models: they can't call
  tools, and the agent needs them to check real-time arrivals.

# Setup

Clone this repo with submodules and build the MCP server (only once,
downloads ~200MB of GTFS data):

```
git clone --recurse-submodules https://github.com/Edorka/SICOSIG.git
cd SICOSIG/mcp-madrid-public-transport && npm install && npm run build && cd ..
```

(For an existing clone: `git submodule update --init`.)

Then the python side:

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in DEEPINFRA_API_KEY
```

Download and integrate the official CRTM GTFS feeds (metro + cercanías,
fixes cercanías arrivals and builds the local route planner DB, stdlib
only):

```
python scripts/update_gtfs.py
```

⚠️ **Warning for node >= 25**: `better-sqlite3@12.4.1` (shipped by the
upstream submodule) doesn't compile on this node. The working fix is
bumping it to `^13.0.3` in `mcp-madrid-public-transport/package.json`,
but since the submodule points at upstream, **this patch is not in a
fresh clone** — `npm install` will fail. Re-apply it by hand after
cloning before building the server.


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

- **Metro**: real-time arrivals (teleindicadores), works out of the box ✅
- **Cercanías**: station search fixed with the official CRTM M5 feed
  (run `scripts/update_gtfs.py`); realtime comes from Renfe GTFS-RT,
  which publishes vehicle positions only, so expected arrivals at a
  station are computed from positions + scheduled times and can be empty.
- **Route planner**: `plan_route` tool computes A→B metro+cercanías+
  interurban bus routes with the CRTM scheduled times (runs
  `scripts/update_gtfs.py` first, builds `agent/data/network.db`). Note:
  the metro M4 feed the CRTM publishes is stale (valid until 2026-05):
  the planner falls back to weekday patterns then and flags the answer
  with `warning`. Active alerts (Renfe's official GTFS-RT ServiceAlerts,
  no auth) are handled outside the tool and lazily: only once the agent
  loop has proposed an itinerary, alerts are fetched and a separate
  verification prompt checks the itinerary against them (no itinerary →
  nothing is fetched or verified); if compromised, it reports back to
  the agent, which replans with `plan_route(avoid=[...])` or informs
  about the alert. The CLI shows each stage (planning via MCP/GTFS
  tools, checking alerts, verifying) on stderr.
- **Bus EMT realtime**: needs `EMT_CLIENT_ID` and `EMT_PASS_KEY`
  (free at https://openapi.emtmadrid.es) in `.env`; untested without them.
  Interurban buses already plan from their GTFS schedules.

# Running the tests

```
python -m unittest discover tests
```
