import unittest

from agent import alerts
from agent.models import Alert, Leg


def alert(route_ids, text='aviso test'):
    return Alert(route_ids=set(route_ids), text=text)


def leg(route_id, line='C-1'):
    return Leg(mode='cercanias', line=line, route_id=route_id,
               direction='B', frm='A', to='B', dep='09:00', arr='09:10')


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
        self.assertEqual(result[0].route_ids, {'10T0011C4'})
        self.assertEqual(result[0].text, '#MadC4b reajuste')

    def test_inactive_period_filtered(self):
        result = alerts.madrid_alerts(SAMPLE_FEED, now=9999)
        self.assertEqual(result, [])

    def test_compromised_legs_matches_route_ids(self):
        legs = [leg('10R1'), leg('10R2', line='C-2'), leg('')]
        hits = alerts.compromised_legs(legs, [alert(('10R1',))])
        self.assertEqual([(found.line, [a.text for a in found_alerts])
                          for found, found_alerts in hits],
                         [('C-1', ['aviso test'])])
        self.assertFalse(alerts.compromised_legs(legs, [alert(('OTRA',))]))


if __name__ == '__main__':
    unittest.main()
