AGGIORNAMENTO BOT DISCORD — 25 ottobre 2026
Leggi AGGIORNAMENTO-DISCORD.md per aggiornare pannelli, coda staff, preferenze, archivi e notifiche.
La cancellazione dei ticket chiusi e archiviati non richiede più sette giorni di attesa.

AGGIORNAMENTO SITO, TUTORIAL E VERIFICA DISCORD — 19 ottobre 2026
Leggi AGGIORNAMENTO-PAYPAL.md per dashboard, ordini, PayPal e Discord dedicato all’assistenza.
Include tutorial clienti, accesso agli ordini dalla homepage, ruolo Da verificare e pannello di verifica senza obbligo di DM.
Questa guida sostituisce le precedenti istruzioni su Stripe e sugli ordini da Discord.

LUMIA WORKSPACE — aggiornamento del 17 ottobre 2026
Per la nuova board, tutorial e conversazioni segui AGGIORNAMENTO-WORKSPACE.md.
Il pacchetto cumulativo conserva ambiente, configurazione e dati esistenti.

AGGIORNAMENTO INSTALLAZIONE ESISTENTE — 17 ottobre 2026
Se hai già configurato il bot sulla VPS, usa install.sh nel nuovo archivio
e leggi AGGIORNAMENTO-REDESIGN.md. Non ricreare .env o config.json.
Le istruzioni PRIMO AVVIO seguenti servono solo per nuove installazioni.

LUMIA MANAGER — INSTALLAZIONE E UTILIZZO

Questo pacchetto contiene il bot Discord e la dashboard web per gestire Lumia Development.
Non contiene credenziali e non è già collegato al vostro server. I dati della modalità demo sono fittizi.

PRIMO AVVIO — BOT

1. Installa Python 3.12 sul server, oppure usa Docker con il file compose incluso.
2. Crea una nuova applicazione su https://discord.com/developers/applications chiamata Lumia Manager.
3. Nella sezione Bot abilita Server Members Intent e Message Content Intent. Non serve Presence Intent per i contatori inclusi.
4. Aggiungi il bot al tuo server tramite OAuth2 URL Generator: scopes bot e applications.commands.
   Seleziona Visualizza canali, Invia messaggi, Leggi cronologia, Incorpora link, Allega file, Gestisci canali, Gestisci ruoli, Gestisci messaggi, Modera membri, Espelli membri, Banna membri, Visualizza registro attività e Gestisci server. Le funzioni vocali accessorie richiedono i permessi pertinenti. Non è necessario Administrator.
5. Sposta il ruolo del bot sopra i ruoli Member/Customer e sopra quelli che deve poter moderare o contenere. Il proprietario resta sempre fuori dalla capacità di sanzione del bot.
6. Copia config.example.json in config.json e inserisci guild_id, cioè l'ID del server, e roles.member con l'ID del ruolo membro già presente. L'allestimento richiede questo ruolo e non ne crea uno sostitutivo. Gli altri ID possono rimanere vuoti fino all'allestimento.
   Per copiare l'ID abilita Modalità sviluppatore nelle impostazioni avanzate di Discord, poi usa Copia ID server nel menu del server.
7. Copia .env.example in .env. Inserisci DISCORD_TOKEN localmente; non mandarlo in chat. Per il solo bot lascia WEB_ENABLED=false.
8. Nella cartella del progetto esegui:

   Windows:
   py -3.12 -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   .venv\Scripts\python bot.py --check
   .venv\Scripts\python bot.py

   Linux:
   python3.12 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   .venv/bin/python bot.py --check
   .venv/bin/python bot.py

9. Dal server Discord, con l'account proprietario o un account il cui ID è in owner_ids di config.json, usa /server allestimento. Il bot mostra la struttura e richiede la conferma dello stesso account autorizzato prima di creare risorse. Dopo modifiche al codice o alla configurazione riavvia il bot.
   Il comando crea risorse nuove e riutilizza quelle registrate dal bot. Non elimina il vecchio server e non assume che un canale con lo stesso nome sia quello corretto.
   Se un'operazione fallisce, correggi i permessi e ripeti: gli ID già salvati vengono riutilizzati.
   I ruoli Lumia hanno il suffisso ®. Quelli già configurati vengono rinominati sul posto; il ruolo membro esistente mantiene ID, assegnazioni e permessi del ruolo. Il collegamento di accesso viene trasferito dal vecchio ruolo membro Lumia alle risorse pubbliche create dal bot, preservando eventuali permessi già impostati sul nuovo ruolo. I vecchi ruoli non vengono eliminati.
