"""Pruebas de los workflows de GitHub, leídos como texto.

No hay forma de correr Actions aquí, pero sí de impedir que vuelvan dos
errores que ya pasaron o que serían graves: pegar texto de un hilo en la
terminal y reintentar una publicación deshaciendo lo que otra corrida subió.
"""

from __future__ import annotations

import re
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
