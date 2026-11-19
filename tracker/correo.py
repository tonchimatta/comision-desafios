"""Arma y envía el correo con el resumen (HTML + texto plano)."""
from __future__ import annotations

import html
import os
import re
import smtplib
from datetime import date
from email.message import EmailMessage

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_larga(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} {d.year}"


def _md(texto: str) -> str:
    """Markdown mínimo (negritas, cursivas, links, listas) a HTML."""
    t = html.escape(texto)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', t)
    lineas, salida, en_lista = t.split("\n"), [], False
    for l in lineas:
        m = re.match(r"\s*[-•]\s+(.*)", l)
        if m:
            if not en_lista:
                salida.append('<ul style="margin:6px 0 6px 18px;padding:0">')
                en_lista = True
            salida.append(f'<li style="margin:3px 0">{m.group(1)}</li>')
        else:
            if en_lista:
                salida.append("</ul>")
                en_lista = False
            if l.strip():
                salida.append(f'<p style="margin:6px 0">{l}</p>')
    if en_lista:
        salida.append("</ul>")
    return "".join(salida)


def _md_linea(texto: str) -> str:
    """Markdown en línea (sin párrafos), para dentro de un <li>."""
    return re.sub(r"</?p[^>]*>", " ", _md(texto.replace("\n", " "))).strip()


def _hms(s: int) -> str:
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _minuto(videos: list[dict], parte: int, segundo: int) -> str:
    if segundo is None or segundo < 0 or not videos:
        return ""
    v = videos[min(max(parte, 1), len(videos)) - 1]
    etiqueta = _hms(segundo) + (f" (parte {parte})" if len(videos) > 1 else "")
    return f' <a href="https://youtu.be/{v["id"]}?t={segundo}" style="color:#b4232a;text-decoration:none;white-space:nowrap">▶ {etiqueta}</a>'


H2 = 'style="font-size:17px;margin:26px 0 8px;padding-top:14px;border-top:1px solid #e5e5e5"'
H3 = 'style="font-size:15px;margin:18px 0 6px"'


def _bloque_documentos(docs: list[dict]) -> str:
    if not docs:
        return ""
    filas = []
    orden = {"alta": 0, "media": 1, "baja": 2}
    docs = sorted(docs, key=lambda d: (not d.get("relacionado_ia"), orden.get(d.get("relevancia"), 1)))
    for d in docs:
        etiqueta = " 🤖 <strong>IA</strong>" if d.get("relacionado_ia") else ""
        links = []
        if d.get("url_copia"):
            links.append(f'<a href="{d["url_copia"]}">copia guardada</a>')
        if d.get("url_original"):
            links.append(f'<a href="{d["url_original"]}">senado.cl</a>')
        filas.append(
            f'<div style="margin:12px 0;padding:10px 12px;background:#f7f7f8;border-radius:8px">'
            f'<div><strong>📄 {html.escape(d["titulo"])}</strong>{etiqueta}</div>'
            f'<div style="color:#666;font-size:13px">{html.escape(d.get("autor") or "")}'
            f'{" · " + " · ".join(links) if links else ""}</div>'
            f'{_md(d.get("resumen") or "")}</div>'
        )
    return f"<h2 {H2}>Documentos de la sesión</h2>" + "".join(filas)


