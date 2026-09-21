#!/usr/bin/env python3
"""Línea de comandos de la quiniela.

    python cli.py actualizar --semana 2
    python cli.py actualizar --semana 2 --sin-red
    python cli.py tabla --semana 2
    python cli.py general
    python cli.py escenarios --participante "Angel D Luffy"
    python cli.py validar --semana 2
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from quiniela.equipos import EquipoDesconocidoError
from quiniela.espn import ErrorESPN, ahora_cdmx, obtener_partidos
from quiniela.picks import ErrorPicks, leer_picks, numero_semana
from quiniela.render_html import SemanaRender, generar_html
from quiniela.render_png import generar_iconos, generar_png
from quiniela.scoring import (
    ErrorCalendario,
    emparejar_resultados,
    escenarios,
    panorama,
    tabla_general,
    tabla_semana,
)

RAIZ = Path(__file__).resolve().parent
DIR_PICKS = RAIZ / "data" / "picks"

_log = logging.getLogger("quiniela")


class _Formato(logging.Formatter):
    """Prefijos en español y cortos, para que el log se lea de un vistazo."""

    PREFIJOS = {
        logging.DEBUG: "      ",
        logging.INFO: "      ",
        logging.WARNING: "AVISO ",
        logging.ERROR: "ERROR ",
        logging.CRITICAL: "ERROR ",
    }

    def format(self, registro: logging.LogRecord) -> str:
        return self.PREFIJOS.get(registro.levelno, "") + registro.getMessage()


def configurar_log(verboso: bool) -> None:
    manejador = logging.StreamHandler(sys.stderr)
    manejador.setFormatter(_Formato())
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO, handlers=[manejador], force=True
    )


def anio_por_defecto() -> int:
    """La temporada empieza en septiembre y termina en febrero del año siguiente."""
    hoy = date.today()
    return hoy.year if hoy.month >= 3 else hoy.year - 1


#: Formatos que sabe leer el proyecto, en orden de preferencia.
EXTENSIONES = (".xlsx", ".pdf")


def ruta_picks(semana: int) -> Path:
    for extension in EXTENSIONES:
        ruta = DIR_PICKS / f"Semana_{semana:02d}{extension}"
        if ruta.exists():
            return ruta
    alternativas = [p for p in semanas_disponibles() if numero_semana(p) == semana]
    if alternativas:
        return alternativas[0]
    disponibles = ", ".join(p.name for p in semanas_disponibles()) or "ninguno"
    raise ErrorPicks(
        f"No encontré los picks de la semana {semana} en {DIR_PICKS}. "
        f"Archivos disponibles: {disponibles}."
    )


def semanas_disponibles() -> list[Path]:
    """Los archivos de picks, en Excel o PDF, ordenados por semana.

    Si una semana está en los dos formatos gana el Excel, que es el original.
    """
    if not DIR_PICKS.exists():
        return []
    rutas = [
        p for p in DIR_PICKS.iterdir()
        if p.suffix.lower() in EXTENSIONES and not p.name.startswith("~$")
        and re.search(r"emana", p.name)
    ]
    por_semana: dict[int, Path] = {}
    for ruta in sorted(rutas, key=lambda p: EXTENSIONES.index(p.suffix.lower())):
        por_semana.setdefault(numero_semana(ruta), ruta)
    return [por_semana[s] for s in sorted(por_semana)]


def ultima_semana() -> int:
    rutas = semanas_disponibles()
    if not rutas:
        raise ErrorPicks(f"No hay ningún archivo de picks en {DIR_PICKS}.")
    return numero_semana(rutas[-1])


def imprimir_tabla(tabla: pd.DataFrame, titulo: str) -> None:
    """Texto tabulado, sin dependencias de formato."""
    print(f"\n{titulo}")
    print("=" * len(titulo))

    tabla = tabla.drop(columns=[c for c in ("proyectado",) if c in tabla.columns])
    columnas = list(tabla.columns)
    filas = [[str(valor) for valor in fila] for fila in tabla.itertuples(index=False)]
    anchos = [
        max(len(columna), *(len(fila[indice]) for fila in filas)) if filas else len(columna)
        for indice, columna in enumerate(columnas)
    ]

    def alinear(celda: str, indice: int) -> str:
        return celda.ljust(anchos[indice]) if columnas[indice] == "participante" else celda.rjust(anchos[indice])

    print("  ".join(alinear(columna.upper(), i) for i, columna in enumerate(columnas)))
    print("  ".join("-" * ancho for ancho in anchos))
    for fila in filas:
        print("  ".join(alinear(celda, i) for i, celda in enumerate(fila)))
    print()


def _cargar_semana(semana: int, anio: int, sin_red: bool):
    ruta = ruta_picks(semana)
    partidos, picks = leer_picks(ruta)
    resultados = obtener_partidos(anio, semana, sin_red=sin_red)
    alineados = emparejar_resultados(partidos, resultados)
    return partidos, picks, alineados


def _resultados_de(anio: int, semana: int, *, activa: bool, sin_red: bool):
    """La semana activa se refresca; las anteriores salen del caché."""
    if activa and not sin_red:
        return obtener_partidos(anio, semana, sin_red=False)
    try:
        return obtener_partidos(anio, semana, sin_red=True)
    except ErrorESPN:
        if sin_red:
            raise
        _log.info("No hay caché de la semana %d todavía: la consulto una vez.", semana)
        return obtener_partidos(anio, semana, sin_red=False)


def construir_semanas(anio: int, semana_activa: int, sin_red: bool) -> list[SemanaRender]:
    """Arma todas las semanas con picks, para que el sitio sea navegable."""
    construidas: list[SemanaRender] = []
    for ruta in semanas_disponibles():
        numero = numero_semana(ruta)
        partidos, picks = leer_picks(ruta)
        resultados = _resultados_de(
            anio, numero, activa=(numero == semana_activa), sin_red=sin_red
        )
        alineados = emparejar_resultados(partidos, resultados)
        tabla = tabla_semana(partidos, picks, alineados)

        pendientes = [partido for partido in alineados if not partido.finalizado]
        vista = None
        if pendientes:
            firmes = dict(zip(tabla["participante"], tabla["firme"]))
            vista = panorama(pendientes, picks, firmes)
            _log.info(
                "Semana %d: %d combinaciones posibles con %d partidos abiertos.",
                numero, 2 ** len(pendientes), len(pendientes),
            )
        construidas.append(SemanaRender(numero, alineados, picks, tabla, vista))
    return construidas


def semana_por_cargar(anio: int, numero: int, sin_red: bool) -> SemanaRender | None:
    """La semana siguiente, cuando todavía no llega su Excel.

    Sirve para que el sitio muestre los partidos programados y el letrero de
    "actualizando la semana N" en lugar de quedarse en la anterior.
    """
    try:
        partidos = _resultados_de(anio, numero, activa=True, sin_red=sin_red)
    except ErrorESPN as error:
        _log.info("Sin partidos para la semana %d todavía (%s).", numero, error)
        return None
    _log.info("Semana %d sin picks: se publica como 'actualizando'.", numero)
    return SemanaRender(numero, partidos)


def comando_actualizar(argumentos) -> int:
    semana = argumentos.semana or ultima_semana()
    semanas = construir_semanas(argumentos.anio, semana, argumentos.sin_red)
    activa = next(s for s in semanas if s.numero == semana)

    proxima = semana_por_cargar(argumentos.anio, max(s.numero for s in semanas) + 1, argumentos.sin_red)
    if proxima is not None:
        semanas.append(proxima)

    general = tabla_general(semanas_disponibles())
    momento = ahora_cdmx()

    html = generar_html(
        anio=argumentos.anio,
        semanas=semanas,
        tabla_acumulada=general,
        momento=momento,
    )
    generar_iconos()
    png = generar_png(
        tabla_acumulada=general,
        semana=semana,
        anio=argumentos.anio,
        cerrados=activa.cerrados,
        total_partidos=len(activa.partidos),
        momento=momento,
    )

    lider = general.iloc[0]
    _log.info(
        "Semana %d lista: %d de %d partidos cerrados. Lidera %s con %d.",
        semana, activa.cerrados, len(activa.partidos), lider["participante"], lider["acumulado"],
    )
    print(f"{html}\n{png}")
    return 0


def comando_tabla(argumentos) -> int:
    semana = argumentos.semana or ultima_semana()
    partidos, picks, resultados = _cargar_semana(semana, argumentos.anio, sin_red=True)
    cerrados = sum(1 for partido in resultados if partido.finalizado)
    imprimir_tabla(
        tabla_semana(partidos, picks, resultados),
        f"Semana {semana} · {cerrados} de {len(resultados)} partidos cerrados",
    )
    return 0


def comando_general(argumentos) -> int:
    rutas = semanas_disponibles()
    tabla = tabla_general(rutas)
    semanas = ", ".join(str(numero_semana(ruta)) for ruta in rutas)
    imprimir_tabla(tabla, f"General · semanas {semanas}")
    return 0


def comando_escenarios(argumentos) -> int:
    semana = argumentos.semana or ultima_semana()
    partidos, picks, resultados = _cargar_semana(semana, argumentos.anio, sin_red=True)
    semanal = tabla_semana(partidos, picks, resultados)
    firmes = dict(zip(semanal["participante"], semanal["firme"]))

    participante = argumentos.participante
    if participante not in picks:
        coincidencias = [
            nombre for nombre in picks if participante.casefold() in nombre.casefold()
        ]
        if len(coincidencias) != 1:
            raise ErrorPicks(
                f"No encontré a {participante!r}. Participantes: {', '.join(sorted(picks))}"
            )
        participante = coincidencias[0]
        _log.info("Interpreté %r como %r.", argumentos.participante, participante)

    pendientes = [partido for partido in resultados if not partido.finalizado]
    if not pendientes:
        print(f"\nLa semana {semana} ya cerró: no quedan escenarios por jugar.\n")
        imprimir_tabla(semanal.head(10), f"Semana {semana} · top 10")
        return 0

    resultado = escenarios(participante, pendientes, picks, firmes)
    total = resultado.combinaciones
    print(f"\nEscenarios de {participante} · semana {semana}")
    print("=" * (len(participante) + 26))
    print(f"Va con {firmes[participante]} firmes y quedan {len(pendientes)} partidos abiertos.")
    print(f"Combinaciones posibles: {total:,}".replace(",", " "))
    print()
    print(f"  Gana solo   {resultado.gana_solo:>7,} ({resultado.gana_solo / total:6.1%})".replace(",", " "))
    print(f"  Empatado    {resultado.empata:>7,} ({resultado.empata / total:6.1%})".replace(",", " "))
    print(f"  Pierde      {resultado.pierde:>7,} ({resultado.pierde / total:6.1%})".replace(",", " "))
    print()

    if not resultado.vive:
        print("Ya no le alcanza esta semana.\n")
        return 0
    if resultado.indispensables:
        print("Indispensables (si falla uno, se acabó):")
        for clave, equipo in resultado.indispensables.items():
            print(f"  {clave:<24} tiene que ganar {equipo}")
    else:
        print("Ningún partido es indispensable: llega por varios caminos.")
    print()
    return 0


def comando_importar(argumentos) -> int:
    """Guarda el archivo del organizador con el nombre que espera el proyecto.

    Acepta el Excel o el PDF tal como llega ("Quiniela 3.pdf"), detecta de qué
    semana es leyendo su contenido y lo deja en data/picks/ ya validado.
    """
    origen = Path(argumentos.archivo).expanduser()
    if not origen.exists():
        raise ErrorPicks(f"No existe el archivo: {origen}")

    partidos, picks = leer_picks(origen)
    semana = argumentos.semana
    if semana is None:
        try:
            semana = numero_semana(origen)
        except ErrorPicks:
            raise ErrorPicks(
                f"No pude deducir la semana de {origen.name!r}. "
                "Pásala con --semana."
            ) from None

    destino = DIR_PICKS / f"Semana_{semana:02d}{origen.suffix.lower()}"
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and not argumentos.forzar:
        raise ErrorPicks(f"Ya existe {destino}. Usa --forzar para reemplazarlo.")
    shutil.copy2(origen, destino)

    _log.info(
        "Guardé %s como %s: %d partidos, %d participantes.",
        origen.name, destino.name, len(partidos), len(picks),
    )
    print(destino)
    return 0


def comando_pendientes(argumentos) -> int:
    """Cuántos partidos siguen abiertos. Lo usa el workflow para saber si parar."""
    semana = argumentos.semana or ultima_semana()
    partidos, _, resultados = _cargar_semana(semana, argumentos.anio, sin_red=True)
    abiertos = sum(1 for partido in resultados if not partido.finalizado)
    print(abiertos)
    return 0


def comando_proximo(argumentos) -> int:
    """Segundos hasta el próximo partido por empezar.

    Imprime 0 si alguno ya arrancó y sigue abierto, y -1 si no queda ninguno.
    Con eso el workflow sabe si ponerse a trabajar, esperar o irse a dormir.
    """
    rutas = semanas_disponibles()
    if not rutas:
        print(-1)
        return 0

    ahora = datetime.now(timezone.utc)
    faltantes: list[float] = []
    for ruta in rutas:
        semana = numero_semana(ruta)
        try:
            resultados = obtener_partidos(argumentos.anio, semana, sin_red=True)
        except ErrorESPN:
            continue
        for partido in resultados:
            if partido.finalizado:
                continue
            if partido.inicio is None or partido.inicio <= ahora:
                print(0)  # ya empezó (o no sabemos cuándo): hay que mirarlo
                return 0
            faltantes.append((partido.inicio - ahora).total_seconds())

    print(int(min(faltantes)) if faltantes else -1)
    return 0


def comando_validar(argumentos) -> int:
    semana = argumentos.semana or ultima_semana()
    ruta = ruta_picks(semana)
    partidos, picks = leer_picks(ruta)
    print(f"\n{ruta.name}: {len(partidos)} partidos, {len(picks)} participantes.")
    for indice, partido in enumerate(partidos, start=1):
        print(f"  {indice:>2}. {partido.visitante} @ {partido.local}")
    print("\nEl archivo está bien: todos los picks corresponden a su partido.\n")
    return 0


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py", description="Quiniela NFL: tablas automáticas a partir del Excel semanal."
    )
    parser.add_argument("-v", "--verboso", action="store_true", help="log con más detalle")
    parser.add_argument(
        "--anio", type=int, default=anio_por_defecto(), help="temporada (por defecto la actual)"
    )
    subcomandos = parser.add_subparsers(dest="comando", required=True)

    actualizar = subcomandos.add_parser("actualizar", help="jala marcadores y regenera docs/")
    actualizar.add_argument("--semana", type=int, help="por defecto, la última con picks")
    actualizar.add_argument(
        "--sin-red", action="store_true", dest="sin_red", help="usa solo el caché"
    )
    actualizar.set_defaults(funcion=comando_actualizar)

    tabla = subcomandos.add_parser("tabla", help="imprime la tabla de la semana")
    tabla.add_argument("--semana", type=int)
    tabla.set_defaults(funcion=comando_tabla)

    general = subcomandos.add_parser("general", help="imprime la tabla acumulada")
    general.set_defaults(funcion=comando_general)

    escenarios_ = subcomandos.add_parser("escenarios", help="qué necesita un participante")
    escenarios_.add_argument("--participante", required=True)
    escenarios_.add_argument("--semana", type=int)
    escenarios_.set_defaults(funcion=comando_escenarios)

    importar = subcomandos.add_parser(
        "importar", help="guarda el archivo del organizador (Excel o PDF) en data/picks/"
    )
    importar.add_argument("archivo", help="ruta del archivo tal como llegó")
    importar.add_argument("--semana", type=int, help="si no se puede deducir del nombre")
    importar.add_argument("--forzar", action="store_true", help="reemplaza si ya existe")
    importar.set_defaults(funcion=comando_importar)

    pendientes = subcomandos.add_parser(
        "pendientes", help="imprime cuántos partidos siguen abiertos"
    )
    pendientes.add_argument("--semana", type=int)
    pendientes.set_defaults(funcion=comando_pendientes)

    proximo = subcomandos.add_parser(
        "proximo", help="segundos hasta el próximo partido (0 si ya empezó, -1 si no hay)"
    )
    proximo.set_defaults(funcion=comando_proximo)

    validar = subcomandos.add_parser("validar", help="solo revisa el archivo, no calcula")
    validar.add_argument("--semana", type=int)
    validar.set_defaults(funcion=comando_validar)

    return parser


def main(argumentos: list[str] | None = None) -> int:
    parser = construir_parser()
    opciones = parser.parse_args(argumentos)
    configurar_log(opciones.verboso)
    try:
        return opciones.funcion(opciones)
    except (ErrorPicks, ErrorESPN, ErrorCalendario, EquipoDesconocidoError, KeyError) as error:
        _log.error("%s", str(error).strip("'"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
