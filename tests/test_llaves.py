"""Pruebas de los enlaces personales (herramientas/llaves.py).

Supabase se sustituye por una función que anota lo que se le pediría publicar.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("llaves", RAIZ / "herramientas" / "llaves.py")
llaves = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(llaves)

#: SHA-256 de "abc", el vector de la norma. La función de Supabase prueba el mismo.
VECTOR = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


class _Supabase:
    def __init__(self, falla: bool = False):
        self.publicado: list[tuple[str, str]] = []
        self.falla = falla

    def __call__(self, nombre: str, valor: str) -> None:
        if self.falla:
            raise llaves.ErrorLlaves("Supabase no respondió")
        self.publicado.append((nombre, valor))


def test_la_huella_es_la_misma_que_calcula_la_funcion():
    assert llaves.huella("abc") == VECTOR


def test_una_llave_nueva(tmp_path: Path):
    ruta, supabase = tmp_path / "llaves.json", _Supabase()
    llave = llaves.nueva("Organizador", ruta=ruta, publicar=supabase)

    # La forma que acepta la función: 32 a 64 caracteres seguros para una URL.
    assert re.fullmatch(r"[A-Za-z0-9_-]{32,64}", llave)
    assert llaves.enlace(llave) == f"https://vegeeks.github.io/angabave/cargar.html#k={llave}"

    guardadas = llaves.leer(ruta)
    assert [(l["nombre"], l["huella"]) for l in guardadas] == [("Organizador", llaves.huella(llave))]
    assert llave not in ruta.read_text(encoding="utf-8")   # la llave no se guarda
    nombre, valor = supabase.publicado[-1]
    assert nombre == "ANGABAVE_LLAVES" and json.loads(valor) == {llaves.huella(llave): "Organizador"}


def test_cada_llave_es_distinta(tmp_path: Path):
    ruta, supabase = tmp_path / "llaves.json", _Supabase()
    una = llaves.nueva("Uno", ruta=ruta, publicar=supabase)
    otra = llaves.nueva("Dos", ruta=ruta, publicar=supabase)
    assert una != otra and len(json.loads(supabase.publicado[-1][1])) == 2


@pytest.mark.parametrize("nombre, mensaje", [
    ("organizador", "Ya hay"), ("ORGANIZADÓR", "Ya hay"),
    ("<b>x</b>", "solo puede"), ("A", "2 a 40"), ("x" * 41, "2 a 40"),
])
def test_nombres_que_no_se_aceptan(tmp_path: Path, nombre: str, mensaje: str):
    ruta, supabase = tmp_path / "llaves.json", _Supabase()
    llaves.nueva("Organizador", ruta=ruta, publicar=supabase)
    with pytest.raises(llaves.ErrorLlaves, match=mensaje):
        llaves.nueva(nombre, ruta=ruta, publicar=supabase)


def test_quitar_un_enlace(tmp_path: Path):
    ruta, supabase = tmp_path / "llaves.json", _Supabase()
    llaves.nueva("Uno", ruta=ruta, publicar=supabase)
    dos = llaves.nueva("Dos", ruta=ruta, publicar=supabase)
    llaves.quitar("uno", ruta=ruta, publicar=supabase)
    assert [l["nombre"] for l in llaves.leer(ruta)] == ["Dos"]
    assert json.loads(supabase.publicado[-1][1]) == {llaves.huella(dos): "Dos"}
    with pytest.raises(llaves.ErrorLlaves, match="No hay ningún enlace"):
        llaves.quitar("Tres", ruta=ruta, publicar=supabase)


def test_si_supabase_falla_el_archivo_no_cambia(tmp_path: Path):
    ruta = tmp_path / "llaves.json"
    llaves.nueva("Uno", ruta=ruta, publicar=_Supabase())
    antes = ruta.read_text(encoding="utf-8")
    with pytest.raises(llaves.ErrorLlaves):
        llaves.nueva("Dos", ruta=ruta, publicar=_Supabase(falla=True))
    with pytest.raises(llaves.ErrorLlaves):
        llaves.quitar("Uno", ruta=ruta, publicar=_Supabase(falla=True))
    assert ruta.read_text(encoding="utf-8") == antes


def test_el_archivo_del_repo_solo_tiene_huellas():
    ruta = RAIZ / "data" / "llaves_de_carga.json"
    if not ruta.exists():
        pytest.skip("todavía no hay enlaces")
    for l in llaves.leer(ruta):
        assert set(l) == {"nombre", "huella", "creada"}
        assert re.fullmatch(r"[0-9a-f]{64}", l["huella"])


@pytest.mark.parametrize("codigo, mensaje", [
    (401, "no reconoce"), (404, "Only select"), (403, "Read and write"), (500, "500"),
])
def test_el_token_se_revisa_con_una_escritura_inofensiva(codigo: int, mensaje: str):
    pedidas = []
    def github(metodo, ruta, token):
        pedidas.append((metodo, ruta))
        return codigo
    with pytest.raises(llaves.ErrorLlaves, match=mensaje):
        llaves.revisar_token("github_pat_x", consultar=github)
    assert pedidas == [("PUT", "/repos/Vegeeks/angabave/actions/workflows/cargar.yml/enable")]


def test_un_token_bueno_pasa_y_uno_viejo_ni_se_consulta():
    llaves.revisar_token("github_pat_x", consultar=lambda *a: 204)
    with pytest.raises(llaves.ErrorLlaves, match="github_pat_"):
        llaves.revisar_token("ghp_viejo", consultar=lambda *a: pytest.fail("no debía consultar"))


def test_el_formulario_del_token_viene_prellenado():
    assert "target_name=Vegeeks" in llaves.FORMA_TOKEN and "actions=write" in llaves.FORMA_TOKEN
    assert "expires_in=366" in llaves.FORMA_TOKEN