def html_sesion(s: dict) -> str:
    r, videos = s["resumen"], s.get("videos") or []
    partes = [
        f'<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:680px;margin:auto;color:#1d1d1f;font-size:15px;line-height:1.5">',
        f'<div style="font-size:13px;color:#666">Comisión de Desafíos del Futuro, Ciencia, Tecnología e Innovación · Senado de Chile</div>',
        f'<h1 style="font-size:22px;margin:4px 0 6px">{fecha_larga(s["fecha"])}</h1>',
        f'<div style="font-size:16px;margin-bottom:10px"><strong>{html.escape(r["titular"])}</strong></div>',
    ]
    links = [f'<a href="{v["url"]}">▶ Video{" parte " + str(i) if len(videos) > 1 else ""}</a>' for i, v in enumerate(videos, 1)]
    links.append(f'<a href="{s["ficha"]["url"]}">Ficha oficial</a>')
    dur = s.get("duracion_total_s")
    partes.append(f'<div style="font-size:14px">{" · ".join(links)}{" · " + _hms(dur) if dur else ""}</div>')

    partes.append(f"<h2 {H2}>En 30 segundos</h2>" + _md("\n".join(f"- {x}" for x in r["en_30_segundos"])))

    a = r["asistentes"]
    filas = [(k, v) for k, v in (("Senadores", a["senadores"]), ("Gobierno", a["gobierno"]), ("Invitados", a["invitados"])) if v]
    if filas:
        partes.append(f"<h2 {H2}>Quiénes estuvieron</h2>" + _md("\n".join(f"- **{k}:** {', '.join(v)}" for k, v in filas)))

    for i, p in enumerate(r["puntos"], 1):
        bol = f' <span style="color:#666;font-weight:normal">· Boletín {html.escape(p["boletin"])}</span>' if p["boletin"] else ""
        partes.append(f'<h2 {H2}>{i}. {html.escape(p["titulo"])}{bol}{_minuto(videos, p["parte"], p["segundo"])}</h2>')
        partes.append(_md(p["resumen"]))
        if p["posturas"]:
            partes.append(f"<h3 {H3}>Posturas</h3><ul style='margin:6px 0 6px 18px;padding:0'>")
            for po in p["posturas"]:
                partes.append(f'<li style="margin:4px 0"><strong>{html.escape(po["quien"])}:</strong> {_md_linea(po["postura"])}{_minuto(videos, po["parte"], po["segundo"])}</li>')
            partes.append("</ul>")
        if p["en_que_quedo"]:
            partes.append(f'<h3 {H3}>En qué quedó</h3>' + _md("\n".join(f"- {x}" for x in p["en_que_quedo"])))

    if r["cuenta_y_varios"]:
        partes.append(f"<h2 {H2}>Cuenta y varios</h2><ul style='margin:6px 0 6px 18px;padding:0'>")
        for c in r["cuenta_y_varios"]:
            partes.append(f'<li style="margin:4px 0">{_md_linea(c["texto"])}{_minuto(videos, c["parte"], c["segundo"])}</li>')
        partes.append("</ul>")

    if r["que_viene"]:
        partes.append(f"<h2 {H2}>Qué viene</h2>" + _md("\n".join(f"- {x}" for x in r["que_viene"])))

    partes.append(_bloque_documentos(s.get("documentos") or []))

    if r.get("advertencias"):
        partes.append('<div style="margin-top:22px;font-size:13px;color:#666">⚠️ ' + " ".join(html.escape(x) for x in r["advertencias"]) + "</div>")
    partes.append('<div style="margin-top:26px;font-size:12px;color:#999">Resumen generado automáticamente a partir del video de TV Senado y la ficha oficial de senado.cl. Puede contener errores; verifica en las fuentes.</div></div>')
    return "".join(partes)


def html_documentos_nuevos(s: dict, docs: list[dict]) -> str:
    return (
        f'<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:680px;margin:auto;color:#1d1d1f;font-size:15px;line-height:1.5">'
        f'<div style="font-size:13px;color:#666">Comisión de Desafíos del Futuro · Senado de Chile</div>'
        f'<h1 style="font-size:20px;margin:4px 0 6px">Nuevos documentos · sesión del {fecha_larga(s["fecha"])}</h1>'
        f'<div style="font-size:14px"><a href="{s["ficha"]["url"]}">Ficha oficial</a></div>'
        f"{_bloque_documentos(docs)}</div>"
    )


def texto_plano(html_str: str) -> str:
    t = re.sub(r"<(br|/p|/li|/h1|/h2|/h3|/div)[^>]*>", "\n", html_str)
    t = re.sub(r"<li[^>]*>", "• ", t)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(t)).strip()


def enviar(asunto: str, cuerpo_html: str) -> None:
    usuario = os.environ["GMAIL_USER"]
    destino = os.environ.get("EMAIL_TO") or usuario
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = f"Tracker Comisión Desafíos <{usuario}>"
    msg["To"] = destino
    msg.set_content(texto_plano(cuerpo_html))
    msg.add_alternative(cuerpo_html, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(usuario, os.environ["GMAIL_APP_PASSWORD"])
        smtp.send_message(msg)
