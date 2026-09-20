"""Cálculo de las tablas: la de la semana y la acumulada.

Dos conceptos que nunca se mezclan:

* **Firme**: aciertos sobre partidos ya cerrados. Es el número oficial.
* **Proyectado**: firme más los partidos en curso que ya tienen líder en el
  marcador. Es orientativo y puede cambiar hasta el último snap.

Los empates de la NFL no le dan acierto a nadie: si un partido cerró empatado,
cuenta como error para todos los que lo pronosticaron, porque nadie le atinó.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

from .espn import Partido, cargar_cache, aplicar_overrides, DIR_RESULTADOS, RUTA_OVERRIDES
from .picks import clave_participante, leer_picks, numero_semana

__all__ = [
    "ACUMULADO_SEMANAL",
    "ACUMULADO_TOTAL",
    "COLUMNAS_SEMANA",
    "PREMIO_SEMANAL",
    "REPARTO_FINAL",
    "SEMANAS_TEMPORADA",
    "Escenarios",
    "ErrorCalendario",
    "emparejar_resultados",
    "escenarios",
    "ganadores",
    "panorama",
    "premio_semanal",
    "reparto_final",
    "posiciones",
    "tabla_general",
    "tabla_semana",
]

_log = logging.getLogger(__name__)

COLUMNAS_SEMANA = ["posicion", "participante", "firme", "errores", "proyectado"]


class ErrorCalendario(ValueError):
    """Los enfrentamientos del Excel no cuadran con los partidos reales."""


def emparejar_resultados(partidos: list[Partido], resultados: list[Partido]) -> list[Partido]:
    """Alinea los enfrentamientos del Excel con los marcadores reales.

    Es la verificación de "lo que dice el Excel" contra "lo que pasó": si el
    organizador capturó un partido que no existe en el calendario de la NFL, se
    entera aquí y no con una tabla equivocada.
    """
    por_clave = {resultado.clave: resultado for resultado in resultados}
    alineados: list[Partido] = []
    faltantes: list[str] = []

    for partido in partidos:
        real = por_clave.pop(partido.clave, None)
        if real is None:
            faltantes.append(partido.clave)
        else:
            alineados.append(real)

    if faltantes:
        raise ErrorCalendario(
            "Estos enfrentamientos del Excel no existen en el calendario de la NFL de esa "
            "semana: " + ", ".join(faltantes) + ". Revisa la captura o usa data/overrides.json."
        )
    for sobrante in por_clave:
        _log.warning("El partido %s se juega esta semana pero no está en la quiniela.", sobrante)
    return alineados


def _contar(picks: list[str], resultados: list[Partido]) -> tuple[int, int, int]:
    """Devuelve (firme, errores, proyectado) de un participante."""
    firme = errores = en_curso = 0
    for pick, partido in zip(picks, resultados):
        if partido.finalizado:
            if partido.ganador is not None and pick == partido.ganador:
                firme += 1
            else:
                errores += 1  # incluye los empates: ahí nadie acierta
        elif partido.lider is not None and pick == partido.lider:
            en_curso += 1
    return firme, errores, firme + en_curso


def posiciones(claves: list[tuple]) -> list[int]:
    """Numeración con empates compartidos: 1, 1, 1, 4.

    `claves` viene ya ordenada de mejor a peor; dos participantes comparten
    posición cuando su clave es idéntica.
    """
    resultado: list[int] = []
    anterior = None
    for indice, clave in enumerate(claves, start=1):
        if clave != anterior:
            posicion = indice
            anterior = clave
        resultado.append(posicion)
    return resultado


def _ordenar_y_numerar(filas: list[dict], columna_firme: str) -> pd.DataFrame:
    """Ordena por firme, luego proyectado, luego alfabético, y numera.

    La posición se decide **solo** con los aciertos firmes, que es el número
    que se publica. El proyectado sigue ordenando las filas dentro de un
    empate —así los que van ganando en vivo suben dentro de su grupo— pero
    nunca parte una posición: no se puede quedar arriba de alguien por un
    número que no se muestra.
    """
    filas = sorted(
        filas,
        key=lambda fila: (-fila[columna_firme], -fila["proyectado"], fila["participante"].lower()),
    )
    claves = [(fila[columna_firme],) for fila in filas]
    for fila, posicion in zip(filas, posiciones(claves)):
        fila["posicion"] = posicion
    return pd.DataFrame(filas)


def tabla_semana(
    partidos: list[Partido], picks: dict[str, list[str]], resultados: list[Partido]
) -> pd.DataFrame:
    """Tabla de una semana: posicion, participante, firme, errores, proyectado."""
    alineados = emparejar_resultados(partidos, resultados)
    filas = []
    for participante, elegidos in picks.items():
        firme, errores, proyectado = _contar(elegidos, alineados)
        filas.append(
            {
                "participante": participante,
                "firme": firme,
                "errores": errores,
                "proyectado": proyectado,
            }
        )
    tabla = _ordenar_y_numerar(filas, "firme")
    return tabla[COLUMNAS_SEMANA].reset_index(drop=True)


def _resultados_de(
    semana: int, dir_cache: Path, ruta_overrides: Path
) -> list[Partido]:
    resultados = cargar_cache(semana, dir_cache)
    if not resultados:
        raise ErrorCalendario(
            f"No hay marcadores en caché para la semana {semana}. "
            f"Corre primero: python cli.py actualizar --semana {semana}"
        )
    return aplicar_overrides(resultados, semana, ruta_overrides)


def tabla_general(
    semanas: list[Path],
    *,
    dir_cache: Path = DIR_RESULTADOS,
    ruta_overrides: Path = RUTA_OVERRIDES,
) -> pd.DataFrame:
    """Tabla acumulada de temporada, una columna por semana.

    No toca la red: los marcadores salen del caché de cada semana.
    """
    if not semanas:
        raise ErrorCalendario("No hay archivos de picks que acumular.")

    por_clave: dict[str, dict] = {}
    nombres_vistos: dict[str, Counter] = {}
    columnas_semana: list[str] = []

    for ruta in sorted(semanas, key=numero_semana):
        semana = numero_semana(ruta)
        columna = f"S{semana}"
        columnas_semana.append(columna)

        partidos, picks = leer_picks(ruta)
        alineados = emparejar_resultados(partidos, _resultados_de(semana, dir_cache, ruta_overrides))

        for participante, elegidos in picks.items():
            clave = clave_participante(participante)
            nombres_vistos.setdefault(clave, Counter())[participante] += 1
            registro = por_clave.setdefault(
                clave, {"acumulado": 0, "errores": 0, "proyectado": 0}
            )
            firme, errores, proyectado = _contar(elegidos, alineados)
            registro["acumulado"] += firme
            registro["errores"] += errores
            registro["proyectado"] += proyectado
            registro[columna] = firme

    filas = []
    for clave, registro in por_clave.items():
        variantes = nombres_vistos[clave]
        nombre = variantes.most_common(1)[0][0]
        if len(variantes) > 1:
            otras = ", ".join(repr(v) for v in variantes if v != nombre)
            _log.info("Unifiqué %s bajo %r (misma persona, acentos o espacios distintos).", otras, nombre)
        fila = {"participante": nombre}
        fila.update(registro)
        for columna in columnas_semana:
            fila.setdefault(columna, 0)
        filas.append(fila)

    tabla = _ordenar_y_numerar(filas, "acumulado")
    orden = ["posicion", "participante", "acumulado", "errores", "proyectado", *columnas_semana]
    return tabla[orden].reset_index(drop=True)


@dataclass(frozen=True, slots=True)
class Escenarios:
    """Resultado de enumerar todos los desenlaces posibles."""

    participante: str
    #: Partidos que siguen abiertos, en orden.
    pendientes: list[str]
    combinaciones: int
    gana_solo: int
    empata: int
    pierde: int
    #: Partido -> equipo que tiene que ganar en todos los escenarios en que
    #: el participante termina primero. Vacío si ya no le alcanza.
    indispensables: dict[str, str]

    @property
    def vive(self) -> bool:
        return self.gana_solo + self.empata > 0


def _pick_de(elegidos: list[str], partido: Partido, participante: str) -> str:
    """Qué eligió un participante en un partido concreto.

    Los picks vienen alineados con los partidos de la semana, pero aquí llega
    solo el subconjunto de pendientes. Como un equipo juega una sola vez por
    semana, basta con buscar cuál de los dos aparece en su lista.
    """
    elegidos_unicos = set(elegidos)
    if partido.local in elegidos_unicos:
        return partido.local
    if partido.visitante in elegidos_unicos:
        return partido.visitante
    raise ErrorCalendario(
        f"{participante} no tiene pick para {partido.clave}; no puedo enumerar escenarios."
    )


def _mascaras(picks: dict[str, list[str]], pendientes: list[Partido]) -> dict[str, int]:
    """Bit i encendido = el participante eligió al local del pendiente i."""
    mascaras: dict[str, int] = {}
    for participante, elegidos in picks.items():
        mascara = 0
        for bit, partido in enumerate(pendientes):
            if _pick_de(elegidos, partido, participante) == partido.local:
                mascara |= 1 << bit
        mascaras[participante] = mascara
    return mascaras


def escenarios(
    participante: str,
    partidos_pendientes: list[Partido],
    picks: dict[str, list[str]],
    firmes: dict[str, int],
) -> Escenarios:
    """Enumera por fuerza bruta las 2^n combinaciones de resultados pendientes.

    Con 16 partidos son 65,536 combinaciones: se recorren todas. Los empates no
    se enumeran, se asume que cada partido pendiente lo gana uno de los dos
    equipos; por eso el resultado es una guía, no una promesa.
    """
    if participante not in picks:
        raise KeyError(
            f"{participante!r} no está en la quiniela de esta semana. "
            f"Participantes: {', '.join(sorted(picks))}"
        )

    total = len(partidos_pendientes)
    combinaciones = 2**total
    mascaras = _mascaras(picks, partidos_pendientes)
    mascara_propia = mascaras[participante]
    base_propia = firmes.get(participante, 0)
    # Los rivales se resumen en (firme actual, máscara de picks).
    rivales = [
        (firmes.get(nombre, 0), mascaras[nombre]) for nombre in picks if nombre != participante
    ]

    gana_solo = empata = pierde = 0
    veces_gana_el_local = [0] * total
    favorables = 0

    for desenlace in range(combinaciones):
        mio = base_propia + total - (mascara_propia ^ desenlace).bit_count()
        mejor_ajeno = -1
        for firme_rival, mascara_rival in rivales:
            ajeno = firme_rival + total - (mascara_rival ^ desenlace).bit_count()
            if ajeno > mejor_ajeno:
                mejor_ajeno = ajeno

        if mio > mejor_ajeno:
            gana_solo += 1
        elif mio == mejor_ajeno:
            empata += 1
        else:
            pierde += 1
            continue

        favorables += 1
        for bit in range(total):
            if desenlace >> bit & 1:
                veces_gana_el_local[bit] += 1

    indispensables: dict[str, str] = {}
    if favorables:
        for bit, cuantas in enumerate(veces_gana_el_local):
            partido = partidos_pendientes[bit]
            if cuantas == favorables:
                indispensables[partido.clave] = partido.local
            elif cuantas == 0:
                indispensables[partido.clave] = partido.visitante

    return Escenarios(
        participante=participante,
        pendientes=[partido.clave for partido in partidos_pendientes],
        combinaciones=combinaciones,
        gana_solo=gana_solo,
        empata=empata,
        pierde=pierde,
        indispensables=indispensables,
    )


def panorama(
    partidos_pendientes: list[Partido],
    picks: dict[str, list[str]],
    firmes: dict[str, int],
) -> dict[str, dict[str, int]]:
    """Quién puede ganar la semana, para todos, en una sola pasada.

    Llamar a `escenarios` 34 veces recorrería las combinaciones 34 veces. Aquí
    se recorren una sola vez y en cada desenlace se anota quién queda arriba,
    que es lo que necesita la vista de "potenciales ganadores".

    Devuelve, por participante, en cuántas combinaciones gana solo y en
    cuántas empata el primer lugar.
    """
    total = len(partidos_pendientes)
    if total > 18:  # 2^18 ya son 262,144 combinaciones por participante
        raise ValueError(f"Demasiados partidos pendientes para enumerar: {total}")

    nombres = list(picks)
    if not nombres:
        return {}

    mascaras = _mascaras(picks, partidos_pendientes)
    # El total de cada quien es base_ajustada - fallos, y los fallos son los
    # bits en que su máscara difiere del desenlace.
    ajustadas = [firmes.get(nombre, 0) + total for nombre in nombres]
    lista = [mascaras[nombre] for nombre in nombres]

    resumen = {nombre: {"gana_solo": 0, "empata": 0} for nombre in nombres}

    for desenlace in range(2**total):
        mejor = -1
        lideres: list[int] = []
        for indice, mascara in enumerate(lista):
            marca = ajustadas[indice] - (mascara ^ desenlace).bit_count()
            if marca > mejor:
                mejor = marca
                lideres = [indice]
            elif marca == mejor:
                lideres.append(indice)

        if len(lideres) == 1:
            resumen[nombres[lideres[0]]]["gana_solo"] += 1
        else:
            for indice in lideres:
                resumen[nombres[indice]]["empata"] += 1

    return resumen


# --- premios ---------------------------------------------------------------

#: Bolsa que se lleva quien gana la semana.
PREMIO_SEMANAL = Decimal("5200")
#: Lo que se aparta cada semana para la bolsa final.
ACUMULADO_SEMANAL = Decimal("1400")
#: Semanas de la temporada regular que alimentan la bolsa final.
SEMANAS_TEMPORADA = 18
#: Bolsa final: ACUMULADO_SEMANAL por cada semana.
ACUMULADO_TOTAL = ACUMULADO_SEMANAL * SEMANAS_TEMPORADA
#: Reparto de la bolsa final entre los tres primeros lugares.
REPARTO_FINAL = (Decimal("0.70"), Decimal("0.20"), Decimal("0.10"))


def _centavos(cantidad: Decimal) -> Decimal:
    return cantidad.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ganadores(tabla: pd.DataFrame) -> list[str]:
    """Quiénes van en primer lugar. Son varios si hay empate."""
    if tabla.empty:
        return []
    return list(tabla[tabla["posicion"] == 1]["participante"])


def premio_semanal(cuantos: int, bolsa: Decimal = PREMIO_SEMANAL) -> Decimal:
    """Lo que toca a cada ganador de la semana. Si empatan, se divide."""
    if cuantos <= 0:
        return Decimal("0")
    return _centavos(bolsa / cuantos)


def reparto_final(tabla: pd.DataFrame, bolsa: Decimal = ACUMULADO_TOTAL) -> list[dict]:
    """Los tres primeros lugares de la general con su premio.

    Si varias personas comparten un lugar, se suman los porcentajes de los
    lugares que ocupan entre todas y se divide en partes iguales: dos en primer
    lugar se reparten el 70 % más el 20 %, y quien sigue queda tercero con el
    10 %.
    """
    if tabla.empty:
        return []

    reparto: list[dict] = []
    lugar = 0
    for posicion, grupo in tabla.groupby("posicion", sort=True):
        if lugar >= len(REPARTO_FINAL):
            break
        integrantes = list(grupo["participante"])
        ocupados = REPARTO_FINAL[lugar : lugar + len(integrantes)]
        if not ocupados:
            break
        porcentaje = sum(ocupados) / len(integrantes)
        for participante in integrantes:
            reparto.append(
                {
                    "posicion": int(posicion),
                    "participante": participante,
                    "aciertos": int(grupo.loc[grupo["participante"] == participante, "acumulado"].iloc[0]),
                    "porcentaje": porcentaje,
                    "premio": _centavos(bolsa * porcentaje),
                }
            )
        lugar += len(integrantes)
    return reparto
