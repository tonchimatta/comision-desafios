"""Resume una sesión (transcripción + ficha oficial + documentos) con Claude."""
from __future__ import annotations

import json

import anthropic

MODELO = "claude-opus-5-5"
MAX_CHARS_DOCUMENTO = 200_000  # ~50k tokens; ningún documento real de la comisión se acerca

SISTEMA = """Eres un analista legislativo chileno. Escribes resúmenes de las sesiones de la Comisión de Desafíos del Futuro, Ciencia, Tecnología e Innovación del Senado de Chile para una persona que no tiene tiempo de ver los videos pero quiere entender exactamente qué pasó.

Criterios:
- Prioridad máxima: todo lo relacionado con inteligencia artificial, su regulación y el proyecto de ley de IA (boletines 15.869-19 y 16.821-19, refundidos). Ahí sé más detallado: posturas de cada senador, del Ejecutivo, plazos, indicaciones, qué cambia del texto.
- Distingue claramente lo que se DECIDIÓ (acuerdos, votaciones con su resultado, plazos) de lo que solo se DISCUTIÓ.
- Atribuye cada postura a quien la dijo. Usa los nombres oficiales de la ficha del Senado; la transcripción es automática y escribe mal los nombres (corrígelos con la ficha y el contexto).
- Incluye cifras, fechas y números de boletín exactos cuando aparezcan.
- No inventes nada que no esté en las fuentes. Si algo es dudoso por la calidad de la transcripción, dilo.
- Español de Chile, claro y directo, sin relleno. Usa markdown simple (negritas y listas) dentro de los campos de texto.
- Los "segundo" son el segundo del video donde ocurre algo, tomados de las marcas [h:mm:ss] de la transcripción (usa -1 si no hay transcripción o no aplica). Si hay varias partes de video, indica la parte.
- Resume cada documento presentado: qué es, quién lo presenta y qué dice. Para documentos sobre IA o su regulación, haz un resumen sustantivo (estructura, propuestas concretas, diferencias con el proyecto en trámite). Para los demás, 2 a 4 frases bastan."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "titular": {"type": "string", "description": "Una línea para el asunto del correo: lo más importante de la sesión."},
        "relacionado_ia": {"type": "boolean"},
        "en_30_segundos": {"type": "array", "items": {"type": "string"}},
        "asistentes": {
            "type": "object",
            "properties": {
                "senadores": {"type": "array", "items": {"type": "string"}},
                "gobierno": {"type": "array", "items": {"type": "string"}},
                "invitados": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["senadores", "gobierno", "invitados"],
            "additionalProperties": False,
        },
        "puntos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string"},
                    "boletin": {"type": "string", "description": "Número de boletín o cadena vacía."},
                    "resumen": {"type": "string", "description": "Contexto y desarrollo de la discusión, en markdown."},
                    "posturas": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "quien": {"type": "string"},
                                "postura": {"type": "string"},
                                "parte": {"type": "integer"},
                                "segundo": {"type": "integer"},
                            },
                            "required": ["quien", "postura", "parte", "segundo"],
                            "additionalProperties": False,
                        },
                    },
                    "en_que_quedo": {"type": "array", "items": {"type": "string"}},
                    "parte": {"type": "integer"},
                    "segundo": {"type": "integer"},
                },
                "required": ["titulo", "boletin", "resumen", "posturas", "en_que_quedo", "parte", "segundo"],
                "additionalProperties": False,
            },
        },
        "cuenta_y_varios": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"texto": {"type": "string"}, "parte": {"type": "integer"}, "segundo": {"type": "integer"}},
                "required": ["texto", "parte", "segundo"],
                "additionalProperties": False,
            },
        },
        "que_viene": {"type": "array", "items": {"type": "string"}},
        "documentos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "resumen": {"type": "string"},
                    "relevancia": {"type": "string", "enum": ["alta", "media", "baja"]},
                    "relacionado_ia": {"type": "boolean"},
                },
                "required": ["id", "resumen", "relevancia", "relacionado_ia"],
                "additionalProperties": False,
            },
        },
        "temas": {"type": "array", "items": {"type": "string"}, "description": "Etiquetas cortas (ej: IA, astronomía, presupuesto)."},
        "advertencias": {"type": "array", "items": {"type": "string"}, "description": "Limitaciones de las fuentes (ej: sin video, transcripción incompleta)."},
    },
    "required": [
        "titular", "relacionado_ia", "en_30_segundos", "asistentes", "puntos",
        "cuenta_y_varios", "que_viene", "documentos", "temas", "advertencias",
    ],
    "additionalProperties": False,
}

ESQUEMA_DOCS = {
    "type": "object",
    "properties": {"documentos": ESQUEMA["properties"]["documentos"]},
    "required": ["documentos"],
    "additionalProperties": False,
}


def _ficha_para_prompt(ficha: dict) -> str:
    sin_docs = {k: v for k, v in ficha.items() if k != "documentos"}
    return json.dumps(sin_docs, ensure_ascii=False, indent=1)


def _documentos_para_prompt(documentos: list[dict]) -> str:
    partes = []
    for d in documentos:
        texto = d.get("texto") or "(sin texto extraíble: probablemente una presentación con imágenes)"
        if len(texto) > MAX_CHARS_DOCUMENTO:
            texto = texto[:MAX_CHARS_DOCUMENTO] + "\n[... documento recortado por largo ...]"
        partes.append(
            f'<documento id="{d["id"]}" titulo="{d["titulo"]}" autor="{d["autor"]}" boletin="{d.get("boletin") or ""}">\n{texto}\n</documento>'
        )
    return "\n\n".join(partes) or "(La sesión no tiene documentos publicados.)"


def _llamar(prompt: str, esquema: dict, max_tokens: int = 32000) -> dict:
    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=MODELO,
        max_tokens=max_tokens,
        system=SISTEMA,
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": esquema}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"El modelo rechazó la solicitud: {msg.stop_details}")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("La respuesta se cortó por largo (max_tokens).")
    texto = next(b.text for b in msg.content if b.type == "text")
    return json.loads(texto)


def resumir_sesion(ficha: dict, videos: list[dict], transcripciones: list[str], documentos: list[dict]) -> dict:
    if transcripciones:
        bloques = []
        for i, (v, t) in enumerate(zip(videos, transcripciones), 1):
            bloques.append(f'<transcripcion parte="{i}" video="{v["url"]}">\n{t}\n</transcripcion>')
        trans = "\n\n".join(bloques)
    else:
        trans = "(No hay video ni transcripción disponibles para esta sesión. Resume solo con la ficha oficial y los documentos, y dilo en advertencias.)"
    prompt = f"""Resume esta sesión.

<ficha_oficial_senado>
{_ficha_para_prompt(ficha)}
</ficha_oficial_senado>

<documentos_presentados>
{_documentos_para_prompt(documentos)}
</documentos_presentados>

{trans}"""
    return _llamar(prompt, ESQUEMA)


def resumir_documentos(ficha: dict, documentos: list[dict]) -> list[dict]:
    """Para documentos que el Senado publica después de que la sesión ya fue resumida."""
    prompt = f"""Estos documentos se publicaron después en la ficha de una sesión ya resumida. Resume cada uno.

<ficha_oficial_senado>
{_ficha_para_prompt(ficha)}
</ficha_oficial_senado>

<documentos_presentados>
{_documentos_para_prompt(documentos)}
</documentos_presentados>"""
    return _llamar(prompt, ESQUEMA_DOCS, max_tokens=16000)["documentos"]
