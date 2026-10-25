# Aggiornamento Discord Lumia — 25 ottobre 2026

Questo aggiornamento riguarda il bot. Le pagine e le funzioni del sito restano invariate; le notifiche Discord degli ordini usano una nuova coda persistente. Ordini e pagamenti continuano a essere gestiti dal sito.

## Cosa cambia

- **Eliminazione immediata dei ticket:** Management può eliminare un ticket appena chiuso, dopo la verifica dell'archivio e la conferma `ELIMINA #numero`. Non serve attendere sette giorni. Un ticket aperto non viene cancellato da questo comando.
- **Coda staff privata:** `/ticket coda` e il pulsante «Coda staff» mostrano dieci ticket per pagina, priorità e attesa della risposta. Support vede i ticket ordinari; partnership e segnalazioni restano riservate a Management. Ogni aggiornamento ricontrolla i permessi.
- **Attesa e priorità:** i nuovi messaggi del cliente impostano «attende staff», quelli dello staff «attende cliente». Il proprietario del ticket viene riconosciuto come cliente anche se ha ruoli staff. Sono disponibili anche modifiche manuali e la registrazione della prima risposta staff.
- **Archivi recuperabili:** Management può usare `/ticket archivio numero` anche dopo aver eliminato il canale. Il bot verifica l'integrità del file e registra l'accesso. Gli allegati nella trascrizione conservano i riferimenti originali: non sono copie permanenti dei file Discord.
- **Partnership:** nel relativo ticket Management può salvare stato, nota e storico, con l'operatore che aggiorna la pratica come referente. Gli stati disponibili sono proposta, valutazione, approvata, attiva, conclusa e rifiutata.
- **Preferenze senza DM:** un membro verificato può usare `/preferenze` o il nuovo pannello per selezionare gli interessi, incluso «Discord & Web», direttamente con una risposta privata. Il menu non assegna ruoli staff.
- **Notifiche persistenti:** una notifica ordine non consegnata viene salvata nel database e riprovata per gli errori temporanei. I DM chiusi bloccano i tentativi automatici e producono una segnalazione allo staff. Management dispone di `/notifiche stato` e `/notifiche ritenta identificativo`.
- **Diagnostica:** `/server diagnostica` controlla ruoli, gerarchia, permessi effettivi del bot, accessibilità dei registri ai ruoli pubblici configurati, pannelli, processi periodici e integrità SQLite. Il controllo legge la configurazione senza correggerla automaticamente.
- **Pannello ticket riutilizzato:** ripetere `/ticket pannello` aggiorna il messaggio registrato. Al primo aggiornamento viene cercato e riutilizzato anche il vecchio pannello del bot.

## Come aggiornare l'installazione esistente

