import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage

from agent import (DEFAULT_MODEL, MAX_VERIFICATION_ROUNDS, MCP_DIR,
                   SYSTEM_PROMPT, SicosigAgent, unindent, build_mcp_client,
                   build_model, itinerary_of)
from agent.models import Alert, Itinerary, Leg


class AgentConfigTestCase(unittest.TestCase):

    def test_prompt_is_brief_and_spanish(self):
        self.assertIn('SICOSIG', SYSTEM_PROMPT)
        self.assertIn('espanol', SYSTEM_PROMPT)
        self.assertIn('breve', SYSTEM_PROMPT)

    def test_prompt_is_unindented(self):
        self.assertFalse(SYSTEM_PROMPT.startswith((' ', '\n')))
        for line in SYSTEM_PROMPT.splitlines():
            self.assertFalse(line.startswith(' '))

    def test_unindent_strips_common_indentation(self):
        self.assertEqual(unindent('''
            hola
              mundo
        '''), 'hola\n  mundo')

    def test_unindent_keeps_relative_indentation(self):
        self.assertEqual(unindent('''
              a
                b
              c
        '''), 'a\n  b\nc')

    def test_model_defaults_to_deepinfra(self):
        with patch.dict(os.environ, {'DEEPINFRA_API_KEY': 'test'}), \
                patch('agent.load_dotenv'):
            model = build_model()
            self.assertEqual(model.model_name, DEFAULT_MODEL)
            self.assertEqual(model.openai_api_base,
                             'https://api.deepinfra.com/v1/openai')

    def test_model_requires_api_key(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch('agent.load_dotenv'):
            self.assertRaises(RuntimeError, build_model)

    def test_local_model_needs_no_key(self):
        env = {'SICOSIG_BASE_URL': 'http://localhost:11434/v1'}
        with patch.dict(os.environ, env, clear=True), \
                patch('agent.load_dotenv'):
            model = build_model()
            self.assertEqual(model.openai_api_base,
                             'http://localhost:11434/v1')

    def test_mcp_server_points_to_built_server(self):
        with patch('agent.load_dotenv'):
            target = build_mcp_client().connections['madrid-transport']
        entrypoint = target['args'][0]
        self.assertTrue(entrypoint.startswith(MCP_DIR))
        self.assertTrue(entrypoint.endswith('dist/index.js'))

    def test_mcp_transport_is_stdio(self):
        with patch('agent.load_dotenv'):
            target = build_mcp_client().connections['madrid-transport']
        self.assertEqual(target['transport'], 'stdio')

    def test_itinerary_of_picks_last_valid_route(self):
        error = ToolMessage(content='{"kind": "error", "error": "sin ruta"}',
                            tool_call_id='1', name='plan_route')
        valid = ToolMessage(content=make_itinerary().model_dump_json(),
                            tool_call_id='2', name='plan_route')
        self.assertEqual(itinerary_of([error, valid]), make_itinerary())
        self.assertIsNone(itinerary_of([error]))
        self.assertIsNone(itinerary_of([]))


def make_itinerary():
    leg = Leg(mode='cercanias', line='C-1', route_id='10R1',
              direction='B', frm='A', to='B', dep='09:00', arr='09:10')
    return Itinerary(origin='A', destination='B', depart='09:00',
                     arrive='09:10', duration_min=10, transfers=0,
                     legs=[leg])


ROUTE = make_itinerary()
ACTIVE = [Alert(route_ids={'10R1'}, text='obras en via')]


class FakeGraph:

    def __init__(self, probe, itinerary):
        self.probe = probe
        self.itinerary = itinerary
        self.runs = 0

    async def astream(self, state, stream_mode=None):
        self.probe.append('run')
        self.runs += 1
        messages = list(state['messages'])
        if self.itinerary is not None:
            call = AIMessage(content='', tool_calls=[
                {'name': 'plan_route', 'args': {}, 'id': 't'}])
            tool = ToolMessage(content=self.itinerary.model_dump_json(),
                               tool_call_id='t', name='plan_route')
            messages += [call, tool]
        messages.append(AIMessage(content='respuesta'))
        yield {'messages': messages}


class FakeJudge:

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        return SimpleNamespace(content=self.reply)


class FakeAgent(SicosigAgent):

    def __init__(self, probe, itinerary, judge_reply):
        self.graph = FakeGraph(probe, itinerary)
        self.model = FakeJudge(judge_reply)


class AskFlowTestCase(unittest.IsolatedAsyncioTestCase):

    def make_agent(self, itinerary, judge_reply='LIMPIO', probe=None):
        probe = probe if probe is not None else []
        return FakeAgent(probe, itinerary, judge_reply), probe

    def probe_fetch(self, probe):
        def fetch(*args, **kwargs):
            probe.append('fetch')
            return ACTIVE
        return patch('agent.alerts.safe_fetch', side_effect=fetch)

    async def test_no_verification_before_itinerary(self):
        agent_, probe = self.make_agent(None)
        with self.probe_fetch(probe) as fetch:
            answer = await agent_.ask('hola')
        self.assertEqual(answer, 'respuesta')
        self.assertFalse(fetch.called)
        self.assertEqual(agent_.model.calls, 0)
        self.assertEqual(agent_.graph.runs, 1)
        self.assertEqual(probe, ['run'])

    async def test_alerts_fetched_only_after_itinerary(self):
        agent_, probe = self.make_agent(ROUTE)
        with self.probe_fetch(probe):
            await agent_.ask('de A a B')
        self.assertEqual(probe, ['run', 'fetch'])  # fetch tras el itinerario

    async def test_compromised_loops_then_agent_answers(self):
        agent_, probe = self.make_agent(ROUTE, 'COMPROMETIDO: C-1 | obras')
        with self.probe_fetch(probe):
            answer = await agent_.ask('de A a B')
        self.assertEqual(probe.count('run'), MAX_VERIFICATION_ROUNDS + 1)
        self.assertEqual(answer, 'respuesta')
        self.assertFalse(answer.startswith('[VERIFICACION]'))


if __name__ == '__main__':
    unittest.main()
