"""Fuente oficial: senado.cl (fichas de sesión y documentos presentados)."""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime

import requests

COMISION_ID = 941  # Comisión de Desafíos del Futuro, Ciencia, Tecnología e Innovación
API = "https://web-back.senado.cl/api"
WEB = "https://www.senado.cl/actividad-legislativa/comisiones"
UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "es-CL,es;q=0.9",
}

_session = requests.Session()
_session.headers.update(UA)


def _get(url: str, **kw) -> requests.Response:
    for attempt in range(4):
        try:
            r = _session.get(url, timeout=60, **kw)
            if r.status_code < 500:
                return r
        except requests.RequestException:
            if attempt == 3:
                raise
        time.sleep(2 * (attempt + 1))
    r.raise_for_status()
    return r


def legislaturas() -> list[dict]:
    """Legislaturas (11 de marzo a 10 de marzo), de la más reciente a la más antigua."""
    return _get(f"{API}/legislatures").json()["data"]


def legislaturas_vigentes(hoy: date | None = None) -> list[int]:
    hoy = hoy or date.today()
    ids = []
    for leg in legislaturas():
        inicio = datetime.strptime(leg["INICIO"], "%d/%m/%Y").date()
        termino = datetime.strptime(leg["TERMINO"], "%d/%m/%Y").date()
        # La vigente y, durante las primeras semanas, también la anterior.
        if inicio <= hoy <= termino or 0 <= (hoy - termino).days <= 45:
            ids.append(leg["ID_LEGISLATURA"])
    return ids


def listar_sesiones(id_legislatura: int) -> list[dict]:
    sesiones, offset = [], 0
    while True:
        r = _get(
            f"{API}/commission_sessions",
            params={
                "id_comision": COMISION_ID,
                "id_legislatura": id_legislatura,
                "limit": 50,
                "offset": offset,
                "sort": "fecha",
                "order": "desc",
            },
        ).json()["data"]
        sesiones += r["data"]
        offset += 50
        if offset >= r["total"]:
            return sesiones


def url_sesion(id_sesion: int) -> str:
    return f"{WEB}/{COMISION_ID}/{id_sesion}"


def ficha_sesion(id_sesion: int) -> dict:
    """Detalle completo de una sesión: puntos de tabla, acuerdos, asistentes, documentos."""
    r = _get(url_sesion(id_sesion))
    html = r.text
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError(
            f"No se pudo leer la ficha de la sesión {id_sesion} "
            f"(HTTP {r.status_code}, {len(html)} bytes): {re.sub(r'\s+', ' ', html[:300])}"
        )
    data = json.loads(m.group(1))["props"]["pageProps"]["resource"]["data"]
    d = data["commissionSessionData"]
    if d.get("ID_COMISION") != COMISION_ID:
        raise RuntimeError(f"La sesión {id_sesion} no es de la comisión {COMISION_ID}")

    def limpio(s):
        return (s or "").replace("\r\n", "\n").strip()

    puntos = []
    for p in d.get("PUNTOS") or []:
        puntos.append(
            {
                "numero": p.get("NUMERO_PUNTO"),
                "boletin": p.get("NUMERO_BOLETIN"),
                "tema": limpio(p.get("PUNTO_TABLA")),
                "aspectos_considerados": limpio(p.get("ASPECTOS_CONSIDERADOS")),
                "acuerdos": limpio(p.get("ACUERDOS")),
                "invitados": limpio(p.get("INVITADOS")),
                "otros_asistentes": limpio(p.get("OTROS_ASISTENTES")),
                "link_proyecto": p.get("LINK_PROYECTO_LEY"),
                "senadores": [
                    {"nombre": " ".join(a["PARLAMENTARIO"].split()), "tipo": a.get("TIPO_ASISTENTE"), "nota": a.get("NOTA")}
                    for a in (p.get("ASISTENTES") or []) + (p.get("INTEGRANTES") or [])
                ],
            }
        )
    documentos = [
        {
            "id": str(doc["ID_PRESENTACION"]),
            "titulo": limpio(doc.get("TITULO_PRESENTACION")),
            "autor": limpio(doc.get("AUTOR") or doc.get("ORGANIZACION")),
            "tema": limpio(doc.get("TEMA")),
            "boletin": doc.get("BOLETIN"),
            "url_original": doc.get("LINK_DOCUMENTO"),
        }
        for doc in d.get("PRESENTACIONES") or []
    ]
    return {
        "id": id_sesion,
        "fecha": datetime.strptime(d["FECHA"], "%d/%m/%Y").date().isoformat(),
        "inicio": d.get("INICIO"),
        "termino": d.get("TERMINO"),
        "lugar": d.get("LUGAR"),
        "fracasada": d.get("FRACASADA") == "Sí",
        "url": url_sesion(id_sesion),
        "puntos": puntos,
        "documentos": documentos,
    }


EXT = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}


def descargar_documento(url: str) -> tuple[bytes, str]:
    r = _get(url)
    r.raise_for_status()
    tipo = r.headers.get("content-type", "").split(";")[0].strip()
    contenido = r.content
    if contenido[:4] == b"%PDF":
        tipo = "application/pdf"
    return contenido, EXT.get(tipo, "bin")
