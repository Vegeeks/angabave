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

from .equipos import ABREVIATURAS_ESPN
from .espn import URL_SCOREBOARD, Partido, a_cdmx, ahora_cdmx
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
    "generar_manifiesto",
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
#:
#: Esquema: alfa vMAYOR.MENOR.PARCHE
#:   MENOR  sube con cada función nueva visible
#:   PARCHE sube con correcciones
#:   MAYOR  llega a 1 cuando la temporada corra completa sin intervención
ETAPA = "alfa"
VERSION = "v0.6.0"

#: Dos colores por equipo, aclarados para leerse sobre fondo oscuro: el de casa
#: y el de visita. El portal se tiñe con uno u otro según dónde juegue el
#: equipo que elija cada quien.
COLORES_EQUIPO: dict[str, dict[str, str]] = {
    "Cardinals":  {"local": "#C8102E", "visita": "#E8EDF5"},
    "Falcons":    {"local": "#E8383D", "visita": "#D6D9DD"},
    "Ravens":     {"local": "#6B4FD8", "visita": "#FFC547"},
    "Bills":      {"local": "#4A7DFF", "visita": "#E8413C"},
    "Panthers":   {"local": "#0BA0E8", "visita": "#C6CDD2"},
    "Bears":      {"local": "#E8642A", "visita": "#4A6FA8"},
    "Bengals":    {"local": "#FB4F14", "visita": "#E8EDF5"},
    "Browns":     {"local": "#FF6A2A", "visita": "#E8DCC8"},
    "Cowboys":    {"local": "#7FA3E8", "visita": "#C6CDD2"},
    "Broncos":    {"local": "#FB6B1E", "visita": "#6D8FE8"},
    "Lions":      {"local": "#35A7E8", "visita": "#C6CDD2"},
    "Packers":    {"local": "#FFC547", "visita": "#4FA37A"},
    "Texans":     {"local": "#E8455C", "visita": "#6D8FE8"},
    "Colts":      {"local": "#4A93E8", "visita": "#E8EDF5"},
    "Jaguars":    {"local": "#2FC2C9", "visita": "#D7A22A"},
    "Chiefs":     {"local": "#FF3B4E", "visita": "#FFC547"},
    "Chargers":   {"local": "#2BA8FF", "visita": "#FFC72C"},
    "Rams":       {"local": "#FFB020", "visita": "#6D8FE8"},
    "Raiders":    {"local": "#C6CDD2", "visita": "#E8EDF5"},
    "Dolphins":   {"local": "#17C5CC", "visita": "#FF8C2E"},
    "Vikings":    {"local": "#9B6BE8", "visita": "#FFC547"},
    "Patriots":   {"local": "#E85A72", "visita": "#6D8FE8"},
    "Saints":     {"local": "#E3CB94", "visita": "#C6CDD2"},
    "Giants":     {"local": "#6D8FE8", "visita": "#E8455C"},
    "Jets":       {"local": "#2FBF7A", "visita": "#E8EDF5"},
    "Eagles":     {"local": "#16A085", "visita": "#C6CDD2"},
    "Steelers":   {"local": "#FFC72C", "visita": "#C6CDD2"},
    "49ers":      {"local": "#E8503F", "visita": "#E3CB94"},
    "Seahawks":   {"local": "#69BE28", "visita": "#6D8FE8"},
    "Buccaneers": {"local": "#FF3535", "visita": "#C6853F"},
    "Titans":     {"local": "#67A9E8", "visita": "#6D8FE8"},
    "Washington": {"local": "#C8656B", "visita": "#FFC547"},
}


# --- contraste --------------------------------------------------------------
#
# Los colores de equipo se usan de dos formas: como texto sobre el fondo oscuro
# del portal y como fondo de la sigla con texto encima. Ninguna de las dos se
# deja al ojo: se calcula el contraste (WCAG) y se corrige si no llega.

#: Fondo de los paneles, contra el que se mide el texto de color.
FONDO_PANEL = "#101724"
#: Mínimo exigido: 4.5:1, el umbral de WCAG para texto normal.
CONTRASTE_MINIMO = 4.5


