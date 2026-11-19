# Tracker · Comisión de Desafíos del Futuro (Senado de Chile)

Sigue automáticamente las sesiones de la **Comisión de Desafíos del Futuro, Ciencia, Tecnología e Innovación** del Senado de Chile, las resume y guarda todas las fuentes en este repositorio.

Todos los días a las 18:00 (hora de Santiago) un proceso en un Mac:

1. Consulta en **senado.cl** las sesiones de la comisión. De cada una baja la ficha oficial, con los puntos de tabla, los acuerdos y los asistentes, y todos los **documentos presentados**.
2. Busca el video de la sesión en el canal de **TV Senado** en YouTube y baja la transcripción automática.
3. Resume la sesión con Claude (`claude-opus-5-5`), con especial énfasis en la regulación de la inteligencia artificial.
4. Guarda todo en `data/`, lo sube a este repositorio y envía el resumen por correo.

Corre en un Mac y no en GitHub Actions porque senado.cl está detrás de Cloudflare, que bloquea las consultas desde servidores en la nube.

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

Corre con `launchd` (`~/Library/LaunchAgents/com.tonchimatta.comision-desafios.plist`), que lanza `scripts/diario.sh` cada hora. El script trabaja una sola vez al día, a partir de las 18:00. Si el Mac estuvo apagado o dormido, se pone al día al encenderlo. El registro queda en `~/Library/Logs/comision-desafios.log`.

Los secretos se guardan en el Llavero de macOS, con el servicio `comision-desafios`:

```bash
security add-generic-password -s comision-desafios -a ANTHROPIC_API_KEY -w
security add-generic-password -s comision-desafios -a GMAIL_USER -w
security add-generic-password -s comision-desafios -a GMAIL_APP_PASSWORD -w   # https://myaccount.google.com/apppasswords
security add-generic-password -s comision-desafios -a EMAIL_TO -w             # opcional
```

`data/config.json` → `desde`: fecha desde la cual la corrida diaria procesa y envía sesiones.

## Uso manual

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
scripts/diario.sh --sesion 23160            # una sesión puntual (envía correo)
scripts/diario.sh --sesion 23160 --sin-correo
scripts/diario.sh --backfill 2022           # historial desde la legislatura 2022-2023, sin correos
```
