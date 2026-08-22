# Piano: Google Photos Browser Cleaner

## File

**Create:**
- `main.py`
- `googlephotos_cleaner/__init__.py`
- `googlephotos_cleaner/cli.py`
- `googlephotos_cleaner/automation.py`
- `googlephotos_cleaner/browser.py`
- `tests/test_cli.py`
- `tests/test_automation.py`
- `requirements.txt`
- `README.md`
- `.gitignore`
- `data/.gitkeep`

## Wave 1 — Contratti e CLI

### Task 1 — Definire opzioni CLI e configurazione

**Files:** `tests/test_cli.py`, `googlephotos_cleaner/cli.py`, `main.py`

- Scrivere prima test fallenti per parsing dei default, `--dry-run`, `--max-batches` e propagazione del codice d'errore.
- Implementare il parser e l'entry point senza avviare il browser durante il parsing.
- Verificare che il limite batch accetti interi positivi e rifiuti valori non validi.

### Task 2 — Aggiungere dipendenze e protezioni locali

**Files:** `requirements.txt`, `.gitignore`, `data/.gitkeep`, `googlephotos_cleaner/__init__.py`

- Dichiarare Playwright.
- Ignorare profilo persistente, log, cache, virtualenv e segreti.
- Creare il package minimo.

## Wave 2 — Motore di automazione

Dipende da Wave 1.

### Task 3 — Implementare il contratto dell'adapter browser

**Files:** `tests/test_automation.py`, `googlephotos_cleaner/browser.py`

- Scrivere test con adapter fake per sessione autenticata/non autenticata, numero di elementi e azione di cestinamento.
- Implementare un'interfaccia piccola che permetta di testare l'orchestratore senza Google.
- Implementare l'avvio Playwright con profilo persistente e browser visibile.

### Task 4 — Implementare elaborazione batch deterministica

**Files:** `tests/test_automation.py`, `googlephotos_cleaner/automation.py`

- Scrivere test fallenti per dry-run, batch limit, progressione, terminazione su libreria vuota e stop su errore.
- Implementare il ciclo: attendi sessione, individua pagina più vecchia, seleziona batch, cestina, verifica esito, registra log.
- Applicare timeout e guardie per evitare click ciechi o loop infiniti.

## Wave 3 — Documentazione e integrazione

Dipende da Wave 2.

### Task 5 — Collegare CLI, logging e runtime

**Files:** `googlephotos_cleaner/cli.py`, `googlephotos_cleaner/automation.py`, `googlephotos_cleaner/browser.py`, `main.py`

- Collegare gli argomenti al runner.
- Configurare logging su stdout e `data/run.log`.
- Mantenere `--dry-run` privo di side effect verso Google Foto.
- Chiudere correttamente il browser in caso di errore o interruzione.

### Task 6 — Scrivere guida operativa e avvertenze

**Files:** `README.md`

- Documentare installazione virtualenv, installazione dipendenze e browser Playwright.
- Documentare primo login manuale, sessione locale, esecuzione dry-run, esecuzione senza conferma e recupero dopo errore.
- Evidenziare che il tool sposta foto nel Cestino e che il recupero/lo svuotamento definitivo è responsabilità dell'utente.

## Wave 4 — Diagnostica e autoriparazione

Dipende da Wave 3.

### Task 7 — Aggiungere eventi diagnostici, checkpoint e artefatti

**Files:** `tests/test_diagnostics.py`, `googlephotos_cleaner/diagnostics.py`

- Scrivere test fallenti per eventi JSONL, redazione di URL sensibili, checkpoint atomico e nomi artefatti per run.
- Implementare logger diagnostico strutturato con `run_id`, timestamp UTC, fase, tentativo e contesto non sensibile.
- Implementare salvataggio screenshot/HTML solo su errore e checkpoint senza cookie/password.

### Task 8 — Aggiungere retry e autoriparazione sicura

**Files:** `tests/test_automation.py`, `googlephotos_cleaner/automation.py`

- Scrivere test fallenti per retry limitati su errori recuperabili, reload/nuova scansione e stop su stato ambiguo dopo azione distruttiva.
- Implementare policy esplicita: recupero solo prima dell'azione distruttiva; nessun retry del click cestino dopo timeout.
- Registrare ogni tentativo e aggiornare checkpoint dopo batch completato.

### Task 9 — Integrare browser diagnostics e opzioni CLI

**Files:** `tests/test_browser.py`, `tests/test_cli.py`, `googlephotos_cleaner/browser.py`, `googlephotos_cleaner/cli.py`, `main.py`, `.gitignore`

- Aggiungere hook browser per reload, dismiss di dialoghi noti, screenshot e HTML diagnostici.
- Aggiungere `--max-retries`, `--diagnostics-dir` e `--checkpoint-file`.
- Configurare logger JSONL e cleanup sicuro in caso di interruzione.
- Ignorare checkpoint, JSONL e diagnostics locali.

