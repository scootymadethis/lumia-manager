# Lumia · Ordini sul sito e PayPal

Aggiornamento del 19 ottobre 2026, basato sul commit `5f21accb7f919a8afba945ea215a6ef23ac4d67d`.
Questa guida sostituisce le precedenti indicazioni su checkout Stripe e creazione degli ordini da Discord.

## Tutorial clienti e accesso dalla homepage

La homepage mette in evidenza «Hai già un ordine in corso? Vai all’area clienti». Il collegamento apre l’accesso alla dashboard con lo stesso account Discord usato per ordinare.

Il tutorial è nella navigazione, nella Home e nel menu account. Gli otto capitoli spiegano account, richiesta facoltativa con «Altro», preventivo, PayPal e tranche, avanzamento, conversazioni, consegne e assistenza. I comandi Avanti, Indietro, indice e Ricomincia salvano il punto di lettura su quel browser, distinto per utente. La lettura non modifica ordini o pagamenti. Senza JavaScript tutti i capitoli rimangono leggibili.

## Verifica Discord e canali di assistenza

L’allestimento aggiunge il ruolo «Da verificare ®» e il canale «✅・verifica» nell’ingresso. Il ruolo Member già configurato viene riutilizzato. All’ingresso il bot assegna solo Da verificare. Il pulsante «Inizia la verifica» mostra regole e controllo in messaggi visibili solo alla persona che li apre: funziona anche con i DM chiusi. Dopo l’accettazione e il controllo corretto, il bot assegna Member e rimuove Da verificare. I limiti dei tentativi restano anche dopo un’uscita e un nuovo ingresso.

Il pannello pubblico rimane utilizzabile dopo il riavvio e viene aggiornato senza duplicati. I canali Lumia registrati vengono riordinati e i loro permessi aggiornati per distinguere ingresso, community, assistenza e staff. Non vengono cancellati canali o messaggi. Le categorie con canali esterni sincronizzati non cambiano permessi: il bot aggiorna direttamente i propri canali, evitando effetti sui canali aggiunti a mano. Conserva le personalizzazioni dei ruoli estranei; eventuali permessi aggiuntivi già concessi da tali ruoli richiedono controllo da parte del gestore.

Per migrare gli utenti già presenti usa `/verifica sincronizza`: chi possiede Member lo conserva; gli altri ricevono Da verificare. Il comando non verifica automaticamente le persone. Il ruolo del bot deve stare sopra Member e Da verificare, con Gestisci ruoli. Abilita Server Members Intent nell’app Discord. Il canale di verifica deve consentire al bot visualizzazione, invio e cronologia.

## Pulsante per eliminare un ticket Discord

I nuovi ticket includono il pulsante rosso **Elimina ticket**. Nei ticket già esistenti Management può eseguire `/ticket controlli` nel canale: il bot aggiorna i controlli originali quando disponibili, oppure pubblica un pannello. Le esecuzioni successive aggiornano lo stesso messaggio. I pulsanti continuano a funzionare dopo un riavvio.

L’eliminazione è riservata a Management, al proprietario del server e agli account autorizzati in `owner_ids`. Prima occorre chiudere il ticket con **Chiudi / richiedi chiusura**, con trascrizione finale verificata; dal 25 ottobre 2026 il canale può essere eliminato subito dopo la chiusura, senza attesa minima. Il pulsante chiede di scrivere `ELIMINA #numero` e ricontrolla autorizzazione, stato chiuso del ticket e integrità dell’archivio alla conferma. Clienti e Support non possono eliminare il canale. L’operazione cancella canale e messaggi su Discord; mantiene la trascrizione locale e gli ordini sul sito. Il bot deve avere Gestisci canali. Resta disponibile anche `/ticket elimina-canale`.

## Richiesta guidata semplificata

Piattaforma, tipo di progetto, budget e tempi includono «Altro», con uno spazio facoltativo per precisare la scelta. Tutte le domande possono essere saltate, anche nome, descrizione e data. Non ci sono minimi di caratteri: i dettagli mancanti si definiscono con il team. Un pulsante «Salta per ora» permette di avanzare. Restano accesso e conferma finale per inviare la richiesta. Gli approfondimenti usano due domande semplici e sono chiusi in una sezione facoltativa. Le bozze precedenti restano disponibili.

## Il nuovo percorso

