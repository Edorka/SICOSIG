import os

from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

DEEPINFRA_URL = 'https://api.deepinfra.com/v1/openai'
DEFAULT_MODEL = 'google/gemma-3-4b-it'  # ollama: gemma3:4b
MCP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                       'mcp-madrid-public-transport'))

SYSTEM_PROMPT = '''Eres SICOSIG (Should I Come Or Should I GO). Dices como ir de un punto
a otro de Madrid en metro o cercanias prebuiltsiendo lo mas breve posible.
Usa la herramienta de metro para saber cuanto tardan los proximos trenes
en la salida y decir si salir ya o esperar. Para trazar la ruta usa tu
conocimiento de la red de metro de Madrid. Las herramientas de cercanias
y autobus no tienen datos ahora: si el viaje los necesita, dilo en una
frase y nunca inventes tiempos. Responde solo con la ruta: salir ya o
esperar, lineas, transbordos y minutos de espera. Maximo 4 lineas, en
espanol, sin explicaciones.'''


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
        self.graph = create_react_agent(self.model, tools,
                                        prompt=SYSTEM_PROMPT)
        return self

    async def ask(self, question):
        result = await self.graph.ainvoke({'messages': [question]})
        return result['messages'][-1].content
