# Piano: spostamento sicuro di tutte le foto e i video nel Cestino

Spec approvata: `doc/specs/2026-08-26-delete-all-google-photos-media.md`

Decisione successiva: con richiesta utente esplicita, `--pending-action inspect` scarta automaticamente il solo journal locale dopo timeout bounded e continua la scansione senza ripetere il click incerto.

Decisione successiva: dopo errori consecutivi di selezione del giorno, il cleaner esegue round bounded di reset/stabilizzazione della timeline prima di terminare con `scan_failed`.
Worktree: `/Users/donato/googlephotos/.worktrees/delete-all-media`  
Branch: `chore/delete-all-media`

## Files

**Create:**
- `doc/specs/2026-08-26-delete-all-google-photos-media.md` — specifica ratificata.
- `doc/plans/2026-08-26-delete-all-google-photos-media.md` — questo piano.
- `prompts/googlephotos-engineering-loop.md` — prompt versionato per il loop di engineering, privo di esecuzione live implicita.

**Modify:**
- `googlephotos_cleaner/cli.py` — flag di esecuzione/conferma e parametri bounded.
- `googlephotos_cleaner/automation.py` — gating distruttivo, esiti, pending/resume e criteri di completamento.
- `googlephotos_cleaner/browser.py` — inclusione coerente foto/video, mouse motion bounded, scroll evidence e feedback Trash.
- `googlephotos_cleaner/diagnostics.py` — journal/checkpoint redatti e stato di run.
- `main.py` — wiring CLI, lifecycle e terminal summary.
- `README.md` — istruzioni dry-run/execute, limiti, prompt e loop.
- `HANDOFF-2026-08-24-googlephotos-scan.md` — aggiornamento append-only delle evidenze.
- `.gitignore` — eventuali artefatti del loop.
- `tests/test_cli.py` — test CLI.
- `tests/test_automation.py` — test macchina di stato.
- `tests/test_browser.py` — test adapter, selezione, scroll e pointer motion.
- `tests/test_diagnostics.py` — test redazione e checkpoint.
- `tests/test_lock.py` — test ownership/lock se richiesti dal wiring.

**Delete:**
- Nessun file.

## Wave 1 — contratti CLI e engineering prompt

### Task 1 — CLI fail-closed e prompt del loop

**File ownership:** `googlephotos_cleaner/cli.py`, `tests/test_cli.py`, `prompts/googlephotos-engineering-loop.md`, `README.md` (solo sezioni CLI/prompt).  
**Dipendenze:** nessuna.

RED:
- Aggiungere test che `--execute` senza `--confirm-all-media-to-trash` fallisce.
- Aggiungere test che la conferma senza `--execute` fallisce.
- Aggiungere test che dry-run resta non distruttivo anche se la conferma è presente, oppure definire e testare l’incompatibilità scelta.
- Aggiungere test per i parametri positivi bounded di timeout, idle scroll e failure limit.

Implementazione:
- Introdurre flag espliciti e validazione parser senza prompt interattivi.
- Documentare nel prompt l’obiettivo foto+video, il solo spostamento nel Cestino, gli invarianti, i criteri di successo e le stop condition.
- Dichiarare nel prompt che il loop non esegue cleaner live; il runtime deve essere invocato separatamente e manualmente.

Comandi scoped:
```bash
python3 -m unittest tests.test_cli
```

## Wave 2 — core state machine e adapter browser

### Task 2 — macchina di stato e pending fail-closed

**File ownership:** `googlephotos_cleaner/automation.py`, `tests/test_automation.py`.  
**Dipendenze:** Task 1 solo per i nomi dei flag se necessari; nessuna dipendenza runtime da Task 1.

RED:
- Testare rifiuto di click in assenza di gating esplicito.
- Testare pending block immediato senza attesa lunga.
- Testare riconciliazione solo con feedback positivo.
- Testare esito ambiguo senza retry Trash, pending conservato e stop.
- Testare che `pass_done` richieda scansione completa/criteri vuoti e non derivi solo da `max_batches` salvo esito esplicitamente bounded.
- Testare resume da checkpoint senza ripetere il click ambiguo.

Implementazione:
- Aggiungere capability/contract di autorizzazione distruttiva al `Cleaner`.
- Preservare compatibilità degli interi restituiti, ma valorizzare sempre `last_outcome`.
- Distinguere `running`, `pending`, `ambiguous`, `scan_failed`, `stop_safe`, `pass_done` negli eventi/checkpoint.
- Applicare policy `block`, `inspect`, `discard` solo dove esplicitamente richiesta; default block.
- Mantenere nessun retry dopo click incerto.

