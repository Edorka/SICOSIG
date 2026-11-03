import json
import os
import textwrap

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from agent import router

DEEPINFRA_URL = 'https://api.deepinfra.com/v1/openai'
DEFAULT_MODEL = 'google/gemma-3-4b-it'  # ollama: gemma3:4b
MCP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                       'mcp-madrid-public-transport'))


def unindent(text):
    return textwrap.dedent(text).strip()


SYSTEM_PROMPT = unindent('''
    Eres SICOSIG (Should I Come Or Should I GO). Dices como ir de un punto
    a otro de Madrid en metro o cercanias prefiriendo lo mas breve posible.
    Traza la ruta SIEMPRE con la herramienta plan_ruta (horarios reales
    del GTFS del CRTM), nunca de memoria. Usa las herramientas de llegadas
    del MCP para saber cuanto tardan los proximos trenes en la salida y
    decir si salir ya o esperar. Si plan_ruta devuelve sugerencias por
    estacion ambigua, reintenta UNA vez con la mas adecuada para el viaje.
    Si plan_ruta dice que no hay ruta o el feed esta caducado (aviso),
    dilo en una frase y nunca inventes tiempos.
    La herramienta MCP de autobus no tiene llegadas ahora, pero plan_ruta
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
def plan_ruta(origen: str, destino: str) -> str:
    '''Calcula la ruta mas rapida de Madrid (metro + cercanias) con los
    horarios GTFS reales del CRTM para la hora actual. Devuelve lineas,
    transbordos y duracion. Usar siempre antes de responder la ruta.'''
    try:
        return json.dumps(router.plan(origen, destino), ensure_ascii=False)
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


class SicosigAgent:

    def __init__(self):
        self.model = build_model()
        self.mcp = build_mcp_client()

    @classmethod
    async def create(cls):
        self = cls()
        tools = await self.mcp.get_tools()
        self.graph = create_react_agent(self.model, tools + [plan_ruta],
                                        prompt=SYSTEM_PROMPT)
        return self

    async def ask(self, question):
        result = await self.graph.ainvoke({'messages': [question]})
        return result['messages'][-1].content
