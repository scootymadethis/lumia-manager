# Lumia Workspace · 17 ottobre 2026

Questo aggiornamento comprende il nuovo workspace, la landing cinematica e tutte le modifiche della versione precedente: verifica Discord, DM di ingresso e Stripe per tranche. Basta installare questo pacchetto, anche se non hai ancora applicato quello precedente.

## Cosa trovi nel manager

- Home con progetti attivi, incassi, residui e prossime azioni.
- Board per fase ed elenco alternativo, ricerca, filtro per stato e preferiti.
- Ricerca rapida di pagine e progetti con `Ctrl K` / `⌘ K`.
- Agenda delle milestone e delle tranche datate.
- Centro attività con messaggi, consegne e risposte alle revisioni.
- Conversazione per progetto; note interne visibili solo a Management.
- Consegne tramite link HTTPS, approvazione del cliente o richiesta di modifiche.
- Esportazioni CSV dei progetti e dei movimenti, limitate ai dati accessibili all’account.
- Creazione ordine con selezione del cliente per nome; ID manuale come alternativa.
- Tutorial iniziale con waypoint, evidenziazione dei controlli e progressi salvati per account e ruolo.

La landing aggiunge una scena iniziale in 3D durante lo scroll sui desktop adatti, una rete animata fra FiveM, Minecraft e Discord, rotazioni più evidenti, luce al puntatore e card interattive. I loghi restano gli SVG originali forniti. Lo scroll è nativo; schermi bassi, assenza di JavaScript e movimento ridotto hanno una presentazione leggibile senza sequenze fissate.

## Aggiorna l’installazione esistente

L’installer conserva `.env`, `config.json`, `compose.yaml`, `Caddyfile`, testi personalizzati e volume Docker. Nel `.env` modifica solo questi tre valori pubblici:

```dotenv
LUMIA_PUBLIC_URL=https://manager.lumiadevelopment.it
LUMIA_SITE_URL=https://lumiadevelopment.it
LUMIA_DISCORD_INVITE=https://discord.gg/lumiadevelopment
```

Token e chiavi Stripe rimangono quelli già configurati. I dati vengono mantenuti aggiungendo le tabelle per messaggi e consegne; nessun ordine o pagamento viene cancellato.

### 1. Dal PC Windows

Apri PowerShell e sostituisci i due segnaposto con il tuo utente Ubuntu e l’IP della VPS:

```powershell
scp "C:\Users\scooty\Downloads\Lumia Development\outputs\lumia-workspace-2026-10-17.zip" UTENTE_UBUNTU@IP_DELLA_VPS:~/
```

### 2. Sulla VPS Ubuntu

```bash
sudo apt update
sudo apt install -y unzip python3
mkdir -p ~/lumia-workspace-update
unzip -o ~/lumia-workspace-2026-10-17.zip -d ~/lumia-workspace-update
bash ~/lumia-workspace-update/install.sh ~/lumia-manager
```

`~/lumia-manager` deve essere **la cartella della tua installazione attuale**, quella che contiene `.env`, `config.json`, `compose.yaml` e `bot.py`. Se li hai in un altro percorso, modifica solo l’ultimo argomento. Mantieni il progetto Compose e il volume già esistenti.

L’app deve avere già un contenitore Compose `app` creato. L’installer verifica il manifest, salva sorgenti e configurazione in una cartella protetta sotto `backups/`, costruisce l’immagine, ferma brevemente l’app ed esegue un backup del database prima del nuovo avvio. Verifica ZIP, integrità SQLite e risposta delle pagine di landing e login.

Se una fase fallisce, tenta il ripristino dei sorgenti, dell’ambiente e dell’immagine precedente. Conserva il database attuale per evitare di perdere pagamenti già registrati. Il percorso dei backup viene stampato; contiene anche una copia privata del vecchio `.env` e non va condiviso.

### 3. Controlla l’avvio

```bash
cd ~/lumia-manager
sudo docker compose ps
sudo docker compose logs --tail=80 app cloudflared
```

Apri `https://manager.lumiadevelopment.it/login`, accedi con Discord e avvia il tutorial. Il tour compare al primo accesso della nuova versione per ciascun ruolo. L’installer controlla le pagine all’interno del contenitore; i controlli pubblici sul tunnel e quelli sui servizi reali restano necessari.

## Uso quotidiano

### Management

1. Da **Nuovo ordine**, scegli il cliente e inserisci progetto, totale e accordi. Se il membro non è disponibile nell’elenco, usa **Il cliente non è nell’elenco?** e inserisci l’ID. Selezione e ID alternativo non possono indicare due persone diverse.
2. Gestisci i progetti dalla board oppure passa alla vista elenco. Lo stato si cambia nel dettaglio; le card non si trascinano per evitare cambi involontari.
3. Nel progetto aggiungi milestone e piano a tranche come nella versione precedente.
4. Usa **Conversazione** per parlare con il cliente. Se selezioni **Nota interna al team**, il testo resta accessibile soltanto a Management, anche nel centro attività.
5. In **Consegne → Aggiungi una consegna**, inserisci un link HTTPS e le istruzioni per la prova. Può essere un collegamento a un file, a una demo o a un ambiente di test. Il manager non carica file sul server e non rende privato un link esterno pubblico.
6. Controlla la risposta del cliente. Se richiede modifiche, pubblica una nuova consegna quando è pronta: la precedente risposta rimane conservata.