10. Assegna manualmente Management, Support, Developer e Moderator alle persone autorizzate. Nessuno riceve un ruolo staff automaticamente.
11. Usa /server testi, /pannelli e /ticket pannello. Leggi i testi prima di pubblicarli e adatta ciò che richiede decisioni commerciali.
12. Usa /server diagnostica, poi prova due ticket con account diversi e verifica che non siano visibili all'altro cliente.

Il nome server e l'icona si aggiornano dalle impostazioni Discord: nome Lumia Development, icona lumia-logo-discord.png. Il logo completo è adatto a presentazioni e materiali promozionali.

STILE DISCORD
I canali usano nomi leggibili come 🎫・apri-ticket. Log, pannelli, ticket, benvenuti e riepiloghi ordine condividono schede sobrie, campi ordinati e avatar del cliente o dell'utente coinvolto quando disponibili. I riferimenti alle persone sono menzioni silenziose.
Dopo un aggiornamento: riavvia il bot, usa /server anteprima per vedere un esempio privato e /server stile per aggiornare i canali già creati dal bot. Poi /server testi, /pannelli e /ticket pannello aggiornano i messaggi pubblici. Vedi STILE.txt.
/server embed aggiorna lo stile degli ultimi 20 messaggi del bot per canale configurato e per ticket registrato, senza modificare gli incassi. Non modifica messaggi di persone o altri bot.

REDESIGN, LANDING E TRANCHE
La landing pubblica vive su https://lumiadevelopment.it; il manager su https://manager.lumiadevelopment.it. Con Cloudflare Tunnel entrambe le rotte puntano a http://app:8080, mantenendo il proprio header Host. Il backend serve solo i percorsi pubblici sul dominio della landing.
Il manager usa un tema dark condiviso con la landing, viste distinte per cliente e Management, navigazione mobile e pagamenti Stripe per tranche. Gli ordini esistenti rimangono a pagamento unico finché Management non definisce esplicitamente un piano.
La verifica di ingresso è un breve calcolo nei DM dopo l'accettazione delle regole. /verifica disattiva durata:30m sospende il controllo; senza durata resta sospeso fino a /verifica attiva. La pausa viene conservata dopo il riavvio e non disabilita l'anti-raid.
Per aggiornare la VPS preservando configurazione e dati, leggi AGGIORNAMENTO-REDESIGN.md e usa l'installer del pacchetto dedicato. Per i backup ordinari: bash backup-docker.sh.

DASHBOARD SUL VOSTRO DOMINIO

1. Punta un dominio/sottodominio al server e predisponi HTTPS. Il compose incluso offre Caddy come reverse proxy.
2. Nella stessa app Discord configura il redirect OAuth2 esattamente come indicato in DASHBOARD.txt.
3. Inserisci nel file .env DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET e LUMIA_PUBLIC_URL con l'URL HTTPS finale. Imposta WEB_ENABLED=true.
4. Mantieni WEB_HOST=127.0.0.1 se usi un proxy già installato sullo stesso host. Il compose lo imposta a 0.0.0.0 solo dentro la rete Docker privata.
5. Riavvia il servizio. Accedi con Discord: il Management gestisce gli ordini; il cliente vede solo i propri lavori.
6. La dashboard condivide lo stesso database del bot. Usa /ordine crea, /ordine stato, /ordine pagamento e /ordine scadenza anche da Discord.

Ordini e preventivi hanno ID distinti dai ticket. L'ordine può essere collegato al ticket del suo cliente. Stati e pagamenti sono separati: una consegna non prova un incasso.
Gli importi sono conservati come centesimi interi in EUR. Un pagamento manuale registra un fatto già verificato dallo staff; non muove denaro, non emette documenti fiscali e non genera una fattura. Un errore di registrazione manuale si corregge con uno storno motivato nella dashboard o /ordine storna, conservando l'originale e ripristinando il residuo. /ordine movimenti mostra gli ID. Lo storno non invia rimborsi e non è utilizzabile per cancellare un pagamento Stripe.
Consulta DASHBOARD.txt per autenticazione, Checkout Stripe opzionale, eventi webhook, demo e limitazioni del registro.

DOCKER

Prepara config.json e .env prima dell'avvio. Inserisci LUMIA_DOMAIN e LUMIA_PUBLIC_URL coerenti, abilita WEB_ENABLED e configura le credenziali OAuth.
Comando: docker compose up -d --build
Controlla i log: docker compose logs -f app
Arresta: docker compose stop