1. Dopo il push su `main`, apri [GitHub Actions](https://github.com/scootymadethis/lumia-manager/actions) e attendi l'esito del workflow **Deploy Lumia sulla VPS** relativo al nuovo commit. Serve il runner della VPS online, con le etichette già configurate `self-hosted`, `linux`, `lumia-prod`. Un job in coda non significa che il bot sia già aggiornato.
2. Il workflow costruisce l'immagine, esegue i test, crea un backup prima del riavvio e avvia l'app aggiornata. Conserva configurazione, credenziali e dati esistenti. Non avviare in parallelo un secondo deploy manuale. Se il job fallisce, leggi i suoi log prima di riprovare.
3. In Discord, dal proprietario o da un account autorizzato in `owner_ids`, esegui `/server allestimento` e conferma il riepilogo. Riutilizza le risorse registrate e aggiunge il ruolo «Discord & Web». Controlla che il ruolo del bot sia sopra quelli che deve assegnare.
4. Con Management esegui `/pannelli` per aggiornare anche l'accesso privato alle preferenze, poi `/ticket pannello` per aggiornare il pannello generale.
5. Nei ticket già esistenti usa `/ticket controlli` dove vuoi aggiornare i comandi visibili e aggiungere «Coda staff». I vecchi messaggi storici non vengono riscritti in massa: l'eliminazione immediata dipende dal nuovo codice, anche se un vecchio messaggio menziona ancora l'attesa.
6. Esegui `/server diagnostica` e `/notifiche stato`. Risolvi gli eventuali permessi mancanti segnalati e ripeti la diagnostica.
7. Prova `/preferenze` con un normale membro verificato e DM chiusi. Da Support controlla `/ticket coda`; da Management verifica anche un ticket partnership. Chiudi un ticket di prova, recuperane l'archivio ed eliminalo con la conferma richiesta.

Il bot sincronizza i comandi all'avvio. Se i nuovi comandi non compaiono, controlla prima che il deploy e l'avvio del bot siano terminati correttamente.

Per un controllo dalla VPS, nella cartella standard:

```bash
cd /home/scooty/lumia-manager
git log -1 --oneline
docker compose ps
docker compose logs --tail=80 app
```

Se hai impostato `LUMIA_DEPLOY_DIR`, usa quel percorso. Non ricreare `.env` o `config.json` e non condividere token o log contenenti credenziali.

## Uso quotidiano

| Persona | Operazione | Comando |
| --- | --- | --- |
| Membro verificato | Scegliere interessi senza DM | `/preferenze` |
| Support / Management | Consultare la coda privata | `/ticket coda` |
| Support / Management | Impostare chi deve rispondere | `/ticket attesa risposta` |
| Support / Management | Impostare la priorità | `/ticket priorita livello` |
| Management | Aggiornare una collaborazione | `/ticket partnership stato nota` |
| Management | Scaricare un archivio finale | `/ticket archivio numero` |
| Management | Eliminare un ticket chiuso e archiviato | Pulsante «Elimina ticket» o `/ticket elimina-canale conferma` |
| Management | Controllare notifiche non consegnate | `/notifiche stato` |
| Management | Ritentare dopo aver risolto il problema | `/notifiche ritenta identificativo` |
| Management | Controllare il bot | `/server diagnostica` |

La coda si aggiorna con il pulsante di aggiornamento; le risposte successive all'aggiornamento alimentano i dati di attesa. Non viene ricostruita la cronologia dei messaggi precedenti: per i vecchi ticket puoi correggere l'attesa manualmente. Non sono ancora previsti solleciti automatici allo staff.

## Limiti operativi

Le notifiche temporaneamente non consegnate hanno al massimo sei tentativi automatici, con attesa crescente; il processo controlla fino a dieci notifiche al minuto. Le notifiche in attesa più vecchie di sette giorni scadono; i metadati delle notifiche terminate vengono rimossi dopo trenta giorni. Questa scadenza riguarda le notifiche e non introduce un'attesa per eliminare i ticket.

Un timeout ambiguo o un arresto subito dopo l'invio può causare un DM duplicato al tentativo successivo. Il retry non modifica mai ordini o pagamenti. Esegui una sola istanza del bot sullo stesso database. La diagnostica dei ruoli configurati non certifica ogni combinazione di ruoli personalizzati o i backup della VPS: questi ultimi richiedono controlli separati e prove di ripristino.

Il push del codice e il risultato dei test locali non dimostrano da soli che la VPS o i pannelli Discord siano aggiornati. Per confermarlo servono l'esito del workflow e i controlli dal server indicati sopra.

## Prossime funzionalità utili

- Solleciti per ticket senza risposta, con orari di assistenza e pausa fuori orario.
- Valutazione dell'assistenza alla chiusura e recensioni pubblicate con consenso.
- Risposte rapide per lo staff con anteprima prima dell'invio.
- Scadenze delle partnership e promemoria dei rinnovi.
- Portfolio dei lavori conclusi, pubblicato con il consenso del cliente.
- Backup esterni con prova periodica di ripristino.
