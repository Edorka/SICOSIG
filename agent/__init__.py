import json
import os
import textwrap

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from agent import alerts, router, verify

DEEPINFRA_URL = 'https://api.deepinfra.com/v1/openai'
DEFAULT_MODEL = 'google/gemma-3-4b-it'  # ollama: gemma3:4b
MCP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                       'mcp-madrid-public-transport'))
MAX_VERIFICATION_ROUNDS = 2


def unindent(text):
    return textwrap.dedent(text).strip()


SYSTEM_PROMPT = unindent('''
    Eres SICOSIG (Should I Come Or Should I GO). Dices como ir de un punto
    a otro de Madrid en metro, cercanias o bus interurbano prefiriendo
    lo mas breve posible.
    Traza la ruta SIEMPRE con la herramienta plan_route (horarios reales
    del GTFS del CRTM), nunca de memoria. Usa las herramientas de llegadas
    del MCP para saber cuanto tardan los proximos trenes en la salida y
    decir si salir ya o esperar. Si plan_route devuelve sugerencias por
    estacion ambigua, reintenta UNA vez con la mas adecuada para el viaje.
    Los avisos de servicio se comprueban FUERA del bucle, tras proponer
    tu itinerario: si despues llega un informe '[VERIFICACION] ...'
    indicando que quedo comprometido, replantea la ruta con plan_route y
    avoid=<esas lineas> o, si no hay alternativa sin aviso, informa del
    aviso en una frase.
    Si plan_route dice que no hay ruta o el feed esta caducado (warning),
    dilo en una frase y nunca inventes tiempos.
    La herramienta MCP de autobus no tiene llegadas ahora, pero plan_route
    ya incluye autobuses interurbanos con sus horarios. Responde solo con
    la ruta: salir ya o esperar, lineas, transbordos y minutos de espera.
    Maximo 4 lineas, en espanol, sin explicaciones.
    ''')


def build_model():
    load_dotenv()
    base_url = os.getenv('SICOSIG_BASE_URL', DEEPINFRA_URL)
    key = os.getenv('SICOSIG_API_KEY') or os.getenv('DEEPINFRA_API_KEY')
    if not key and 'deepinfra' in base_url:
        raise RuntimeError('DEEPINFRA_API_KEY missing, copy .env.example to '
                           '.env and fill it in')
    return ChatOpenAI(model=os.getenv('SICOSIG_MODEL', DEFAULT_MODEL),
                      base_url=base_url,
                      api_key=key or 'not-needed',
                      max_tokens=400,
                      temperature=0.2)


@tool
def plan_route(origin: str, destination: str, avoid: list[str] = []) -> str:
    '''Calcula la ruta mas rapida de Madrid (metro + cercanias + bus
    interurbano) con los horarios GTFS reales del CRTM para la hora
    actual. avoid (opcional): lista de lineas a evitar, p.ej.
    ["C-5", "10"], porque tienen avisos de servicio activos. Devuelve
    lineas, transbordos y duracion. Usar siempre antes de responder la
    ruta.'''
    try:
        result = router.plan_avoiding(origin, destination, avoid)
        return json.dumps(result, ensure_ascii=False)
    except FileNotFoundError as exc:
        return json.dumps({'error': str(exc)}, ensure_ascii=False)
    except LookupError as exc:
        return json.dumps({'error': 'estacion ambigua o desconocida',
                           'sugerencias': exc.args[0]}, ensure_ascii=False)
    except RuntimeError as exc:
        return json.dumps({'error': str(exc)}, ensure_ascii=False)


def build_mcp_client():
    load_dotenv()
    env = {name: os.environ[name]
           for name in ('EMT_CLIENT_ID', 'EMT_PASS_KEY') if os.getenv(name)}
    return MultiServerMCPClient({'madrid-transport': {
        'transport': 'stdio',
        'command': os.getenv('SICOSIG_NODE_BIN', 'node'),
        'args': [os.path.join(MCP_DIR, 'dist', 'index.js')],
        'cwd': MCP_DIR,  # server resolves GTFS data relative to its own dir
        'env': env,
    }})


def noop(_msg):
    pass


def itinerary_of(messages):
    '''Ultima salida util de plan_route en la pasada del agente.'''
    for msg in reversed(messages):
        if getattr(msg, 'name', None) != 'plan_route':
            continue
        try:
            data = json.loads(getattr(msg, 'content', '') or '')
        except ValueError:
            continue
        if isinstance(data, dict) and data.get('legs'):
            return data
    return None


def tool_status(name):
    known = {'plan_route': 'trazando la ruta con los horarios GTFS…'}
    return known.get(name, 'consultando datos en tiempo real (%s)…' % name)


class SicosigAgent:

    def __init__(self):
        self.model = build_model()
        self.mcp = build_mcp_client()

    @classmethod
    async def create(cls, status=noop):
        self = cls()
        status('descargando herramientas del servidor MCP…')
        tools = await self.mcp.get_tools()
        self.graph = create_react_agent(self.model, tools + [plan_route],
                                        prompt=SYSTEM_PROMPT)
        return self

    async def ask(self, question, status=noop):
        messages = [HumanMessage(question)]
        active = None
        for round_ in range(MAX_VERIFICATION_ROUNDS + 1):
            messages = await self.run_loop(messages, status)
            itinerary = itinerary_of(messages)
            if round_ == MAX_VERIFICATION_ROUNDS or not itinerary:
                break  # sin itinerario no hay verificacion ni fetch de avisos
            if active is None:
                status('comprobando avisos de servicio activos…')
                active = alerts.safe_fetch()
                if active:
                    status('%d aviso(s) activo(s) en cercanias' % len(active))
            if not active:
                break
            status('verificando el itinerario contra los avisos…')
            verdict = await verify.check_itinerary(self.model, itinerary,
                                                   active)
            if verdict['clean']:
                break
            status('itinerario comprometido (%s): reportando al agente '
                   'para replanificar…' % ', '.join(verdict['lines'] or ['?']))
            messages = list(messages) + [
                HumanMessage(verify.report_message(verdict))]
        return messages[-1].content

    async def run_loop(self, messages, status):
        latest, seen = messages, len(messages)
        async for state in self.graph.astream({'messages': messages},
                                              stream_mode='values'):
            latest = state['messages']
            for msg in latest[seen:]:
                for call in getattr(msg, 'tool_calls', None) or []:
                    status(tool_status(call.get('name', '?')))
            seen = len(latest)
        return latest