Il cliente invia la richiesta dal sito, riceve il preventivo, lo accetta e segue sviluppo, milestone e consegne nella propria dashboard. Il pagamento unico o per tranche usa esclusivamente PayPal. Le conversazioni sul progetto restano disponibili nel sito.

Management ha code dedicate a richieste, preventivi, pagamenti disponibili, consegne da verificare e scadenze trascorse. Board ed elenco condividono ricerca immediata, filtro di stato, preferiti e ordinamento per aggiornamento, scadenza o residuo. Il dettaglio mostra il percorso dell’ordine. Gli aggiornamenti degli altri partecipanti vengono segnalati ogni 30 secondi con un pulsante di ricarica: i moduli in compilazione restano intatti.

L’accesso continua a usare l’identità Discord. I clienti web non devono iscriversi al server per seguire un ordine; i permessi Management vengono verificati dal bot. Ogni cliente accede solo ai propri progetti. Le note interne rimangono riservate al team.

Discord è dedicato all’assistenza: il pannello offre assistenza, partnership e segnalazioni riservate. I vecchi ticket rimangono consultabili. Le nuove richieste commerciali e i vecchi comandi di modifica ordini rimandano al sito; le consultazioni esistenti rimangono disponibili. Dal progetto il cliente può creare un ticket privato con codice LM e collegamento all’ordine già inclusi. Per il ticket occorrono iscrizione e verifica nel server. Invii ripetuti riutilizzano il ticket attivo dello stesso ordine.

L’aura della landing ora applica direttamente le coordinate del puntatore, senza interpolazione o ritardo elastico. Le animazioni delle card e il supporto alla riduzione del movimento sono conservati.

## Aggiornare un’installazione esistente

Il pacchetto dei sorgenti non contiene credenziali, dati operativi o ambiente Python. La patch separata contiene tutte le modifiche e i nuovi file.

1. Esegui il backup dell’installazione e del database con la procedura già in uso (`backup-docker.sh` per l’installazione Docker). Conserva anche le personalizzazioni del codice e dei testi.
2. Copia `lumia-paypal-dashboard.patch` nel server. Dalla cartella del repository verifica e applica:

   ```bash
   git -c core.whitespace=cr-at-eol apply --check /percorso/lumia-paypal-dashboard.patch
   git -c core.whitespace=cr-at-eol apply /percorso/lumia-paypal-dashboard.patch
   ```

   Se il controllo segnala conflitti, integra le differenze prima di procedere. Non usare opzioni che scartano modifiche locali. Se hai personalizzato `server_texts.json`, conserva i tuoi testi e aggiorna soltanto il percorso sito/assistenza.
3. Aggiungi le variabili PayPal al tuo `.env` esistente come indicato sotto. Conserva dominio, token Discord, segreti OAuth, Compose, tunnel, ID e volume dati. Non sostituire `.env` con `.env.example` e non eseguire `docker compose down -v`.
4. Ricostruisci e riavvia il servizio esistente:

   ```bash
   docker compose build app
   docker compose up -d --no-deps app
   docker compose logs --tail=80 app
   ```

5. Nel server Discord, con il proprietario o un account autorizzato in `owner_ids`, esegui `/server allestimento` e conferma la struttura aggiornata. Poi usa `/server testi`, `/pannelli` e `/ticket pannello` per aggiornare i messaggi. Con Management esegui `/verifica sincronizza` e `/server diagnostica`. Controlla con un account senza Member: ingresso → Da verificare → canale verifica → regole e controllo → Member, anche con DM chiusi. La pubblicazione nel tuo server va eseguita nella tua installazione; non è stata eseguita da questa consegna.

Le tabelle e la colonna che identifica il provider vengono aggiunte automaticamente. Gli incassi precedenti sono mantenuti con il loro metodo originario. Nessun nuovo checkout Stripe viene creato. Se esistono ancora sessioni Stripe aperte, conserva temporaneamente `STRIPE_WEBHOOK_SECRET` e il relativo webhook, finché gli eventi storici sono stati riconciliati. Un checkout precedente ancora aperto blocca un nuovo pagamento dello stesso ordine.

## Configurare PayPal

Nel PayPal Developer Dashboard crea o seleziona un’app REST per il conto Business che riceve gli incassi. Inizia dall’ambiente Sandbox e aggiungi al `.env` del server, senza inviare credenziali in chat:

