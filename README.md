# Google Photos Cleaner

Tool Python + Playwright che apre browser visibile e sposta nel Cestino le foto Google Foto **un giorno alla volta**, usando primo giorno disponibile nella posizione timeline corrente, senza richiesta di conferma manuale e senza ordinamento cronologico.

## Avvertenza

Operazione distruttiva. Il tool sposta foto nel Cestino Google Foto. Google normalmente conserva elementi nel Cestino per un periodo limitato; non usare questo progetto se vuoi una conferma per ogni eliminazione. Il tool non svuota il Cestino.

Usare prima dry-run e verificare account/browser. Non eseguire su account sbagliato.

## Installazione

```bash
cd /home/public/googlephotos
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

Se Chromium è già installato in `/usr/bin/chromium`, il tool lo usa direttamente.

## Primo avvio

```bash
.venv/bin/python main.py --dry-run --max-batches 1
```

Si apre automaticamente browser visibile su `https://photos.google.com/login`. Completa manualmente login Google, 2FA o CAPTCHA. Dopo autenticazione tool passa a `https://photos.google.com/u/0/`. Tool non legge né salva password. Profilo sessione viene salvato in `data/browser-profile/` e ignorato da Git. Non cancellare questa directory: contiene cookie/sessione necessari per riusare accesso.

## Cancellazione automatica

```bash
.venv/bin/python main.py
```

Nessun prompt per foto. Per fermare, usa `Ctrl+C`; processo termina senza svuotare il Cestino.

## Opzioni

```text
--dry-run              trova batch ma non sposta foto nel Cestino
--max-batches N        limita numero batch
--batch-size N         opzione legacy, non usata in modalità giorno
--profile-dir PATH     profilo browser persistente
--log-file PATH        log runtime, default data/run.log
--max-retries N        tentativi recupero sicuro, default 2
--diagnostics-dir PATH screenshot/HTML errori, default data/diagnostics
--checkpoint-file PATH checkpoint atomico, default data/checkpoint.json
--exit-on-error        chiude browser dopo errore; default lascia browser aperto
--max-idle-scrolls N   scansioni senza progresso prima dello scroll reale, default 5
--selection-size N     massimo numero di media visibili selezionati prima di un solo Cestino, default 1
--pending-action MODE  block (default), inspect o discard esplicito del pending
--pending-timeout-ms N timeout bounded per riconciliazione pending, default 30000
```

Tool clicca il primo controllo giorno disponibile `Seleziona tutte le foto a partire da: ...`, poi `Elimina`/`Sposta nel cestino` e conferma automaticamente il dialogo. Non dipende dal giorno più vecchio. Se DOM non espone giorni, scorre timeline virtualizzata, aspetta caricamento e ripete: una singola scansione senza giorni non significa libreria vuota.

Esempio prudente:

```bash
.venv/bin/python main.py --dry-run --max-batches 1 --batch-size 10
```

Log vengono scritti su stdout e `data/run.log`. Diagnostica strutturata JSONL viene scritta in `data/run.jsonl`. In caso di errore, screenshot e HTML vengono salvati in `data/diagnostics/<run_id>/`; URL vengono redatti senza query e nessun cookie/password viene scritto. `data/checkpoint.json` viene aggiornato atomicamente dopo ogni batch.

Prima del Cestino viene scritto `data/pending-action.json` con label non segreta del target e posizione timeline. La scomparsa del target dal DOM o l'assenza della checkbox non dimostrano che Google Foto abbia completato l'azione: il pending resta conservato finché non compare feedback positivo. L'avvio predefinito (`--pending-action block`) ispeziona il pending e termina senza nuovo click né attesa lunga. `--pending-action inspect` registra l'ispezione e termina; `--pending-action discard` cancella il journal solo come autorizzazione esplicita, senza dichiarare Trash completato. `--pending-timeout-ms` limita ogni riconciliazione esplicita.

Autoriparazione prova solo operazioni non distruttive: chiude dialoghi noti, ricarica pagina e ripete scansione fino a `--max-retries`. Se risultato di `Elimina`/`Sposta nel cestino` è ambiguo, processo salva diagnosi e termina; non ripete click distruttivo.
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

## Sviluppo

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m compileall -q .
```

Test non usano account Google reale.
