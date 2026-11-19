#!/bin/zsh
# Corrida diaria en el Mac. launchd la lanza cada hora; el tracker solo trabaja
# una vez al día (con éxito) a partir de las 18:00 de Santiago.
# Uso manual: scripts/diario.sh [argumentos de tracker.run]   (sin argumentos = --diario)
set -u
REPO="${0:A:h:h}"
cd "$REPO" || exit 1

# Corrida automática: antes de las 18:00 o si ya corrió hoy, no hace nada.
if [ $# -eq 0 ]; then
  [ "$(TZ=America/Santiago date +%H)" -lt 18 ] && exit 0
  grep -q "\"ultima_corrida\": \"$(TZ=America/Santiago date +%F)\"" data/estado.json 2>/dev/null && exit 0
fi
export PATH="$REPO/.venv/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

# Secretos desde el Llavero de macOS (servicio "comision-desafios").
secreto() { security find-generic-password -s comision-desafios -a "$1" -w 2>/dev/null; }
export ANTHROPIC_API_KEY="$(secreto ANTHROPIC_API_KEY)"
export GMAIL_USER="$(secreto GMAIL_USER)"
export GMAIL_APP_PASSWORD="$(secreto GMAIL_APP_PASSWORD)"
export EMAIL_TO="$(secreto EMAIL_TO)"

avisar() { osascript -e "display notification \"$1\" with title \"Tracker Comisión Desafíos\"" 2>/dev/null; }

# Sin internet (por ejemplo, recién despertando): salir sin marcar el día como hecho.
if ! curl -s --max-time 10 -o /dev/null https://www.youtube.com; then
  echo "$(date '+%F %T') sin conexión, se reintenta en la próxima hora"
  exit 0
fi

git pull -q --rebase --autostash || avisar "No se pudo actualizar el repo (git pull)."

[ $# -eq 0 ] && set -- --diario
echo "=== $(date '+%F %T') tracker.run $*"
python -m tracker.run "$@"
codigo=$?

git add data
if ! git diff --cached --quiet; then
  git commit -q -m "Datos: $(date +%F)" && git push -q || avisar "No se pudieron subir los datos a GitHub."
fi

[ $codigo -ne 0 ] && avisar "Hubo un error. Revisa ~/Library/Logs/comision-desafios.log"
exit $codigo
