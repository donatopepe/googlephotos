# Google Photos Browser Cleaner

## Obiettivo

Creare un tool Python che apra automaticamente un browser visibile, acceda a Google Foto tramite una sessione autenticata dall'utente e sposti nel Cestino tutte le foto della libreria senza chiedere conferma per ogni operazione.

## Vincoli e sicurezza

- Il tool non raccoglie né salva password, codici 2FA o CAPTCHA.
- Il primo accesso avviene manualmente nella finestra del browser aperta dal tool.
- Cookie e storage della sessione vengono conservati in una directory locale dedicata, esclusa da Git.
- Il profilo persistente deve essere aperto sempre dallo stesso utente della sessione grafica Google. Il tool non deve cancellare o ricreare il profilo durante un normale riavvio.
- Se il profilo è già in uso, il tool deve terminare con errore esplicito invece di aprire un secondo browser che potrebbe bloccare o danneggiare sessione.
- Il lock del profilo va gestito esplicitamente con file lock applicativo; lock stale può essere rimosso solo dopo aver verificato che PID non esista più.
- Il processo deve restare attivo e lasciare browser visibile quando un errore è stato diagnosticato; non deve chiudere, rilanciare o ricaricare l'intero browser Chrome tra giorni o dopo un errore recuperabile.
- Il browser Chrome persistente viene aperto una sola volta per esecuzione. Il tool non esegue scroll: opera esclusivamente su primo controllo già visibile nella viewport corrente, ordinato dall'alto verso il basso e da sinistra verso destra.
- Errori prima dell'azione distruttiva non devono chiudere la finestra senza dare tempo all'utente di leggere la diagnosi.
- Il browser resta visibile durante l'automazione.
- Le operazioni usano l'interfaccia di `photos.google.com`, non endpoint privati chiamati direttamente dal programma.
- La cancellazione significa spostamento nel Cestino di Google Foto; lo svuotamento definitivo non viene eseguito automaticamente.
- Nessun prompt interattivo deve interrompere l'elaborazione di ciascuna foto.
- Il tool deve interrompersi davanti a una schermata di login, a un layout non riconosciuto o a un'azione non verificabile, invece di operare alla cieca.

## Comportamento previsto

1. Il comando `python3 main.py` riusa il profilo browser dedicato e apre `https://photos.google.com/login`; creazione iniziale è consentita solo se directory è vuota.
2. Se la sessione non è autenticata, il programma attende che l'utente completi login, 2FA o CAPTCHA manualmente.
3. Dopo l'accesso, il programma naviga esplicitamente a `https://photos.google.com/u/0/`, non considera `/login` o pagine marketing come autenticazione.
4. Il programma individua il primo controllo disponibile di selezione del giorno nella posizione timeline corrente, riconoscibile da un'etichetta come `Seleziona tutte le foto a partire da: ...`, e seleziona l'intero giorno in un'unica azione. Non calcola né forza ordinamento cronologico. Se un giorno contiene una sola foto/video e non espone controllo giorno selezionabile, seleziona il singolo media item associato al gruppo e lo sposta nel Cestino.
5. Il programma verifica che la selezione del giorno o del singolo media item sia attiva, clicca `Elimina`/`Sposta nel cestino`, conferma automaticamente solo se appare realmente un dialogo e accetta la scomparsa selezione come esito immediato valido. Se la selezione rimane attiva ma il target non è più presente dopo un refresh locale, considera successo; se resta presente, non ripete il click e salva il target in pending journal per riconciliazione all'avvio successivo.
6. I controlli giorno di Google Foto hanno larghezza zero finché non viene fatto hover sul relativo contenitore: il programma fa hover sul contenitore padre e poi verifica `locator.is_visible()`/bounding box prima del click. Se il controllo individuato diventa stale dopo refresh locale, esegue nuova scansione del DOM senza reimpostare timeline all'inizio.
7. Il programma registra giorno, timestamp e contatore e continua dalla posizione timeline corrente. Non torna all'inizio della libreria dopo ogni cancellazione: prima riesamina giorni già caricati e usa scroll piccoli solo quando non sono disponibili controlli giorno.
8. In caso di errore, perdita sessione, elemento non riconosciuto o timeout, salva il log e resta attivo con browser visibile, salvo `--exit-on-error`. Errori di selezione/locator prima del click cestino non arrestano il ciclo: vengono registrati, il target viene saltato temporaneamente e il tool avanza nella stessa timeline. Un successivo avvio riusa la stessa sessione e riparte dopo una nuova scansione.
9. Assenza di selettori giorno nel DOM non equivale a libreria vuota. Il programma resta nella posizione timeline corrente e attende un refresh locale; non esegue scroll automatico.
10. Se dopo più scansioni locali non trova target, registra `timeline_idle` e resta con browser aperto; non dichiara la libreria vuota e non cambia posizione timeline automaticamente.

