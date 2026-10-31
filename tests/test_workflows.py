"""Pruebas de los workflows de GitHub, leídos como texto.

No hay forma de correr Actions aquí, pero sí de impedir que vuelvan dos
errores que ya pasaron o que serían graves: pegar texto de un hilo en la
terminal y reintentar una publicación deshaciendo lo que otra corrida subió.
"""

from __future__ import annotations

import re
import stat
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((RAIZ / ".github" / "workflows").glob("*.yml"))
FORMA = RAIZ / ".github" / "ISSUE_TEMPLATE" / "cargar-semana.yml"

#: Lo que escribe alguien de afuera. Metido en ${{ }} dentro de un comando, es
#: una puerta para ejecutar lo que quiera.
_TEXTO_AJENO = re.compile(
    r"\$\{\{[^}]*github\.(event\.(issue|comment|pull_request|review|discussion)\.(body|title)"
    r"|event\.issue\.user\.login|head_ref)"
)


def _codigo(ruta: Path) -> list[str]:
    """Las líneas que no son comentario."""
    return [linea for linea in ruta.read_text(encoding="utf-8").splitlines()
            if not linea.strip().startswith("#")]


def test_hay_workflows():
    assert {r.name for r in WORKFLOWS} >= {"actualizar.yml", "directo.yml", "cargar.yml"}


@pytest.mark.parametrize("ruta", WORKFLOWS, ids=lambda r: r.name)
def test_ningun_workflow_pega_texto_ajeno_en_la_terminal(ruta: Path):
    peligrosas = [linea for linea in _codigo(ruta) if _TEXTO_AJENO.search(linea)]
    assert peligrosas == []


@pytest.mark.parametrize("ruta", WORKFLOWS, ids=lambda r: r.name)
def test_ningun_workflow_reintenta_con_reset_soft(ruta: Path):
    """Con --soft el reintento volvía a subir archivos viejos y deshacía cargas."""
    assert not [linea for linea in _codigo(ruta) if "reset" in linea and "--soft" in linea]


@pytest.mark.parametrize("nombre", ["actualizar.yml", "directo.yml", "cargar.yml"])
def test_los_que_publican_suben_los_sellos(nombre: str):
    lineas = [l for l in _codigo(RAIZ / ".github" / "workflows" / nombre) if "git add" in l]
    assert lineas and all("data/sellos.json" in linea for linea in lineas)


def test_la_carga_solo_atiende_la_forma_y_contesta_siempre():
    texto = (RAIZ / ".github" / "workflows" / "cargar.yml").read_text(encoding="utf-8")
    assert "types: [opened]" in texto
    assert "'carga'" in texto and "### Archivo de la semana" in texto
    assert "if: failure()" in texto
    assert "cancel-in-progress" not in texto  # una carga en espera no se descarta nunca


def test_la_forma_coincide_con_lo_que_busca_el_workflow():
    forma = FORMA.read_text(encoding="utf-8")
    assert "labels: [carga]" in forma
    assert "label: Archivo de la semana" in forma


def test_el_secreto_del_enlace_solo_existe_en_ese_camino():
    """Un hilo lo puede abrir cualquiera: ese camino nunca tiene el secreto a mano."""
    lineas = [l for l in _codigo(RAIZ / ".github" / "workflows" / "cargar.yml") if "secrets.ANGABAVE_SECRETO" in l]
    assert lineas and all("github.event_name == 'workflow_dispatch' &&" in l for l in lineas)


def test_la_carga_del_enlace_entra_por_variable_y_no_en_el_comando():
    lineas = [l.strip() for l in _codigo(RAIZ / ".github" / "workflows" / "cargar.yml") if "inputs.carga" in l]
    assert lineas == ["CARGA: ${{ inputs.carga }}"]


def test_el_directo_se_despierta_a_diario_y_alcanza_cualquier_partido():
    """La NFL también juega miércoles, viernes y sábados: nada de ventanas por día."""
    texto = (RAIZ / ".github" / "workflows" / "directo.yml").read_text(encoding="utf-8")
    crones = re.findall(r'cron: "([^"]+)"', texto)
    assert len(crones) == 1
    minuto, horas, dia, mes, semana = crones[0].split()
    assert (dia, mes, semana) == ("*", "*", "*")
    # GitHub avisa que la hora en punto es cuando más retrasa o descarta corridas.
    assert minuto != "0"

    # De 2 a 5 horas tarde, medido: siempre tiene que caer una corrida en la ventana.
    separacion = 24 / len(horas.split(","))
    ventana = int(re.search(r'VENTANA: "(\d+)"', texto).group(1)) / 3600
    assert separacion + 5 <= ventana


