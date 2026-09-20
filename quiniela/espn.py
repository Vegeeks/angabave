"""Cliente del scoreboard público de ESPN y tipo `Partido`.

El endpoint no está documentado oficialmente y puede cambiar sin aviso, así que
todo el parseo va envuelto en validaciones que dicen exactamente qué campo
faltó en vez de devolver una tabla equivocada.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

#: México abolió el horario de verano en 2022, así que el centro del país está
#: fijo en UTC-6 todo el año. Con un offset fijo no dependemos de tzdata.
ZONA_CDMX = timezone(timedelta(hours=-6), "CDMX")


def a_cdmx(momento: datetime | None) -> datetime | None:
    """Pasa un instante a horario de Ciudad de México."""
    if momento is None:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(ZONA_CDMX)


def ahora_cdmx() -> datetime:
    return datetime.now(ZONA_CDMX)

__all__ = ["Partido", "ZONA_CDMX", "a_cdmx", "ahora_cdmx"]


@dataclass(frozen=True, slots=True)
class Partido:
    """Un enfrentamiento, con o sin marcador.

    Los partidos que salen del Excel de picks traen solo `visitante` y `local`;
    los que salen de ESPN traen además marcador y estado.
    """

    visitante: str
    local: str
    marcador_visitante: int | None = None
    marcador_local: int | None = None
    #: Ganador. None si el partido no ha terminado O si terminó empatado.
    ganador: str | None = None
    finalizado: bool = False
    #: Texto tal cual lo reporta ESPN: "Final", "In Progress", "Scheduled".
    estado: str = "sin datos"
    #: Momento de inicio en UTC. None cuando el partido viene del Excel.
    inicio: datetime | None = None

    @property
    def clave(self) -> str:
        """Identificador del partido: "Giants@Rams". Llave de overrides."""
        return f"{self.visitante}@{self.local}"

    @property
    def empatado(self) -> bool:
        """Terminó y nadie ganó. En la NFL pasa; nadie acierta ese partido."""
        return self.finalizado and self.ganador is None

    @property
    def hay_marcador(self) -> bool:
        return self.marcador_visitante is not None and self.marcador_local is not None

    @property
    def lider(self) -> str | None:
        """Equipo arriba en el marcador. None si van iguales o no hay marcador.

        Es la base del "proyectado": orientativo, nunca oficial.
        """
        if not self.hay_marcador:
            return None
        if self.marcador_visitante > self.marcador_local:
            return self.visitante
        if self.marcador_local > self.marcador_visitante:
            return self.local
        return None

    def con_ganador(self, ganador: str | None, estado: str) -> "Partido":
        """Copia con el ganador forzado y marcado como cerrado (overrides)."""
        return replace(self, ganador=ganador, finalizado=True, estado=estado)


import json
import logging
import time
from pathlib import Path

import requests

from .equipos import EquipoDesconocidoError, normalizar

__all__ += [
    "URL_SCOREBOARD",
    "ErrorESPN",
    "ErrorRed",
    "ErrorEstructura",
    "aplicar_overrides",
    "cargar_cache",
    "guardar_cache",
    "obtener_partidos",
    "ruta_cache",
]

_log = logging.getLogger(__name__)

URL_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
TIEMPO_ESPERA = 10
MAX_REINTENTOS = 3
ESPERA_BASE = 1.0  # 1 s, 2 s, 4 s

RAIZ = Path(__file__).resolve().parents[1]
DIR_RESULTADOS = RAIZ / "data" / "resultados"
RUTA_OVERRIDES = RAIZ / "data" / "overrides.json"


class ErrorESPN(RuntimeError):
    """Problema al obtener o interpretar los marcadores."""


class ErrorRed(ErrorESPN):
    """La API no respondió después de todos los reintentos."""


class ErrorEstructura(ErrorESPN):
    """La respuesta llegó, pero no tiene la forma esperada."""


def _exigir(dato: object, clave: str | int, contexto: str) -> object:
    """Saca una clave obligatoria diciendo exactamente cuál faltó si no está."""
    if isinstance(clave, int):
        if not isinstance(dato, list):
            raise ErrorEstructura(f"{contexto}: se esperaba una lista, llegó {type(dato).__name__}")
        if len(dato) <= clave:
            raise ErrorEstructura(f"{contexto}[{clave}]: la lista solo trae {len(dato)} elemento(s)")
        return dato[clave]
    if not isinstance(dato, dict):
        raise ErrorEstructura(f"{contexto}: se esperaba un objeto, llegó {type(dato).__name__}")
    if clave not in dato:
        disponibles = ", ".join(sorted(dato)) or "ninguna"
        raise ErrorEstructura(
            f"{contexto}: falta el campo {clave!r} (campos presentes: {disponibles})"
        )
    return dato[clave]


def _marcador(competidor: dict, contexto: str) -> int | None:
    crudo = competidor.get("score")
    if crudo is None or crudo == "":
        return None
    if isinstance(crudo, dict):  # algunos endpoints anidan {"value": 27}
        crudo = crudo.get("value")
    try:
        return int(float(crudo))
    except (TypeError, ValueError):
        raise ErrorEstructura(f"{contexto}: marcador ilegible {crudo!r}") from None


def _fecha(evento: dict, contexto: str) -> datetime | None:
    crudo = evento.get("date")
    if not crudo:
        return None
    try:
        return datetime.fromisoformat(str(crudo).replace("Z", "+00:00"))
    except ValueError:
        raise ErrorEstructura(f"{contexto}: fecha ilegible {crudo!r}") from None


def _parsear_evento(evento: dict, indice: int) -> Partido:
    identificador = evento.get("id", f"#{indice}")
    contexto = f"evento {identificador}"

    competencias = _exigir(evento, "competitions", contexto)
    competencia = _exigir(competencias, 0, f"{contexto}.competitions")
    competidores = _exigir(competencia, "competitors", f"{contexto}.competitions[0]")
    if not isinstance(competidores, list) or len(competidores) != 2:
        raise ErrorEstructura(
            f"{contexto}.competitions[0].competitors: se esperaban 2 equipos, "
            f"llegaron {len(competidores) if isinstance(competidores, list) else '?'}"
        )

    equipos: dict[str, tuple[str, int | None]] = {}
    for posicion, competidor in enumerate(competidores):
        ruta = f"{contexto}.competitions[0].competitors[{posicion}]"
        lado = _exigir(competidor, "homeAway", ruta)
        equipo = _exigir(competidor, "team", ruta)
        abreviatura = _exigir(equipo, "abbreviation", f"{ruta}.team")
        try:
            nombre = normalizar(str(abreviatura))
        except EquipoDesconocidoError as error:
            raise ErrorEstructura(f"{ruta}.team.abbreviation: {error}") from error
        equipos[str(lado)] = (nombre, _marcador(competidor, ruta))

    if set(equipos) != {"home", "away"}:
        raise ErrorEstructura(
            f"{contexto}.competitions[0].competitors: se esperaba un 'home' y un 'away', "
            f"llegó {sorted(equipos)}"
        )

    visitante, marcador_visitante = equipos["away"]
    local, marcador_local = equipos["home"]

    estado_crudo = competencia.get("status") or evento.get("status")
    if estado_crudo is None:
        raise ErrorEstructura(f"{contexto}: falta el campo 'status' en el evento y en la competencia")
    tipo = _exigir(estado_crudo, "type", f"{contexto}.status")
    if "completed" not in tipo:
        raise ErrorEstructura(
            f"{contexto}.status.type: falta el campo 'completed', que es el único que "
            "define si el partido cerró"
        )
    finalizado = bool(tipo["completed"])
    estado = str(tipo.get("description") or tipo.get("name") or "desconocido")

    ganador: str | None = None
    if finalizado:
        if marcador_visitante is None or marcador_local is None:
            raise ErrorEstructura(
                f"{contexto}: el partido está marcado como terminado pero llegó sin marcador"
            )
        if marcador_visitante > marcador_local:
            ganador = visitante
        elif marcador_local > marcador_visitante:
            ganador = local
        # Empate: ganador se queda en None y nadie acierta ese partido.

    return Partido(
        visitante=visitante,
        local=local,
        marcador_visitante=marcador_visitante,
        marcador_local=marcador_local,
        ganador=ganador,
        finalizado=finalizado,
        estado=estado,
        inicio=_fecha(evento, contexto),
    )


def parsear_scoreboard(carga: dict) -> list[Partido]:
    """Convierte la respuesta cruda de ESPN en partidos."""
    eventos = _exigir(carga, "events", "respuesta de ESPN")
    if not isinstance(eventos, list):
        raise ErrorEstructura(
            f"respuesta de ESPN: 'events' debería ser una lista, llegó {type(eventos).__name__}"
        )
    if not eventos:
        raise ErrorEstructura("respuesta de ESPN: 'events' llegó vacío, no hay partidos que leer")
    return [_parsear_evento(evento, indice) for indice, evento in enumerate(eventos)]


def _consultar_api(anio: int, semana: int) -> dict:
    parametros = {"dates": anio, "seasontype": 2, "week": semana}
    ultimo_error: Exception | None = None

    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            respuesta = requests.get(URL_SCOREBOARD, params=parametros, timeout=TIEMPO_ESPERA)
            respuesta.raise_for_status()
            return respuesta.json()
        except Exception as error:  # noqa: BLE001 - se reintenta cualquier fallo de red
            ultimo_error = error
            if intento == MAX_REINTENTOS:
                break
            espera = ESPERA_BASE * 2 ** (intento - 1)
            _log.warning(
                "Intento %d/%d falló (%s). Reintento en %.0f s.",
                intento, MAX_REINTENTOS, error, espera,
            )
            time.sleep(espera)

    raise ErrorRed(
        f"No pude consultar el scoreboard de ESPN para {anio} semana {semana} "
        f"después de {MAX_REINTENTOS} intentos: {ultimo_error}"
    ) from ultimo_error


def ruta_cache(semana: int, dir_cache: Path = DIR_RESULTADOS) -> Path:
    return Path(dir_cache) / f"semana_{semana:02d}.json"


def cargar_cache(semana: int, dir_cache: Path = DIR_RESULTADOS) -> list[Partido]:
    """Lee el caché de la semana. Devuelve lista vacía si no existe."""
    ruta = ruta_cache(semana, dir_cache)
    if not ruta.exists():
        return []
    try:
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ErrorESPN(f"El caché {ruta} no es JSON válido: {error}") from error

    partidos = []
    for registro in crudo.get("partidos", []):
        inicio = registro.get("inicio")
        partidos.append(
            Partido(
                visitante=registro["visitante"],
                local=registro["local"],
                marcador_visitante=registro.get("marcador_visitante"),
                marcador_local=registro.get("marcador_local"),
                ganador=registro.get("ganador"),
                finalizado=bool(registro.get("finalizado", False)),
                estado=registro.get("estado", "desconocido"),
                inicio=datetime.fromisoformat(inicio) if inicio else None,
            )
        )
    return partidos


def guardar_cache(semana: int, partidos: list[Partido], dir_cache: Path = DIR_RESULTADOS) -> Path:
    """Escribe el caché de la semana con los datos crudos de la API.

    Los overrides no se guardan: se aplican al vuelo para poder corregirlos sin
    invalidar el caché.
    """
    ruta = ruta_cache(semana, dir_cache)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    contenido = {
        "semana": semana,
        "partidos": [
            {
                "visitante": partido.visitante,
                "local": partido.local,
                "marcador_visitante": partido.marcador_visitante,
                "marcador_local": partido.marcador_local,
                "ganador": partido.ganador,
                "finalizado": partido.finalizado,
                "estado": partido.estado,
                "inicio": partido.inicio.isoformat() if partido.inicio else None,
            }
            for partido in partidos
        ],
    }
    ruta.write_text(
        json.dumps(contenido, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return ruta


def _mezclar(cacheados: list[Partido], frescos: list[Partido]) -> list[Partido]:
    """Los partidos ya cerrados salen del caché; los abiertos, de la API."""
    por_clave = {partido.clave: partido for partido in cacheados}
    mezclados = []
    for partido in frescos:
        previo = por_clave.pop(partido.clave, None)
        if previo is not None and previo.finalizado:
            mezclados.append(previo)
        else:
            mezclados.append(partido)
    for sobrante in por_clave.values():
        _log.warning(
            "El partido %s está en el caché pero ya no viene en la respuesta de ESPN; lo conservo.",
            sobrante.clave,
        )
        mezclados.append(sobrante)
    return mezclados


def aplicar_overrides(
    partidos: list[Partido], semana: int, ruta_overrides: Path = RUTA_OVERRIDES
) -> list[Partido]:
    """Fuerza ganadores desde data/overrides.json. Siempre ganan sobre la API."""
    ruta = Path(ruta_overrides)
    if not ruta.exists():
        return partidos

    try:
        todos = json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ErrorESPN(f"El archivo de overrides {ruta} no es JSON válido: {error}") from error

    de_la_semana = todos.get(str(semana)) or {}
    if not de_la_semana:
        return partidos

    por_clave = {partido.clave: indice for indice, partido in enumerate(partidos)}
    resultado = list(partidos)
    for clave, equipo in de_la_semana.items():
        indice = por_clave.get(clave)
        if indice is None:
            raise ErrorESPN(
                f"El override {clave!r} de la semana {semana} no corresponde a ningún partido. "
                f"Partidos de la semana: {', '.join(sorted(por_clave))}"
            )
        anterior = resultado[indice]
        ganador = None if equipo is None else normalizar(str(equipo))
        if ganador is not None and ganador not in (anterior.visitante, anterior.local):
            raise ErrorESPN(
                f"El override {clave!r} dice que ganó {ganador}, que no juega ese partido."
            )
        resultado[indice] = anterior.con_ganador(ganador, estado="Final (override)")
        _log.warning(
            "Override aplicado en semana %d, %s: gana %s (la API decía %s).",
            semana, clave, ganador or "empate", anterior.ganador or "empate/sin cerrar",
        )
    return resultado


def obtener_partidos(
    anio: int,
    semana: int,
    *,
    sin_red: bool = False,
    dir_cache: Path = DIR_RESULTADOS,
    ruta_overrides: Path = RUTA_OVERRIDES,
) -> list[Partido]:
    """Devuelve los partidos de la semana, del caché y de la API según haga falta.

    El endpoint entrega la semana completa, no partido por partido, así que la
    regla "no volver a consultar lo ya cerrado" se cumple así: si el caché
    existe y todos sus partidos están cerrados, no se toca la red; si alguno
    sigue abierto, se hace una sola petición y los cerrados se conservan tal
    cual estaban en el caché.
    """
    cacheados = cargar_cache(semana, dir_cache)

    if sin_red:
        if not cacheados:
            raise ErrorESPN(
                f"Se pidió trabajar sin red pero no hay caché para la semana {semana} "
                f"({ruta_cache(semana, dir_cache)})."
            )
        _log.info("Modo sin red: uso el caché de la semana %d tal cual.", semana)
        return aplicar_overrides(cacheados, semana, ruta_overrides)

    if cacheados and all(partido.finalizado for partido in cacheados):
        _log.info(
            "Los %d partidos de la semana %d ya están cerrados; no consulto la API.",
            len(cacheados), semana,
        )
        return aplicar_overrides(cacheados, semana, ruta_overrides)

    abiertos = [p for p in cacheados if not p.finalizado]
    if cacheados:
        _log.info(
            "Consulto ESPN por %d partido(s) todavía abierto(s) de la semana %d.",
            len(abiertos), semana,
        )
    else:
        _log.info("Sin caché para la semana %d: consulto ESPN.", semana)

    frescos = parsear_scoreboard(_consultar_api(anio, semana))
    partidos = _mezclar(cacheados, frescos)
    guardar_cache(semana, partidos, dir_cache)
    cerrados = sum(1 for p in partidos if p.finalizado)
    _log.info("Semana %d: %d de %d partidos cerrados.", semana, cerrados, len(partidos))
    return aplicar_overrides(partidos, semana, ruta_overrides)
