"""herramientas/momentos.py: copias del portal en otros momentos de la semana."""

import importlib.util
import json
import re
from pathlib import Path

import pytest

from tests.test_render import armado, datos_embebidos, render  # noqa: F401  (armado es fixture)

RAIZ = Path(__file__).resolve().parent.parent


def _momentos():
    spec = importlib.util.spec_from_file_location("momentos", RAIZ / "herramientas" / "momentos.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _sitio_con_semana_cerrada(armado, tmp_path: Path) -> Path:  # noqa: F811
    html = render(armado, tmp_path)
    D = datos_embebidos(html)
    s = next(x for x in D["semanas"] if x["estado"] == "en_vivo")
    for p in s["partidos"]:
        p.update(cerrado=True, mv=21, ml=17, g="v", vivo=False)
    s.update(estado="cerrada", cerrados=len(s["partidos"]))
    datos = json.dumps(D, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    sitio = tmp_path / "sitio"
    sitio.mkdir()
    (sitio / "index.html").write_text(
        re.sub(r'(id="datos">)(.*?)(</script>)', lambda m: m.group(1) + datos + m.group(3), html,
               count=1, flags=re.S),
        encoding="utf-8",
    )
    return sitio


def test_arma_los_momentos_con_reloj_falso(armado, tmp_path: Path):  # noqa: F811
    sitio = _sitio_con_semana_cerrada(armado, tmp_path)
    salida = tmp_path / "salida"
    assert _momentos().main(["--sitio", str(sitio), "--salida", str(salida)]) == 0
    hechas = {p.name for p in salida.iterdir()}
    assert {"fase-hoy.html", "fase-domingo-noche.html", "fase-martes.html", "fase-final.html"} <= hechas
    pagina = (salida / "fase-martes.html").read_text(encoding="utf-8")
    # El reloj de mentira corre antes que el portal, y la semana siguiente queda en picks.
    assert pagina.index("window.Date=F") < pagina.index('id="datos"')
    D = datos_embebidos(pagina)
    siguiente = next(s for s in D["semanas"] if s["n"] == D["activa"])
    assert siguiente["estado"] == "pendiente" and siguiente["tandas"]


def test_nunca_escribe_en_docs(armado, tmp_path: Path):  # noqa: F811
    sitio = _sitio_con_semana_cerrada(armado, tmp_path)
    with pytest.raises(SystemExit):
        _momentos().main(["--sitio", str(sitio), "--salida", str(RAIZ / "docs" / "momentos")])
    assert not (RAIZ / "docs" / "momentos").exists()
