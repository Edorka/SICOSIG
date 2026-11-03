#!/usr/bin/env python3
'''Descarga los GTFS del CRTM (metro M4 y cercanias M5) y los integra:

- transport-data/train/gtfs-static/  <- M5 tal cual (lo reconstruye el MCP)
- transport-data/train/stops.txt     <- M5 con stop_id prefijado par_5_
- transport-data/metro/              <- M4 refrescado (textos GTFS)
- mcp-madrid-public-transport/gtfs-static.db(.zip) <- reconstruida desde M5
- agent/data/network.db              <- M4+M5 unificada para agent.router

Uso: python scripts/update_gtfs.py [--only metro|cercanias]
'''
import csv
import io
import math
import os
import shutil
import sqlite3
import sys
import urllib.request
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MCP = os.path.join(ROOT, 'mcp-madrid-public-transport')
DATA = os.path.join(MCP, 'transport-data')

FEEDS = {
    'metro': 'https://www.arcgis.com/sharing/rest/content/items/'
             '5c7f2951962540d69ffe8f640d94c246/data',
    'cercanias': 'https://www.arcgis.com/sharing/rest/content/items/'
                 '1a25440bf66f499bae2657ec7fb40144/data',
    'interurbanos': 'https://www.arcgis.com/sharing/rest/content/items/'
                    '885399f83408473c8d815e40c5e702b7/data',
}

GTFS_TXT = ('agency.txt', 'calendar.txt', 'calendar_dates.txt', 'routes.txt',
            'trips.txt', 'stops.txt', 'stop_times.txt', 'transfers.txt',
            'shapes.txt', 'frequencies.txt', 'feed_info.txt',
            'fare_attributes.txt', 'fare_rules.txt')

STOP_HEADERS = ('stop_id', 'stop_code', 'stop_name', 'stop_desc', 'stop_lat',
                'stop_lon', 'zone_id', 'stop_url', 'location_type',
                'parent_station', 'stop_timezone', 'wheelchair_boarding')


def download(url):
    print('  descargando', url.rsplit('/', 3)[-2][:8] + '...')
    with urllib.request.urlopen(url, timeout=120) as res:
        return res.read()


def read_gtfs(zdata):
    '''{nombre.txt: [filas dict]} sin BOM, solo textos GTFS conocidos.'''
    files = {}
    with zipfile.ZipFile(io.BytesIO(zdata)) as zf:
        for name in GTFS_TXT:
            try:
                raw = zf.read(name)
            except KeyError:
                continue
            text = raw.decode('utf-8-sig')
            files[name] = list(csv.DictReader(io.StringIO(text)))
    return files


