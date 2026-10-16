"""Copias del portal que simulan otros momentos de la semana, para revisarlas a ojo.

    .venv/bin/python herramientas/momentos.py                  # deja las copias en /tmp/angabave-momentos
    .venv/bin/python herramientas/momentos.py --salida otra/carpeta
    python3 -m http.server 8766 --directory /tmp/angabave-momentos

"Hoy" cambia según el momento: picks, partidos de hoy, en vivo, resultados,
semana cerrada. Esperar al domingo para ver cómo se acomoda no es práctico, así
que esto toma docs/index.html y la última semana cerrada (S) y arma cinco
páginas, cada una con los datos retocados, un reloj falso y un ESPN falso:

  fase-hoy.html            domingo de S a las 06:00: todo por jugar
  fase-vivo.html           domingo de S, hora y media después del primer partido de la tarde
  fase-domingo-noche.html  domingo de S a las 22:30: ya acabó el domingo, falta el lunes
  fase-martes.html         martes después de S: ya cerró y la siguiente está en picks
  fase-final.html          como si la temporada hubiera terminado en S

Las tablas no se recalculan (la de S es la final): las páginas sirven para ver
el acomodo, no para revisar cuentas. Nada de esto se publica, y por eso la
salida no puede quedar dentro de docs/.

Solo usa la biblioteca estándar de Python.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CDMX = timezone(timedelta(hours=-6))
DATOS = re.compile(r'(<script type="application/json" id="datos">)(.*?)(</script>)', re.S)
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def dia(p: dict) -> date:
    return datetime.fromtimestamp(p["t"], CDMX).date()


def a_las(d: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(d, time(h, m), CDMX)


def semana(D: dict, n: int) -> dict | None:
    return next((s for s in D["semanas"] if s["n"] == n), None)


def domingo_de(s: dict) -> date:
    """El día con más partidos de la semana."""
    juegos = s["partidos"] + (s.get("por_entregar") or [])
    return Counter(dia(p) for p in juegos).most_common(1)[0][0]


def reabrir(s: dict, desde: datetime) -> None:
    """Deja abiertos los partidos que arrancan a partir de `desde`."""
    for p in s["partidos"]:
        if p["t"] >= desde.timestamp():
            p.update(mv=None, ml=None, g=None, cerrado=False, vivo=False, e=p["grupo"])
    s.update(cerrados=sum(p["cerrado"] for p in s["partidos"]), estado="en_vivo", oficial=False)


def tanda(cierre: datetime, juegos: list[dict]) -> dict:
    texto = f"{DIAS[cierre.weekday()]} {cierre.day} de {MESES[cierre.month - 1]} a las {cierre:%H:%M}"
    return {"cierre": cierre.isoformat(), "cierre_texto": texto, "claves": [p["v"] + "@" + p["l"] for p in juegos]}


def en_picks(s: dict) -> None:
    """La semana, sin repartir: el jueves cierra la víspera y el resto el sábado."""
    juegos = s["partidos"] + (s.get("por_entregar") or [])
    domingo = domingo_de(s)
    antes = [p for p in juegos if dia(p) < domingo]
    resto = [p for p in juegos if dia(p) >= domingo]
    tandas = []
    if antes:
        tandas.append(tanda(a_las(min(dia(p) for p in antes) - timedelta(days=1), 23, 59), antes))
    if resto:
        tandas.append(tanda(a_las(domingo - timedelta(days=1), 23, 59), resto))
    for p in juegos:
        p.update(mv=None, ml=None, g=None, cerrado=False, vivo=False)
    s.update(estado="pendiente", cerrados=0, total=len(juegos), partidos=juegos, jugadores=[], picks=[],
             tabla=[], panorama={}, ganadores=[], oficial=False, por_entregar=[], tandas_por_entregar=[],
             proyectable=False, tandas=tandas)


def marcador(D: dict, s: dict, ahora: datetime, en_juego: bool) -> dict:
    """ESPN de mentira: lo cerrado como final, lo que ya arrancó en juego y lo demás por jugar."""
    siglas = {}
    for sigla, equipo in D["vivo"]["equipos"].items():
        siglas.setdefault(equipo, sigla)
    eventos = []
    for i, p in enumerate(s["partidos"] + (s.get("por_entregar") or [])):
        if p["cerrado"]:
            estado, completo, mv, ml, texto = "post", True, p["mv"], p["ml"], "Final"
        elif en_juego and p["t"] <= ahora.timestamp():
            estado, completo, texto = "in", False, "In Progress"
            mv, ml = (14, 10) if i % 2 else (7, 13)
        else:
            estado, completo, mv, ml, texto = "pre", False, 0, 0, "Scheduled"
        eventos.append({"competitions": [{
            "competitors": [
                {"homeAway": "away", "team": {"abbreviation": siglas[p["v"]]}, "score": str(mv)},
                {"homeAway": "home", "team": {"abbreviation": siglas[p["l"]]}, "score": str(ml)},
            ],
            "status": {"period": 2 if estado == "in" else 0, "displayClock": "5:32",
                       "type": {"completed": completo, "state": estado, "description": texto}},
        }]})
    return {"events": eventos}


# Un reloj y un ESPN de mentira, antes de que corra cualquier otro script.
RELOJ = (
    "<script>(function(){var R=Date,d=%d-R.now();"
    "function F(){var a=[].slice.call(arguments);"
    "return a.length?new (Function.prototype.bind.apply(R,[null].concat(a)))():new R(R.now()+d)}"
    "F.prototype=R.prototype;F.now=function(){return R.now()+d};F.parse=R.parse;F.UTC=R.UTC;window.Date=F;"
    "var M=%s,f=window.fetch;window.fetch=function(u){if(String(u).indexOf('scoreboard')>=0)"
    "return Promise.resolve(new Response(JSON.stringify(M),{status:200,headers:{'Content-Type':'application/json'}}));"
    "return f.apply(this,arguments)};})();</script>"
)


def escribir(salida: Path, html: str, nombre: str, D: dict, ahora: datetime, espn: dict) -> None:
    datos = json.dumps(D, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    pagina = DATOS.sub(lambda m: m.group(1) + datos + m.group(3), html, count=1)
    pagina = pagina.replace("<head>", "<head>" + RELOJ % (int(ahora.timestamp() * 1000), json.dumps(espn)), 1)
    (salida / f"fase-{nombre}.html").write_text(pagina, encoding="utf-8")
    print(f"  fase-{nombre}.html  ({DIAS[ahora.weekday()]} {ahora:%d/%m %H:%M})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sitio", type=Path, default=RAIZ / "docs", help="de dónde se toma index.html")
    parser.add_argument("--salida", type=Path, default=Path("/tmp/angabave-momentos"))
    args = parser.parse_args(argv)

    salida = args.salida.resolve()
    if salida == (RAIZ / "docs").resolve() or (RAIZ / "docs").resolve() in salida.parents:
        parser.error("la salida no puede estar dentro de docs/: eso se publica")
    html = (args.sitio / "index.html").read_text(encoding="utf-8")
    D0 = json.loads(DATOS.search(html).group(2))
    if not D0.get("vivo"):
        sys.path.insert(0, str(RAIZ))
        from quiniela.equipos import ABREVIATURAS_ESPN
        D0["vivo"] = {"url": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
                      "cada": 60, "equipos": ABREVIATURAS_ESPN, "estados": {}}

    cerradas = [s for s in D0["semanas"] if s["estado"] == "cerrada"]
    if not cerradas:
        print("Todavía no hay una semana cerrada que simular.")
        return 1
    n = cerradas[-1]["n"]
    domingo = domingo_de(cerradas[-1])
    lunes, martes = domingo + timedelta(days=1), domingo + timedelta(days=2)
    salida.mkdir(parents=True, exist_ok=True)
    # El aviso de versión de la página lo pide; sin él, la consola se llena de 404.
    for archivo in ("version.json", "manifest.webmanifest"):
        if (args.sitio / archivo).exists():
            (salida / archivo).write_bytes((args.sitio / archivo).read_bytes())
    print(f"Semana {n} (domingo {domingo:%d/%m}) → {salida}")

    def base(hasta: int) -> dict:
        """Las semanas hasta `hasta`; la que sigue a S, si existe, en tiempo de picks."""
        D = copy.deepcopy(D0)
        D["semanas"] = [s for s in D["semanas"] if s["n"] <= hasta]
        siguiente = semana(D, n + 1)
        if siguiente:
            en_picks(siguiente)
        D["activa"] = n
        return D

    D = base(n + 1)
    reabrir(semana(D, n), a_las(domingo, 0))
    ahora = a_las(domingo, 6)
    escribir(salida, html, "hoy", D, ahora, marcador(D, semana(D, n), ahora, False))

    D = base(n + 1)
    tarde = min((p["t"] for p in semana(D, n)["partidos"]
                 if dia(p) == domingo and p["t"] >= a_las(domingo, 11).timestamp()), default=None)
    if tarde:
        reabrir(semana(D, n), datetime.fromtimestamp(tarde, CDMX))
        ahora = datetime.fromtimestamp(tarde, CDMX) + timedelta(minutes=90)
        escribir(salida, html, "vivo", D, ahora, marcador(D, semana(D, n), ahora, True))

    D = base(n + 1)
    reabrir(semana(D, n), a_las(lunes, 0))
    ahora = a_las(domingo, 22, 30)
    escribir(salida, html, "domingo-noche", D, ahora, marcador(D, semana(D, n), ahora, False))

    D = base(n + 1)
    if semana(D, n + 1):
        D["activa"] = n + 1
        ahora = a_las(martes, 10)
        escribir(salida, html, "martes", D, ahora, {"events": []})

    D = base(n)
    D["vivo"] = None
    escribir(salida, html, "final", D, a_las(martes, 10), {"events": []})
    return 0


if __name__ == "__main__":
    sys.exit(main())