```dotenv
PAYPAL_ENVIRONMENT=sandbox
PAYPAL_CLIENT_ID=
PAYPAL_CLIENT_SECRET=
PAYPAL_WEBHOOK_ID=
```

Nella stessa app e nello stesso ambiente registra il webhook:

```text
https://manager.lumiadevelopment.it/webhooks/paypal
```

Usa l’hostname HTTPS effettivo di `LUMIA_PUBLIC_URL`, se diverso. Sottoscrivi questi eventi e riporta il Webhook ID nel `.env`:

- `CHECKOUT.ORDER.APPROVED`
- `PAYMENT.CAPTURE.COMPLETED`
- `PAYMENT.CAPTURE.REFUNDED`
- `PAYMENT.CAPTURE.REVERSED`
- `CUSTOMER.DISPUTE.CREATED`

Riavvia l’app dopo ogni modifica dell’ambiente. In Impostazioni la dashboard distingue Sandbox, Live e configurazione mancante. Senza tutte e tre le credenziali il checkout rimane indisponibile.

Il pagamento apre la pagina PayPal dal server; non richiede SDK esterni nel browser. L’importo, la valuta EUR e la tranche provengono dal database. Il ritorno dal provider esegue la verifica tramite un POST protetto da CSRF; la sola visita alla pagina di successo non registra un incasso. Il webhook di approvazione permette di completare il pagamento anche se il cliente chiude la scheda dopo l’approvazione.

Per il passaggio a Live, configura un’app e un webhook Live, sostituisci tutte le credenziali con quelle dell’ambiente Live e imposta `PAYPAL_ENVIRONMENT=live`. Concludi o verifica prima i tentativi Sandbox aperti. Non usare credenziali miste.

## Verifica e recupero pagamenti

I retry riusano identificativi persistenti per creazione e acquisizione. Un incasso viene registrato una sola volta anche se arrivano contemporaneamente ritorno del cliente e webhook. Sono controllati ordine PayPal, ordine Lumia, tranche, importo esatto, valuta e stato COMPLETED. Un importo ricevuto incoerente non modifica il saldo e viene segnalato per riconciliazione.

In **Pagamenti → Checkout PayPal aperti**, Management può verificare lo stato direttamente con PayPal. L’azione recupera un incasso già completato; non avvia nuovi addebiti. Un tentativo viene chiuso senza incasso solo se PayPal lo dichiara VOIDED. I pagamenti in attesa rimangono aperti.

Se la risposta alla creazione è andata persa, il tentativo viene ripreso con lo stesso identificativo entro cinque ore. Oltre questo intervallo viene richiesta una verifica manuale presso PayPal prima di iniziare un nuovo pagamento; non cancellare i record a mano per sbloccare l’ordine. La conservazione del tentativo evita di creare un altro pagamento quando l’esito precedente è incerto.

Rimborsi e contestazioni sono segnalati nel registro e richiedono riconciliazione contabile. Questo aggiornamento non esegue rimborsi né emette fatture. Le vecchie registrazioni manuali e i loro storni rimangono nello storico; il checkout proposto ai clienti è solo PayPal.

## Collaudo effettuato e attivazione

254 test automatici passati su database isolati, inclusi autorizzazioni, isolamento tra clienti, preventivi, tranche, firme webhook, callback, retry dopo timeout, doppie notifiche, valuta/importo alterati, recupero admin, ticket collegati, tutorial, verifica Discord ed eliminazione dei canali ticket. Verificati anche sintassi Python/JavaScript, navigazione del tutorial con ripresa e riavvio e patch applicabile. La dashboard e la richiesta erano state controllate su desktop e a 390 px; l’ultima verifica visiva del nuovo tutorial non è stata possibile perché l’uso del browser locale è disabilitato nelle impostazioni Work.

Gli scenari PayPal e Discord dei test usano servizi simulati. Non sono stati eseguiti pagamenti Sandbox o Live, OAuth con la tua app reale, apertura di ticket sul tuo server o deployment sulla VPS. Prima di attivare Live completa sulla tua installazione un acquisto Sandbox con account cliente distinto da Management, verifica il webhook, il saldo e il ticket privato, poi controlla il flusso sul telefono.

Riferimenti dell’integrazione: [creazione ordine PayPal](https://developer.paypal.com/sdk/orders/v2/orders-create/), [acquisizione del pagamento](https://developer.paypal.com/api/orders/v2/orders-capture), [verifica dei webhook](https://developer.paypal.com/api/webhooks/v1).
