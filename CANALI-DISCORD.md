# Canali Discord · aggiornamento del 18 ottobre 2026

Questo pacchetto cumulativo comprende le funzioni del sito e del bot già consegnate, la correzione del pannello ticket e le modifiche ai canali richieste il 18 ottobre. Non serve installare prima gli ZIP precedenti.

## Cosa cambia

- Il canale `📋・commesse` diventa **`📋・ᴄᴏᴍᴍɪꜱꜱɪᴏɴɪ`**. La chiave di configurazione resta `staff_orders`, per conservare l'ID e i collegamenti agli ordini.
- I nomi dei canali Lumia, delle categorie e dei ticket esistenti usano i caratteri richiesti. Emoji, numeri e separatore `・` vengono mantenuti. Sono completate anche le lettere mancanti nell'esempio: `ᴊ`, `ᴋ`, `ᴡ`, `x`, `ʏ`; la Q usa il carattere `Q` indicato.
- Il comando **`/server canali`** applica la rinomina tramite gli ID già configurati o registrati da Lumia. Modifica gli stessi canali e i ticket aperti o chiusi ancora presenti. Mantiene ID, messaggi, descrizioni, posizioni e permessi; non crea ruoli, categorie o canali.
- Se un canale è stato collegato manualmente a Lumia nella configurazione, viene usato il suo ID corrente. Una vecchia destinazione sostituita nella configurazione non viene rinominata.
- Le risorse di altri bot che non sono collegate a Lumia restano escluse dalla rinomina, inclusi i canali ServerStats.
- Lumia non crea più il contatore membri, non lo aggiorna periodicamente e non registra più `/statistiche`. La manutenzione dei metadati di sicurezza continua senza leggere o modificare canali statistici.

La rinomina si applica al server Discord configurato, da un account Management. Il bot deve avere **Gestisci canali** sulle risorse da modificare. I comandi vengono sincronizzati al riavvio del bot.

## Installazione sulla VPS esistente

Da PowerShell sul PC, sostituisci `IP_DELLA_VPS` con l'indirizzo usato per SSH:

```powershell
scp "C:\Users\scooty\Downloads\Lumia Development\outputs\lumia-discord-canali-2026-10-18.zip" scooty@IP_DELLA_VPS:~/
ssh scooty@IP_DELLA_VPS
```

Poi nel terminale Ubuntu:

```bash
cd ~/lumia-manager
umask 077
mkdir -p ~/aggiornamenti/lumia-discord-canali-2026-10-18
unzip -o ~/lumia-discord-canali-2026-10-18.zip -d ~/aggiornamenti/lumia-discord-canali-2026-10-18
bash ~/aggiornamenti/lumia-discord-canali-2026-10-18/install.sh ~/lumia-manager
```

L'installer verifica gli hash, salva sorgenti e configurazione, costruisce l'app e crea un backup del database prima del riavvio. Conserva i segreti e i valori personalizzati del `.env`, Compose, testi, configurazione e database. Come negli aggiornamenti precedenti, allinea soltanto i tre indirizzi pubblici Lumia nel `.env`. Non cancellare i volumi e non usare `docker compose down -v`.

Attendi la connessione del bot e, **nel tuo server Discord**, esegui:

```text
/server canali
```

Non serve `/server allestimento`: quel comando è dedicato alla costruzione della struttura iniziale. `/server canali` modifica le risorse presenti e lascia invariati i ruoli. È ripetibile: se i nomi sono già corretti non esegue altre rinomine.

Il comando `/server stile` continua a essere disponibile e include la stessa convenzione per i nomi, ma aggiorna anche i ruoli e le descrizioni standard. Per questa richiesta usa `/server canali`.

## Vecchio contatore Lumia e ServerStats

Con `/server canali`, il riferimento obsoleto `channels.member_counter` viene disattivato nella configurazione attiva del volume. Non serve modificare a mano `config.json` e il canale non viene ricreato al successivo allestimento.

Il vecchio canale vocale viene eliminato soltanto se è vuoto, conserva il nome `👥・membri-N` (anche in small caps) e la sua creazione da parte di Lumia è dimostrata dal registro delle risorse o dal registro attività Discord. Per leggere il registro attività serve **Visualizza registro attività**. Il controllo legge al massimo 200 creazioni di canali: se la creazione è troppo vecchia o il registro non è accessibile, non viene considerata provata.

Se non è possibile verificarlo, il comando mostra il riferimento al canale da controllare. Il contatore resta comunque disattivato in Lumia. Se riconosci che si tratta del vecchio contatore Lumia, puoi eliminarlo manualmente da Discord; i canali di ServerStats devono rimanere. Un canale con persone connesse non viene eliminato dal comando.

I contatori effettivi di ServerStats restano gestiti da ServerStats: questa versione non legge la sua configurazione e non prende il controllo dei suoi canali.

## Controlli e problemi

```bash
cd ~/lumia-manager
sudo docker compose ps -a
sudo docker compose logs --tail=60 app
```

Se il nuovo comando non compare, chiudi e riapri Discord e verifica che il bot risulti connesso nello stesso server configurato. Per verificare il codice contenuto nell'immagine in esecuzione:

```bash
sudo docker compose exec -T app python -c "from pathlib import Path; print('Comando canali:', 'async def channels(' in Path('lumia/setup_server.py').read_text()); print('Stats Lumia rimosse:', 'async def statistics(' not in Path('lumia/community.py').read_text())"
```

I test locali verificano rinomina senza ricreazioni, ID e permessi invariati, ripetizione sicura, gestione dei vecchi contatori e caricamento delle estensioni. Non è stata effettuata una connessione al tuo Discord o alla VPS: le rinomine saranno applicate quando eseguirai il comando dopo l'installazione.
