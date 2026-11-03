import unittest

from agent import alerts


def alert(route_ids, text='aviso test'):
    return {'route_ids': set(route_ids), 'stop_ids': set(),
            'active_period': [], 'text': text}


SAMPLE_FEED = {'entity': [
    {'id': '1', 'alert': {
        'activePeriod': [{'start': '100', 'end': '200'}],
        'informedEntity': [{'routeId': '10T0011C4'}],
        'descriptionText': {'translation': [
            {'text': '#MadC4b reajuste', 'language': 'es'}]}},},
    {'id': '2', 'alert': {
        'informedEntity': [{'routeId': '70X999'}],
        'descriptionText': {'translation': [
            {'text': 'sevilla', 'language': 'es'}]}},},
]}


class AlertsTestCase(unittest.TestCase):

    def test_parse_entity_keeps_madrid_routes(self):
        result = alerts.madrid_alerts(SAMPLE_FEED, now=150)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['route_ids'], {'10T0011C4'})
        self.assertEqual(result[0]['text'], '#MadC4b reajuste')

    def test_inactive_period_filtered(self):
        result = alerts.madrid_alerts(SAMPLE_FEED, now=9999)
        self.assertEqual(result, [])

    def test_compromised_legs_matches_route_ids(self):
        legs = [{'route_id': '10R1', 'line': 'C-1'}, {'route_id': '10R2'},
                {'route_id': ''}]
        hits = alerts.compromised_legs(legs, [alert(('10R1',))])
        self.assertEqual([hit['leg']['line'] for hit in hits], ['C-1'])
        self.assertEqual(hits[0]['alerts'][0]['text'], 'aviso test')
        self.assertFalse(alerts.compromised_legs(legs, [alert(('OTRA',))]))


if __name__ == '__main__':
    unittest.main()