# --- el recorrido del directo, de verdad, sin GitHub --------------------------


def _paso_del_directo() -> str:
    lineas = (RAIZ / ".github" / "workflows" / "directo.yml").read_text(encoding="utf-8").splitlines()
    inicio = next(i for i, linea in enumerate(lineas) if "id: jornada" in linea) + 2
    bloque = []
    for linea in lineas[inicio:]:
        if linea.strip() and not linea.startswith(" " * 10):
            break
        bloque.append(linea[10:])
    return "\n".join(bloque)


_PYTHON = """#!/bin/bash
echo "python $2" >> "$BITACORA"
if [ "$2" = "proximo" ]; then
  valor=$(head -n 1 "$GUION")
  tail -n +2 "$GUION" > "$GUION.resto"; mv "$GUION.resto" "$GUION"
  echo "${valor:-$AL_ACABARSE}"
  exit 0
fi
if [ "$2" = "actualizar" ]; then
  n=$(($(cat "$CONTEO") + 1)); echo "$n" > "$CONTEO"
  case ",$FALLA_ACTUALIZAR," in *",$n,"*) exit 1;; esac
fi
exit 0
"""
_GIT = """#!/bin/bash
echo "git $*" >> "$BITACORA"
[ "$1" = "diff" ] && exit "$HAY_CAMBIOS"
exit 0
"""
_SLEEP = """#!/bin/bash
echo "sleep $1" >> "$BITACORA"
echo $(($(cat "$RELOJ") + $1)) > "$RELOJ"
"""
_DATE = """#!/bin/bash
if [ "$2" = "+%s" ]; then cat "$RELOJ"; else echo ahora; fi
"""


