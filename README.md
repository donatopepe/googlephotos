# Google Photos Cleaner

Tool Python + Playwright che apre browser visibile e sposta nel Cestino foto e video Google Photos **un giorno alla volta**, usando il primo giorno disponibile nella posizione timeline corrente, senza svuotare il Cestino e senza eliminazione definitiva.

## Avvertenza

Operazione distruttiva. Il tool sposta foto nel Cestino Google Foto. Google normalmente conserva elementi nel Cestino per un periodo limitato; non usare questo progetto se vuoi una conferma per ogni eliminazione. Il tool non svuota il Cestino.

Usare prima dry-run e verificare account/browser. Non eseguire su account sbagliato. Modalità delete resta bloccata finché eventuali pending o checkpoint ambigui non vengono riconciliati con feedback positivo Google Photos. Con `--pending-action inspect`, dopo il timeout bounded viene eliminato solo il journal locale e la scansione continua senza ripetere il click incerto.

## Installazione

```bash
cd /home/public/googlephotos
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

Se Chromium è già installato in `/usr/bin/chromium`, il tool lo usa direttamente.

Su macOS o quando Chrome è già aperto e autenticato, avvialo con un profilo dedicato e
remote debugging, poi collega il cleaner via CDP. Il collegamento non apre un secondo
browser e non tenta un nuovo login:

```bash
/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
  --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \\
  --user-data-dir="$PWD/data/cdp-profile" https://photos.google.com/
.venv/bin/python main.py --cdp-url http://127.0.0.1:9222 --dry-run --max-batches 1
```

## Primo avvio

```bash
.venv/bin/python main.py --dry-run --max-batches 1
```

Si apre automaticamente browser visibile su `https://photos.google.com/login`. Completa manualmente login Google, 2FA o CAPTCHA. Dopo autenticazione tool passa a `https://photos.google.com/u/0/`. Tool non legge né salva password. Profilo sessione viene salvato in `data/browser-profile/` e ignorato da Git. Non cancellare questa directory: contiene cookie/sessione necessari per riusare accesso.

## Cancellazione automatica

Prima controllare stato processo, lock, pending e checkpoint:

```bash
ps -p "$(cat data/googlephotos.pid 2>/dev/null)" -o pid=,user=,args= 2>/dev/null || true
 test -e data/browser-profile/.googlephotos.lock && echo LOCK_PRESENT || echo LOCK_ABSENT
 test -e data/pending-action.json && echo PENDING_PRESENT || echo PENDING_ABSENT
 python3 -c 'import json; print(json.load(open("data/checkpoint.json")))' 2>/dev/null || true
```

Eseguire una scansione non distruttiva prima del runtime autorizzato:

```bash
.venv/bin/python main.py --dry-run --max-batches 1
```

Dopo aver verificato account, profilo, lock, pending e checkpoint, lo spostamento esplicito di foto **e video** nel Cestino richiede entrambe le autorizzazioni CLI:

```bash
runuser -u rdpuser -- env HOME=/home/rdpuser USER=rdpuser LOGNAME=rdpuser DISPLAY=:10 XAUTHORITY=/home/rdpuser/.Xauthority .venv/bin/python main.py --execute --confirm-all-media-to-trash
```

Nessun comando svuota il Cestino. Per fermare, usa `Ctrl+C`; dopo un esito ambiguo non ripetere il click Trash. `--pending-action inspect` consente, dopo il timeout di riconciliazione, di scartare automaticamente solo il pending locale e continuare; l'evento viene registrato come `pending_discarded_after_timeout` e non costituisce feedback positivo.

## Opzioni

```text
--dry-run              trova foto e video ma non sposta media nel Cestino
--execute              abilita il runtime distruttivo; richiede anche la conferma esplicita
--confirm-all-media-to-trash
                       conferma foto e video selezionati; richiede anche --execute
--max-batches N        limita numero batch
--batch-size N         opzione legacy, non usata in modalità giorno
--profile-dir PATH     profilo browser persistente
--log-file PATH        log runtime, default data/run.log
--cdp-url URL          collega Chrome già autenticato via CDP, senza nuovo login
--max-retries N        tentativi recupero sicuro, default 2
--diagnostics-dir PATH screenshot errori senza page-content, default data/diagnostics
--checkpoint-file PATH checkpoint atomico, default data/checkpoint.json
--exit-on-error        chiude browser dopo errore; default lascia browser aperto
--max-idle-scrolls N   scansioni senza progresso prima dello scroll reale, default 5
--max-day-scan-failures N  errori consecutivi prima di un recupero bounded della timeline, default 3
--selection-size N     massimo numero di media visibili selezionati prima di un solo Cestino, default 1
--scroll-step N        distanza wheel per avanzamento, default 240
--scroll-delay-ms N    attesa dopo scroll, default 1500
--pointer-pause-ms N   pausa tra movimenti mouse bounded, default 40
--pointer-max-steps N  massimo punti per traiettoria mouse bounded, default 4
--inactivity-timeout-seconds N timeout hard per inattività login/scansione, default 300
--pending-action MODE  inspect (default: scarta il journal solo dopo timeout e continua), block o discard esplicito senza riconciliazione
--pending-timeout-ms N timeout bounded per riconciliazione pending, default 30000
```

