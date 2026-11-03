import os
import sqlite3
import tempfile
import unittest
from datetime import datetime

from zoneinfo import ZoneInfo

from agent.router import (active_services, find_station, freq_connections,
                          normalize, plan, plan_avoiding)


SCHEMA = '''
    CREATE TABLE stops (stop_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                        lat REAL, lon REAL, parent TEXT, mode TEXT);
    CREATE TABLE routes (route_id TEXT PRIMARY KEY, short TEXT,
                         long TEXT, type INTEGER, mode TEXT);
    CREATE TABLE trips (trip_id TEXT PRIMARY KEY, route_id TEXT,
                        service_id TEXT, headsign TEXT, freq INTEGER);
    CREATE TABLE stop_times (trip_id TEXT NOT NULL, seq INTEGER NOT NULL,
                             stop_id TEXT NOT NULL, arr INTEGER NOT NULL,
                             dep INTEGER NOT NULL,
                             PRIMARY KEY (trip_id, seq));
    CREATE TABLE frequencies (trip_id TEXT NOT NULL, start INTEGER,
                              "end" INTEGER, headway INTEGER);
    CREATE TABLE calendar (service_id TEXT PRIMARY KEY, dows INTEGER,
                           start TEXT, "end" TEXT);
    CREATE TABLE calendar_dates (service_id TEXT, date TEXT,
                                 exception INTEGER);
    CREATE TABLE transfers (frm TEXT, "to" TEXT, secs INTEGER,
                            PRIMARY KEY (frm, "to"));
    CREATE INDEX idx_stop_times_stop ON stop_times(stop_id);
    CREATE INDEX idx_transfers_frm ON transfers(frm);
    '''


def hour(value):
    h, m = divmod(value, 100)
    return h * 3600 + m * 60


def build_db(path):
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    stops = [('par_4_1', 'ALFA', 40.0, -3.7, '', 'metro'),
             ('par_4_2', 'BETA', 40.001, -3.7, '', 'metro'),
             ('par_4_3', 'GAMMA', 40.002, -3.7, '', 'metro'),
             ('90001', 'Madrid-Gamma Cercanias', 40.0021, -3.7001, '',
              'cercanias'),
             ('90002', 'DELTA', 40.003, -3.7, '', 'cercanias'),
             ('par_8_1', 'EPSILON', 40.0032, -3.7002, '', 'bus'),
             ('par_8_2', 'ZETA', 40.004, -3.7, '', 'bus')]
    db.executemany('INSERT INTO stops VALUES (?, ?, ?, ?, ?, ?)', stops)
    db.executemany('INSERT INTO routes VALUES (?, ?, ?, ?, ?)',
                   [('4__1___', '1', 'Alfa-Gamma', 1, 'metro'),
                    ('C1', 'C1', 'Gamma-Delta', 2, 'cercanias'),
                    ('8__421___', '421', 'Epsilon-Zeta', 3, 'bus')])
    db.executemany('INSERT INTO trips VALUES (?, ?, ?, ?, ?)',
                   [('I12-1', '4__1___', 'I12', 'GAMMA', 1),
                    ('C1-t1', 'C1', '1001', 'Delta', 0),
                    ('421-t1', '8__421___', 'BUS1', 'Zeta', 0)])
    db.executemany('INSERT INTO calendar VALUES (?, ?, ?, ?)',
                   [('I12', 31, '20200101', '20201231'),
                    ('1001', 127, '20200101', '20991231'),
                    ('BUS1', 127, '20200101', '20991231')])
    db.executemany('INSERT INTO stop_times VALUES (?, ?, ?, ?, ?)',
                   [('I12-1', 1, 'par_4_1', hour(900), hour(900)),
                    ('I12-1', 2, 'par_4_2', hour(905), hour(905)),
                    ('I12-1', 3, 'par_4_3', hour(910), hour(910)),
                    ('C1-t1', 1, '90001', hour(920), hour(920)),
                    ('C1-t1', 2, '90002', hour(935), hour(935)),
                    ('421-t1', 1, 'par_8_1', hour(940), hour(940)),
                    ('421-t1', 2, 'par_8_2', hour(955), hour(955))])
    db.execute('INSERT INTO frequencies VALUES (?, ?, ?, ?)',
               ('I12-1', hour(900), hour(1100), 300))
    db.executemany('INSERT INTO transfers VALUES (?, ?, ?)',
                   [('par_4_3', '90001', 180), ('90002', 'par_8_1', 180)])
    db.commit()
    return db


