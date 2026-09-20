"""Genera docs/index.html: un solo archivo, sin servidor y sin recursos externos.

La página lleva JavaScript embebido para los menús, la navegación entre
semanas y las animaciones. No hay CDN, ni hojas de estilo aparte, ni llamadas
de red: toda la temporada viaja dentro del mismo archivo como JSON, y el
navegador solo la dibuja.

El podio y la tabla general se escriben directo en el HTML, así que se ven
aunque el navegador no ejecute nada; las vistas por semana se arman al vuelo.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from .espn import Partido, a_cdmx, ahora_cdmx
from .scoring import (
    ACUMULADO_SEMANAL,
    ACUMULADO_TOTAL,
    PREMIO_SEMANAL,
    SEMANAS_TEMPORADA,
    ganadores,
    premio_semanal,
    reparto_final,
)

__all__ = [
    "DESARROLLADOR",
    "ETAPA",
    "MARCA",
    "RUTA_SALIDA",
    "SemanaRender",
    "UMBRAL_PODIO",
    "UMBRAL_SEMANA",
    "VERSION",
    "generar_html",
]

_log = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parents[1]
DIR_PLANTILLAS = Path(__file__).resolve().parent / "plantillas"
RUTA_SALIDA = RAIZ / "docs" / "index.html"

#: Cómo se llama la quiniela.
MARCA = "ANGABAVE"

#: Quién firma el sitio.
DESARROLLADOR = "Angel Barrera"

#: Etapa y versión del portal. Se muestra junto a la marca.
ETAPA = "alfa"
VERSION = "v0.0.0.1"

#: Partidos cerrados en la temporada antes de mostrar el podio. Con dos o tres
#: juegos todo el mundo va empatado y un podio ahí no dice nada.
UMBRAL_PODIO = 16

#: Partidos cerrados de una semana antes de hablar de su ganador. Con uno o dos
#: juegos no hay nada que proyectar.
UMBRAL_SEMANA = 8

#: A partir de cuántos empatados se deja de enlistar nombres y solo se cuenta.
MAXIMO_NOMBRES = 3

#: Cada cuántos segundos se recarga sola la página mientras haya juego.
SEGUNDOS_RECARGA = 300

#: ESPN describe el estado en inglés; aquí se traduce lo que puede aparecer.
ESTADOS = {
    "Final": "Final",
    "Final/OT": "Final/TE",
    "In Progress": "En curso",
    "End of Period": "Fin del periodo",
    "Halftime": "Medio tiempo",
    "Scheduled": "Por jugar",
    "Postponed": "Pospuesto",
    "Delayed": "Demorado",
    "Canceled": "Cancelado",
    "Suspended": "Suspendido",
}

_DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


@dataclass(slots=True)
class SemanaRender:
    """Todo lo que la página necesita saber de una semana."""

    numero: int
    partidos: list[Partido]
    #: Vacío mientras no se haya subido el Excel de esa semana.
    picks: dict[str, list[str]] = field(default_factory=dict)
    tabla: pd.DataFrame | None = None
    #: participante -> {"gana_solo": n, "empata": n}, solo si quedan pendientes.
    panorama: dict[str, dict[str, int]] | None = None

    @property
    def cerrados(self) -> int:
        return sum(1 for partido in self.partidos if partido.finalizado)

    @property
    def pendientes(self) -> int:
        return len(self.partidos) - self.cerrados

    @property
    def estado(self) -> str:
        if not self.picks:
            return "pendiente"
        if self.cerrados == len(self.partidos):
            return "cerrada"
        return "en_vivo"


def _fecha_larga(momento: datetime) -> str:
    return f"{momento.day} {_MESES[momento.month - 1]} {momento.year}, {momento.strftime('%H:%M')}"


def _fecha_corta(momento: datetime) -> str:
    return f"{_DIAS[momento.weekday()]} {momento.day} · {momento.strftime('%H:%M')}"


def _describir(partido: Partido) -> dict:
    """Un partido, listo para la plantilla."""
    if partido.finalizado:
        estado = "Empate" if partido.empatado else ESTADOS.get(partido.estado, "Final")
    elif partido.estado == "Scheduled" and partido.inicio is not None:
        estado = _fecha_corta(a_cdmx(partido.inicio))
    else:
        estado = ESTADOS.get(partido.estado, partido.estado)

    if partido.finalizado:
        gana = "x" if partido.empatado else ("v" if partido.ganador == partido.visitante else "l")
    elif partido.lider is not None:
        gana = "v" if partido.lider == partido.visitante else "l"
    else:
        gana = None

    en_juego = not partido.finalizado and partido.estado != "Scheduled"
    return {
        "v": partido.visitante,
        "l": partido.local,
        "mv": partido.marcador_visitante if (partido.finalizado or en_juego) else None,
        "ml": partido.marcador_local if (partido.finalizado or en_juego) else None,
        "e": estado,
        "g": gana,
        "cerrado": partido.finalizado,
        "vivo": en_juego,
    }


def _datos_semana(semana: SemanaRender, indice_global: dict[str, int]) -> dict:
    """Arma el bloque JSON de una semana."""
    jugadores = list(semana.picks)
    matriz = [
        [1 if pick == partido.local else 0 for pick, partido in zip(picks, semana.partidos)]
        for picks in semana.picks.values()
    ]

    bloque = {
        "n": semana.numero,
        "estado": semana.estado,
        "cerrados": semana.cerrados,
        "total": len(semana.partidos),
        "partidos": [_describir(partido) for partido in semana.partidos],
        "jugadores": [indice_global[nombre] for nombre in jugadores],
        "picks": matriz,
        "tabla": [],
        "panorama": {},
        "ganadores": [],
        "oficial": False,
    }

    if semana.tabla is not None:
        bloque["tabla"] = [
            {
                "p": indice_global[fila["participante"]],
                "pos": int(fila["posicion"]),
                "f": int(fila["firme"]),
                "e": int(fila["errores"]),
            }
            for fila in semana.tabla.to_dict("records")
        ]

    bloque["proyectable"] = semana.cerrados >= UMBRAL_SEMANA
    bloque["umbral"] = UMBRAL_SEMANA
    if semana.tabla is not None and not semana.tabla.empty and bloque["proyectable"]:
        primeros = ganadores(semana.tabla)
        bloque["ganadores"] = [indice_global[nombre] for nombre in primeros]
        bloque["oficial"] = semana.estado == "cerrada"
        cada_uno = premio_semanal(len(primeros))
        bloque["premio"] = _pesos(cada_uno)
        bloque["premio_total"] = _pesos(PREMIO_SEMANAL)

    if semana.panorama:
        bloque["combinaciones"] = 2**semana.pendientes
        bloque["panorama"] = {
            str(indice_global[nombre]): [valores["gana_solo"], valores["empata"]]
            for nombre, valores in semana.panorama.items()
            if valores["gana_solo"] or valores["empata"]
        }
    return bloque


def _armar_podio(general: list[dict], participantes: list[str], reparto: list[dict]) -> list[dict]:
    """Los tres primeros lugares, agrupando a los empatados.

    Al arrancar la temporada medio mundo va empatado, así que el podio se arma
    por posición y no por persona: un escalón puede llevar a veinte.
    """
    escalones: list[dict] = []
    for fila in general:
        actual = escalones[-1] if escalones else None
        if actual is None or actual["pos"] != fila["pos"]:
            if len(escalones) == 3:
                break
            escalones.append({"pos": fila["pos"], "total": fila["total"], "nombres": []})
            actual = escalones[-1]
        actual["nombres"].append(participantes[fila["p"]])

    premios = {fila["nombre"]: fila["premio"] for fila in reparto}
    for escalon in escalones:
        escalon["cuantos"] = len(escalon["nombres"])
        # Con muchos empatados se cuenta, no se enlista.
        escalon["enlistar"] = escalon["cuantos"] <= MAXIMO_NOMBRES
        escalon["premio"] = premios.get(escalon["nombres"][0]) if escalon["cuantos"] == 1 else None
    return escalones


def _pesos(cantidad) -> str:
    """Formato de dinero: $5,200 si es redondo, $1,733.33 si no."""
    cantidad = Decimal(cantidad)
    if cantidad == cantidad.to_integral_value():
        return f"${cantidad:,.0f}"
    return f"${cantidad:,.2f}"


def _entorno() -> Environment:
    return Environment(
        loader=FileSystemLoader(DIR_PLANTILLAS),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def generar_html(
    *,
    anio: int,
    semanas: list[SemanaRender],
    tabla_acumulada: pd.DataFrame,
    ruta_salida: Path = RUTA_SALIDA,
    momento: datetime | None = None,
    desarrollador: str = DESARROLLADOR,
) -> Path:
    """Escribe la página completa de la temporada y devuelve la ruta."""
    momento = momento or ahora_cdmx()
    semanas = sorted(semanas, key=lambda semana: semana.numero)

    participantes = list(tabla_acumulada["participante"])
    for semana in semanas:
        for nombre in semana.picks:
            if nombre not in participantes:
                participantes.append(nombre)
    indice_global = {nombre: indice for indice, nombre in enumerate(participantes)}

    columnas_semana = [c for c in tabla_acumulada.columns if c.startswith("S") and c[1:].isdigit()]
    general = [
        {
            "p": indice_global[fila["participante"]],
            "pos": int(fila["posicion"]),
            "total": int(fila["acumulado"]),
            "err": int(fila["errores"]),
            "sem": {columna[1:]: int(fila[columna]) for columna in columnas_semana},
        }
        for fila in tabla_acumulada.to_dict("records")
    ]

    activa = next(
        (s for s in reversed(semanas) if s.estado == "en_vivo"),
        next((s for s in reversed(semanas) if s.estado == "pendiente"), semanas[-1] if semanas else None),
    )

    jugadas = [semana for semana in semanas if semana.picks]
    cerrados_temporada = sum(semana.cerrados for semana in jugadas)
    podio_listo = cerrados_temporada >= UMBRAL_PODIO
    hay_juego = any(semana.pendientes for semana in semanas)

    temporada_cerrada = (
        len(jugadas) >= SEMANAS_TEMPORADA
        and all(semana.estado == "cerrada" for semana in jugadas)
    )
    reparto = [
        {
            "pos": fila["posicion"],
            "p": indice_global[fila["participante"]],
            "nombre": fila["participante"],
            "aciertos": fila["aciertos"],
            "porcentaje": f"{fila['porcentaje']:.0%}",
            "premio": _pesos(fila["premio"]),
        }
        for fila in reparto_final(tabla_acumulada)
    ] if temporada_cerrada else []

    premios = {
        "semanal": _pesos(PREMIO_SEMANAL),
        "acumulado_semanal": _pesos(ACUMULADO_SEMANAL),
        "total": _pesos(ACUMULADO_TOTAL),
        "semanas_temporada": SEMANAS_TEMPORADA,
        "semanas_jugadas": len(jugadas),
        "apartado": _pesos(ACUMULADO_SEMANAL * len(jugadas)),
        "reparto": reparto,
        "temporada_cerrada": temporada_cerrada,
        # Las reglas del reparto: se muestran siempre, los nombres no.
        "reglas": [
            {"lugar": "1º", "porcentaje": "70%", "monto": _pesos(ACUMULADO_TOTAL * Decimal("0.70"))},
            {"lugar": "2º", "porcentaje": "20%", "monto": _pesos(ACUMULADO_TOTAL * Decimal("0.20"))},
            {"lugar": "3º", "porcentaje": "10%", "monto": _pesos(ACUMULADO_TOTAL * Decimal("0.10"))},
        ],
    }

    datos = {
        "marca": MARCA,
        "anio": anio,
        "actualizado": _fecha_larga(momento),
        "participantes": participantes,
        "general": general,
        "semanas": [_datos_semana(semana, indice_global) for semana in semanas],
        "activa": activa.numero if activa else None,
        "premios": premios,
        "podio_listo": podio_listo,
        "cerrados_temporada": cerrados_temporada,
        "umbral_podio": UMBRAL_PODIO,
        "recarga": SEGUNDOS_RECARGA if hay_juego else 0,
    }

    podio = _armar_podio(general, participantes, reparto) if podio_listo else []
    contexto = {
        "marca": MARCA,
        "etapa": ETAPA,
        "version": VERSION,
        "anio": anio,
        "desarrollador": desarrollador,
        "actualizado": _fecha_larga(momento),
        "podio_listo": podio_listo,
        "cerrados_temporada": cerrados_temporada,
        "umbral_podio": UMBRAL_PODIO,
        "premios": premios,
        # El \u003c evita que un "<" del contenido cierre el <script> por accidente.
        "datos": json.dumps(datos, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c"),
        "general": general,
        "podio": podio,
        "participantes": participantes,
        "semanas": semanas,
        "activa": activa,
        "columnas_semana": columnas_semana,
    }

    html = _entorno().get_template("index.html.j2").render(**contexto)
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    ruta_salida.write_text(html, encoding="utf-8")
    _log.info("Escribí %s (%.0f KB).", ruta_salida, len(html.encode("utf-8")) / 1024)
    return ruta_salida