### Task 10 — Documentare diagnosi e recupero

**Files:** `README.md`

- Documentare percorsi log/diagnostics/checkpoint, esempi di eventi e ripresa.
- Spiegare che stato ambiguo dopo cestinamento termina il processo senza retry distruttivo.

## Wave 5 — Persistenza sessione e avvio idempotente

Dipende da Wave 4.

### Task 11 — Proteggere profilo persistente e ownership sessione

**Files:** `tests/test_browser.py`, `googlephotos_cleaner/browser.py`, `main.py`

- Scrivere test fallenti per riuso del profilo, assenza di cleanup distruttivo e rifiuto di profilo già usato.
- Validare directory profilo e creare solo directory mancanti.
- Avviare browser con utente della sessione grafica e usare lock/controllo processo per impedire due istanze.
- Registrare percorso profilo e utente non sensibili nei log.

### Task 12 — Documentare riavvio senza logout

**Files:** `README.md`, `.gitignore`

- Documentare che profilo persistente non va cancellato.
- Documentare stop/ripresa, profilo occupato e recupero da processo terminato.
- Ignorare file di lock runtime senza rimuovere cookie.

## Wave 5 — Persistenza sessione e avvio idempotente

Dipende da Wave 4.

### Task 11 — Proteggere profilo persistente e ownership sessione

**Files:** `tests/test_browser.py`, `googlephotos_cleaner/browser.py`, `main.py`

- Scrivere test fallenti per riuso del profilo, lock attivo/stale, assenza di cleanup distruttivo e rifiuto di profilo già usato.
- Validare directory profilo e creare solo directory mancanti.
- Aggiungere lock applicativo con PID e rilascio in `finally`; rimuovere lock stale solo se PID non esiste.
- Usare path assoluti e verificare utente/processo della sessione grafica.
- Registrare percorso profilo e utente non sensibili nei log.

### Task 12 — Mantenere browser visibile sugli errori e documentare riavvio

**Files:** `tests/test_cli.py`, `googlephotos_cleaner/cli.py`, `main.py`, `README.md`, `.gitignore`

- Scrivere test fallenti per `--exit-on-error` e comportamento di default senza chiusura immediata.
- Documentare che profilo persistente non va cancellato.
- Documentare stop/ripresa, profilo occupato e recupero da processo terminato.
- Ignorare file di lock runtime senza rimuovere cookie.

## Wave 6 — Cancellazione per giorno

Dipende da Wave 5.

### Task 13 — Selezionare giorno più vecchio

**Files:** `tests/test_browser.py`, `googlephotos_cleaner/browser.py`

- Scrivere test fallenti per selettore italiano/inglese del controllo giorno e per esclusione del controllo globale.
- Implementare `select_oldest_day()` usando etichette `Seleziona tutte le foto a partire da:` / `Select all photos starting from:`.
- Selezionare un solo controllo giorno, verificare `aria-checked="true"` e restituire identificativo/etichetta giorno.

### Task 14 — Cestinare giorno e ripetere scansione

**Files:** `tests/test_automation.py`, `googlephotos_cleaner/automation.py`, `googlephotos_cleaner/browser.py`

- Scrivere test fallenti per dry-run, limite giorni, checkpoint per giorno e stop su azione ambigua.
- Implementare ciclo giorno-per-giorno: scansione, selezione, `Elimina`/`Sposta nel cestino`, conferma, attesa, reload.
- Non usare più selezione tile-per-tile nel percorso operativo.

### Task 15 — Aggiornare diagnostica e documentazione del nuovo flusso

**Files:** `tests/test_cli.py`, `README.md`, `.gitignore`

- Documentare cancellazione un giorno alla volta e conferma automatica del dialogo.
- Registrare label/data del giorno negli eventi JSONL e checkpoint.
- Aggiornare esempi CLI e avvertenze.

## Wave 7 — Recupero selettore giorno

Dipende da Wave 6.

### Task 16 — Scansione robusta del controllo giorno

**Files:** `tests/test_browser.py`, `googlephotos_cleaner/browser.py`

- Scrivere test fallenti per controllo nascosto, controllo stale dopo reload, scroll incrementale e nuova scansione.
- Implementare locator con `:visible`, attesa di stabilità, scroll incrementale e fallback su selettori semantici.
- Se nessun controllo visibile esiste dopo limite di scansioni, restituire libreria vuota o errore diagnostico distinto.

### Task 17 — Retry del ciclo giorno prima dell'azione distruttiva

**Files:** `tests/test_automation.py`, `googlephotos_cleaner/automation.py`

