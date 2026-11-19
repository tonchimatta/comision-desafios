"""Extrae texto de los documentos (PDF, PPTX, DOCX) para resumirlos."""
from __future__ import annotations

import io
import zipfile


def extraer_texto(contenido: bytes, ext: str) -> str:
    try:
        if ext == "pdf":
            from pypdf import PdfReader

            r = PdfReader(io.BytesIO(contenido))
            return "\n".join((p.extract_text() or "") for p in r.pages).strip()
        if ext == "pptx":
            from pptx import Presentation

            prs = Presentation(io.BytesIO(contenido))
            partes = []
            for i, slide in enumerate(prs.slides, 1):
                textos = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
                if textos:
                    partes.append(f"[Diapositiva {i}]\n" + "\n".join(textos))
            return "\n\n".join(partes)
        if ext == "docx":
            from docx import Document

            return "\n".join(p.text for p in Document(io.BytesIO(contenido)).paragraphs).strip()
        if ext == "bin" and zipfile.is_zipfile(io.BytesIO(contenido)):
            return ""
    except Exception as e:  # documento dañado o protegido
        return f"(No se pudo extraer el texto: {e})"
    return ""


def paginas_pdf(contenido: bytes) -> int | None:
    try:
        from pypdf import PdfReader

        return len(PdfReader(io.BytesIO(contenido)).pages)
    except Exception:
        return None
