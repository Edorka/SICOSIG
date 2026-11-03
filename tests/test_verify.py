import json
import unittest
from types import SimpleNamespace

from agent import verify


def alert(route_ids, text='obras en via'):
    return {'route_ids': set(route_ids), 'stop_ids': set(),
            'active_period': [], 'text': text}


ITINERARY = {'origin': 'Alfa', 'destination': 'Beta', 'legs': [
    {'mode': 'cercanias', 'line': 'C-1', 'route_id': '10R1',
     'frm': 'ALFA', 'to': 'BETA', 'direction': 'Beta'}]}


class FakeModel:

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        return SimpleNamespace(content=self.reply)


class VerifyCheckTestCase(unittest.IsolatedAsyncioTestCase):

    async def test_compromised_verdict_from_model(self):
        model = FakeModel('COMPROMETIDO: C-1 | obras entre Alfa y Beta')
        result = await verify.check_itinerary(model, ITINERARY,
                                              [alert(('10R1',))])
        self.assertFalse(result['clean'])
        self.assertEqual(result['lines'], ['C-1'])
        self.assertIn('obras', result['detail'])
        self.assertEqual(model.calls, 1)

    async def test_clean_verdict_from_model(self):
        model = FakeModel('LIMPIO')
        result = await verify.check_itinerary(
            model, ITINERARY, [alert(('10R1',), 'retrasos leves')])
        self.assertTrue(result['clean'])

    async def test_unparseable_verdict_falls_back_to_id_match(self):
        model = FakeModel('parece que... hay algo')
        result = await verify.check_itinerary(model, ITINERARY,
                                              [alert(('10R1',))])
        self.assertFalse(result['clean'])
        self.assertEqual(result['lines'], ['C-1'])
        self.assertIn('obras en via', result['detail'])

    async def test_no_id_match_skips_the_judge(self):
        model = FakeModel('COMPROMETIDO: X | y')
        result = await verify.check_itinerary(model, ITINERARY,
                                              [alert(('10R2',))])
        self.assertTrue(result['clean'])
        self.assertEqual(model.calls, 0)


class VerifyFormatTestCase(unittest.TestCase):

    def test_payload_carries_itinerary_and_alerts(self):
        data = json.loads(verify.payload(ITINERARY, [alert(('10R1',))]))
        self.assertEqual(data['itinerario'][0]['route_id'], '10R1')
        self.assertEqual(data['itinerario'][0]['line'], 'C-1')
        self.assertNotIn('direction', data['itinerario'][0])
        self.assertEqual(data['avisos_activos'][0]['route_id'], '10R1')

    def test_report_message_tells_agent_to_replan(self):
        verdict = {'clean': False, 'lines': ['C-1'], 'detail': 'obras en via'}
        report = verify.report_message(verdict)
        self.assertIn('[VERIFICACION]', report)
        self.assertIn('C-1', report)
        self.assertIn('avoid=["C-1"]', report)
        self.assertIn('obras en via', report)

    def test_prompt_is_unindented(self):
        self.assertFalse(verify.VERIFY_PROMPT.startswith((' ', '\n')))
        for line in verify.VERIFY_PROMPT.splitlines():
            self.assertFalse(line.startswith(' '))

    def test_parse_verdict_accepts_compact_forms(self):
        result = verify.parse_verdict('COMPROMETIDO:C-1|obras')
        self.assertEqual(result['lines'], ['C-1'])
        self.assertEqual(result['detail'], 'obras')


if __name__ == '__main__':
    unittest.main()