def write_txt(path, headers, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(headers),
                                extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def install_feed(subdir, files):
    '''Vuelca los textos GTFS del feed a transport-data/<subdir> y
    retira los .zip obsoletos de los textos que se sustituyen.'''
    dest = os.path.join(DATA, subdir)
    for name, rows in files.items():
        write_txt(os.path.join(dest, name), rows[0].keys() if rows else
                  [h for h in STOP_HEADERS], rows)
        sidecar = os.path.join(dest, name + '.zip')
        if os.path.exists(sidecar):
            os.remove(sidecar)
    print('  instalado en', subdir, sorted(files))


def build_train_inmemory_stops(m5):
    '''stops.txt del store en memoria del MCP: modo por prefijo par_5_.'''
    rows = [{'stop_id': 'par_5_' + s['stop_id'], 'stop_code': s['stop_id'],
             'stop_name': s['stop_name'], 'stop_lat': s['stop_lat'],
             'stop_lon': s['stop_lon'],
             'wheelchair_boarding': s.get('wheelchair_boarding', '')}
            for s in m5['stops.txt']]
    write_txt(os.path.join(DATA, 'train', 'stops.txt'), STOP_HEADERS, rows)
    print('  train/stops.txt:', len(rows), 'paradas par_5_*')


def build_gtfs_static_db(m5):
    '''Reconstruye gtfs-static.db(.zip) con el mismo esquema que crea
    SqliteGtfsStaticRepository.ts, a partir del M5.'''
    db_path = os.path.join(MCP, 'gtfs-static.db')
    for suffix in ('', '-shm', '-wal'):
        if os.path.exists(db_path + suffix):
            os.remove(db_path + suffix)
    db = sqlite3.connect(db_path)
    db.executescript('''
        CREATE TABLE stops (stop_id TEXT PRIMARY KEY, stop_name TEXT NOT NULL,
                            stop_lat REAL, stop_lon REAL);
        CREATE TABLE routes (route_id TEXT PRIMARY KEY,
                             route_short_name TEXT NOT NULL,
                             route_long_name TEXT, route_type INTEGER NOT NULL);
        CREATE TABLE trips (trip_id TEXT PRIMARY KEY, route_id TEXT NOT NULL,
                            service_id TEXT, trip_headsign TEXT);
        CREATE TABLE stop_times (trip_id TEXT NOT NULL, stop_id TEXT NOT NULL,
                                 stop_sequence INTEGER NOT NULL,
                                 arrival_time TEXT NOT NULL,
                                 departure_time TEXT NOT NULL,
                                 PRIMARY KEY (trip_id, stop_sequence));
        CREATE TABLE transfers (from_stop_id TEXT NOT NULL,
                                to_stop_id TEXT NOT NULL,
                                transfer_type INTEGER NOT NULL,
                                min_transfer_time INTEGER,
                                PRIMARY KEY (from_stop_id, to_stop_id));
        ''')
    db.executemany(
        'INSERT OR IGNORE INTO stops VALUES (?, ?, ?, ?)',
        [(s['stop_id'], s['stop_name'], s['stop_lat'], s['stop_lon'])
         for s in m5['stops.txt']])
    db.executemany(
        'INSERT OR IGNORE INTO routes VALUES (?, ?, ?, ?)',
        [(r['route_id'], r.get('route_short_name', ''),
          r.get('route_long_name', ''), r.get('route_type', '2'))
         for r in m5['routes.txt']])
    db.executemany(
        'INSERT OR IGNORE INTO trips VALUES (?, ?, ?, ?)',
        [(t['trip_id'], t['route_id'], t.get('service_id', ''),
          t.get('trip_headsign', '')) for t in m5['trips.txt']])
    db.executemany(
        'INSERT OR IGNORE INTO stop_times VALUES (?, ?, ?, ?, ?)',
        [(st['trip_id'], st['stop_id'], st['stop_sequence'],
          st['arrival_time'], st['departure_time'])
         for st in m5['stop_times.txt']])
    db.executemany(
        'INSERT OR IGNORE INTO transfers VALUES (?, ?, ?, ?)',
        [(t['from_stop_id'], t['to_stop_id'],
          t.get('transfer_type') or '0', t.get('min_transfer_time') or None)
         for t in m5.get('transfers.txt', [])])
    db.executescript('''
        CREATE INDEX idx_stop_times_trip ON stop_times(trip_id);
        CREATE INDEX idx_stop_times_stop ON stop_times(stop_id);
        CREATE INDEX idx_stop_times_trip_stop ON stop_times(trip_id, stop_id);
        CREATE INDEX idx_transfers_from ON transfers(from_stop_id);
        CREATE INDEX idx_transfers_to ON transfers(to_stop_id);
        ''')
    db.commit()
    db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    db.close()
    zip_path = db_path + '.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(db_path, 'gtfs-static.db')
    print('  gtfs-static.db reconstruida y comprimida')


def parse_time(value):
    ''''HH:MM:SS' GTFS (puede pasar de 24h) a segundos.'''
    if not value:
        return None
    h, m, s = value.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)


def distance_m(a, b):
    lat1, lon1, lat2, lon2 = (math.radians(v) for v in
                              (a[0], a[1], b[0], b[1]))
    dx = (lon2 - lon1) * math.cos((lat1 + lat2) / 2)
    return 6371000 * math.hypot(dx, lat2 - lat1)


