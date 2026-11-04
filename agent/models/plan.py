'''Contrato del resultado de plan_route.

El router sigue devolviendo dicts; la frontera pydantic es el propio
tool: plan_route valida con itinerary() y serializa con dump(), y el
mensaje del tool se re-valida con Itinerary.model_validate_json en la
etapa de verificacion. PlanResult es la union discriminada por kind que
distingue itinerario de error sin adivinar por la forma del JSON.
'''
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class Leg(BaseModel):
    mode: str
    line: str
    route_id: str = ''
    direction: str
    frm: str
    to: str
    dep: str
    arr: str


class Itinerary(BaseModel):
    kind: Literal['itinerary'] = 'itinerary'
    origin: str
    destination: str
    depart: str
    arrive: str
    duration_min: int
    transfers: int
    legs: list[Leg]
    warning: str | None = None


class PlanError(BaseModel):
    kind: Literal['error'] = 'error'
    error: str
    sugerencias: list[str] | None = None


PlanResult = Annotated[Union[Itinerary, PlanError],
                       Field(discriminator='kind')]


def itinerary(result):
    '''Dict del router -> Itinerary (kind toma su valor por defecto).'''
    return Itinerary.model_validate(result)


def error(message, sugerencias=None):
    return PlanError(error=message, sugerencias=sugerencias)


def dump(model):
    '''JSON que ve el LLM: mismo formato que hoy, sin claves nulas.'''
    return model.model_dump_json(exclude_none=True)
