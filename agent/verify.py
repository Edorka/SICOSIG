'''Verificacion del itinerario, una etapa aparte por encima del agent loop.

check_itinerary() se ejecuta tras cada pasada del agente: cruza las etapas
del itinerario propuesto (route_id) con los avisos de servicio activos y,
si hay coincidencias, el prompt aparte VERIFY_PROMPT decide si el aviso
compromete de verdad el viaje (servicio suspendido, tramo cortado, desvio
importante) o es un mero retraso/leve reajuste. El veredicto (Verdict)
vuelve al agente como mensaje '[VERIFICACION] ...' para que replantee la
ruta con plan_route(avoid=...) o informe del aviso. Si el juez no
responde en el formato pedido se es conservador: toda coincidencia por
route_id cuenta como compromiso.
'''
import json
import re
from textwrap import dedent

from agent import alerts
from agent.models import Verdict

VERIFY_PROMPT = dedent('''
    Eres la verificacion de itinerarios de SICOSIG, una etapa aparte que se
    ejecuta despues de que el agente proponga una ruta. Recibes un JSON
    con 'itinerario' (etapas con line, route_id y estaciones) y
    'avisos_activos' (avisos de servicio vigentes con route_id y text).
    Comprueba si alguna etapa del itinerario usa una linea cuyo aviso
    compromete el viaje AHORA: servicio suspendido, tramo cortado, sin
    parada en alguna estacion del trayecto o desvio importante. No
    comprometen meros retrasos, reajustes de frecuencia o avisos
    informativos.
    Responde EXACTAMENTE con UNA linea, sin nada mas:
    LIMPIO
    o bien
    COMPROMETIDO: <lineas afectadas separadas por comas> | <explicacion
    muy breve para el agente>
    ''').strip()

VERDICT = re.compile(r'\s*(LIMPIO|COMPROMETIDO)\b\s*:?(.*)', re.I | re.S)


async def check_itinerary(model, itinerary, active):
    '''Veredicto sobre el itinerario propuesto. Sin coincidencias por
    route_id no hay ni llamada al juez.'''
    hits = alerts.compromised_legs(itinerary.legs, active)
    if not hits:
        return Verdict(clean=True)
    res = await model.ainvoke([('system', VERIFY_PROMPT),
                               ('user', payload(itinerary, active))])
    return parse_verdict(getattr(res, 'content', '') or '') or fallback(hits)


def payload(itinerary, active):
    return json.dumps({'itinerario': legs_payload(itinerary.legs),
                       'avisos_activos': alerts_payload(active)},
                      ensure_ascii=False)


def legs_payload(legs):
    include = {'mode', 'line', 'route_id', 'frm', 'to'}
    return [leg.model_dump(include=include) for leg in legs]


def alerts_payload(active):
    return [{'route_id': rid, 'text': alert.text}
            for alert in active for rid in sorted(alert.route_ids)]


def parse_verdict(text):
    match = VERDICT.match(text or '')
    if not match:
        return None
    if match.group(1).upper() == 'LIMPIO':
        return Verdict(clean=True)
    return compromised(match.group(2))


def compromised(rest):
    lines, _, detail = rest.partition('|')
    names = [n.strip() for n in re.split(r'[,;]', lines) if n.strip()]
    detail = detail.strip() or 'avisos en: ' + lines.strip()
    return Verdict(clean=False, lines=names, detail=detail)


def fallback(hits):
    lines = sorted({leg.line or '?' for leg, _ in hits})
    texts = sorted({a.text for _, found in hits for a in found})
    return Verdict(clean=False, lines=lines,
                   detail='avisos activos por route_id: ' + '; '.join(texts))


def report_message(verdict):
    lines = ', '.join(verdict.lines) or '?'
    avoid = json.dumps(verdict.lines, ensure_ascii=False)
    return ('[VERIFICACION] el itinerario propuesto esta comprometido por '
            'avisos de servicio (%s; lineas: %s). Traza de nuevo con '
            'plan_route pasando avoid=%s; si no hay alternativa sin aviso, '
            'informa del aviso en una frase y da la mejor opcion '
            'disponible.' % (verdict.detail, lines, avoid))
