'''Veredicto de la etapa de verificacion: LIMPIO o COMPROMETIDO con las
lineas afectadas y el detalle que viaja al agente en el informe
[VERIFICACION].'''
from pydantic import BaseModel


class Verdict(BaseModel):
    clean: bool
    lines: list[str] = []
    detail: str = ''