Solo il cliente associato all’ordine può approvare o richiedere modifiche. L’approvazione non registra pagamenti e non completa automaticamente il progetto o una milestone: questi passaggi rimangono espliciti.

### Clienti

1. **Tocca a te** raccoglie preventivi, tranche disponibili e consegne da controllare.
2. Apri un progetto per leggere gli accordi, seguire le milestone e parlare con il team.
3. Apri la consegna, provala e scegli **Approva consegna** oppure **Richiedi modifiche**, descrivendo ciò che va rivisto. La risposta è unica per quella versione.
4. Paga la tranche disponibile con Stripe. Ogni Checkout richiede la tua conferma; il webhook aggiorna il saldo.
5. In **Attività** ritrovi messaggi, consegne e revisioni; **Segna come lette** aggiorna il contatore.

### Tutorial, preferiti e ricerca

La guida spiega la pagina che stai usando, evidenzia i controlli e mantiene il focus nei suoi pulsanti. `Esc`, la X o **Più tardi** la chiudono. Puoi riprenderla con **Fammi da guida** nella barra laterale, **Serve una mano?** nel fondo pagina o dal menu account su mobile. Il punto raggiunto viene salvato nel database per account e ruolo; in assenza di salvataggio server viene mantenuto nel browser.

I preferiti e la scelta board/elenco sono salvati sul browser e separati per account e ruolo: non vengono sincronizzati fra dispositivi. La ricerca rapida funziona con tastiera e tocco; `↑`, `↓`, `Invio` ed `Esc` permettono di usarla senza mouse.

Le conversazioni mostrano gli ultimi 200 messaggi accessibili; il centro attività raccoglie le 80 attività più recenti. I messaggi precedenti rimangono nel database. I CSV contengono solo progetti e pagamenti autorizzati; non includono le note interne. Gli importi usano la virgola decimale e le celle testuali potenzialmente interpretate come formule vengono neutralizzate.

## Landing e Cloudflare

Se hai già applicato le due rotte, lasciale così:

| Dominio | Servizio del tunnel |
| --- | --- |
| `lumiadevelopment.it` | `http://app:8080` |
| `manager.lumiadevelopment.it` | `http://app:8080` |

Lascia **HTTP Host Header** vuoto per conservare l’hostname originale. Se lo specifichi, usa il dominio corrispondente per ciascuna rotta, senza protocollo. La landing vive sulla root del dominio principale e il manager sul sottodominio. Non servono un secondo contenitore o un secondo server web.

Il tunnel si riconnette con IP dinamico senza un aggiornamento DDNS del record A. Mantieni il bypass cache sul manager e il webhook raggiungibile senza challenge interattive. L’invito `discord.gg/lumiadevelopment` è quello richiesto ed è ancora da attivare.

## Discord e Stripe già configurati

Le nuove funzioni del workspace non richiedono nuove chiavi o un nuovo endpoint. Restano:

```text
OAuth Discord: https://manager.lumiadevelopment.it/auth/callback
Webhook Stripe: https://manager.lumiadevelopment.it/webhooks/stripe
```

Se non hai ancora applicato gli embed e i pannelli del redesign precedente, dopo il riavvio esegui su Discord:

```text
/server stile
/server testi
/pannelli
/ticket pannello
/server embed
/server diagnostica
```

La verifica degli ingressi si gestisce con `/verifica stato`, `/verifica disattiva durata:30m`, `/verifica disattiva` e `/verifica attiva`. La pausa senza durata resta attiva fino alla riattivazione manuale.

Eventi Stripe, configurazione iniziale del tunnel, backup e dipendenze voice opzionali sono descritti in `AGGIORNAMENTO-REDESIGN.md`, incluso nel progetto. Il bot attuale continua a non riprodurre audio: le dipendenze voice non sono necessarie alle sue funzioni.

## Controlli prima dell’uso reale

Il rapporto locale è `VERIFICHE-WORKSPACE.txt`. Prova sul server due account distinti, una nota interna, un messaggio pubblico, una consegna con revisione e un piano Stripe in sandbox. Verifica il tutorial anche su un telefono reale: l’emulazione non riproduce completamente Safari, tastiera e safe area.

Fonti tecniche: [dialog nativo e focus, W3C](https://www.w3.org/WAI/WCAG22/Techniques/html/H102), [Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/), [Stripe webhook](https://docs.stripe.com/webhooks). I riferimenti di design e copy della landing rimangono nella guida precedente.
