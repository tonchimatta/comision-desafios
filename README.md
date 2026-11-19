# Tracker · Comisión de Desafíos del Futuro (Senado de Chile)

Sigue automáticamente las sesiones de la **Comisión de Desafíos del Futuro, Ciencia, Tecnología e Innovación** del Senado de Chile, las resume y guarda todas las fuentes en este repositorio.

Todos los días a las 18:00 (hora de Santiago) un GitHub Action:

1. Consulta en **senado.cl** las sesiones de la comisión. De cada una baja la ficha oficial, con los puntos de tabla, los acuerdos y los asistentes, y todos los **documentos presentados**.
2. Busca el video de la sesión en el canal de **TV Senado** en YouTube y baja la transcripción automática.
3. Resume la sesión con Claude (`claude-opus-5-5`), con especial énfasis en la regulación de la inteligencia artificial.
4. Guarda todo en `data/` y envía el resumen por correo.

Si el video todavía no está publicado, espera hasta 7 días. Pasado ese plazo, resume solo con la ficha y los documentos. Si el Senado publica documentos nuevos de una sesión ya resumida, los baja, los resume y avisa por correo.

## Datos

| Ruta | Contenido |
|---|---|
| `data/index.json` | Índice de todas las sesiones: fecha, titular, temas y boletines |
| `data/sessions/AAAA-MM-DD_ID.json` | Ficha oficial, videos, documentos y resumen estructurado de cada sesión |
| `data/docs/AAAA-MM-DD_ID/` | Copia de cada documento presentado en la sesión |
| `data/transcripts/` | Transcripción automática de cada video, con marcas de tiempo |

Fuentes: [senado.cl](https://www.senado.cl/actividad-legislativa/comisiones/941) y [TV Senado](https://www.youtube.com/@TVSENADOCHILE). Los resúmenes se generan automáticamente y pueden contener errores; verifica siempre en las fuentes.

## Configuración

Secretos del repositorio (Settings → Secrets and variables → Actions):

| Secreto | Para qué sirve |
|---|---|
| `ANTHROPIC_API_KEY` | Generar los resúmenes |
| `GMAIL_USER` | Cuenta de Gmail que envía el correo |
| `GMAIL_APP_PASSWORD` | [Contraseña de aplicación](https://myaccount.google.com/apppasswords) de esa cuenta |
| `EMAIL_TO` | Destinatario (opcional; por defecto, `GMAIL_USER`) |
| `YT_COOKIES` | Opcional. Cookies de YouTube en formato Netscape, por si YouTube bloquea las descargas desde GitHub |

`data/config.json` → `desde`: fecha desde la cual la corrida diaria procesa y envía sesiones.

## Uso manual

Desde la pestaña **Actions → Tracker diario → Run workflow** se puede:

- procesar una sesión puntual (`sesion`: ID de la sesión en senado.cl), o
- cargar el historial (`backfill`: año, por ejemplo `2022`). El historial no envía correos.

Para correrlo en local:

```bash
pip install -r requirements.txt
python -m tracker.run --sesion 23160 --sin-correo
python -m tracker.run --backfill 2022
```