## Scelte tecniche

- Python 3.11+ (compatibile con Python moderno disponibile sul sistema).
- Playwright Python e Chromium locale con sandbox Chromium attiva (`chromium_sandbox=True`); `--no-sandbox` e `--disable-blink-features=AutomationControlled` non sono consentiti.
- `argparse` per opzioni essenziali: `--dry-run` per contare e loggare senza eliminare, `--max-batches` per limitare un'esecuzione e `--batch-size` mantenuto solo per compatibilità.
- Logging su stdout e su `data/run.log`; nessun dato immagine viene scaricato.
- Profilo persistente in `data/browser-profile/`.

## Testabilità

La logica non deve dipendere interamente da selettori sparsi nella funzione principale. Un modulo di automazione deve separare:

- attesa dell'autenticazione;
- rilevamento del primo controllo giorno disponibile nella posizione corrente e selezione dell'intero giorno;
- azione di cestinamento;
- attesa/verifica post-azione;
- gestione dei limiti e del dry-run;
- scroll progressivo, attesa caricamento e criterio di esaurimento della timeline virtualizzata.

I test unitari devono verificare almeno parsing delle opzioni, contatore dei batch, modalità dry-run e comportamento su errore/timeout con un adapter browser simulabile. I test non devono usare account Google reali.

## File previsti

- `main.py`: entry point CLI.
- `googlephotos_cleaner/`: package con logica applicativa e adapter Playwright.
- `tests/`: test unitari con browser mockato.
- `requirements.txt`: dipendenza Playwright.
- `README.md`: installazione, primo login, uso e avvertenze.
- `.gitignore`: profilo browser, log locali e cache.
- `data/.gitkeep`: directory locale per runtime.

## Criteri di accettazione

- Il comando di avvio apre una finestra browser visibile sull'indirizzo Google Foto.
- Il primo login può essere completato manualmente e viene riutilizzato in un avvio successivo.
- In `--dry-run` nessuna azione di cestinamento viene eseguita.
- In esecuzione normale il tool non chiede conferma per ogni foto e procede a batch.
- Un errore di riconoscimento o di rete non causa click ripetuti incontrollati: il tool registra l'errore e termina.
- Il repository non include password, cookie, profili browser o log generati.
- I comandi operativi non devono eseguire `rm -rf data/browser-profile`.

## Diagnostica e autoriparazione

Il tool deve fornire osservabilità e recupero automatico limitato, senza usare click casuali o ripetere azioni distruttive in stato ambiguo.

- Ogni esecuzione riceve un `run_id` e scrive eventi JSONL in `data/run.jsonl` con timestamp UTC, fase, livello, tentativo, URL senza query string, conteggio batch e messaggio.
- Eventi minimi: avvio, login richiesto/completato, scansione, selezione, azione cestino iniziata/completata, checkpoint salvato, retry, errore, diagnosi catturata, terminazione.
- In caso di errore il tool salva screenshot PNG e HTML della pagina in `data/diagnostics/<run_id>/`; il percorso viene scritto nel log. Nessun contenuto viene inviato a servizi esterni.
- Un checkpoint JSON atomico in `data/checkpoint.json` conserva solo stato operativo non segreto: ultimo batch completato, conteggio, timestamp e stato. Non conserva password, cookie o HTML.
- Un pending-action journal atomico conserva label del target selezionato e posizione timeline prima del click. Dopo un risultato post-cestino incerto il prossimo ciclo ricarica localmente e riconcilia: target assente = completato, target presente = riprende selezione senza duplicare il click precedente.
- Errori sicuri e non distruttivi (timeout di navigazione, dialogo transitorio, selettore non trovato prima della selezione) possono attivare al massimo `--max-retries` tentativi. Ogni tentativo registra causa, recupero e risultato.
- Recupero consiste in chiusura di dialoghi transitori, attesa, reload della pagina Foto e nuova scansione con selettori alternativi.
- Dopo l'invio di un'azione di cestinamento, timeout o stato non verificabile produce `destructive_action_ambiguous`: il tool cattura diagnosi, salva checkpoint e termina senza ripetere il click.
- Il recupero automatico non svuota il Cestino, non ri-autentica con password e non cambia codice o selettori a runtime.