def transfer_edges(stops):
    '''Transbordos a pie: andenes del mismo complejo (parent_station) 150s,
    cualquier parada a menos de 250m 300s. Devuelve aristas simetricas.'''
    edges = set()
    by_parent = {}
    for s in stops:
        if s['parent']:
            by_parent.setdefault(s['parent'], []).append(s)
    for group in by_parent.values():
        for a in group:
            for b in group:
                if a['id'] != b['id']:
                    edges.add((a['id'], b['id'], 150))
    cell = 0.003
    grid = {}
    for s in stops:
        key = (int(s['lat'] / cell), int(s['lon'] / cell))
        grid.setdefault(key, []).append(s)
    for s in stops:
        gx, gy = int(s['lat'] / cell), int(s['lon'] / cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for o in grid.get((gx + dx, gy + dy), []):
                    if o['id'] >= s['id'] or o['parent'] == s['parent'] != '':
                        continue
                    if distance_m((s['lat'], s['lon']),
                                  (o['lat'], o['lon'])) <= 250:
                        edges.add((s['id'], o['id'], 300))
                        edges.add((o['id'], s['id'], 300))
    return edges


def build_network_db(metro, cercanias, interurbanos):
    '''agent/data/network.db: red unificada metro+cercanias+interurbano.'''
    out = os.path.join(ROOT, 'agent', 'data', 'network.db')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out):
        os.remove(out)
    db = sqlite3.connect(out)
    db.executescript('''
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
        ''')

    bus_stops = [s for s in interurbanos['stops.txt']
                 if s.get('location_type', '') in ('', '0')]
    platforms = [s for s in metro['stops.txt']
                 if s.get('location_type', '') in ('', '0')
                 and s['stop_id'].startswith('par_4_')]
    stops, modes = [], {}
    for s in platforms:
        modes[s['stop_id']] = 'metro'
        stops.append({'id': s['stop_id'], 'name': s['stop_name'],
                      'lat': float(s['stop_lat']), 'lon': float(s['stop_lon']),
                      'parent': s.get('parent_station', ''),
                      'mode': 'metro'})
    for s in cercanias['stops.txt']:
        modes[s['stop_id']] = 'cercanias'
        stops.append({'id': s['stop_id'], 'name': s['stop_name'],
                      'lat': float(s['stop_lat']), 'lon': float(s['stop_lon']),
                      'parent': '', 'mode': 'cercanias'})
    for s in bus_stops:
        if s['stop_id'] in modes:
            continue
        modes[s['stop_id']] = 'bus'
        stops.append({'id': s['stop_id'], 'name': s['stop_name'],
                      'lat': float(s['stop_lat']), 'lon': float(s['stop_lon']),
                      'parent': '', 'mode': 'bus'})
    db.executemany('INSERT INTO stops VALUES (?, ?, ?, ?, ?, ?)',
                   [(s['id'], s['name'], s['lat'], s['lon'], s['parent'],
                     s['mode']) for s in stops])

    all_feeds = ((metro, 'metro'), (cercanias, 'cercanias'),
                 (interurbanos, 'bus'))
    for feed, mode in all_feeds:
        db.executemany(
            'INSERT INTO routes VALUES (?, ?, ?, ?, ?)',
            [(r['route_id'], r.get('route_short_name', ''),
              r.get('route_long_name', ''), int(r.get('route_type') or 0), mode)
             for r in feed['routes.txt']])

    freq_trips = {f['trip_id'] for f in metro.get('frequencies.txt', [])}
    for feed, mode in all_feeds:
        db.executemany(
            'INSERT INTO trips VALUES (?, ?, ?, ?, ?)',
            [(t['trip_id'], t['route_id'], t.get('service_id', ''),
              t.get('trip_headsign', '').strip(),
              1 if t['trip_id'] in freq_trips else 0)
             for t in feed['trips.txt']])
        db.executemany(
            'INSERT INTO stop_times VALUES (?, ?, ?, ?, ?)',
            [(st['trip_id'], int(st['stop_sequence']), st['stop_id'],
              parse_time(st['arrival_time']), parse_time(st['departure_time']))
             for st in feed['stop_times.txt']])
        for cal in feed.get('calendar.txt', []):
            dows = sum((int(cal[d]) << i) for i, d in enumerate(
                ('monday', 'tuesday', 'wednesday', 'thursday', 'friday',
                 'saturday', 'sunday')))
            db.execute('INSERT OR REPLACE INTO calendar VALUES (?, ?, ?, ?)',
                       (cal['service_id'], dows, cal['start_date'],
                        cal['end_date']))
        db.executemany(
            'INSERT INTO calendar_dates VALUES (?, ?, ?)',
            [(c['service_id'], c['date'], int(c['exception_type']))
             for c in feed.get('calendar_dates.txt', [])])

    db.executemany(
        'INSERT INTO frequencies VALUES (?, ?, ?, ?)',
        [(f['trip_id'], parse_time(f['start_time']), parse_time(f['end_time']),
          int(f['headway_secs'])) for f in metro.get('frequencies.txt', [])])

    edges = transfer_edges(stops)
    for t in cercanias.get('transfers.txt', []):
        secs = t.get('min_transfer_time')
        if t['from_stop_id'] in modes and t['to_stop_id'] in modes and secs:
            edges.add((t['from_stop_id'], t['to_stop_id'], int(secs)))
            edges.add((t['to_stop_id'], t['from_stop_id'], int(secs)))
    db.executemany('INSERT OR REPLACE INTO transfers VALUES (?, ?, ?)', edges)

    db.commit()
    db.close()
    print('  network.db:', len(stops), 'paradas,', len(edges),
          'transbordos a pie')


def main():
    only = None
    if '--only' in sys.argv:
        only = sys.argv[sys.argv.index('--only') + 1]
        if only not in FEEDS:
            raise SystemExit('--only debe ser metro, cercanias o interurbanos')

    feeds = {}
    for name in FEEDS:
        if only and name != only:
            continue
        print('feed', name)
        feeds[name] = read_gtfs(download(FEEDS[name]))

    if 'metro' in feeds:
        install_feed('metro', feeds['metro'])
    if 'cercanias' in feeds:
        install_feed(os.path.join('train', 'gtfs-static'), feeds['cercanias'])
        build_train_inmemory_stops(feeds['cercanias'])
        build_gtfs_static_db(feeds['cercanias'])
    if 'interurbanos' in feeds:
        install_feed(os.path.join('bus', 'interurban'),
                     feeds['interurbanos'])

    missing = [name for name in FEEDS if name not in feeds]
    if missing:
        print('network.db necesita todos los feeds (%s);'
              ' vuelve a ejecutar sin --only' % ', '.join(missing))
        return
    build_network_db(feeds['metro'], feeds['cercanias'],
                     feeds['interurbanos'])
    print('listo')


if __name__ == '__main__':
    main()
