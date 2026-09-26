"""Pruebas del lado del workflow del buzón por enlace.

La función de Supabase se sustituye por una sesión falsa: aquí se prueba qué se
le pide, con qué secreto, y qué se hace con lo que contesta.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import cli
from quiniela import enlace
from quiniela.enlace import ErrorEnlace, bajar, contestar

CARGA = "0123456789abcdef/20260926T031500-00c0ffee"
SECRETO = "secreto-de-prueba"


class _Respuesta:
    def __init__(self, estado: int, cabeceras: dict | None = None, contenido: bytes = b""):
        self.status_code = estado
        self.headers = cabeceras or {}
        self._contenido = contenido

    def iter_content(self, tamano: int):
        for inicio in range(0, len(self._contenido), tamano):
            yield self._contenido[inicio:inicio + tamano]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class _Sesion:
    def __init__(self, respuesta: _Respuesta):
        self.respuesta = respuesta
        self.pedidos: list[tuple[str, dict]] = []

    def get(self, url, **opciones):
        self.pedidos.append(("GET", opciones))
        return self.respuesta

    def post(self, url, **opciones):
        self.pedidos.append(("POST", opciones))
        return self.respuesta


def test_baja_el_archivo_con_el_secreto(tmp_path: Path):
    sesion = _Sesion(_Respuesta(200, {"X-Archivo": "Quiniela_3.xlsx", "X-Cargador": "Organizador%20Uno"}, b"PK\x03\x04"))
    ruta, cargador = bajar(CARGA, tmp_path, secreto=SECRETO, sesion=sesion)
    assert ruta == tmp_path / "Quiniela_3.xlsx" and ruta.read_bytes() == b"PK\x03\x04"
    assert cargador == "Organizador Uno"
    metodo, opciones = sesion.pedidos[0]
    assert metodo == "GET" and opciones["headers"] == {"x-secreto": SECRETO}
    assert opciones["params"] == {"que": "archivo", "carga": CARGA}


def test_el_nombre_que_manda_la_funcion_tampoco_se_sale_de_su_carpeta(tmp_path: Path):
    sesion = _Sesion(_Respuesta(200, {"X-Archivo": "../../.ssh/id.xlsx"}, b"PK"))
    ruta, _ = bajar(CARGA, tmp_path, secreto=SECRETO, sesion=sesion)
    assert ruta.parent == tmp_path and not ruta.name.startswith(".")


@pytest.mark.parametrize("carga", ["", "../../etc", "0123/abc", CARGA + "/x", CARGA.upper()])
def test_una_carga_mal_formada_no_se_pide(tmp_path: Path, carga: str):
    sesion = _Sesion(_Respuesta(200))
    with pytest.raises(ErrorEnlace, match="forma"):
        bajar(carga, tmp_path, secreto=SECRETO, sesion=sesion)
    assert sesion.pedidos == []


def test_sin_secreto_no_se_pide_nada(tmp_path: Path):
    sesion = _Sesion(_Respuesta(200))
    with pytest.raises(ErrorEnlace, match="ANGABAVE_SECRETO"):
        bajar(CARGA, tmp_path, secreto="", sesion=sesion)
    assert sesion.pedidos == []


def test_si_la_funcion_no_da_el_archivo_se_explica(tmp_path: Path):
    with pytest.raises(ErrorEnlace, match="401"):
        bajar(CARGA, tmp_path, secreto=SECRETO, sesion=_Sesion(_Respuesta(401)))


def test_corta_un_archivo_enorme(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(enlace, "TAMANO_MAXIMO", 100)
    with pytest.raises(ErrorEnlace, match="tamaño"):
        bajar(CARGA, tmp_path, secreto=SECRETO, sesion=_Sesion(_Respuesta(200, {}, b"x" * 500)))
    assert list(tmp_path.iterdir()) == []


def test_contesta_con_el_resultado(tmp_path: Path):
    sesion = _Sesion(_Respuesta(200))
    contestar(CARGA, "listo", {"titulo": "Semana 3 cargada"}, secreto=SECRETO, sesion=sesion)
    metodo, opciones = sesion.pedidos[0]
    assert metodo == "POST" and opciones["headers"]["x-secreto"] == SECRETO
    assert json.loads(opciones["data"]) == {"estado": "listo", "resultado": {"titulo": "Semana 3 cargada"}}


def test_solo_hay_tres_estados_posibles():
    with pytest.raises(ErrorEnlace, match="inválido"):
        contestar(CARGA, "aprobado", {}, secreto=SECRETO, sesion=_Sesion(_Respuesta(200)))


# --- el comando que usa el workflow -------------------------------------------------


def _enlace(*argumentos: str) -> int:
    return cli.comando_enlace(cli.construir_parser().parse_args(["enlace", *argumentos]))


def test_el_comando_baja_y_deja_la_ruta_y_el_nombre(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANGABAVE_SECRETO", SECRETO)
    def falso(carga, carpeta, *, secreto):
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "Q.xlsx").write_bytes(b"PK")
        return carpeta / "Q.xlsx", "Organizador"
    monkeypatch.setattr(cli, "bajar_enlace", falso)
    salida, cargador = tmp_path / "archivo.txt", tmp_path / "cargador.txt"
    assert _enlace("bajar", "--carga", CARGA, "--carpeta", str(tmp_path / "e"),
                   "--salida", str(salida), "--cargador", str(cargador)) == 0
    assert Path(salida.read_text()).name == "Q.xlsx" and cargador.read_text() == "Organizador"


def test_el_comando_contesta_falla_sin_confundir_con_un_resumen_viejo(tmp_path: Path, monkeypatch):
    """Si publicar falló después de aceptar, la página no puede decir que quedó."""
    monkeypatch.setenv("ANGABAVE_SECRETO", SECRETO)
    enviados = []
    monkeypatch.setattr(cli, "contestar_enlace",
                        lambda carga, estado, resultado, *, secreto: enviados.append((estado, resultado)))
    resumen = tmp_path / "resumen.json"
    resumen.write_text(json.dumps({"aceptado": True, "titulo": "Semana 3 cargada"}), encoding="utf-8")
    assert _enlace("contestar", "--carga", CARGA, "--estado", "falla", "--resumen", str(resumen),
                   "--nota", "ESPN no respondió") == 0
    estado, resultado = enviados[0]
    assert estado == "falla" and resultado["aceptado"] is False
    assert resultado["error"] == "ESPN no respondió"


def test_el_comando_devuelve_3_si_no_puede_hablar_con_la_funcion(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ANGABAVE_SECRETO", raising=False)
    assert _enlace("contestar", "--carga", CARGA, "--estado", "falla") == 3
