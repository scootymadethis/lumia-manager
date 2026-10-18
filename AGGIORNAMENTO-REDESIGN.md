# Lumia · Aggiornamento del 17 ottobre 2026

Landing e manager condividono un nuovo stile dark: tipografia di sistema, testi essenziali, superfici discrete, glow, materiali traslucidi e animazioni. La landing usa gli SVG forniti di FiveM, Minecraft e Discord, card con rotazione al mouse e un percorso fissato durante lo scroll; sui display bassi, senza JavaScript o con movimento ridotto il percorso rimane leggibile in forma statica. Lo scroll resta nativo. Il manager usa effetti discreti per mantenere leggibili i dati. La landing è pubblica; il manager continua a verificare appartenenza e ruolo Discord. Il cliente vede solo i propri progetti, pagamenti e milestone. Creazione ordini, clienti, piani e rettifiche restano riservati a Management.

## Aggiorna la VPS esistente

Il pacchetto `lumia-redesign-2026-10-17.zip` contiene `install.sh`, il manifest e i sorgenti in `payload/`. Non contiene credenziali, database o configurazioni di produzione.

L’installer conserva il tuo `compose.yaml`, il `Caddyfile`, il nome del progetto Docker, il volume dati, `config.json` e `server_texts.json`. Nel `.env` mantiene i segreti e aggiorna solo questi tre indirizzi pubblici:

```dotenv
LUMIA_PUBLIC_URL=https://manager.lumiadevelopment.it
LUMIA_SITE_URL=https://lumiadevelopment.it
LUMIA_DISCORD_INVITE=https://discord.gg/lumiadevelopment
```

L’invito Discord è quello richiesto, attualmente da attivare: sostituiscilo nel `.env` quando avrai un invito funzionante. I pulsanti della landing usano quel valore.

### 1. Trasferisci l’archivio da Windows

Apri PowerShell sul PC. Sostituisci `UTENTE_UBUNTU` e `IP_DELLA_VPS`:

```powershell
scp "C:\Users\scooty\Downloads\Lumia Development\outputs\lumia-redesign-2026-10-17.zip" UTENTE_UBUNTU@IP_DELLA_VPS:~/
```

### 2. Su Ubuntu prepara gli strumenti ed estrai

```bash
sudo apt update
sudo apt install -y unzip python3
mkdir -p ~/lumia-redesign
unzip -o ~/lumia-redesign-2026-10-17.zip -d ~/lumia-redesign
```

Il bot deve avere un contenitore `app` già creato nella sua installazione. Esegui l’installer indicando la cartella in cui hai già `.env` e `compose.yaml`:

```bash
bash ~/lumia-redesign/install.sh ~/lumia-manager
```

Non spostare l’installazione in una nuova cartella e non usare un nuovo nome di progetto Compose: cambierebbe il volume selezionato.

L’installer verifica il pacchetto, salva sorgenti e `.env` precedenti in una cartella protetta sotto `backups/`, costruisce l’immagine e ferma brevemente l’app. Prima di avviare la nuova versione crea e verifica un backup del database, delle trascrizioni e della configurazione attiva. Le nuove tabelle e colonne vengono aggiunte senza cancellare i dati esistenti.

Se la costruzione, il backup o il controllo interno falliscono, prova a ripristinare sorgenti, ambiente e immagine precedente. Il database non viene ripristinato automaticamente, per conservare qualsiasi incasso già registrato. Il percorso dei backup viene stampato al termine. La cartella contiene anche una copia privata del vecchio `.env`: non condividerla.

### 3. Controlla l’app

```bash
cd ~/lumia-manager
sudo docker compose ps
sudo docker compose logs --tail=80 app cloudflared
```

Controlla che app e tunnel restino avviati e che il bot risulti connesso. L’installer verifica le due pagine dentro il contenitore; la configurazione pubblica del tunnel e i servizi Discord/Stripe richiedono anche i controlli seguenti.

## Pubblica la landing con lo stesso tunnel

Nel pannello Cloudflare apri il tunnel `lumia` e aggiungi una rotta **Published application**:

| Campo | Landing | Manager già esistente |
| --- | --- | --- |
| Subdomain | Vuoto | `manager` |
| Domain | `lumiadevelopment.it` | `lumiadevelopment.it` |
| Path | Vuoto | Vuoto |
| Tipo servizio | HTTP | HTTP |
| URL servizio | `app:8080` | `app:8080` |