Comandi scoped:
```bash
python3 -m unittest tests.test_automation
```

### Task 3 — selezione foto/video e pointer motion bounded

**File ownership:** `googlephotos_cleaner/browser.py`, `tests/test_browser.py`.  
**Dipendenze:** Task 2 per il contratto di esito solo se l’adapter lo richiede; altrimenti parallelizzabile concettualmente, ma viene serializzato per condividere il test gate.

RED:
- Testare selettori per etichette italiane/inglesi di foto e video senza duplicati.
- Testare traiettoria mouse con massimo punti e pause configurabili usando una fake page che registra `mouse.move` e `wait_for_timeout`.
- Testare che le coordinate non vengano journalizzate.
- Testare scroll evidence prima/dopo e distinzione DOM cambiato/non cambiato.
- Testare target visibile, checkbox verificata, popup feedback positivo foto/video e feedback assente/quantità incoerente.
- Testare target/browser chiuso come errore ambiguo senza seconda azione.

Implementazione:
- Centralizzare selettori media includendo foto e video in entrambe le lingue.
- Implementare helper pointer path bounded con punti generati da bounding box/viewport, passo massimo, pause limitate e gestione fail-closed.
- Usarlo durante avanzamento timeline e materializzazione/selezione, senza tentare bypass di challenge o access-control.
- Emettere solo conteggi di movimenti/passi e pause nel diagnostic event.
- Rendere le evidenze di scroll strutturate e redatte.
- Conservare feedback positivo come unica conferma dell’azione Trash.

Comandi scoped:
```bash
python3 -m unittest tests.test_browser
```

## Wave 3 — diagnostica, wiring e documentazione operativa

### Task 4 — checkpoint/journal e lifecycle

**File ownership:** `googlephotos_cleaner/diagnostics.py`, `main.py`, `tests/test_diagnostics.py`, `tests/test_lock.py`, `README.md` (sezioni lifecycle).  
**Dipendenze:** Task 2 e Task 3.

RED:
- Testare redazione URL/query e campi sensibili.
- Testare stati terminali coerenti quando pending/checkpoint restano presenti.
- Testare cleanup lock solo per owner corretto e processo terminato.
- Testare wiring dei flag e summary con outcome reale.

Implementazione:
- Rendere gli eventi sufficienti a ricostruire preflight, selezione, click, feedback e chiusura.
- Aggiungere process metadata sicuri e profilo normalizzato, senza credenziali o contenuto pagina.
- Assicurare lifecycle `run_started → ... → cleaner_stopped → run_finished` una sola volta.
- Non terminare PID estranei e non usare kill forzato salvo ownership verificata e timeout documentato.

Comandi scoped:
```bash
python3 -m unittest tests.test_diagnostics tests.test_lock tests.test_cli
```

### Task 5 — README e handoff evidenze

**File ownership:** `README.md`, `HANDOFF-2026-08-24-googlephotos-scan.md`.  
**Dipendenze:** Task 4.

- Documentare comandi dry-run obbligatorio, comando execute esplicito, account/profilo, Cestino non svuotato, resume, pending e stop safe.
- Documentare che “tutti” è limitato ai media enumerabili e verificabili nella libreria principale; album e Archivio non sono collezioni indipendenti se la UI non li espone come originali separati.
- Annotare pointer motion come stabilizzazione UI bounded e non come bypass anti-bot.
- Aggiornare il handoff solo con risultati realmente verificati e comandi eseguiti.

Comandi scoped:
```bash
git diff --check
```

## Wave 4 — gate completo

### Task 6 — suite completa e review

**File ownership:** tutto il deliverable.  
**Dipendenze:** Task 1–5.

Eseguire:
```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
git diff --check
```

Poi eseguire eventuale dry-run bounded solo se ambiente, profilo e account sono verificati; mai execute in loop automatico. Conservare output journal/log e aggiornare il handoff con fatti osservati. Richiedere code review e correggere ogni finding critico/moderato prima di proporre merge.

## Criteri di accettazione

- La CLI rende impossibile un click Trash senza doppia autorizzazione esplicita.
- Foto e video sono selezionati senza affidarsi a un solo prefisso linguistico.
- Pointer motion è bounded, testato, osservabile solo tramite conteggi e non permette bypass di accesso.
- Ogni azione distruttiva ha pending prima del click e feedback positivo dopo il click.
- Errori ambigui non producono retry ciechi.
- Il Cestino non viene mai svuotato e il codice non contiene un percorso di eliminazione definitiva.
- Test, compileall e diff check passano con output fresco.
- Nessuna conclusione live viene dichiarata senza evidenza runtime corrente.
