'''Aviso de servicio GTFS-RT (Renfe) tal y como lo consume el cruce con el
itinerario: route_ids/stop_ids ya filtrados a los selectores de Madrid.
'''
from pydantic import BaseModel


class Alert(BaseModel):
    route_ids: set[str] = set()
    stop_ids: set[str] = set()
    active_period: list[dict] = []
    text: str
