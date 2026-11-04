'''Contratos pydantic compartidos entre el loop de tools y el de
verificacion: lo que circula entre plan_route, alerts y verify.'''
from agent.models.alert import Alert
from agent.models.plan import (Itinerary, Leg, PlanError, PlanResult,
                               dump, error, itinerary)
from agent.models.verdict import Verdict
