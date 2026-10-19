#!/usr/bin/env bash
# Executed from a temporary copy: a Git update must not replace a running script.
set -Eeuo pipefail
umask 077
target=${1:-/home/scooty/lumia-manager}
[[ -d "$target" ]] || { echo 'Cartella di produzione assente.' >&2; exit 1; }
cd -- "$target"
target=$(pwd -P)
for command in git docker python3 flock; do command -v "$command" >/dev/null || { echo "Manca $command." >&2; exit 1; }; done
git_root=$(git rev-parse --show-toplevel)
[[ $(cd -- "$git_root" && pwd -P) == "$target" ]] || { echo 'Il progetto deve essere la radice del repository Git.' >&2; exit 1; }
[[ $(git branch --show-current) == main ]] || { echo 'La produzione deve trovarsi sul branch main.' >&2; exit 1; }
python3 scripts/deploy_checks.py worktree
for file in .env config.json compose.yaml server_texts.json; do
  [[ -f "$file" ]] || { echo "Manca $file nella produzione." >&2; exit 1; }
done
docker info >/dev/null
docker compose config --quiet
mkdir -p backups
exec 9>backups/.deploy.lock
flock -n 9 || { echo 'Un altro deploy è già in corso.' >&2; exit 1; }

old_sha=$(git rev-parse HEAD)
changed=0
stopped=0
finished=0
snapshot=''
askpass=''
old_image=''
image_tag=''
rollback_tag=''

recover() {
  code=$?
  trap - EXIT INT TERM
  if [[ $finished == 0 && $changed == 1 ]]; then
    echo 'Deploy fallito: tento il ripristino della versione precedente.' >&2
    git reset --keep "$old_sha" || echo 'Ripristino dei sorgenti non riuscito: controlla la VPS.' >&2
    [[ -z "$old_image" || -z "$image_tag" ]] || docker tag "$old_image" "$image_tag" || true
    if [[ $stopped == 1 ]]; then
      docker compose stop app >/dev/null 2>&1 || true
      docker compose up -d --no-deps --no-build app || true
    fi
    echo "Backup: $snapshot" >&2
    echo 'Il database non è stato ripristinato: i pagamenti registrati restano conservati.' >&2
  fi
  [[ -z "$askpass" ]] || rm -f -- "$askpass"
  if [[ -n ${GITHUB_STEP_SUMMARY:-} && $code != 0 ]]; then
    printf 'Deploy non riuscito. Controlla i log del job e della VPS.\n' >> "$GITHUB_STEP_SUMMARY"
  fi
  exit "$code"
}
trap recover EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ -n ${GITHUB_REPOSITORY:-} ]]; then
  origin=$(git remote get-url origin)
  expected="${GITHUB_SERVER_URL:-https://github.com}/$GITHUB_REPOSITORY"
  origin=${origin%.git}
  [[ ${origin,,} == ${expected,,} ]] || { echo 'origin non corrisponde al repository di questo workflow HTTPS.' >&2; exit 1; }
fi
if [[ -n ${GH_TOKEN:-} ]]; then
  askpass=$(mktemp "${RUNNER_TEMP:-/tmp}/lumia-askpass.XXXXXX")
  cat > "$askpass" <<'SH'
#!/usr/bin/env sh
case "$1" in
  *Username*|*username*) printf '%s\n' x-access-token ;;
  *Password*|*password*) printf '%s\n' "$GH_TOKEN" ;;
  *) exit 1 ;;
esac
SH
  chmod 700 "$askpass"
  export GIT_ASKPASS="$askpass"
  git -c credential.helper= fetch --no-tags origin refs/heads/main:refs/remotes/origin/main
else
  git fetch --no-tags origin refs/heads/main:refs/remotes/origin/main
fi
next_sha=$(git rev-parse refs/remotes/origin/main)
if [[ -n ${GITHUB_SHA:-} && "$GITHUB_SHA" != "$next_sha" ]]; then
  echo 'Push superato da un commit più recente: questo job non modifica la produzione.'
  finished=1
  exit 0