La prima esecuzione copia la configurazione iniziale nel volume persistente, in /app/data/config.json. Le successive modifiche dell'allestimento vengono salvate lì. Non cancellare il volume lumia_data.
Il contenitore usa un utente privo di privilegi. Il database e gli archivi restano nel volume; le credenziali passano come variabili d'ambiente.
Il compose presume che le porte 80 e 443 siano libere e raggiungibili per il dominio. Se hai già un reverse proxy, integra l'app nella configurazione esistente.

ANTEPRIMA LOCALE

Con le dipendenze installate: python bot.py --preview
Apri http://127.0.0.1:8080. È una dimostrazione in sola lettura, con ordini inventati, e non richiede token Discord. Non pubblicarla come dashboard operativa.

USO QUOTIDIANO

Cliente: riceve benvenuto e regolamento in privato → accetta le regole nei DM → riceve automaticamente Member → sceglie interessi e notifiche nel menu privato → apre ticket → invia requisiti → riceve preventivo → segue ordine e scadenze nella dashboard → testa la consegna.
Se Discord blocca i DM, il bot avvisa lo staff senza pubblicare un benvenuto personale nei canali. L'utente può abilitare i DM dal server e usare /inizia. /server testi e /pannelli aggiornano i messaggi pubblici con i pulsanti e le istruzioni per il percorso privato. Vedi ONBOARDING-DM.txt.
Support: prende in carico i ticket, chiede le informazioni mancanti, assegna gli sviluppatori autorizzati, aggiorna lo stato e archivia.
Management: concorda il preventivo, crea l'ordine, verifica i pagamenti, aggiorna le milestone e gestisce gli accessi.
Developer: accede ai singoli ticket ai quali viene aggiunto. Il solo ruolo Developer non apre i ticket degli altri clienti.

La raccolta requisiti dovrebbe sempre specificare: piattaforma/framework, versione, funzionalità incluse, materiali disponibili, compatibilità, consegne, sorgenti/licenza, revisioni, prezzo e scadenze. La conferma del ticket non equivale a un ordine accettato.

PROTEZIONI E SOSTITUZIONE DEI VECCHI BOT

Inizia nel server di test. Il modulo sicurezza parte in observe: leggi OPERATIONS.txt per l'esatto comportamento e per l'attivazione del contenimento.
Attiva l'automod dopo aver configurato eccezioni, domini e soglie. Evita di lasciare due bot che sanzionano lo stesso evento.
Mantieni Security finché protezioni e gerarchia non sono state collaudate. L'anti-nuke reagisce a eventi osservati e non può recuperare messaggi di canali già cancellati.
I ticket precedenti continuano con Tickets v2 fino alla chiusura. Non è prevista una migrazione automatica dello storico privato di altri servizi.
La matrice COPERTURA.txt indica quali funzioni sono incluse e quali restano esterne.

DATI, ARCHIVI E RIPRISTINO

data/lumia.sqlite: database condiviso bot/dashboard.
data/: trascrizioni e altri dati locali, secondo i moduli.
.env: credenziali; deve restare privato e non entra nei backup di esempio.
config.json: ID e impostazioni, senza token; in Docker si trova nel volume data dopo il primo avvio.

Prima dell'attivazione informa gli utenti su contenuti archiviati, personale con accesso e conservazione effettiva. Il valore retention_days è una politica predisposta in configurazione e non esegue cancellazioni automatiche. Trascrizioni, ordini, pagamenti, audit e backup richiedono una politica di conservazione applicata dall'operatore; consulta TICKETS.txt.
Il testo dei messaggi generali non viene salvato per il solo conteggio delle statistiche. I link agli allegati dei ticket non sono una copia permanente degli allegati stessi.

Per un backup coerente, ferma il bot e usa: python backup.py
Nel contenitore usa i percorsi del volume dopo aver fermato il servizio; in alternativa esegui un backup gestito del volume a servizio fermo.
Conserva una copia protetta su un'altra macchina. Prova il ripristino in una cartella/server di test: estrai database, trascrizioni e config, configura nuovamente le credenziali locali e avvia una sola istanza del bot.
Non eseguire due processi Lumia sullo stesso database.

VERIFICHE

Test locali: python -m unittest discover -s tests -v
Import e sintassi: python -m compileall -q bot.py lumia
L'esito reale della consegna è registrato in VERIFICHE.txt. Il pacchetto non include una promessa di collaudo online senza configurazione e accessi reali.

Fonti tecniche principali:
https://discordpy.readthedocs.io/en/stable/
https://docs.discord.com/developers/topics/oauth2
https://docs.discord.com/developers/topics/permissions
https://docs.stripe.com/events/manage-webhook-endpoints
