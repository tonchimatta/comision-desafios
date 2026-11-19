"""Videos de TV Senado (YouTube) y sus subtítulos automáticos."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import unicodedata
from pathlib import Path

CANAL = "https://www.youtube.com/@TVSENADOCHILE"
MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def _ytdlp(*args: str, timeout: int = 900) -> subprocess.CompletedProcess:
    cmd = ["yt-dlp", "--extractor-args", "youtube:lang=es", "--no-warnings", *args]
    cookies = os.environ.get("YT_COOKIES_FILE")
    if cookies and Path(cookies).exists():
        cmd[1:1] = ["--cookies", cookies]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def es_de_la_comision(titulo: str) -> bool:
    t = _sin_tildes(titulo)
    return "comision" in t and "desafios del futuro" in t


def fecha_del_titulo(titulo: str) -> str | None:
    m = re.search(r"(\d{1,2})\s+de\s+([a-z]+)\s+(?:de\s+|del\s+)?(\d{4})", _sin_tildes(titulo))
    if not m or m.group(2) not in MESES:
        return None
    return f"{int(m.group(3)):04d}-{MESES[m.group(2)]:02d}-{int(m.group(1)):02d}"


def parte_del_titulo(titulo: str) -> int:
    m = re.search(r"\[(\d+)\s*/\s*\d+\]", titulo)
    return int(m.group(1)) if m else 1


def _listar(url: str, cuantos: int) -> list[dict]:
    r = _ytdlp("--flat-playlist", "--playlist-end", str(cuantos), "--print", "%(id)s\t%(title)s", url)
    videos = []
    for linea in r.stdout.splitlines():
        if "\t" in linea:
            vid, titulo = linea.split("\t", 1)
            videos.append({"id": vid, "titulo": titulo})
    return videos


def buscar_por_fecha(fecha_iso: str) -> list[dict]:
    """Búsqueda dirigida en el canal para una fecha puntual (respaldo cuando el listado no la trae)."""
    a, m, d = (int(x) for x in fecha_iso.split("-"))
    mes = next(k for k, v in MESES.items() if v == m and k != "setiembre")
    encontrados = []
    for q in (f"Desafíos del Futuro {d} de {mes} {a}", f"Desafíos del Futuro {d:02d} de {mes} {a}"):
        url = f"{CANAL}/search?query=" + requests_quote(q)
        for v in _listar(url, 15):
            if es_de_la_comision(v["titulo"]) and fecha_del_titulo(v["titulo"]) == fecha_iso:
                if v["id"] not in {e["id"] for e in encontrados}:
                    v["parte"] = parte_del_titulo(v["titulo"])
                    v["url"] = f"https://www.youtube.com/watch?v={v['id']}"
                    encontrados.append(v)
        if encontrados:
            break
    return sorted(encontrados, key=lambda v: v["parte"])


def requests_quote(s: str) -> str:
    from urllib.parse import quote

    return quote(s)


def videos_de_la_comision(profundidad: int = 300) -> dict[str, list[dict]]:
    """Devuelve {fecha ISO: [videos ordenados por parte]} buscando en subidas, directos y búsqueda."""
    fuentes = [
        f"{CANAL}/videos",
        f"{CANAL}/streams",
        f"{CANAL}/search?query=Comisi%C3%B3n%20Desaf%C3%ADos%20del%20Futuro",
    ]
    vistos, por_fecha = set(), {}
    for url in fuentes:
        for v in _listar(url, profundidad):
            if v["id"] in vistos or not es_de_la_comision(v["titulo"]):
                continue
            vistos.add(v["id"])
            fecha = fecha_del_titulo(v["titulo"])
            if fecha:
                v["parte"] = parte_del_titulo(v["titulo"])
                v["url"] = f"https://www.youtube.com/watch?v={v['id']}"
                por_fecha.setdefault(fecha, []).append(v)
    for lista in por_fecha.values():
        lista.sort(key=lambda v: v["parte"])
    return por_fecha


def _hms(segundos: int) -> str:
    return f"{segundos // 3600}:{segundos % 3600 // 60:02d}:{segundos % 60:02d}"


def transcripcion(video_id: str) -> dict | None:
    """Subtítulos en español con marcas de tiempo cada ~30 s. None si aún no existen."""
    eventos, r = None, None
    for intento in range(4):
        with tempfile.TemporaryDirectory() as tmp:
            r = _ytdlp(
                "--skip-download", "--write-auto-subs", "--write-subs",
                "--sub-langs", "es-orig,es-419,es" if intento % 2 else "es-orig,es-419",
                "--sub-format", "json3", "--sleep-subtitles", "3",
                "--print", "%(duration)s", "--no-simulate",
                "-o", f"{tmp}/%(id)s.%(ext)s",
                f"https://www.youtube.com/watch?v={video_id}",
            )
            archivos = sorted(Path(tmp).glob("*.json3"), key=lambda p: ("orig" not in p.name, p.name))
            if archivos:
                eventos = json.loads(archivos[0].read_text()).get("events", [])
                break
        if "429" not in (r.stderr or ""):
            break
        time.sleep(60 * (intento + 1))
    if eventos is None:
        raise_si_bloqueado(r)
        return None
    lineas, inicio, buf = [], None, []
    for e in eventos:
        if "segs" not in e:
            continue
        texto = "".join(s.get("utf8", "") for s in e["segs"]).replace("\n", " ").strip()
        if not texto:
            continue
        t = e["tStartMs"] // 1000
        if inicio is None or t - inicio >= 30:
            if buf:
                lineas.append(f"[{_hms(inicio)}] " + " ".join(buf))
            inicio, buf = t, []
        buf.append(texto)
    if buf:
        lineas.append(f"[{_hms(inicio)}] " + " ".join(buf))
    if not lineas:
        return None
    duracion = next((int(float(x)) for x in r.stdout.split() if x.replace(".", "").isdigit()), None)
    return {"texto": "\n".join(lineas), "duracion_s": duracion}


class YouTubeBloqueado(RuntimeError):
    pass


def raise_si_bloqueado(r: subprocess.CompletedProcess) -> None:
    err = r.stderr or ""
    if "Sign in to confirm" in err or "not a bot" in err or "HTTP Error 429" in err or "page needs to be reloaded" in err:
        raise YouTubeBloqueado(err.strip().splitlines()[-1])