Tool clicca il primo controllo giorno disponibile `Seleziona tutte le foto a partire da: ...`, include foto e video visibili, poi `Move to trash`/`Sposta nel cestino` e conferma automaticamente il dialogo. Il controllo generico `Delete`/`Elimina` non viene mai usato. I movimenti mouse bounded aiutano la materializzazione della griglia virtualizzata, senza aggirare CAPTCHA o controlli di accesso. Non dipende dal giorno più vecchio. Se DOM non espone giorni, scorre timeline virtualizzata, aspetta caricamento e ripete: una singola scansione senza giorni non significa libreria vuota. Dopo errori consecutivi di checkbox virtualizzati, il cleaner esegue un numero limitato di round di recupero con reset timeline e stabilizzazione; se falliscono, si ferma senza nuovi click distruttivi.

Esempio prudente:

```bash
.venv/bin/python main.py --dry-run --max-batches 1 --batch-size 10
```

Log vengono scritti su stdout e `data/run.log`. Diagnostica strutturata JSONL dettagliata viene scritta in `data/run.jsonl`: include PID/lock/profilo, comando e configurazione, controlli autenticazione, locator/selettori, conteggi DOM prima/dopo scroll, wheel/delay, stato aria prima/dopo selezione, click/dialog/conferma Trash, feedback positivo, riconciliazione pending, checkpoint ed esito terminale. In caso di errore viene salvato solo screenshot in `data/diagnostics/<run_id>/`; non vengono salvati HTML, page content o cookie. URL vengono redatti senza query e nessun cookie/password viene scritto. `data/checkpoint.json` viene aggiornato atomicamente dopo ogni batch. Stati terminali includono `bounded_stop`, `completed`, `idle`, `scan_failed`, `pending` e `ambiguous`; un vecchio checkpoint `state=running` senza `run_id` viene classificato `stale` e non viene ripreso automaticamente.

Prima del Cestino viene scritto `data/pending-action.json` con label non segreta del target e posizione timeline. La scomparsa del target dal DOM o l'assenza della checkbox non dimostrano che Google Foto abbia completato l'azione: il pending resta conservato finché non compare feedback positivo. L'avvio predefinito (`--pending-action block`) ispeziona il pending e termina senza nuovo click né attesa lunga. `--pending-action inspect` registra l'ispezione e termina; `--pending-action discard` cancella il journal solo come autorizzazione esplicita, senza dichiarare Trash completato. `--pending-timeout-ms` limita ogni riconciliazione esplicita.

Autoriparazione prova solo operazioni non distruttive: chiude dialoghi noti, ricarica pagina e ripete scansione fino a `--max-retries`. Se risultato di `Move to trash`/`Sposta nel cestino` è ambiguo, processo salva diagnosi e termina; non ripete click distruttivo.
Eventi JSONL includono `day_scan`, `day_trash_started`, `day_trash_completed` e `day_checkpoint_saved`.

Se layout Google cambia, tool si ferma invece di fare click ciechi. Default lascia browser aperto per diagnosi per 5 minuti dopo errore; usa `--exit-on-error` per chiusura immediata. Per fermare manualmente usa `Ctrl+C`.

### Sessione persistente

Profilo browser persistente è:

```text
data/browser-profile/
```

Non cancellarlo e non avviare tool come `root`. Deve essere usato dallo stesso utente della sessione grafica (`rdpuser` in ambiente RDP). Cookie e sessione vengono riusati al riavvio. Login URL iniziale è `https://photos.google.com/login`, poi tool passa alla libreria.

Una sola istanza può usare profilo. Se appare errore `Browser profile already in use`, chiudi precedente processo oppure usa:

```bash
kill "$(cat data/googlephotos.pid)"
```

Lock applicativo si trova in `data/browser-profile/.googlephotos.lock`; viene rimosso solo se PID proprietario non è più attivo.

## Engineering loop

Il prompt versionato per il ciclo di engineering è `prompts/googlephotos-engineering-loop.md`. Il loop scrive test prima del codice, verifica la suite e **non avvia mai il cleaner live** né passa autorizzazioni distruttive implicitamente.

## Sviluppo

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m compileall -q .
```

Test non usano account Google reale.
