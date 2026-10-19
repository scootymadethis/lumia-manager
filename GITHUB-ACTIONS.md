# Deploy automatico Lumia con GitHub Actions

Configurazione del 19 ottobre 2026 per la VPS Ubuntu e il repository privato già creato.

Un runner sulla VPS riceve i job da GitHub con una connessione HTTPS in uscita: funziona anche con IP dinamico, senza aprire una porta SSH per GitHub. Cloudflare Tunnel continua a gestire i domini come prima. [Requisiti di rete GitHub](https://docs.github.com/en/actions/reference/runners/self-hosted-runners#communication).

## Cosa succede a ogni push

Il workflow `.github/workflows/deploy.yml` parte quando un commit viene **caricato su `main`**. Un commit rimasto solo sul PC non attiva GitHub Actions. Puoi anche avviarlo manualmente da Actions → Deploy Lumia sulla VPS → Run workflow, selezionando `main`.

Il job:

1. Blocca i deploy concorrenti e controlla repository, branch e modifiche locali.
2. Scarica `main` con il token temporaneo del job, senza stampare o salvare il token nel repository.
3. Aggiorna i sorgenti solo con un avanzamento Git lineare. Non cancella il lavoro locale.
4. Costruisce la nuova immagine mentre l'app precedente resta in servizio.
5. Esegue i test nella nuova immagine, senza rete e senza montare i dati reali.
6. Ferma `app`, crea e verifica il backup SQLite con la vecchia immagine, poi avvia quella nuova.
7. Controlla landing e login nel container e verifica l'ID dell'immagine avviata.

Se un passaggio fallisce dopo l'aggiornamento dei sorgenti, tenta di ripristinare commit e tag dell'immagine precedente e riavviare `app`. Non ripristina automaticamente il database: gli eventuali pagamenti già registrati restano conservati. Il job resta fallito anche quando il ripristino riesce, così puoi vedere il problema.

Il backup e il riavvio comportano un fermo dell'app. La build e i test vengono completati prima del fermo. `cloudflared`, Ollama e gli altri servizi non vengono riavviati dal job.

`.env`, `config.json`, dati e backup restano sulla VPS. Compose, Caddyfile e `server_texts.json` possono conservare le personalizzazioni locali: il deploy si ferma se un nuovo commit cerca di cambiarli. Per modificare queste configurazioni applica consapevolmente il cambiamento sulla VPS prima di riprendere i deploy. Se hai modifiche locali al codice o file in staging, completa prima il relativo commit.

## 1. Installa i file nella cartella già collegata a GitHub

La guida assume il percorso `/home/scooty/lumia-manager`, branch `main`, remote HTTPS `origin` e utente Linux `scooty`, come nei passaggi precedenti. Non creare un secondo clone nella cartella dell'app.

Da PowerShell sul PC, sostituisci `IP_DELLA_VPS`:

```powershell
scp "C:\Users\scooty\Downloads\Lumia Development\outputs\lumia-github-actions-2026-10-19.zip" scooty@IP_DELLA_VPS:~/
```

Sul terminale Ubuntu:

```bash
sudo apt update
sudo apt install -y git python3 unzip curl ca-certificates util-linux
cd ~/lumia-manager
unzip -o ~/lumia-github-actions-2026-10-19.zip -d ~/lumia-manager
git branch --show-current
git remote -v
git status --short
```

Il pacchetto aggiunge soltanto workflow, script, test del deploy, `.gitattributes` e questa guida. Non contiene configurazione o dati privati e non cambia il codice del sito o del bot.

I due controlli devono mostrare `main` e il tuo repository `https://github.com/.../lumia-manager.git`. Non pubblicare l'output se hai inserito credenziali nell'URL. I comandi suggeriti in precedenza da GitHub CLI usano un URL senza token.

## 2. Dai al servizio runner l'accesso a Docker

```bash
sudo usermod -aG docker scooty
sudo -u scooty -H docker info --format '{{.ServerVersion}}'
```

L'ultimo comando deve stampare una versione, senza chiedere la password Docker. Il gruppo `docker` consente di amministrare il sistema tramite i container: usa questo runner soltanto nel tuo repository **privato** e limita a persone fidate chi può modificarne codice e workflow. Il workflow fornito non viene avviato dalle pull request. [Privilegi del gruppo Docker](https://docs.docker.com/engine/install/linux-postinstall/), [runner per repository privati](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners).

Non aggiungere regole `NOPASSWD: ALL` a sudo: il job non usa sudo.

## 3. Registra il runner nel repository GitHub

Sul sito GitHub apri il repository → **Settings → Actions → Runners → New self-hosted runner**. Seleziona **Linux** e l'architettura della VPS. Per controllarla:

```bash
uname -m
```

`x86_64` corrisponde a **x64**; `aarch64` a **ARM64**.

Sulla VPS crea una cartella separata dal progetto:

```bash
mkdir -p ~/actions-runner
cd ~/actions-runner
```

Dalla sezione **Download** mostrata da GitHub copia i comandi di download, verifica checksum ed estrazione. Eseguili qui. Se il primo comando di GitHub crea e apre `actions-runner`, saltalo: sei già nella cartella giusta. In questo modo scarichi la versione e il checksum correnti indicati da GitHub.

Poi esegui la riga **Configure** generata da GitHub, aggiungendo in fondo:

```text
--name lumia-prod --labels lumia-prod
```

La forma completa sarà questa, ma usa URL e token effettivamente mostrati dal tuo repository:

```bash
./config.sh --url https://github.com/TUO_USERNAME/lumia-manager --token TOKEN_MOSTRATO_DA_GITHUB --name lumia-prod --labels lumia-prod
```

Non inviare il token in chat e non salvarlo nel repository. È un token di registrazione temporaneo, non il token del bot Discord. Se accetti i valori predefiniti, il runner userà la cartella di lavoro `_work`. [Procedura ufficiale](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners).

Non avviare `./run.sh`: useremo il servizio, che resta attivo dopo la chiusura SSH e al riavvio della VPS.

```bash
sudo ./svc.sh install scooty
sudo ./svc.sh start
sudo ./svc.sh status
```

Su GitHub il runner deve risultare **Idle/Online**, con etichetta **lumia-prod**. [Gestione del servizio runner](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/configure-the-application).

## 4. Pubblica il workflow e fai partire il primo deploy

Se hai usato GitHub CLI per accedere tramite HTTPS, abilita anche lo scope necessario a caricare i workflow:

```bash
gh auth refresh --hostname github.com --scopes workflow
```

Completa l'autorizzazione dal browser del PC usando il link e il codice mostrati. Poi:

[Documentazione GitHub CLI sugli scope](https://cli.github.com/manual/gh_auth_refresh).

```bash
cd ~/lumia-manager
git add .github/workflows/deploy.yml .gitattributes scripts/deploy.sh scripts/deploy_checks.py tests/test_deploy_checks.py GITHUB-ACTIONS.md
git commit -m "Aggiungi deploy automatico sulla VPS"
git push origin main
```

Se avevi altre modifiche locali al codice, completa anche quei commit prima del push. GitHub Actions richiede che la produzione non contenga codice non committato.

Nel repository apri **Actions → Deploy Lumia sulla VPS**. Il primo job dovrebbe partire sul runner. Non devi aggiungere token Discord, Stripe o Cloudflare nei Secrets di Actions: rimangono nel `.env` sulla VPS. Il workflow usa `github.token` con il solo permesso `contents: read` per scaricare quel repository.

## 5. Aggiornamenti successivi

Modifica il codice dal PC, da un altro clone o dall'editor GitHub e caricalo su `main`:

```bash
git add .
git commit -m "Descrizione della modifica"
git push origin main
```

Il runner scaricherà l'aggiornamento e riavvierà l'app dopo test e backup. Non devi fare un altro `git pull` a mano sulla VPS. Se prepari un commit dalla VPS stessa, quel commit deve essere stato caricato su `main` prima di avviare il deploy.

Se fai più push durante un deploy, il job già avviato non viene cancellato; i push superati da un commit più recente vengono saltati a favore dell'ultimo aggiornamento. Non è garantito un riavvio separato per ogni commit intermedio. [Concorrenza dei workflow](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#concurrency).

## 6. Se il percorso del progetto è diverso

Nel repository GitHub → Settings → Secrets and variables → Actions → **Variables**, crea:

```text
LUMIA_DEPLOY_DIR=/percorso/assoluto/del/tuo/progetto
```

Non è un segreto. Il servizio runner deve girare con l'utente Linux proprietario di quel progetto e con accesso a Docker. Il valore predefinito è `/home/scooty/lumia-manager`.

## 7. Diagnostica e ripristino

Runner in attesa/Offline:

```bash
cd ~/actions-runner
sudo ./svc.sh status
sudo ./svc.sh stop
sudo ./svc.sh start
```

App e backup:

```bash
cd ~/lumia-manager
sudo docker compose ps -a
sudo docker compose logs --tail=80 app
git status --short
git log -1 --oneline
df -h .
```

I backup sono in `backups/deploy-DATA-ORA-PROCESSO/`, insieme ai file con commit, immagine e tag precedenti. Le immagini precedenti vengono mantenute con tag `lumia-rollback:...`. Non viene eseguita pulizia automatica: controlla lo spazio disponibile.

Per interrompere l'automatismo, disabilita il workflow dalla pagina Actions del repository. Non cancellare i volumi Docker.

Se un job fallisce, controlla prima il suo log. Il ripristino è un tentativo e può fallire se il Docker daemon, il disco o la VPS non sono disponibili. Il codice precedente deve poter leggere il database aggiornato; una futura migrazione distruttiva richiede una procedura dedicata. Evita di annullare manualmente un deploy mentre sta eseguendo backup o riavvio.

## Verifiche effettuate

Il flusso è verificato localmente con vere cronologie Git, backup SQLite reali e un simulatore Docker: successo, build fallita, test falliti, backup corrotto, controlli HTTP falliti, modifiche operative bloccate, codice locale non committato, branch divergenti e job superati. Sono controllati anche la conservazione dei file privati e il ripristino del commit precedente.

Esito: 211 test Python e 9 scenari simulati superati; sintassi Bash verificata.

Docker non è disponibile in questo ambiente: runner, build e primo job reale devono essere verificati sulla VPS. Non è stata effettuata alcuna registrazione del runner o modifica al tuo repository GitHub da qui.
