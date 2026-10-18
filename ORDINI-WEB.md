# Lumia: ordini dal sito e assistente locale

Versione v2: corregge il layout del pannello ticket Discord che poteva bloccare l’avvio dell’app e provocare un 502. Se hai già installato la prima versione, puoi applicare soltanto la correzione del pannello e ricostruire app. Non cambiare le rotte Cloudflare.

Questa versione è cumulativa: comprende il redesign, la dashboard con guida, messaggi, consegne e pagamenti a milestone, più il nuovo percorso per richiedere un progetto dal sito. Non devi installare prima i vecchi pacchetti.

Il percorso principale è: **landing → richiesta guidata → accesso → workspace → preventivo → accettazione → eventuali tranche Stripe → consegne**. La richiesta iniziale non è un acquisto e non produce addebiti. Prezzo, disponibilità, ambito e tempi vengono definiti dal team.

## 1. Aggiornare senza perdere le impostazioni

Si parte dalla tua installazione Docker già funzionante. Non sostituire il suo `.env`, `config.json`, `compose.yaml`, `Caddyfile` o `server_texts.json`. Non eseguire `docker compose down -v`: cancellerebbe i volumi.

Da PowerShell sul PC, sostituisci `UTENTE` e `IP_VPS` con il tuo accesso SSH, poi invia il nuovo pacchetto:

```powershell
scp "C:\Users\scooty\Downloads\Lumia Development\outputs\lumia-ordini-web-2026-10-17-v2.zip" UTENTE@IP_VPS:~/
ssh UTENTE@IP_VPS
```

Tutti i comandi successivi vanno nel terminale Ubuntu aperto con SSH. La guida assume che il progetto esistente sia in `~/lumia-manager`. Se è altrove, usa il suo percorso reale nel comando `bash`.

```bash
sudo apt update
sudo apt install -y unzip python3
umask 077
mkdir -p ~/aggiornamenti/lumia-ordini-web-2026-10-17-v2
unzip -o ~/lumia-ordini-web-2026-10-17-v2.zip -d ~/aggiornamenti/lumia-ordini-web-2026-10-17-v2
bash ~/aggiornamenti/lumia-ordini-web-2026-10-17-v2/install.sh ~/lumia-manager
```

L'installer verifica gli hash, salva sorgenti e configurazione in `backups/aggiornamento-DATA-ORA`, costruisce l'immagine e crea un backup SQLite verificato prima di riavviare. Aggiorna solo i tre indirizzi pubblici Lumia nel `.env`; conserva token, segreti Stripe, Compose, ID, testi e dati. Le nuove tabelle vengono aggiunte al database esistente. Non serve cancellare o ricreare il volume.

Se la build, il backup o i controlli HTTP falliscono, tenta di riavviare l'immagine precedente e ripristina sorgenti e ambiente. Non riporta automaticamente indietro il database, per non perdere pagamenti arrivati nel frattempo. Conserva i backup come file privati: contengono dati e segreti.

Controlla l'avvio:

```bash
cd ~/lumia-manager
sudo docker compose ps
sudo docker compose logs --tail=80 app
```

## 2. Landing, manager, Cloudflare e accesso

Non c'è un secondo sito da avviare: la stessa app serve due hostname distinti.

| Indirizzo | Contenuto |
| --- | --- |
| `https://lumiadevelopment.it/` | Landing |
| `https://lumiadevelopment.it/ordina` | Passaggio al percorso guidato |
| `https://manager.lumiadevelopment.it/start` | Nuova richiesta |
| `https://manager.lumiadevelopment.it/` | Workspace del cliente o di Management |

Nel tunnel Cloudflare già configurato entrambi gli hostname devono puntare a **HTTP `app:8080`**, se `cloudflared` è nello stesso Compose di `app`. Non impostare un override dell'header Host che trasformi i due domini in uno solo. Non creare un hostname pubblico per Ollama.