Se il pannello ha un solo campo, usa `http://app:8080`. Mantieni l’header Host originale: puoi lasciare **HTTP Host Header** vuoto. Se lo imposti esplicitamente, usa `lumiadevelopment.it` sulla rotta della landing e `manager.lumiadevelopment.it` su quella del manager, senza protocollo o porte.

Rimuovi soltanto eventuali record DNS che confliggono con questi stessi hostname, quando Cloudflare lo richiede. Non cambiare i record email. Il tunnel gestisce l’IP dinamico mediante riconnessione; non serve aggiungere DDNS o inoltrare porte del router.

Imposta **Bypass cache** per `manager.lumiadevelopment.it`. Sulla landing evita regole “Cache Everything” durante l’aggiornamento. Il webhook deve essere raggiungibile senza challenge interattive o login Cloudflare Access.

Apri:

- `https://lumiadevelopment.it/`: landing.
- `https://manager.lumiadevelopment.it/login`: area clienti.

Il redirect OAuth2 Discord resta:

```text
https://manager.lumiadevelopment.it/auth/callback
```

## Aggiorna Discord

Dal server, con un account Management, esegui nell’ordine:

```text
/server anteprima
/server stile
/server testi
/pannelli
/ticket pannello
/server embed
/server diagnostica
```

`/server stile` aggiorna i nomi leggibili delle risorse già registrate dal bot, preservando ID e permessi. `/server testi` mantiene i contenuti personalizzati di `server_texts.json`; benvenuto e accesso pubblico indirizzano al percorso nei DM. `/server embed` aggiorna gli ultimi 20 messaggi di questo bot per canale configurato o ticket registrato, conserva il contenuto delle schede e aggiunge il link alla dashboard agli ordini riconoscibili senza pulsanti. I messaggi di persone e altri bot sono esclusi.

Non serve ripetere `/server allestimento` su un server già configurato. Il ruolo del bot deve restare sopra quelli che assegna e avere Gestisci ruoli.

## Verifica degli utenti

Il nuovo utente riceve benvenuto e regolamento nei DM. Premendo **Accetto le regole**, quando il controllo è attivo, risolve una semplice somma. Il bot verifica l’appartenenza attuale al server e assegna Member solo al completamento. Seguono le preferenze facoltative. Gli utenti già membri non perdono il ruolo.

```text
/verifica stato
/verifica disattiva durata:30m
/verifica disattiva durata:2h
/verifica disattiva durata:1g
/verifica disattiva
/verifica attiva
```

Solo Management può cambiare lo stato. Senza durata la pausa è indefinita; con una durata scade automaticamente, anche se nel frattempo il bot viene riavviato. La pausa riguarda il calcolo, non l’accettazione delle regole e non l’anti-raid. Non è una verifica documentale dell’identità. Cinque risposte errate in dieci minuti bloccano ulteriori tentativi per dieci minuti.

Con i DM chiusi, il bot avvisa lo staff senza pubblicare benvenuti personali nei canali. L’utente abilita i DM dal server e usa `/inizia` per riprovare. I pulsanti privati sono legati al destinatario e continuano a funzionare dopo un riavvio.

## Ordini e pagamenti per tranche

Gli ordini esistenti continuano a funzionare come prima. Per suddividere un ordine:

1. Accedi al manager come Management e apri l’ordine.
2. Aggiungi prima le milestone che vuoi collegare alle tranche.
3. In **Piano di pagamento → Dividi in tranche**, definisci nomi e importi. La somma deve essere uguale al totale dell’ordine. Eventuali pagamenti precedenti vengono attribuiti al piano senza riscrivere il registro.
4. Ogni tranche può avere una data oppure una milestone. La prima senza data o milestone è subito disponibile; le successive prive di condizioni si attivano con **Richiedi ora**.
5. Conferma il piano. Gli importi confermati restano fissi e il piano non viene sostituito dal modulo: controllalo prima di salvarlo.
6. Il cliente vede il piano e paga la prossima tranche disponibile con **Stripe Checkout**. Le tranche si pagano in ordine. Il progetto deve essere confermato prima di accettare pagamenti.
7. Il webhook verificato registra l’incasso, aggiorna la tranche e il residuo. I duplicati non aggiungono incassi. Il ritorno dal Checkout da solo non conferma un pagamento.

