#!/usr/bin/env bash
# Run from the installed project. Credentials are never included in the ZIP.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ $(id -u) == 0 ]]; then engine=(docker); else engine=(sudo docker); fi
umask 077
mkdir -p backups
"${engine[@]}" compose config --quiet
trap '"${engine[@]}" compose start app >/dev/null || true' EXIT
"${engine[@]}" compose stop app
"${engine[@]}" compose run --rm --no-deps --user 0 --cap-add DAC_OVERRIDE \
  --volume "$PWD/backups:/backup" --entrypoint python app \
  backup.py --data /app/data --output /backup
for archive in "$PWD"/backups/lumia-*.zip; do
  [[ -f "$archive" ]] || continue
  if [[ $(id -u) != 0 ]]; then sudo chown "$(id -u):$(id -g)" "$archive"; fi
  chmod 600 "$archive"
done
echo 'Backup completato nella cartella backups. Copiane una copia protetta su un’altra macchina.'
