# Specifica: spostamento sicuro di tutte le foto e i video nel Cestino

Data: 2026-08-26  
Worktree: `chore/delete-all-media`  
Ambito: Google Photos Cleaner

## Obiettivo

Aggiornare il cleaner browser affinché possa processare tutti gli elementi media raggiungibili dalla vista principale di Google Photos — foto e video — spostandoli nel Cestino dell'account autenticato. Il Cestino non deve mai essere svuotato e nessun elemento deve essere eliminato definitivamente.

## Perimetro e limiti

- Sono inclusi foto e video visibili nella libreria principale dell'account autenticato, compresi elementi archiviati quando sono raggiungibili dalla navigazione supportata; la promessa operativa resta limitata a ciò che la UI consente di enumerare e verificare.
- Gli album non costituiscono una collezione indipendente: contengono riferimenti agli originali. Non è richiesto visitare ogni album separatamente.
- Il Cestino è escluso dall'operazione e non viene svuotato.
- Elementi condivisi da altri account o non eliminabili dall'account corrente non devono essere forzati; devono produrre un esito osservabile e non distruttivo.
- La selezione deve comprendere sia `Photo`/`Foto` sia `Video`.
- Il programma non può usare l'assenza di checkbox, il numero di nodi DOM o la scomparsa della griglia come prova sufficiente di cancellazione.

## Invarianti distruttive

1. Un click Trash è consentito solo in modalità esplicita `--execute --confirm-all-media-to-trash`.
2. Prima del click viene scritto un pending action durabile con gli identificativi/etichette non sensibili del target e il contesto del run.
3. Ogni click deve essere seguito da feedback positivo osservato nella UI, con quantità coerente quando la UI espone la quantità.
4. Timeout, chiusura di target/browser, popup sconosciuto, quantità incoerente o feedback assente rendono l'esito `ambiguous`/`pending_unresolved`: non si ritenta il click. Con la policy esplicita `--pending-action inspect`, dopo il solo timeout bounded di riconciliazione viene rimosso esclusivamente il journal locale e la scansione continua; l'azione resta registrata come non riconciliata e non viene dichiarata riuscita.
5. Non sono ammessi comandi o API per svuotare il Cestino o per la cancellazione definitiva.
6. Il profilo browser è protetto da lock; cleanup e processi non appartenenti al run non devono essere terminati.

## Stati e resume

Il run deve distinguere almeno `running`, `dry_run`, `pending`, `ambiguous`, `scan_failed`, `stop_safe` e `pass_done`. Il resume è permesso solo dopo riconciliazione di pending/checkpoint tramite feedback positivo oppure, con policy esplicita `inspect`, dopo timeout bounded e scarto locale documentato; mai inferendo il successo dal checkpoint.

Il checkpoint deve rendere ripetibile il resume dalla posizione della timeline senza rieseguire un'azione distruttiva già ambigua. Il limite batch deve restare bounded quando specificato.

## Scansione e completamento

- La griglia virtualizzata viene materializzata con scroll bounded e movimento puntatore bounded.
- Prima/dopo ogni scroll e prima della selezione di un target, il browser può eseguire una traiettoria mouse bounded tra punti visibili della pagina, con numero massimo di passi e pause configurabili; il movimento serve solo a stabilizzare la materializzazione/UI, non ad aggirare CAPTCHA, rate limit o controlli di accesso.
- Ogni avanzamento registra evidenze non sensibili: step, delay, conteggi dei controlli giorno prima/dopo, media visibili dopo, indicazione se il DOM è cambiato e conteggio dei movimenti/passi mouse (mai coordinate o contenuto pagina).
- Dopo il numero configurato di errori consecutivi di scansione giorno, il cleaner può eseguire round di recupero bounded e osservabili con stabilizzazione/reset della timeline; se i round sono esauriti, il run si ferma in modo sicuro.
- `pass_done` richiede: nessun pending, nessun checkpoint ambiguo, autenticazione valida, scansione supportata completata e nessun nuovo media selezionabile per il numero richiesto di pass consecutivi.
- Se la UI non consente di dimostrare il completamento, l'esito è `stop_safe` o `scan_failed`, mai successo.

## CLI e prompt engineering

La CLI espone modalità inequivocabili:

- `--dry-run`: osserva e journalizza senza click Trash;
- `--execute`: abilita il flusso distruttivo ma non basta da solo;
- `--confirm-all-media-to-trash`: conferma esplicita e deve essere combinata con `--execute`;
- opzioni bounded per batch, scroll inattivi, errori scan e timeout feedback;
- `--reconcile-pending`: osserva e riconcilia senza click.

Il prompt engineering deve essere conservato in un file versionato, separando il loop di engineering dal runtime distruttivo. Il loop engineering può leggere contesto, eseguire test, modificare codice in piccoli passi e aggiornare evidenze; non può lanciare il cleaner live. Il runtime live richiede preflight account/profilo/lock/pending/checkpoint e conferma esplicita.

## Test richiesti

Prima dell'implementazione di ogni comportamento nuovo si scrivono test fallenti e si osserva il fallimento. La suite deve coprire:

- gating CLI e incompatibilità tra modalità;
- inclusione di foto e video e selezione verificata;
- traiettorie mouse bounded, pause, errori movimento e journaling senza coordinate;
- feedback positivo foto/video, feedback assente, dialog e quantità incoerente;
- pending prima/dopo click, resume e stop fail-closed;
- target/browser chiuso senza retry cieco;
- scroll con DOM materializzato/non materializzato e stop dopo inattività;
- checkpoint, lock, cleanup e process ownership;
- esclusione del Cestino e assenza di operazioni di eliminazione definitiva;
- journaling redatto e criteri di `pass_done`.

## Non-obiettivi

- Svuotare il Cestino.
- Eliminare definitivamente elementi.
- Usare API private di Google o aggirare CAPTCHA/controlli di accesso.
- Terminare processi globalmente per recuperare un browser.
- Dichiarare la cancellazione completa senza prova positiva e scansione conclusa.