fi
git merge-base --is-ancestor "$old_sha" "$next_sha" || { echo 'La produzione e main sono divergenti. Nessun reset automatico.' >&2; exit 1; }
python3 scripts/deploy_checks.py guard "$old_sha" "$next_sha"
container=$(docker compose ps -q app)
[[ -n "$container" && "$container" != *$'\n'* ]] || { echo 'Atteso un solo container app già in esecuzione.' >&2; exit 1; }
old_image=$(docker inspect --format '{{.Image}}' "$container")
image_tag=$(docker inspect --format '{{.Config.Image}}' "$container")
[[ "$image_tag" != *@* && "$image_tag" != sha256:* ]] || { echo 'Configura app con un tag di immagine locale ricostruibile.' >&2; exit 1; }
docker inspect --format '{{json .Mounts}}' "$container" | python3 -c '
import json,sys
for mount in json.load(sys.stdin):
    destination=mount.get("Destination", "")
    if destination in ("/app", "/app/lumia", "/app/bot.py", "/app/launch.py"):
        raise SystemExit("Il codice è montato in diretta nel container: usa il Compose standard prima del deploy.")
'

snapshot="$target/backups/deploy-$(date +%Y%m%d-%H%M%S)-$$"
mkdir -p "$snapshot"
printf '%s\n' "$old_sha" > "$snapshot/commit-prima.txt"
printf '%s\n' "$next_sha" > "$snapshot/commit-nuovo.txt"
printf '%s\n' "$old_image" > "$snapshot/immagine-prima.txt"
rollback_tag="lumia-rollback:$(date +%Y%m%d%H%M%S)-$$"
docker tag "$old_image" "$rollback_tag"
printf '%s\n' "$rollback_tag" > "$snapshot/tag-ripristino.txt"

changed=1
git merge --ff-only "$next_sha"
docker compose config --quiet
echo 'Costruzione della nuova immagine; il servizio attuale resta in esecuzione.'
docker compose build app
new_image=$(docker image inspect --format '{{.Id}}' "$image_tag")
echo 'Test della nuova immagine senza accesso ai dati di produzione.'
docker run --rm --network none --entrypoint python "$new_image" -m unittest discover -s tests
echo 'Backup prima del riavvio.'
stopped=1
docker compose stop app
# Use the OLD image and its data mounts for a backup independent of the new code.
docker run --rm --network none --user 0 --cap-drop ALL --cap-add DAC_OVERRIDE --cap-add CHOWN \
  --security-opt no-new-privileges:true --volumes-from "$container" \
  --volume "$snapshot:/backup" --env "LUMIA_BACKUP_UID=$(id -u)" --env "LUMIA_BACKUP_GID=$(id -g)" \
  --entrypoint python "$old_image" -c '
import os,runpy,sys
from pathlib import Path
os.umask(0o077)
sys.argv=["backup.py","--data","/app/data","--output","/backup"]
runpy.run_path("/app/backup.py",run_name="__main__")
for file in Path("/backup").glob("lumia-*.zip"):
    file.chmod(0o600)
    os.chown(file,int(os.environ["LUMIA_BACKUP_UID"]),int(os.environ["LUMIA_BACKUP_GID"]))
'
python3 scripts/deploy_checks.py backup "$snapshot"
docker compose up -d --no-deps --no-build app
healthy=0
for attempt in $(seq 1 40); do
  if docker compose exec -T app python scripts/deploy_checks.py health >/dev/null 2>&1; then
    healthy=$((healthy+1))
    [[ $healthy -ge 3 ]] && break
  else
    healthy=0
  fi
  sleep 2
done
[[ $healthy -ge 3 ]] || { echo 'La nuova app non supera i controlli HTTP.' >&2; exit 1; }
[[ $(docker inspect --format '{{.Image}}' "$(docker compose ps -q app)") == "$new_image" ]] || { echo 'Il container non usa la nuova immagine.' >&2; exit 1; }
finished=1
printf 'Deploy completato: %s\nBackup: %s\n' "$next_sha" "$snapshot"
if [[ -n ${GITHUB_STEP_SUMMARY:-} ]]; then
  printf 'Deploy completato: `%s`. Backup e immagine precedente conservati sulla VPS.\n' "$next_sha" >> "$GITHUB_STEP_SUMMARY"
fi