Non ci sono addebiti automatici sulla carta salvata: il cliente conferma ogni Checkout, come richiesto. Gli importi vengono calcolati dal server. Una tranche già pagata fuori da Stripe non può essere accreditata una seconda volta da una vecchia sessione: l’evento viene segnalato per riconciliazione.

Il bot invia aggiornamenti con avatar, menzione e pulsante sul progetto. Controlla ogni 30 minuti le tranche disponibili e tenta una notifica privata; le notifiche già consegnate vengono deduplicate. Se un DM fallisce, avvisa lo staff e ritenta dopo almeno sei ore. Il pagamento resta disponibile nella dashboard anche quando il DM non arriva.

Il Checkout dell’app richiede almeno 0,50 €: prevedi tranche superiori a questa soglia e verifica i minimi del tuo conto Stripe. Residui inferiori restano registrati esattamente e si gestiscono con lo staff, senza arrotondamenti automatici.

Se esiste un Checkout aperto o un tentativo ancora in verifica, il piano non può essere creato finché la sessione non scade. Questo evita che un vecchio link al saldo totale resti utilizzabile mentre si definisce un piano diverso.

### Stripe

Le chiavi già presenti nel `.env` vengono conservate. Non servono nuovi prodotti o prezzi nel catalogo: ogni Checkout usa l’importo della tranche calcolato dall’app.

L’endpoint resta:

```text
https://manager.lumiadevelopment.it/webhooks/stripe
```

Mantieni il formato **Snapshot** e questi eventi:

```text
checkout.session.completed
checkout.session.async_payment_succeeded
checkout.session.expired
charge.refunded
refund.created
refund.updated
charge.dispute.created
```

`checkout.session.expired` è aggiuntivo: libera subito una sessione scaduta; senza quell’evento l’app usa comunque la sua scadenza temporale. Non cambiare segreto webhook o chiavi se l’endpoint resta lo stesso.

Collauda il nuovo piano in sandbox/test con un cliente distinto: due tranche, prima pagata una sola volta, seconda bloccata fino alla richiesta o alla milestone, webhook duplicato, saldo finale. Le prove incluse simulano Stripe; non attestano l’account di produzione. Rimborsi e contestazioni restano eventi da riconciliare; il manager non emette fatture fiscali.

## Avviso sulle funzioni voice

Lumia non si collega ai canali vocali e non riproduce audio o musica. Gli intent vocali consentono di osservare eventi o gestire permessi; non richiedono il motore audio. L’avviso su PyNaCl o altre dipendenze vocali non impedisce le funzioni del progetto.

Non è necessario aggiungere dipendenze voice per questa versione. È comunque incluso un profilo opzionale per futuri moduli audio:

```bash
cd ~/lumia-manager
sudo docker compose -f compose.yaml -f compose.voice.yaml up -d --build app
```

Il profilo installa gli extra ufficiali `discord.py[voice]`. Non aggiunge comandi vocali. Se lo usi, includi entrambi i file anche nelle successive ricostruzioni. FFmpeg servirà solo se introdurrai in seguito una funzione che lo utilizza.

## Backup successivi

```bash
cd ~/lumia-manager
bash backup-docker.sh
```

Il comando ferma brevemente l’app, crea il backup con i permessi temporanei necessari e riavvia l’app anche in caso di errore. Il normale ZIP non include il `.env`. Conserva una copia protetta fuori dalla VPS e prova il ripristino su un’istanza di test. Non eseguire `docker compose down -v`.

## Verifiche e fonti

Il rapporto finale di verifica è in `VERIFICHE-REDESIGN.txt`. Il controllo mobile automatico usa un browser con viewport ridotti: tastiera, safe area, Safari e sensazione delle interazioni richiedono anche una prova su iPhone/Android reali.

Il copy è originale e segue chiarezza della proposta di valore e CTA descrittive. Non utilizza clienti, testimonianze, risultati o statistiche inventati; nessun hook garantisce conversioni.

- Apple, Writing for interfaces: https://developer.apple.com/videos/play/wwdc2022/10037/
- Nielsen Norman Group, Homepage Design Principles: https://www.nngroup.com/articles/homepage-design-principles/
- Stripe Checkout: https://docs.stripe.com/api/checkout/sessions/create
- Stripe webhook: https://docs.stripe.com/webhooks
- Cloudflare Tunnel: https://developers.cloudflare.com/tunnel/
- Discord.py, installazione e supporto voice: https://discordpy.readthedocs.io/en/stable/intro.html#installing
