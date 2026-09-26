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
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from quiniela.buzon import ErrorBuzon, cargadores, descargar, leer_solicitud, reporte_rechazo
from quiniela.carga import recibir, reporte_markdown, reporte_texto
from quiniela.equipos import EquipoDesconocidoError
from quiniela.espn import ErrorESPN, ahora_cdmx, obtener_partidos
from quiniela.picks import (
    RUTA_SELLOS,
    ErrorPicks,
    PicksAlteradosError,
    archivos_por_semana,
    leer_picks,
    numero_semana,
    verificar_sello,
)
from quiniela.render_html import UMBRAL_SEMANA, SemanaRender, generar_html
from quiniela.render_png import generar_iconos, generar_png
from quiniela.render_html import _pesos
from quiniela.scoring import (
    ErrorCalendario,
    PREMIO_SEMANAL,
    ganadores as ganadores_de,
    premio_semanal,
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
    elegidos = []
    for semana, rutas in archivos_por_semana(DIR_PICKS).items():
        if len(rutas) > 1:
            _log.warning(
                "La semana %d tiene %d archivos (%s); uso %s.",
                semana, len(rutas), ", ".join(p.name for p in rutas), rutas[0].name,
            )
        elegidos.append(rutas[0])
    return elegidos


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


def _sellar(ruta: Path, semana: int, resultados) -> None:
    """Congela los picks de cada partido en cuanto ese partido arranca.

    Es la única vía real de trampa que queda: los picks viven en el repo y solo
    se cambian con un push autenticado, pero un cambio hecho con el resultado ya
    en la mano no se puede dar por bueno. Aquí truena.

    Se sella partido por partido, no la semana entera, porque la jornada cierra
    por tandas: con el jueves ya jugado, los picks del domingo todavía se pueden
    entregar y el organizador manda esa hoja aparte.
    """
    ahora = datetime.now(timezone.utc)
    arrancados = {
        partido.clave
        for partido in resultados
        if partido.finalizado or (partido.inicio is not None and partido.inicio <= ahora)
    }
    verificar_sello(ruta, semana, arrancados, RUTA_SELLOS)


def _cargar_semana(semana: int, anio: int, sin_red: bool):
    ruta = ruta_picks(semana)
    partidos, picks = leer_picks(ruta)
    resultados = obtener_partidos(anio, semana, sin_red=sin_red)
    alineados = emparejar_resultados(partidos, resultados)
    _sellar(ruta, semana, alineados)
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
        _sellar(ruta, numero, alineados)
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
        cargados = {partido.clave for partido in alineados}
        faltantes = [r for r in resultados if r.clave not in cargados]
        construidas.append(
            SemanaRender(numero, alineados, picks, tabla, vista, faltantes)
        )
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

    rutas = semanas_disponibles()
    general = tabla_general(rutas)
    # La tabla sin la última semana, para saber quién subió y quién bajó.
    previas: dict[str, int] = {}
    if len(rutas) > 1:
        anterior = tabla_general(rutas[:-1])
        previas = dict(zip(anterior["participante"], anterior["posicion"]))
    momento = ahora_cdmx()

    html = generar_html(
        anio=argumentos.anio,
        semanas=semanas,
        tabla_acumulada=general,
        posiciones_previas=previas,
        momento=momento,
    )
    generar_iconos()
    # La franja del PNG solo aparece cuando ya hay algo que decir.
    primeros: list[str] = []
    monto = None
    if activa.tabla is not None and activa.cerrados >= UMBRAL_SEMANA:
        primeros = ganadores_de(activa.tabla)
        monto = _pesos(
            premio_semanal(len(primeros)) if activa.estado == "cerrada" else PREMIO_SEMANAL
        )
    png = generar_png(
        tabla_acumulada=general,
        semana=semana,
        anio=argumentos.anio,
        cerrados=activa.cerrados,
        total_partidos=len(activa.partidos),
        momento=momento,
        ganadores=primeros,
        premio=monto,
        oficial=activa.estado == "cerrada",
    )

    lider = general.iloc[0]
    _log.info(
        "Semana %d lista: %d de %d partidos cerrados. Lidera %s con %d.",
        semana, activa.cerrados, activa.total, lider["participante"], lider["acumulado"],
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


#: Lo que se contesta cuando falla algo de este lado y no del archivo.
REPORTE_ERROR_INTERNO = (
    "### ⚠️ No pude revisar el archivo\n\n"
    "Algo falló de mi lado, no en tu archivo. No se tocó nada y Angel ya tiene el aviso.\n"
)


def comando_importar(argumentos) -> int:
    """Carga el archivo del organizador: lo revisa completo, lo guarda y lo sella.

    Es la misma puerta que usa la forma "Cargar semana" de GitHub. Acepta el
    Excel o el PDF tal como llega, de la semana completa o de una tanda; la
    semana sale de la hoja. Devuelve 0 si quedó cargado o ya estaba igual, 1 si
    se rechazó por algo del archivo, y 3 si algo falló de este lado.
    """
    origen = Path(argumentos.archivo).expanduser()
    if not origen.exists():
        raise ErrorPicks(f"No existe el archivo: {origen}")

    try:
        resultado = recibir(
            origen,
            calendario=lambda numero: obtener_partidos(
                argumentos.anio, numero, sin_red=argumentos.sin_red
            ),
            dir_picks=DIR_PICKS,
            semana=argumentos.semana,
            ruta_sellos=RUTA_SELLOS,
            escribir=not argumentos.solo_revisar,
        )
    except Exception:
        _log.exception("Falló la carga de %s por algo que no es del archivo.", origen.name)
        if argumentos.reporte:
            Path(argumentos.reporte).write_text(REPORTE_ERROR_INTERNO, encoding="utf-8")
        return 3

    if argumentos.reporte:
        Path(argumentos.reporte).write_text(
            reporte_markdown(resultado, forma=argumentos.forma or ""), encoding="utf-8"
        )
    if argumentos.resumen:
        Path(argumentos.resumen).write_text(
            json.dumps(
                {"aceptado": resultado.aceptado, "accion": resultado.accion, "semana": resultado.semana}
            ),
            encoding="utf-8",
        )
    print(reporte_texto(resultado))
    return 0 if resultado.aceptado else 1


def comando_buzon(argumentos) -> int:
    """Atiende un hilo de la forma "Cargar semana": quién lo abrió y qué adjuntó.

    Lo usa el workflow de carga. Si la cuenta está autorizada y hay un solo
    archivo, lo baja y escribe su ruta en --salida; si no, escribe en --reporte
    lo que hay que contestar. Mismos códigos que `importar`.
    """
    try:
        evento = json.loads(Path(argumentos.evento).read_text(encoding="utf-8"))
        solicitud = leer_solicitud(evento, cargadores())
        archivo = descargar(solicitud, Path(argumentos.carpeta))
    except ErrorBuzon as error:
        _log.warning("%s", error)
        Path(argumentos.reporte).write_text(
            reporte_rechazo(error, forma=argumentos.forma or ""), encoding="utf-8"
        )
        return 1
    except Exception:
        _log.exception("Falló el buzón por algo que no es del hilo.")
        Path(argumentos.reporte).write_text(REPORTE_ERROR_INTERNO, encoding="utf-8")
        return 3

    Path(argumentos.salida).write_text(str(archivo), encoding="utf-8")
    _log.info("Hilo #%d de @%s: bajé %s.", solicitud.numero, solicitud.usuario, archivo.name)
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
    importar.add_argument("--semana", type=int, help="solo si la hoja no dice 'Semana N'")
    importar.add_argument(
        "--solo-revisar", action="store_true", help="revisa todo pero no guarda nada"
    )
    importar.add_argument("--sin-red", action="store_true", help="usa solo el caché de ESPN")
    importar.add_argument("--reporte", help="escribe ahí el reporte en Markdown")
    importar.add_argument("--resumen", help="escribe ahí el resultado en JSON")
    importar.add_argument("--forma", help="enlace para volver a subir, va en el reporte")
    # Antes hacía falta para reemplazar una semana; ahora el reemplazo es seguro
    # por sí solo. Se acepta para no romper instrucciones viejas.
    importar.add_argument("--forzar", action="store_true", help=argparse.SUPPRESS)
    importar.set_defaults(funcion=comando_importar)

    buzon = subcomandos.add_parser(
        "buzon", help="atiende un hilo de la forma 'Cargar semana' (lo usa el workflow)"
    )
    buzon.add_argument("--evento", required=True, help="el JSON del evento de GitHub")
    buzon.add_argument("--carpeta", required=True, help="dónde bajar el archivo")
    buzon.add_argument("--reporte", required=True, help="dónde escribir la respuesta si se rechaza")
    buzon.add_argument("--salida", required=True, help="dónde escribir la ruta del archivo bajado")
    buzon.add_argument("--forma", help="enlace para volver a subir, va en el reporte")
    buzon.set_defaults(funcion=comando_buzon)

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
    except PicksAlteradosError as error:
        _log.error("%s", error)
        return 2
    except (ErrorPicks, ErrorESPN, ErrorCalendario, EquipoDesconocidoError, KeyError) as error:
        _log.error("%s", str(error).strip("'"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
