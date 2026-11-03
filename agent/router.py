'''Planificador A->B de metro y cercanias de Madrid sobre network.db.

CSA (Connection Scan Algorithm) sobre los horarios GTFS del CRTM:
cercanias con stop_times exactos y metro expandido desde frequencies.txt.
Generar network.db con scripts/update_gtfs.py.
'''
import os
import sqlite3
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'network.db')
MADRID_TZ = ZoneInfo('Europe/Madrid')
HORIZON = 3 * 3600
BOARD_SLACK = 90
INF = 10 ** 12


def normalize(text):
    text = text.lower().strip()
    return ''.join(c for c in unicodedata.normalize('NFD', text)
                   if unicodedata.category(c) != 'Mn')


def fmt(sec):
    return '%02d:%02d' % ((sec // 3600) % 24, (sec % 3600) // 60)


def _title(name):
    return name.strip().title()


def service_day(now):
    return (now - timedelta(hours=3)).date()


def seconds_of_day(now):
    t0 = now.hour * 3600 + now.minute * 60 + now.second
    return t0 + 24 * 3600 if now.hour < 3 else t0


def active_services(db, day):
    '''Servicios activos en `day`; fallback por feed caducado (el M4):
    servicios del mismo dia de la semana cuyo rango NO cubre hoy.'''
    active = apply_exceptions(db, day, strict_active(db, day))
    stale = out_of_range_weekday(db, day) - active
    if stale:
        return sorted(active | stale), True
    return sorted(active), False


def strict_active(db, day):
    return {sid for (sid,) in db.execute(
        'SELECT service_id FROM calendar WHERE start <= ? AND "end" >= ?'
        ' AND (dows >> ?) & 1', ymd_dow(day))}


def apply_exceptions(db, day, active):
    for sid, exc in db.execute(
            'SELECT service_id, exception FROM calendar_dates WHERE date = ?',
            (day.strftime('%Y%m%d'),)):
        if exc == 1:
            active.add(sid)
        else:
            active.discard(sid)
    return active


def out_of_range_weekday(db, day):
    return {sid for (sid,) in db.execute(
        'SELECT service_id FROM calendar'
        ' WHERE NOT (start <= ? AND "end" >= ?) AND (dows >> ?) & 1',
        ymd_dow(day))}


def ymd_dow(day):
    return day.strftime('%Y%m%d'), day.strftime('%Y%m%d'), day.weekday()


def services_today(db, now):
    services, stale = active_services(db, service_day(now))
    if not services:
        raise RuntimeError('no hay servicio GTFS activo para hoy')
    return services, stale


def station_rows(db):
    return db.execute('SELECT stop_id, name, parent FROM stops').fetchall()


def find_station(db, query):
    '''Devuelve (etiqueta, {stop_id, ...}) del mejor complejo o sube
    LookupError con nombres parecidos.'''
    norm = normalize(query)
    rows = station_rows(db)
    exact = exact_group(rows, norm)
    if exact:
        return exact
    partials = partial_groups(rows, norm)
    if len(partials) == 1:
        return partial_group(rows, partials)
    raise LookupError(similar_names(partials, rows, norm))


def exact_group(rows, norm):
    exact = [r for r in rows if normalize(r[1]) == norm]
    if not exact:
        return None
    return group_result(rows, exact[0][2] or exact[0][0], exact[0][1])


def partial_groups(rows, norm):
    groups = {}
    for r in rows:
        name = normalize(r[1])
        if norm in name or name.split('-')[-1] == norm:
            groups.setdefault(r[2] or r[0], r[1])
    return groups


def partial_group(rows, groups):
    key, label = next(iter(groups.items()))
    ids = {r[0] for r in rows if (r[2] or r[0]) == key}
    return (_title(label), ids, [_title(p) for p in groups.values()])


def group_result(rows, key, label):
    ids = {r[0] for r in rows if (r[2] or r[0]) == key}
    names = sorted({r[1] for r in rows if r[0] in ids})
    return (_title(label), ids, names)


def similar_names(partials, rows, norm):
    if partials:
        return sorted({_title(p) for p in partials.values()})
    similar = sorted({r[1] for r in rows if norm[:4] in normalize(r[1])})[:5]
    return [_title(s) for s in similar]


def connections_window(db, services, t0):
    conns = static_connections(db, services, t0) + \
        freq_connections(db, services, t0)
    conns.sort(key=lambda c: c[0])
    return conns


def static_connections(db, services, t0):
    marks = ','.join('?' * len(services))
    query = (
        'SELECT a.dep, b.arr, a.stop_id, b.stop_id, a.trip_id'
        ' FROM stop_times a'
        ' JOIN stop_times b ON b.trip_id = a.trip_id AND b.seq = a.seq + 1'
        ' JOIN trips tr ON tr.trip_id = a.trip_id AND tr.freq = 0'
        ' WHERE tr.service_id IN (%s) AND a.dep >= ? AND b.arr <= ?'
        ' ORDER BY a.dep' % marks)
    rows = db.execute(query, (*services, t0, t0 + HORIZON))
    return [(d, a, f, t, ('s', trip)) for d, a, f, t, trip in rows]


def freq_connections(db, services, t0):
    conns = []
    for trip, freqs in freq_trips(db, services).items():
        conns += trip_instances(db, trip, freqs, t0)
    return conns


def freq_trips(db, services):
    marks = ','.join('?' * len(services))
    rows = db.execute(
        'SELECT f.trip_id, f.start, f."end", f.headway'
        ' FROM frequencies f JOIN trips t ON t.trip_id = f.trip_id'
        ' WHERE t.service_id IN (%s)' % marks, services)
    trips = {}
    for trip, start, end, headway in rows:
        trips.setdefault(trip, []).append((start, end, headway))
    return trips


def trip_instances(db, trip, freqs, t0):
    legs = db.execute('SELECT stop_id, arr, dep FROM stop_times'
                      ' WHERE trip_id = ? ORDER BY seq', (trip,)).fetchall()
    if len(legs) < 2:
        return []
    base = legs[0][2]
    return [conn for start, end, headway in freqs
            for conn in instances(legs, trip, base, start, end, headway, t0)]


def instances(legs, trip, base, start, end, headway, t0):
    conns = []
    k = start
    while k < end and k < t0 + HORIZON:
        if k + (legs[-1][1] - base) >= t0:
            conns += leg_connections(legs, ('f', trip, k), k - base)
        k += headway
    return conns


def leg_connections(legs, key, shift):
    return [(da + shift, ab + shift, fa, fb, key)
            for (fa, _aa, da), (fb, ab, _db) in zip(legs, legs[1:])]


def load_transfers(db):
    transfers = {}
    for frm, to, secs in db.execute('SELECT frm, "to", secs FROM transfers'):
        transfers.setdefault(frm, []).append((to, secs))
    return transfers


def csa(connections, transfers, origin_ids, dest_ids, t0):
    earliest = seed_origins(transfers, origin_ids, t0)
    parent, in_trip, best = {}, {}, None
    for dep, arr, frm, to, key in connections:
        if best is not None and dep >= best:
            break
        if not in_trip.get(key) and earliest.get(frm, INF) > dep - BOARD_SLACK:
            continue
        if arr >= earliest.get(to, INF):
            continue
        earliest[to] = arr
        parent[to] = ('ride', frm, key, dep, arr)
        in_trip[key] = True
        relax_foot(earliest, parent, transfers, to, arr)
        if to in dest_ids:
            best = arr
    return earliest, parent


def seed_origins(transfers, origin_ids, t0):
    earliest = {s: t0 for s in origin_ids}
    for frm in origin_ids:
        for to2, secs in transfers.get(frm, ()):
            if t0 + secs < earliest.get(to2, INF):
                earliest[to2] = t0 + secs
    return earliest


def relax_foot(earliest, parent, transfers, to, arr):
    for to2, secs in transfers.get(to, ()):
        if arr + secs < earliest.get(to2, INF):
            earliest[to2] = arr + secs
            parent[to2] = ('walk', to, secs)


def reconstruct(parent, dest_stop, conn_trip_meta):
    legs = merge_legs(chain_legs(parent, dest_stop))
    for leg in legs:
        leg.update(conn_trip_meta(leg['key']))
    return legs


def chain_legs(parent, dest_stop):
    legs = []
    node = dest_stop
    while node in parent:
        step = parent[node]
        if step[0] == 'walk':
            node = step[1]
            continue
        _, frm, key, dep, arr = step
        legs.append({'key': key, 'board': frm, 'alight': node,
                     'dep': dep, 'arr': arr})
        node = frm
    legs.reverse()
    return legs


def merge_legs(legs):
    merged = []
    for leg in legs:
        if merged and merged[-1]['key'] == leg['key']:
            merged[-1]['alight'] = leg['alight']
            merged[-1]['arr'] = leg['arr']
        else:
            merged.append(dict(leg))
    return merged


def trip_meta_query(db):
    def meta(key):
        row = db.execute(
            'SELECT r.short, r.long, r.mode, t.headsign FROM trips t'
            ' JOIN routes r ON r.route_id = t.route_id'
            ' WHERE t.trip_id = ?', (key[1],)).fetchone()
        return meta_dict(row or ('?', '', 'metro', ''))
    return meta


def meta_dict(row):
    short, long_, mode, headsign = row
    return {'modo': mode, 'linea': short,
            'direccion': headsign or _title(long_.split('-')[-1])}


def plan(origin, destination, when=None, db_path=DB_PATH):
    require_db(db_path)
    db = sqlite3.connect(db_path)
    try:
        return build_result(db, origin, destination, when)
    finally:
        db.close()


def require_db(db_path):
    if not os.path.exists(db_path):
        raise FileNotFoundError('network.db no existe; ejecuta '
                                'scripts/update_gtfs.py')


def build_result(db, origin, destination, when):
    now = when or datetime.now(MADRID_TZ)
    t0 = seconds_of_day(now)
    services, stale = services_today(db, now)
    legs, label_o, label_d = solve(db, services, origin, destination, t0)
    result = format_result(db, legs, label_o, label_d)
    if stale:
        result['aviso'] = ('feed GTFS caducado: horarios aproximados por dia'
                           ' de la semana')
    return result


def solve(db, services, origin, destination, t0):
    label_o, ids_o, _ = find_station(db, origin)
    label_d, ids_d, _ = find_station(db, destination)
    conns = connections_window(db, services, t0)
    earliest, parent = csa(conns, load_transfers(db), ids_o, ids_d, t0)
    dest_stop = min(ids_d, key=lambda s: earliest.get(s, INF))
    require_arrival(earliest, dest_stop, label_o, label_d)
    legs = reconstruct(parent, dest_stop, trip_meta_query(db))
    if not legs:
        raise RuntimeError('origen y destino son la misma estacion')
    return legs, label_o, label_d


def require_arrival(earliest, dest_stop, label_o, label_d):
    if earliest.get(dest_stop, INF) == INF:
        raise RuntimeError('no hay ruta con horarios entre %s y %s ahora'
                           % (label_o, label_d))


def format_result(db, legs, label_o, label_d):
    names = {r[0]: r[1] for r in db.execute('SELECT stop_id, name FROM stops')}
    tramos = [tramo_dict(leg, names) for leg in legs]
    salida, llegada = legs[0]['dep'], legs[-1]['arr']
    return {'origen': label_o, 'destino': label_d,
            'salida': fmt(salida), 'llegada': fmt(llegada),
            'duracion_min': round((llegada - salida) / 60),
            'transbordos': max(0, len(tramos) - 1), 'tramos': tramos}


def tramo_dict(leg, names):
    return {'modo': leg['modo'], 'linea': leg['linea'],
            'direccion': leg['direccion'],
            'de': _title(names.get(leg['board'], leg['board'])),
            'a': _title(names.get(leg['alight'], leg['alight'])),
            'sale': fmt(leg['dep']), 'llega': fmt(leg['arr'])}
