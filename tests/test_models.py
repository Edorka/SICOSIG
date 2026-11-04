import json
import unittest

from pydantic import TypeAdapter

from agent import alerts, verify
from agent.models import (Alert, Itinerary, Leg, PlanError, PlanResult,
                          Verdict, dump, error, itinerary)


def router_result(**overrides):
    result = {
        'origin': 'Alfa', 'destination': 'Delta', 'depart': '09:00',
        'arrive': '09:35', 'duration_min': 35, 'transfers': 1,
        'legs': [
            {'mode': 'metro', 'line': '1', 'route_id': '4__1___',
             'direction': 'Gamma', 'frm': 'Alfa', 'to': 'Beta',
             'dep': '09:00', 'arr': '09:05'},
            {'mode': 'cercanias', 'line': 'C1', 'route_id': 'C1',
             'direction': 'Delta', 'frm': 'Gamma', 'to': 'Delta',
             'dep': '09:20', 'arr': '09:35'}],
        'warning': None}
    result.update(overrides)
    return result


RENFE_ENTITY = {
    'alert': {
        'informedEntity': [{'routeId': '10R1'}, {'routeId': '8X'},
                           {'stopId': 'par_5_1'}],
        'activePeriod': [],
        'headerText': {'translation': [
            {'language': 'en', 'text': 'track works'},
            {'language': 'es', 'text': 'obras en la via'}]}}}


class PlanContractTestCase(unittest.TestCase):

    def test_router_dict_round_trips_through_json(self):
        result = itinerary(router_result(warning='feed caducado'))
        self.assertEqual(Itinerary.model_validate_json(dump(result)), result)

    def test_dump_drops_none_warning(self):
        self.assertNotIn('warning', dump(itinerary(router_result())))

    def test_legs_keep_route_ids(self):
        result = itinerary(router_result())
        self.assertEqual([leg.route_id for leg in result.legs],
                         ['4__1___', 'C1'])

    def test_plan_error_discriminates_by_kind(self):
        parsed = TypeAdapter(PlanResult).validate_json(
            dump(error('estacion ambigua', ['Alfa', 'Alfa Centro'])))
        self.assertIsInstance(parsed, PlanError)
        self.assertEqual(parsed.sugerencias, ['Alfa', 'Alfa Centro'])

    def test_plan_result_accepts_itinerary_json(self):
        parsed = TypeAdapter(PlanResult).validate_json(
            dump(itinerary(router_result())))
        self.assertIsInstance(parsed, Itinerary)


class VerdictTestCase(unittest.TestCase):

    def test_parse_verdict_clean(self):
        self.assertEqual(verify.parse_verdict('LIMPIO'), Verdict(clean=True))

    def test_parse_verdict_compromised(self):
        verdict = verify.parse_verdict(
            'COMPROMETIDO: C-5, C-1 | tramo cortado entre Atocha y Aranjuez')
        self.assertEqual(verdict, Verdict(clean=False, lines=['C-5', 'C-1'],
                                          detail='tramo cortado entre '
                                                 'Atocha y Aranjuez'))

    def test_parse_verdict_garbage_is_none(self):
        self.assertIsNone(verify.parse_verdict('no entiendo'))

    def test_fallback_is_conservative(self):
        leg = Leg(mode='cercanias', line='C-1', route_id='10R1',
                  direction='Delta', frm='A', to='B',
                  dep='09:00', arr='09:10')
        alert = Alert(route_ids={'10R1'}, text='obras en la via')
        self.assertEqual(verify.fallback([(leg, [alert])]),
                         Verdict(clean=False, lines=['C-1'],
                                 detail='avisos activos por route_id: '
                                        'obras en la via'))

    def test_report_message_names_lines(self):
        report = verify.report_message(Verdict(clean=False, lines=['C-5'],
                                                detail='obras'))
        self.assertIn('C-5', report)
        self.assertIn('["C-5"]', report)

    def test_payload_carries_itinerary_and_alerts(self):
        alert = Alert(route_ids={'10R1'}, text='obras')
        payload = json.loads(verify.payload(itinerary(router_result()),
                                             [alert]))
        self.assertEqual(payload['avisos_activos'],
                         [{'route_id': '10R1', 'text': 'obras'}])
        self.assertEqual(payload['itinerario'][0]['line'], '1')


class AlertTestCase(unittest.TestCase):

    def test_parse_entity_keeps_madrid_routes(self):
        alert = alerts.parse_entity(RENFE_ENTITY)
        self.assertEqual(alert.route_ids, {'10R1'})
        self.assertEqual(alert.stop_ids, {'par_5_1'})

    def test_parse_entity_prefers_spanish_text(self):
        self.assertEqual(alerts.parse_entity(RENFE_ENTITY).text,
                         'obras en la via')

    def test_madrid_alerts_drops_routeless(self):
        self.assertEqual(alerts.madrid_alerts({'entity': []}), [])

    def test_active_period_filters(self):
        alert = Alert(route_ids={'10R1'}, text='obras',
                      active_period=[{'start': 0, 'end': 100}])
        self.assertTrue(alerts.is_active(alert, now=50))
        self.assertFalse(alerts.is_active(alert, now=200))

    def test_compromised_legs_matches_by_route_id(self):
        leg = Leg(mode='cercanias', line='C-1', route_id='10R1',
                  direction='Delta', frm='A', to='B',
                  dep='09:00', arr='09:10')
        alert = Alert(route_ids={'10R1'}, text='obras')
        self.assertEqual(alerts.compromised_legs([leg], [alert]),
                         [(leg, [alert])])


if __name__ == '__main__':
    unittest.main()