def _directo(tmp_path: Path, guion: list[int], *, minutos: int = 300, al_acabarse: int = -1,
             falla_actualizar: str = "", hay_cambios: int = 0):
    """Corre el paso con python, git, sleep y date de mentira, y un reloj que avanza con cada sleep."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for nombre, codigo in (("python", _PYTHON), ("git", _GIT), ("sleep", _SLEEP), ("date", _DATE)):
        archivo = bin_ / nombre
        archivo.write_text(codigo, encoding="utf-8")
        archivo.chmod(archivo.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "guion").write_text("".join(f"{v}\n" for v in guion), encoding="utf-8")
    (tmp_path / "reloj").write_text("1000000\n", encoding="utf-8")
    (tmp_path / "conteo").write_text("0\n", encoding="utf-8")
    (tmp_path / "bitacora").write_text("", encoding="utf-8")
    (tmp_path / "salida").write_text("", encoding="utf-8")
    script = tmp_path / "paso.sh"
    script.write_text(_paso_del_directo(), encoding="utf-8")
    corrida = subprocess.run(
        ["bash", "-e", str(script)],
        capture_output=True, text=True, timeout=30,
        env={
            "PATH": f"{bin_}:/usr/bin:/bin",
            "BITACORA": str(tmp_path / "bitacora"), "GUION": str(tmp_path / "guion"),
            "RELOJ": str(tmp_path / "reloj"), "CONTEO": str(tmp_path / "conteo"),
            "AL_ACABARSE": str(al_acabarse), "FALLA_ACTUALIZAR": falla_actualizar,
            "HAY_CAMBIOS": str(hay_cambios),
            "GITHUB_OUTPUT": str(tmp_path / "salida"),
            "MINUTOS": str(minutos), "CADA": "120", "ESLABON": "1", "MAX_ESLABONES": "6", "VENTANA": "43200",
        },
    )
    bitacora = (tmp_path / "bitacora").read_text(encoding="utf-8").splitlines()
    return corrida, bitacora, (tmp_path / "salida").read_text(encoding="utf-8")


def _esperas(bitacora: list[str]) -> list[int]:
    return [int(l.split()[1]) for l in bitacora if l.startswith("sleep")]


def test_sin_partidos_revisa_y_se_detiene_en_seguida(tmp_path: Path):
    corrida, bitacora, salida = _directo(tmp_path, [-1])
    assert corrida.returncode == 0, corrida.stderr
    assert bitacora.count("python actualizar") == 1  # una consulta, por si cambió un horario
    assert _esperas(bitacora) == [] and "encadenar" not in salida
    # Y antes de nada se pone al día: una corrida en cola trae una copia vieja.
    assert bitacora.index("git reset -q --hard origin/main") < bitacora.index("python actualizar")


def test_con_el_partido_lejos_no_se_queda_esperando(tmp_path: Path):
    corrida, bitacora, salida = _directo(tmp_path, [13 * 3600])
    assert corrida.returncode == 0
    assert _esperas(bitacora) == [] and "encadenar" not in salida


def test_con_el_partido_cerca_duerme_hasta_cinco_minutos_antes_y_sigue_el_juego(tmp_path: Path):
    corrida, bitacora, salida = _directo(tmp_path, [7200, 0, 0, -1])
    assert corrida.returncode == 0, corrida.stderr
    assert _esperas(bitacora) == [6900, 120, 120, 120]
    assert bitacora.count("python actualizar") == 4
    assert "encadenar" not in salida


def test_si_no_alcanza_el_partido_encadena_el_siguiente_eslabon(tmp_path: Path):
    corrida, bitacora, salida = _directo(tmp_path, [40000])
    assert corrida.returncode == 0
    assert _esperas(bitacora) == [300 * 60 - 120]
    assert "encadenar=si" in salida
    assert bitacora.count("python actualizar") == 1


def test_entre_dos_partidos_duerme_en_vez_de_recalcular_cada_dos_minutos(tmp_path: Path):
    """Del sábado en la tarde a la noche no hay nada que recalcular."""
    corrida, bitacora, _ = _directo(tmp_path, [0, 3 * 3600, 0, -1])
    assert corrida.returncode == 0
    assert _esperas(bitacora) == [120, 3 * 3600 - 300, 120, 120]


def test_al_cerrar_la_jornada_se_detiene_aunque_quede_otro_partido_lejos(tmp_path: Path):
    corrida, bitacora, salida = _directo(tmp_path, [0, 62 * 3600])
    assert corrida.returncode == 0
    assert "encadenar" not in salida
    assert _esperas(bitacora) == [120]


def test_si_se_acaba_el_tiempo_a_media_jornada_encadena(tmp_path: Path):
    corrida, bitacora, salida = _directo(tmp_path, [], minutos=6, al_acabarse=0)
    assert corrida.returncode == 0
    assert bitacora.count("python actualizar") == 1 + 3
    assert "encadenar=si" in salida


def test_si_espn_no_contesta_al_arrancar_sigue_con_lo_que_hay(tmp_path: Path):
    corrida, bitacora, _ = _directo(tmp_path, [7200, -1], falla_actualizar="1", hay_cambios=1)
    assert corrida.returncode == 0, corrida.stderr
    assert _esperas(bitacora) == [6900, 120]
    # Lo que haya dejado a medias no se publica: solo lo de la vuelta buena.
    primera_espera = bitacora.index("sleep 6900")
    assert not [l for l in bitacora[:primera_espera] if l.startswith(("git add", "git commit"))]
    assert [l for l in bitacora[primera_espera:] if l.startswith("git commit")]


def test_si_truena_a_media_jornada_sale_en_rojo_y_no_encadena(tmp_path: Path):
    corrida, _, salida = _directo(tmp_path, [0], falla_actualizar="2")
    assert corrida.returncode != 0
    assert "encadenar" not in salida


def test_sin_cambios_no_hay_commit(tmp_path: Path):
    _, bitacora, _ = _directo(tmp_path, [-1], hay_cambios=0)
    assert not [l for l in bitacora if l.startswith("git commit")]


def test_con_cambios_si_hay_commit(tmp_path: Path):
    _, bitacora, _ = _directo(tmp_path, [-1], hay_cambios=1)
    assert [l for l in bitacora if l.startswith("git commit")]
