"""Orquestador: detecta sesiones nuevas, junta fuentes, resume, guarda y envía correo.

Uso:
  python -m tracker.run                      # corrida diaria (sesiones desde config.desde)
  python -m tracker.run --sesion 23160       # procesa una sesión puntual
  python -m tracker.run --backfill 2022      # historial desde la legislatura que empieza en 2022, sin correo
Opciones: --sin-correo, --sin-resumen (solo baja ficha, documentos y transcripción), --forzar
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
import unicodedata
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import correo, senado, textos, youtube

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
CONFIG = DATA / "config.json"
ESTADO = DATA / "estado.json"
SANTIAGO = ZoneInfo("America/Santiago")
DIAS_ESPERA_VIDEO = 7       # si no aparece el video en 7 días, se resume solo con ficha y documentos
DIAS_VIGILAR_DOCUMENTOS = 45
LIMITE_ARCHIVO = 95 * 1024 * 1024  # GitHub no acepta archivos de más de 100 MB


def leer(p: Path, defecto):
    return json.loads(p.read_text()) if p.exists() else defecto


def escribir(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def slug(s: str, n: int = 60) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:n] or "documento"


def url_repo(ruta: Path) -> str | None:
    repo = os.environ.get("GITHUB_REPOSITORY") or leer(CONFIG, {}).get("repo")
    if not repo:
        return None
    return f"https://github.com/{repo}/blob/main/{ruta.relative_to(RAIZ).as_posix()}"


def ruta_sesion(fecha: str, id_sesion: int) -> Path:
    return DATA / "sessions" / f"{fecha}_{id_sesion}.json"


def bajar_documentos(ficha: dict, ya: dict[str, dict] | None = None) -> list[dict]:
    """Descarga y guarda cada documento nuevo; devuelve sus metadatos (con texto, que no se persiste)."""
    ya = ya or {}
    nuevos = []
    carpeta = DATA / "docs" / f'{ficha["fecha"]}_{ficha["id"]}'
    for d in ficha["documentos"]:
        if d["id"] in ya or not d.get("url_original"):
            continue
        doc = dict(d)
        try:
            contenido, ext = senado.descargar_documento(d["url_original"])
        except Exception as e:
            print(f"  ! no se pudo descargar {d['titulo']}: {e}")
            doc["error"] = str(e)
            nuevos.append(doc)
            continue
        doc["formato"] = ext
        doc["bytes"] = len(contenido)
        doc["paginas"] = textos.paginas_pdf(contenido) if ext == "pdf" else None
        doc["texto"] = textos.extraer_texto(contenido, ext)
        if len(contenido) <= LIMITE_ARCHIVO:
            ruta = carpeta / f'{d["id"]}-{slug(d["titulo"])}.{ext}'
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(contenido)
            doc["archivo"] = ruta.relative_to(RAIZ).as_posix()
            doc["url_copia"] = url_repo(ruta)
        print(f"  documento: {d['titulo']} ({ext}, {len(contenido) // 1024} KB)")
        nuevos.append(doc)
    return nuevos


def guardar_transcripciones(fecha: str, id_sesion: int, videos: list[dict], trans: list[str]) -> None:
    for i, (v, t) in enumerate(zip(videos, trans), 1):
        sufijo = f"_parte{i}" if len(videos) > 1 else ""
        p = DATA / "transcripts" / f"{fecha}_{id_sesion}{sufijo}.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {v['titulo']}\n# {v['url']}\n\n{t}\n")


def fusionar_resumen_docs(docs: list[dict], resumenes: list[dict]) -> None:
    por_id = {r["id"]: r for r in resumenes}
    for d in docs:
        r = por_id.get(d["id"])
        if r:
            d.update(resumen=r["resumen"], relevancia=r["relevancia"], relacionado_ia=r["relacionado_ia"])


def sin_texto(docs: list[dict]) -> list[dict]:
    return [{k: v for k, v in d.items() if k != "texto"} for d in docs]


def procesar_sesion(id_sesion: int, videos_por_fecha: dict, *, resumir: bool, enviar: bool, forzar: bool = False) -> str:
    from . import resumen  # importa anthropic solo si hace falta

    ficha = senado.ficha_sesion(id_sesion)
    fecha = ficha["fecha"]
    ruta = ruta_sesion(fecha, id_sesion)
    previo = leer(ruta, None)
    if previo and previo.get("estado") == "resumida" and not forzar:
        return revisar_documentos_nuevos(previo, ficha, enviar=enviar)

    print(f"Sesión {id_sesion} · {fecha}")
    if ficha["fracasada"]:
        escribir(ruta, {"id": id_sesion, "fecha": fecha, "estado": "fracasada", "ficha": ficha})
        return "fracasada"

    docs = bajar_documentos(ficha)
    videos = videos_por_fecha.get(fecha) or youtube.buscar_por_fecha(fecha)
    dias = (date.today() - date.fromisoformat(fecha)).days
    trans, duracion = [], 0
    for v in videos:
        t = youtube.transcripcion(v["id"])
        if not t:
            trans = []
            break
        trans.append(t["texto"])
        duracion += t.get("duracion_s") or 0
    if trans:
        guardar_transcripciones(fecha, id_sesion, videos, trans)

    registro = {
        "id": id_sesion,
        "fecha": fecha,
        "ficha": ficha,
        "videos": videos,
        "duracion_total_s": duracion or None,
        "documentos": sin_texto(docs),
        "actualizado": datetime.now(SANTIAGO).isoformat(timespec="seconds"),
    }
    if not trans and dias < DIAS_ESPERA_VIDEO and not forzar:
        registro["estado"] = "esperando_video"
        escribir(ruta, registro)
        print(f"  esperando video/subtítulos ({dias} días desde la sesión)")
        return "esperando_video"
    if not resumir:
        registro["estado"] = "sin_resumen"
        escribir(ruta, registro)
        return "sin_resumen"

    r = resumen.resumir_sesion(ficha, videos if trans else [], trans, docs)
    fusionar_resumen_docs(docs, r.pop("documentos"))
    registro.update(resumen=r, documentos=sin_texto(docs), estado="resumida", modelo=resumen.MODELO)
    escribir(ruta, registro)
    print(f"  resumida: {r['titular']}")
    if enviar:
        asunto = f"🏛️ Comisión Desafíos del Futuro · {correo.fecha_larga(fecha)} · {r['titular']}"
        correo.enviar(asunto, correo.html_sesion(registro))
        registro["correo_enviado"] = datetime.now(SANTIAGO).isoformat(timespec="seconds")
        escribir(ruta, registro)
        print("  correo enviado")
    return "resumida"


def revisar_documentos_nuevos(registro: dict, ficha: dict, *, enviar: bool) -> str:
    from . import resumen

    if (date.today() - date.fromisoformat(registro["fecha"])).days > DIAS_VIGILAR_DOCUMENTOS:
        return "sin_cambios"
    ya = {d["id"]: d for d in registro.get("documentos", [])}
    nuevos = bajar_documentos(ficha, ya)
    if not nuevos:
        return "sin_cambios"
    print(f"Sesión {registro['id']} · {len(nuevos)} documento(s) nuevo(s)")
    fusionar_resumen_docs(nuevos, resumen.resumir_documentos(ficha, nuevos))
    registro["ficha"] = ficha
    registro["documentos"] = registro.get("documentos", []) + sin_texto(nuevos)
    registro["actualizado"] = datetime.now(SANTIAGO).isoformat(timespec="seconds")
    escribir(ruta_sesion(registro["fecha"], registro["id"]), registro)
    if enviar:
        correo.enviar(
            f"📄 Comisión Desafíos del Futuro · nuevos documentos · sesión del {correo.fecha_larga(registro['fecha'])}",
            correo.html_documentos_nuevos(registro, sin_texto(nuevos)),
        )
    return "documentos_nuevos"


def reconstruir_indice() -> None:
    sesiones = []
    for p in sorted((DATA / "sessions").glob("*.json"), reverse=True):
        s = leer(p, {})
        r = s.get("resumen") or {}
        sesiones.append(
            {
                "id": s["id"],
                "fecha": s["fecha"],
                "estado": s.get("estado"),
                "titular": r.get("titular"),
                "temas": r.get("temas", []),
                "relacionado_ia": r.get("relacionado_ia"),
                "boletines": sorted({pt["boletin"] for pt in s.get("ficha", {}).get("puntos", []) if pt.get("boletin")}),
                "puntos": [pt["tema"] for pt in s.get("ficha", {}).get("puntos", [])],
                "documentos": len(s.get("documentos", [])),
                "videos": [v["url"] for v in s.get("videos") or []],
                "archivo": p.relative_to(RAIZ).as_posix(),
            }
        )
    escribir(DATA / "index.json", {"actualizado": datetime.now(SANTIAGO).isoformat(timespec="seconds"), "sesiones": sesiones})


def toca_correr_hoy(estado: dict) -> bool:
    """launchd lo lanza cada hora; solo corre una vez al día (con éxito), a partir de las 18:00 de Santiago."""
    ahora = datetime.now(SANTIAGO)
    return ahora.hour >= 18 and estado.get("ultima_corrida") != ahora.date().isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sesion", type=int)
    ap.add_argument("--backfill", type=int, help="año de inicio de la legislatura más antigua a cargar")
    ap.add_argument("--sin-correo", action="store_true")
    ap.add_argument("--sin-resumen", action="store_true")
    ap.add_argument("--forzar", action="store_true", help="reprocesa aunque ya esté resumida")
    ap.add_argument("--diario", action="store_true", help="corrida programada: solo una vez al día, desde las 18:00")
    args = ap.parse_args()

    config, estado = leer(CONFIG, {}), leer(ESTADO, {})
    programada = args.diario
    if programada and not toca_correr_hoy(estado):
        print("Fuera de horario o ya corrió hoy.")
        return 0

    try:
        videos = youtube.videos_de_la_comision(profundidad=600 if args.backfill else 300)
    except youtube.YouTubeBloqueado as e:
        print(f"! YouTube bloqueó la consulta: {e}")
        videos = {}
    print(f"Videos de la comisión encontrados: {len(videos)} fechas")

    if args.sesion:
        objetivos = [args.sesion]
    elif args.backfill:
        objetivos = []
        for leg in senado.legislaturas():
            if int(leg["INICIO"][-4:]) >= args.backfill:
                objetivos += [s["ID_SESION"] for s in senado.listar_sesiones(leg["ID_LEGISLATURA"])]
    else:
        desde = config.get("desde", "2000-01-01")
        objetivos = []
        for leg in senado.legislaturas_vigentes():
            for s in senado.listar_sesiones(leg):
                f = datetime.strptime(s["FECHA"], "%d/%m/%Y").date().isoformat()
                if f >= desde:
                    objetivos.append(s["ID_SESION"])

    enviar = not (args.sin_correo or args.backfill) and bool(os.environ.get("GMAIL_APP_PASSWORD"))
    errores = 0
    for id_sesion in sorted(set(objetivos)):
        try:
            resultado = procesar_sesion(
                id_sesion, videos, resumir=not args.sin_resumen, enviar=enviar, forzar=args.forzar
            )
            if resultado != "sin_cambios":
                print(f"  → {resultado}")
        except youtube.YouTubeBloqueado as e:
            print(f"! YouTube bloqueó la descarga de subtítulos: {e}")
            errores += 1
            break
        except Exception:
            errores += 1
            print(f"! Error en la sesión {id_sesion}:")
            traceback.print_exc()

    reconstruir_indice()
    if programada and not errores:  # si algo falló, se reintenta en la próxima hora
        estado["ultima_corrida"] = datetime.now(SANTIAGO).date().isoformat()
        escribir(ESTADO, estado)
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