def _a_rgb(color: str) -> tuple[float, float, float]:
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _luminancia(color: str) -> float:
    def canal(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    rojo, verde, azul = (canal(v) for v in _a_rgb(color))
    return 0.2126 * rojo + 0.7152 * verde + 0.0722 * azul


def contraste(uno: str, otro: str) -> float:
    a, b = _luminancia(uno), _luminancia(otro)
    claro, oscuro = max(a, b), min(a, b)
    return (claro + 0.05) / (oscuro + 0.05)


def _aclarar(color: str, paso: float = 0.06) -> str:
    """Empuja un color hacia el blanco sin cambiarle el tono."""
    rojo, verde, azul = _a_rgb(color)
    mezcla = lambda v: min(1.0, v + (1.0 - v) * paso)
    return "#%02X%02X%02X" % tuple(round(mezcla(v) * 255) for v in (rojo, verde, azul))


def legible_sobre_oscuro(color: str, fondo: str = FONDO_PANEL) -> str:
    """Devuelve el color aclarado lo justo para leerse sobre el panel."""
    seguro = color
    for _ in range(30):
        if contraste(seguro, fondo) >= CONTRASTE_MINIMO:
            return seguro
        seguro = _aclarar(seguro)
    return seguro


def texto_encima(color: str) -> str:
    """Negro o blanco, el que contraste mejor sobre ese color."""
    return "#070B12" if contraste(color, "#070B12") >= contraste(color, "#FFFFFF") else "#FFFFFF"


def paleta_equipos() -> dict[str, dict[str, str]]:
    """Colores de equipo listos para usar, ya verificados."""
    salida: dict[str, dict[str, str]] = {}
    for equipo, colores in COLORES_EQUIPO.items():
        entrada: dict[str, str] = {}
        for donde, color in colores.items():
            seguro = legible_sobre_oscuro(color)
            entrada[donde] = seguro
            entrada[donde + "_texto"] = texto_encima(seguro)
        salida[equipo] = entrada
    return salida


# --- temas por equipo --------------------------------------------------------
#
# Elegir equipo no cambia solo un acento: tiñe el fondo, las superficies y los
# bordes. Todo se deriva del color del equipo mezclándolo con la base oscura, y
# después se verifica que el texto siga siendo legible encima.

#: Base neutra del portal, sobre la que se mezcla el color del equipo.
BASE_TEMA: dict[str, str] = {
    "bg": "#06090F", "bg2": "#0B1018",
    "panel": "#101724", "panel2": "#161F2E", "panel3": "#1D2838",
    "linea": "#1F2938", "linea2": "#2B3849",
}

#: Cuánto color del equipo lleva cada superficie. Poco en el fondo, más en los
#: bordes: así se nota el tema sin que el texto pierda contraste.
FUERZA_TEMA: dict[str, float] = {
    "bg": 0.20, "bg2": 0.24, "panel": 0.22, "panel2": 0.27,
    "panel3": 0.32, "linea": 0.40, "linea2": 0.48,
}

#: Textos que tienen que seguir leyéndose sobre el panel teñido.
_TEXTOS = {"txt": ("#EEF4FB", 7.0), "tenue": ("#8D9BB0", 4.5), "tenue2": ("#5C6A7E", 3.0)}


def mezclar(fondo: str, tinte: str, fuerza: float) -> str:
    """Mezcla dos colores; `fuerza` es cuánto pesa el tinte."""
    a, b = _a_rgb(fondo), _a_rgb(tinte)
    return "#%02X%02X%02X" % tuple(
        round((x + (y - x) * fuerza) * 255) for x, y in zip(a, b)
    )


def _rgba(color: str, alfa: float) -> str:
    rojo, verde, azul = (round(v * 255) for v in _a_rgb(color))
    return f"rgba({rojo},{verde},{azul},{alfa})"


def tema_equipo(acento: str) -> dict[str, str]:
    """Paleta completa a partir del color del equipo, ya verificada.

    Devuelve las variables CSS tal cual las aplica el navegador.
    """
    tema = {
        "--" + nombre: mezclar(base, acento, FUERZA_TEMA[nombre])
        for nombre, base in BASE_TEMA.items()
    }
    # Resplandor del fondo, en el color del equipo.
    tema["--resplandor"] = _rgba(acento, 0.45)
    tema["--resplandor2"] = _rgba(acento, 0.24)

    # Al teñir, el panel queda más claro que la base neutra, así que el acento
    # se vuelve a verificar contra ESE panel y no contra el original.
    panel = tema["--panel"]
    tema["--acento"] = legible_sobre_oscuro(acento, panel)

    # Las pastillas activas se visten del equipo, con su texto legible encima.
    tema["--pastilla"] = (
        f"linear-gradient(180deg,{tema['--acento']},{mezclar(tema['--acento'], '#000000', 0.22)})"
    )
    tema["--pastilla-txt"] = texto_encima(tema["--acento"])

    # Los textos se aclaran si el panel teñido les quitó contraste.
    for nombre, (color, minimo) in _TEXTOS.items():
        seguro = color
        for _ in range(30):
            if contraste(seguro, panel) >= minimo:
                break
            seguro = _aclarar(seguro)
        tema["--" + nombre] = seguro
    return tema


def temas_equipos() -> dict[str, dict[str, dict[str, str]]]:
    """Un tema por equipo y por dónde juega (casa o visita)."""
    paleta = paleta_equipos()
    return {
        equipo: {donde: tema_equipo(colores[donde]) for donde in ("local", "visita")}
        for equipo, colores in paleta.items()
    }


def _siglas() -> dict[str, str]:
    """Nombre de la quiniela -> abreviatura canónica, para el marcador.

    El catálogo trae variantes (JAC y JAX son Jaguars); se queda la primera,
    que es la forma principal.
    """
    salida: dict[str, str] = {}
    for abreviatura, nombre in ABREVIATURAS_ESPN.items():
        salida.setdefault(nombre, abreviatura)
    return salida

#: Partidos cerrados en la temporada antes de mostrar el podio. Con dos o tres
#: juegos todo el mundo va empatado y un podio ahí no dice nada.
UMBRAL_PODIO = 16

#: Partidos cerrados de una semana antes de hablar de su ganador. Con uno o dos
#: juegos no hay nada que proyectar.
UMBRAL_SEMANA = 8

#: A partir de cuántos empatados se deja de enlistar nombres y solo se cuenta.
MAXIMO_NOMBRES = 3
#: En el podio caben más: es el lugar donde la gente viene a buscar su nombre.
MAXIMO_NOMBRES_PODIO = 6

#: Cada cuántos segundos se recarga la página entera mientras haya juego.
#: Es la red de seguridad: quien manda los números oficiales es CI.
SEGUNDOS_RECARGA = 600

#: Cada cuántos segundos el navegador pide marcadores a ESPN por su cuenta.
SEGUNDOS_VIVO = 60

#: A partir de cuántos minutos sin recalcular se avisa que la tabla va vieja.
#: Con partidos abiertos, quedarse callado es el peor modo de falla.
MINUTOS_REZAGO = 25

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
_DIAS_LARGOS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
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
    local = a_cdmx(partido.inicio)
    return {
        # Etiqueta del horario: así los partidos se agrupan como se vive la
        # jornada, por bloques, en vez de en una lista plana de dieciséis.
        "grupo": f"{_DIAS_LARGOS[local.weekday()]} {local.day} · {local.strftime('%H:%M')}"
        if local else "Por programar",
        # Marca de tiempo para ordenar los bloques cronológicamente.
        "t": int(partido.inicio.timestamp()) if partido.inicio else 0,
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
        escalon["enlistar"] = escalon["cuantos"] <= MAXIMO_NOMBRES_PODIO
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


def generar_manifiesto(ruta_salida: Path, marca: str = MARCA) -> Path:
    """Escribe el manifiesto que usan iOS y Android al guardar el sitio."""
    contenido = {
        "name": f"{marca} · Quiniela NFL",
        "short_name": marca,
        "start_url": ".",
        "scope": ".",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#06090f",
        "theme_color": "#06090f",
        "lang": "es-MX",
        "icons": [
            {"src": "icono-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icono-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "icono-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    ruta = Path(ruta_salida)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(contenido, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ruta


def generar_html(
    *,
    anio: int,
    semanas: list[SemanaRender],
    tabla_acumulada: pd.DataFrame,
    posiciones_previas: dict[str, int] | None = None,
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
    previas = posiciones_previas or {}
    general = []
    for fila in tabla_acumulada.to_dict("records"):
        nombre_fila = fila["participante"]
        antes = previas.get(nombre_fila)
        general.append(
            {
                "p": indice_global[nombre_fila],
                "pos": int(fila["posicion"]),
                "total": int(fila["acumulado"]),
                "err": int(fila["errores"]),
                # Cuánto subió o bajó desde la semana pasada. Positivo = subió.
                "mov": (antes - int(fila["posicion"])) if antes is not None else None,
                "sem": {columna[1:]: int(fila[columna]) for columna in columnas_semana},
            }
        )

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
        # En ISO para que el navegador pueda medir cuánto lleva sin refrescarse.
        "generado": momento.isoformat(),
        "rezago": MINUTOS_REZAGO,
        "participantes": participantes,
        "colores": paleta_equipos(),
        "siglas": _siglas(),
        "temas": temas_equipos(),
        "general": general,
        "semanas": [_datos_semana(semana, indice_global) for semana in semanas],
        "activa": activa.numero if activa else None,
        "premios": premios,
        "podio_listo": podio_listo,
        "cerrados_temporada": cerrados_temporada,
        "umbral_podio": UMBRAL_PODIO,
        "recarga": SEGUNDOS_RECARGA if hay_juego else 0,
        # Capa en vivo: el navegador consulta ESPN directo. Solo refresca el
        # marcador de partidos que aquí siguen abiertos; jamás cierra uno ni
        # toca el conteo oficial, que se calcula en CI y ya está probado.
        "vivo": {
            "url": URL_SCOREBOARD,
            "cada": SEGUNDOS_VIVO,
            "equipos": ABREVIATURAS_ESPN,
            # ESPN describe el estado en inglés: se traduce también en el
            # navegador, no solo en el lado de Python.
            "estados": ESTADOS,
        } if hay_juego else None,
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
    generar_manifiesto(ruta_salida.parent / "manifest.webmanifest")
    _log.info("Escribí %s (%.0f KB).", ruta_salida, len(html.encode("utf-8")) / 1024)
    return ruta_salida
