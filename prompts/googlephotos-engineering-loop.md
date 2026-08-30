# Google Photos Cleaner — engineering loop prompt v1

## Missione

Migliorare in modo incrementale il cleaner browser per processare foto e video dell'account Google Photos autorizzato e, **solo durante un'esecuzione runtime esplicitamente armata**, spostarli nel Cestino. Il Cestino non deve essere svuotato e gli elementi non devono essere eliminati definitivamente.

## Separazione obbligatoria

Questo prompt governa esclusivamente il **loop di engineering**. Il loop può leggere il repository e la memoria di progetto, analizzare log già esistenti, scrivere test, modificare codice, eseguire verifiche locali e aggiornare evidenze documentali.

Il loop **NON DEVE**:

- avviare il cleaner live;
- eseguire `main.py` in modalità distruttiva;
- passare `--execute` o `--confirm-all-media-to-trash` a un comando runtime;
- cliccare UI Google Photos, usare un profilo autenticato o contattare Google Photos;
- svuotare il Cestino o introdurre percorsi di eliminazione definitiva;
- interpretare una richiesta vaga, un loop ricorrente o un test verde come autorizzazione operativa.

Qualsiasi esecuzione live richiede un'invocazione separata, manuale e consapevole dell'operatore, con account, profilo, lock, pending e checkpoint verificati prima dell'avvio.

## Ciclo di lavoro

1. Leggi spec, piano, handoff, memoria e stato Git prima di proporre modifiche.
2. Controlla modifiche non committate: non sovrascriverle né assumere che siano opera del loop.
3. Scegli un solo blocco coerente e definisci il criterio di accettazione.
4. Scrivi prima un test fallente e osserva il RED.
5. Implementa il minimo codice necessario per il GREEN.
6. Esegui test mirati, suite completa, compileall e `git diff --check`.
7. Verifica che nessun file runtime, segreto, cookie o contenuto pagina sia stato aggiunto.
8. Aggiorna il log/evidenza append-only con file, comandi, risultato e rischi residui.
9. Ferma il ciclo se emergono ambiguità distruttive, UI non riconosciuta, pending irrisolto o necessità di una nuova decisione.

## Invarianti di sicurezza

- Un click Trash è consentito solo dal runtime con entrambe le opzioni `--execute --confirm-all-media-to-trash`.
- Foto e video devono essere trattati entrambi; elementi non posseduti non vanno forzati.
- Pending durabile prima del click e feedback positivo dopo il click sono obbligatori.
- Assenza di un nodo DOM, scomparsa di una checkbox o conteggio DOM non dimostrano un'azione completata.
- Timeout, target chiuso, popup sconosciuto o quantità incoerente implicano stop fail-closed senza retry del click.
- Il movimento mouse eventualmente implementato deve restare bounded, visibile e finalizzato solo alla stabilizzazione della UI; non deve aggirare CAPTCHA, rate-limit o controlli d'accesso.

## Output del ciclo

Riporta sempre:

- modifica realizzata e file coinvolti;
- test RED osservato e test GREEN eseguiti;
- comando di suite completa e relativo esito;
- eventuale dry-run locale (mai live delete) e relativo perimetro;
- rischi o decisioni ancora necessarie;
- conferma che non è stata avviata alcuna azione live.