Se il tunnel è già attivo, il cambio dell'IP domestico non richiede uno script DDNS: `cloudflared` ristabilisce la connessione in uscita. I record DNS del tunnel non puntano all'IP dinamico di casa. Questo aggiornamento non modifica il tunnel o le regole del router. Il collegamento in uscita è descritto nella [documentazione Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/).

Nel Discord Developer Portal, nella tua applicazione → OAuth2 → Redirects, conserva esattamente:

```text
https://manager.lumiadevelopment.it/auth/callback
```

Il percorso clienti usa lo scope `identify`: serve l'account Discord come identità, **non l'iscrizione al server**. Non iscrive automaticamente nessuno. Gli scope sono documentati in [Discord OAuth2](https://docs.discord.com/developers/topics/oauth2). Management viene sempre verificato dal bot usando i ruoli attuali; se il bot non può verificarli, l'accesso amministrativo viene negato. Il cliente può continuare a consultare i propri progetti anche se non è nel server. Le vecchie sessioni basate sull'appartenenza al server mantengono il controllo originale: se necessario esci e accedi di nuovo dal sito.

## 3. Cosa vede il cliente

La landing invita a iniziare il progetto. I link FiveM e Minecraft preselezionano la piattaforma. Il percorso comprende sei passaggi:

1. Piattaforma e tipo di progetto.
2. Nome, obiettivo e funzioni indispensabili.
3. Situazione tecnica e approfondimenti facoltativi, diversi per piattaforma.
4. Testi, contenuti, stile e riferimenti.
5. Budget indicativo e tempi desiderati.
6. Riepilogo modificabile, accesso e invio.

La bozza resta nel `sessionStorage` della scheda, con scadenza di sette giorni. Si riprende dopo ricarica e accesso nella stessa scheda; non si sincronizza su altri dispositivi, può essere eliminata dal browser e normalmente si perde chiudendo la scheda. Il comando «Cancella bozza» serve sui dispositivi condivisi. Dopo un invio confermato viene eliminata. Non inserire password, token o dati di pagamento nei testi.

Dopo l'invio si apre il progetto nel manager, in valutazione. Non appare come già pagato: il totale è «Da definire». Il cliente può scrivere al team nella conversazione del progetto, consultare il preventivo, accettarlo, controllare milestone e tranche, aprire consegne e lasciare un riscontro. La guida iniziale e il pulsante «Fammi da guida» mostrano le funzioni del workspace.

L'invio è protetto da accesso, CSRF e controllo dell'origine. Un identificativo persistente evita duplicati quando si riprova dopo un timeout. È previsto un limite di dieci nuove richieste per account ogni 24 ore. Budget indicativo e contenuti AI non impostano mai il prezzo.

## 4. Cosa fa Management

Apri il nuovo progetto dalla home o dalla colonna «Da definire» della board. Leggi «La richiesta originale» e usa la conversazione per le domande. Le note interne restano riservate a Management.

Nel pannello «Prepara il preventivo» indica importo, lavoro compreso, esclusioni, revisioni, tempi e condizioni concordate. «Invia preventivo» pubblica la proposta al cliente. Dopo l'invio importo e proposta restano fissati; puoi aggiungere le tranche prima che il cliente accetti. Per un cambiamento sostanziale dell'accordo, annulla il progetto e concorda una nuova proposta: non modificare il database a mano.

Il cliente accetta dal sito. Le tranche già implementate si attivano per data, milestone o richiesta manuale. Ogni tranche apre un proprio Stripe Checkout: non vengono eseguiti addebiti futuri su carta salvata. I pagamenti sono registrati solo dal webhook firmato Stripe; tornare dal Checkout non accredita denaro.

Stripe mantiene la configurazione già presente. Il webhook deve restare:

```text
https://manager.lumiadevelopment.it/webhooks/stripe
```

Prima di lavorare con denaro reale, esegui un ordine di prova con le chiavi Stripe test e verifica webhook e importi delle tranche come nella guida precedente. Non cambiare direttamente le chiavi di produzione durante un ordine reale.

## 5. Discord come supporto e alternativa

Il pulsante «Scrivi al team» apre la conversazione sul sito. «Supporto Discord» apre l'invito; se il progetto ha già un ticket Discord collegato, rimane anche il link diretto al ticket.

Il nuovo comando `/ordina` apre il percorso del sito. Il pannello ticket propone «Inizia dal sito», ma conserva tutte le categorie e l'apertura dei ticket Discord. Per aggiornare i pannelli già pubblicati usa da Management `/server ticketpannello`; il codice non modifica automaticamente tutti i vecchi messaggi del server. I comandi vengono sincronizzati dal bot al suo avvio.

L'invito provvisorio `discord.gg/lumiadevelopment` rimane quello richiesto: finché non lo attivi, il collegamento non funzionerà. Puoi modificarlo nel `.env` alla voce `LUMIA_DISCORD_INVITE` e ricreare `app` con `sudo docker compose up -d --no-deps --force-recreate app`.

## 6. AI locale facoltativa per i tuoi 16 GB

Il percorso funziona già senza AI: le domande per piattaforma sono integrate. Per l'assistente preparo Ollama con `qwen3:4b`, elaborazione CPU, massimo due CPU logiche e limite di memoria di 6 GB al container. Non è necessario avere una GPU. Le prestazioni dipendono dalla CPU e dagli altri servizi, non soltanto dalla frequenza della RAM. Con server di gioco sulla stessa macchina verifica la memoria libera prima di abilitarlo.

Il file del modello è circa 2,5 GB; la RAM di esecuzione è aggiuntiva e dipende dal contesto. Come margine operativo per questa configurazione, punta ad avere almeno 8 GB di RAM ancora disponibili e diversi GB liberi su disco prima di installare. Sono margini prudenti per questo setup, non un benchmark sulla tua VPS. Fonte del modello: [libreria ufficiale Qwen3 4B](https://ollama.com/library/qwen3:4b).

Non è un modello addestrato da zero sui tuoi clienti. Viene personalizzato con le istruzioni Lumia in `lumia/briefing-guide.txt`, le risposte del cliente e uno schema JSON. Le domande vengono validate; non può eseguire azioni, decidere prezzi o accedere al registro pagamenti. Non conserva una chat AI autonoma e non impara automaticamente dalle conversazioni.

Prima controlla le risorse:

```bash
cd ~/lumia-manager
free -h
df -h .
lscpu
```

Poi avvia Ollama senza modificare il tuo Compose principale:

```bash
sudo docker compose -f compose.yaml -f compose.ai.yaml --profile ai config --quiet
sudo docker compose -f compose.yaml -f compose.ai.yaml --profile ai pull ollama
sudo docker compose -f compose.yaml -f compose.ai.yaml --profile ai up -d ollama
sudo docker compose -f compose.yaml -f compose.ai.yaml --profile ai exec ollama ollama pull qwen3:4b
sudo docker compose -f compose.yaml -f compose.ai.yaml --profile ai exec ollama ollama run qwen3:4b "/no_think Rispondi solo: pronto"
```

Il download e la prima risposta possono richiedere tempo. L'ultima riga deve produrre una risposta; se termina per memoria insufficiente o non risponde, lascia l'AI disabilitata e usa la guida normale.

Abilita l'integrazione:

```bash
python3 configure-local-ai.py --enable
sudo docker compose up -d --no-deps --force-recreate app
sudo docker compose logs --tail=60 app
```

Il piccolo script cambia solo `LUMIA_AI_ENABLED`, `LUMIA_OLLAMA_URL` e `LUMIA_AI_MODEL`, conservando il resto del `.env` e salvandone una copia privata `.env.before-ai-DATA-ORA`. Non serve riscrivere token o configurazione. L'override AI assume la rete Compose predefinita usata dagli esempi del progetto. Se hai personalizzato `networks` nel tuo Compose, assicurati che `app` e `ollama` condividano una rete interna raggiungibile prima di abilitare l'integrazione.

Nel passaggio «Dettagli» compare «Approfondisci con AI locale». Il cliente deve accedere per usarla; la bozza torna allo stesso passaggio. L'AI riceve soltanto piattaforma, servizio, obiettivo, funzioni e contesto tecnico. Testi forniti, nome del progetto e dati dell'account non sono inclusi nella chiamata al modello. Il cliente può continuare subito, anche mentre l'AI lavora.

Una sola generazione alla volta; massimo sei richieste AI per account all'ora. Se il modello è occupato, non raggiungibile, risponde male o supera il timeout, restano disponibili le domande guidate. Il timeout dell'adattatore è 35 secondi; il browser interrompe l'attesa dopo 38. Il limite riduce le attese, ma un timeout HTTP non garantisce che Ollama abbia già liberato ogni risorsa.

Ollama non pubblica porte sull'host e non deve essere aggiunto a Cloudflare Tunnel. `OLLAMA_NO_CLOUD=1` disabilita le funzioni cloud. Internet serve per scaricare immagine e modello; l'inferenza usa il modello locale. Per il funzionamento e le opzioni vedi [Docker Ollama](https://docs.ollama.com/docker), [risposte con schema JSON](https://docs.ollama.com/capabilities/structured-outputs) e [modalità locale e risorse](https://docs.ollama.com/faq).

## 7. Diagnostica e disattivazione AI

```bash
cd ~/lumia-manager
sudo docker compose -f compose.yaml -f compose.ai.yaml --profile ai logs --tail=80 ollama
sudo docker compose -f compose.yaml -f compose.ai.yaml --profile ai exec ollama ollama list
sudo docker compose -f compose.yaml -f compose.ai.yaml --profile ai exec ollama ollama ps
sudo docker stats --no-stream
```

Per controllare che l'app raggiunga Ollama, senza stampare il `.env`:

```bash
sudo docker compose exec -T app python -c "import urllib.request; print(urllib.request.urlopen('http://ollama:11434/api/tags', timeout=5).read().decode())"
```

Per disabilitare l'AI e liberare la memoria, senza eliminare modello o dati:

```bash
python3 configure-local-ai.py --disable
sudo docker compose up -d --no-deps --force-recreate app
sudo docker compose -f compose.yaml -f compose.ai.yaml --profile ai stop ollama
```

Puoi personalizzare il comportamento modificando `lumia/briefing-guide.txt`, poi ricostruendo l'app:

```bash
nano lumia/briefing-guide.txt
sudo docker compose build app
sudo docker compose up -d --no-deps app
```

In nano salva con `Ctrl+O`, Invio, poi esci con `Ctrl+X`. Le modifiche alle istruzioni cambiano il contesto fornito al modello; non sono fine-tuning. Un aggiornamento successivo del codice può sostituire questo file: conserva le tue modifiche separatamente.

## 8. Verifiche prima di aprire al pubblico

Prova con un account cliente distinto da quello amministrativo: richiesta dal sito, ritorno dall'accesso senza perdere risposte, messaggio al team, preventivo, accettazione, consegna e pagamento Stripe test. Ripeti dal tuo telefono, anche con tastiera aperta. Il percorso è stato controllato nel browser desktop e in emulazione mobile; Safari e un telefono fisico richiedono una verifica sul dispositivo reale.

Non sono stati eseguiti deployment sulla tua VPS, benchmark del modello sulla tua CPU, autorizzazioni OAuth con il tuo client reale o pagamenti live. I test locali usano identità e servizi simulati; il codice dell'adattatore Ollama è verificato, il runtime Ollama va collaudato con i comandi sopra.