class RouterTestCase(unittest.TestCase):

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        self.db = build_db(self.db_path)

    def tearDown(self):
        self.db.close()
        os.remove(self.db_path)

    def today(self):
        return datetime(2026, 11, 3, 8, 55, tzinfo=ZoneInfo('Europe/Madrid'))

    def test_normalize_strips_accents(self):
        self.assertEqual(normalize('Príncipe Pío'), 'principe pio')

    def test_find_station_exact(self):
        label, ids, _ = find_station(self.db, 'alfa')
        self.assertEqual(label, 'Alfa')
        self.assertEqual(ids, {'par_4_1'})

    def test_find_station_partial_ambiguous_raises(self):
        self.assertRaises(LookupError, find_station, self.db, 'a')

    def test_active_services_strict(self):
        services, stale = active_services(self.db, self.today().date())
        self.assertIn('1001', services)
        self.assertIn('I12', services)  # caducado: fallback por dia semanal
        self.assertTrue(stale)

    def test_active_services_stale_flag(self):
        self.db.execute('DELETE FROM calendar WHERE service_id = ?', ('I12',))
        self.db.commit()
        services, stale = active_services(self.db, self.today().date())
        self.assertFalse(stale)
        self.assertNotIn('I12', services)

    def test_freq_connections_expand(self):
        conns = freq_connections(self.db, ['I12'], hour(855))
        self.assertTrue(conns)
        deps = sorted(c[0] for c in conns if c[2] == 'par_4_1')
        self.assertEqual(deps[0], hour(900))
        self.assertEqual(deps[1] - deps[0], 300)

    def test_plan_metro_with_cercanias_transfer(self):
        result = plan('Alfa', 'Delta', when=self.today(), db_path=self.db_path)
        self.assertEqual(result['origin'], 'Alfa')
        self.assertEqual(result['destination'], 'Delta')
        self.assertEqual([t['line'] for t in result['legs']], ['1', 'C1'])
        self.assertEqual(result['transfers'], 1)
        self.assertEqual(result['arrive'], '09:35')

    def test_plan_bus_interurbano_chain(self):
        result = plan('Alfa', 'Zeta', when=self.today(), db_path=self.db_path)
        self.assertEqual([t['line'] for t in result['legs']],
                         ['1', 'C1', '421'])
        self.assertEqual(result['transfers'], 2)
        self.assertEqual(result['arrive'], '09:55')

    def test_plan_same_origin_destination(self):
        self.assertRaises(RuntimeError, plan, 'Delta', 'Delta',
                          when=self.today(), db_path=self.db_path)

    def test_plan_unknown_station(self):
        self.assertRaises(LookupError, plan, 'Nada', 'Delta',
                          when=self.today(), db_path=self.db_path)

    def test_legs_carry_route_ids(self):
        result = plan('Alfa', 'Delta', when=self.today(),
                      db_path=self.db_path)
        self.assertEqual([t['route_id'] for t in result['legs']],
                         ['4__1___', 'C1'])

    def test_plan_avoiding_skips_line(self):
        self.assertRaises(RuntimeError, plan_avoiding, 'Alfa', 'Delta',
                          ['c1'], when=self.today(), db_path=self.db_path)

    def test_plan_avoiding_unknown_line_is_noop(self):
        result = plan_avoiding('Alfa', 'Delta', ['X99'], when=self.today(),
                               db_path=self.db_path)
        self.assertEqual([t['line'] for t in result['legs']], ['1', 'C1'])


if __name__ == '__main__':
    unittest.main()