- Scrivere test fallenti per retry su errore di selezione, nessun retry dopo click cestino e progressione dopo reload.
- Usare `max_retries` per selezione/reload; lasciare invariata policy azione distruttiva ambigua.
- Registrare tentativi e stato del giorno.

## Wave 8 — Correzione visibilità controlli Google Foto

Dipende da Wave 7.

### Task 18 — Rimuovere falso negativo `:visible`

**Files:** `tests/test_browser.py`, `googlephotos_cleaner/browser.py`

- Scrivere test fallente: controllo restituito dal locator semantico con `is_visible() == True` deve essere selezionabile anche se pseudo-selettore `:visible` non lo restituisce.
- Rimuovere `:visible` da `DAY_SELECTORS`; filtrare i locator usando `is_visible()` e selezionare primo controllo visibile.
- Mantenere controllo globale escluso tramite prefisso label; restituire `None` solo quando nessun controllo semanticamente valido è presente.

## Wave 9 — Hover controlli giorno

Dipende da Wave 8.

### Task 19 — Rendere cliccabile il controllo giorno

**Files:** `tests/test_browser.py`, `googlephotos_cleaner/browser.py`

- Scrivere test fallente per hover sul contenitore padre prima della verifica visibilità.
- Per ogni candidato giorno: hover sul contenitore data, attesa breve, verifica visibilità e click.
- Se hover non rende il controllo cliccabile, passare al candidato successivo o restituire errore diagnostico; non fare force-click.

## Wave 10 — Timeline virtualizzata e caricamento progressivo

Dipende da Wave 9.

### Task 20 — Rilevare nuovi giorni dopo scroll

**Files:** `tests/test_browser.py`, `googlephotos_cleaner/browser.py`

- Scrivere test fallenti per `advance_timeline()` che scorre contenitore timeline, attende stabilizzazione e restituisce se DOM/timeline è cambiato.
- Identificare il contenitore scrollabile Google Foto, confrontare scrollTop/scrollHeight e label giorni prima/dopo.
- Non dichiarare vuota libreria quando l'attuale DOM non espone giorni.

### Task 21 — Terminare solo dopo esaurimento verificato

**Files:** `tests/test_automation.py`, `tests/test_cli.py`, `googlephotos_cleaner/automation.py`, `googlephotos_cleaner/cli.py`

- Scrivere test fallenti per tentativi scroll consecutivi senza progresso e per stop configurabile `--max-idle-scrolls`.
- Quando `select_oldest_day()` restituisce `None`, chiamare `advance_timeline()` e ripetere; terminare solo al superamento della soglia senza progresso.
- Registrare `timeline_advanced`, `timeline_idle` e `timeline_exhausted` con checkpoint.

### Task 22 — Documentare attese e ripresa

**Files:** `README.md`

- Documentare caricamento progressivo, motivo per cui non basta una singola scansione e soglia idle configurabile.

## Wave 11 — Posizione timeline continua

Dipende da Wave 10.

### Task 23 — Eliminare reset timeline fra giorni

**Files:** `tests/test_browser.py`, `googlephotos_cleaner/browser.py`

- Scrivere test fallente: seconda scansione giorno non chiama `page.goto(PHOTOS_URL)`; l'inizializzazione libreria avviene una volta dopo login/recovery.
- Separare navigazione iniziale della libreria da scansione del controllo giorno.
- Dopo cestino, attendere refresh locale e riesaminare timeline corrente; scroll piccolo solo se nessun controllo giorno è disponibile.

### Task 24 — Verificare progressione giorni intermedi

**Files:** `tests/test_automation.py`, `googlephotos_cleaner/automation.py`

- Scrivere test fallente per sequenza di giorni caricati, incluso il caso 2 agosto → 1 agosto senza salto/reset.
- Conservare policy di stop su azione distruttiva ambigua.

## Wave 12 — Verifica post-cestino nella stessa pagina

Dipende da Wave 11.

### Task 25 — Distinguere dialogo conferma da esito immediato

**Files:** `tests/test_browser.py`, `googlephotos_cleaner/browser.py`

- Scrivere test fallenti per due esiti validi dopo click `Sposta nel cestino`: dialogo di conferma visibile oppure selezione sparita/notifica riuscita.
- Non cercare una seconda conferma inesistente come errore ambiguo.
- Mantenere stessa pagina/browser/timeline; nessun relaunch o reset in recovery.

### Task 26 — Conservare policy su vera ambiguità

**Files:** `tests/test_automation.py`, `googlephotos_cleaner/automation.py`

- Scrivere test fallente per stop solo quando né dialogo né esito post-azione verificabile appaiono entro timeout.
- Conservare screenshot/HTML e browser aperto in questo solo caso.

## Wave 13 — Sandbox Chromium

Dipende da Wave 12.

### Task 27 — Attivare sandbox Chromium

**Files:** `tests/test_browser.py`, `googlephotos_cleaner/browser.py`, `README.md`

