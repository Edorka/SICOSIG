'''Avisos de servicio activos y su cruce con el itinerario propuesto.

Fuente: ServiceAlerts GTFS-RT oficial de Renfe (cercanias, sin auth, se
actualiza cada 20 s). La validacion NO ocurre dentro de plan_route: la
capa verify, por encima del agent loop, cruza el itinerario propuesto
contra estos avisos (compromised_legs) y reporta al agente. Los avisos
solo se piden (safe_fetch) una vez que existe un itinerario; sin
itinerario no hay fetch ni juez.
Metro/CRTM/EMT no exponen avisos publicos accionables hoy; anadir
fuentes = nueva funcion fetcher.
'''
import json
import time
import urllib.request

from agent.models import Alert

RENFE_ALERTS_URL = 'https://gtfsrt.renfe.com/alerts.json'
FETCH_TIMEOUT = 10
CACHE_TTL = 60
_cache = {'at': 0.0, 'alerts': []}


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as res:
        return json.loads(res.read())


def safe_fetch(url=RENFE_ALERTS_URL):
    '''Avisos cacheados; si la fuente falla devuelve [] (no rompe rutas).'''
    if time.time() - _cache['at'] > CACHE_TTL:
        try:
            _cache['alerts'] = madrid_alerts(fetch_json(url))
        except Exception:
            _cache['alerts'] = []
        _cache['at'] = time.time()
    return _cache['alerts']


def madrid_alerts(feed, now=None):
    return [alert for alert in (parse_entity(e) for e in feed.get('entity', []))
            if alert.route_ids and is_active(alert, now)]


def parse_entity(entity):
    alert = entity.get('alert', {})
    selectors = alert.get('informedEntity') or [{}]
    return Alert(route_ids=madrid_routes(selectors),
                 stop_ids=stops_of(selectors),
                 active_period=alert.get('activePeriod') or [],
                 text=first_text(alert))


def madrid_routes(selectors):
    routes = {s.get('routeId') for s in selectors}
    return {r for r in routes if r and r.startswith('10')}


def stops_of(selectors):
    return {s.get('stopId') for s in selectors} - {None}


def first_text(alert):
    for key in ('headerText', 'descriptionText'):
        translations = (alert.get(key) or {}).get('translation') or []
        es = [t['text'] for t in translations if t.get('language') == 'es']
        chosen = es or [t['text'] for t in translations]
        if chosen:
            return ' '.join(chosen[0].split())[:200]
    return 'aviso de servicio'


def is_active(alert, now):
    now = now or time.time()
    periods = alert.active_period
    if not periods:
        return True
    return any(float(p.get('start', 0)) <= now <= float(p.get('end', now + 1))
               for p in periods)


def compromised_legs(legs, active):
    '''Etapas del itinerario cuya linea tiene un aviso activo que le
    repercute; el emparejamiento es por route_id. Devuelve (leg, avisos).'''
    hits = []
    for leg in legs:
        matches = leg_alerts(leg, active)
        if matches:
            hits.append((leg, matches))
    return hits


def leg_alerts(leg, active):
    return [alert for alert in active
            if leg.route_id and leg.route_id in alert.route_ids]