- Scrivere test fallente per configurazione `chromium_sandbox=True`.
- Configurare Playwright persistent context con sandbox attiva e nessun argomento `--no-sandbox`.
- Documentare requisito sandbox e verificare processo Chromium effettivo senza flag proibito.

## Wave 14 — Fallback singolo media item

Dipende da Wave 13.

### Task 28 — Selezionare media quando controllo giorno non è cliccabile

**Files:** `tests/test_browser.py`, `googlephotos_cleaner/browser.py`

- Scrivere test fallenti per fallback: day control non disponibile/non cliccabile ma checkbox foto/video visibile.
- Individuare singolo media checkbox tramite label `Foto -` / `Video -` (italiano) e `Photo -` / `Video -` (inglese), fare hover sul contenitore e cliccare un item.
- Restituire label media come unità elaborata; non cliccare controllo giorno non verificato.

### Task 29 — Verificare esito immediato post-cestino

**Files:** `tests/test_browser.py`, `googlephotos_cleaner/browser.py`, `tests/test_automation.py`

- Attendere breve polling della scomparsa selezione dopo click cestino.
- Dialogo viene confermato solo se `role=dialog` è presente; assenza dialogo più selezione sparita è successo.
- Ambiguità solo se selezione resta attiva e nessun dialogo/feedback verificabile appare entro timeout.

## Wave 15 — Pending action e riconciliazione post-cestino

Dipende da Wave 14.

### Task 30 — Journal atomico azione distruttiva pendente

**Files:** `tests/test_diagnostics.py`, `googlephotos_cleaner/diagnostics.py`

- Scrivere test fallenti per salvataggio atomico, lettura e cancellazione di `pending-action.json` senza cookie/password.
- Salvare target label, tipo, timestamp e posizione timeline prima del primo click cestino.

### Task 31 — Riconciliare esito incerto senza doppio click

**Files:** `tests/test_browser.py`, `tests/test_automation.py`, `googlephotos_cleaner/browser.py`, `googlephotos_cleaner/automation.py`, `main.py`

- Scrivere test fallenti: target assente dopo refresh = completato; target presente = azione non completata e può essere selezionata una sola nuova volta.
- Dopo click senza dialogo/selezione sparita, non sollevare ambiguità immediata: mantenere journal e tornare al ciclo di riconciliazione.
- Non rilanciare browser, non cancellare profilo e non duplicare click sullo stesso journal senza conferma del DOM.

### Task 32 — Documentare journal di ripresa

**Files:** `README.md`, `.gitignore`

- Documentare `data/pending-action.json`, riconciliazione dopo crash e dati non segreti conservati.

## Wave 16 — Rimozione semantica ordine cronologico

Dipende da Wave 15.

### Task 33 — Rinominare flusso per posizione corrente

**Files:** `tests/test_browser.py`, `tests/test_automation.py`, `googlephotos_cleaner/browser.py`, `googlephotos_cleaner/automation.py`, `README.md`

- Rimuovere riferimenti operativi a oldest/più vecchio da nomi, log e documentazione.
- Mantenere scansione del primo controllo disponibile nella posizione timeline già aperta.
- Verificare che nessun metodo effettui scroll verso una data specifica o resetti timeline per ordinare.

## Wave 17 — Tolleranza errori di selezione

Dipende da Wave 16.

### Task 34 — Saltare target UI stale senza fermare ciclo

**Files:** `tests/test_automation.py`, `googlephotos_cleaner/automation.py`

- Scrivere test fallente per timeout/selettore stale su un giorno e continuazione su giorno/media successivo.
- Dopo retry esauriti su `select_current_day()`, registrare `day_scan_skipped`, chiamare advance_timeline e proseguire; nessun click cestino avviene per target fallito.
- Terminare solo dopo soglia idle timeline, non dopo singolo errore locator.

## Wave 18 — Nessun scroll automatico e flag Chromium puliti

Dipende da Wave 17.

### Task 35 — Rimuovere automazione non richiesta

**Files:** `tests/test_browser.py`, `tests/test_automation.py`, `googlephotos_cleaner/browser.py`, `googlephotos_cleaner/automation.py`, `README.md`

- Scrivere test fallenti per assenza flag `AutomationControlled` e per ciclo senza `advance_timeline()` automatico.
- Rimuovere argomento Chromium non supportato.
- Quando scansione non trova target: attesa breve e `timeline_idle`, browser resta nella stessa posizione senza scroll o terminazione automatica.

## Verifica finale

- `python3 -m pytest -q`
- `python3 main.py --help`
- `python3 main.py --dry-run --max-batches 1` con adapter/runtime verificabile e senza account reale, se l'ambiente lo consente.
- Controllo `git status` per assicurare che non siano presenti profili, cookie, log o segreti.
