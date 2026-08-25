# Handoff — Google Photos scan reliability and runtime diagnostics

Data: 2026-08-25, aggiornato dopo verifica run pointer-motion e policy inspection transitoria
Repo: `/home/public/googlephotos`
Branch principale: `main`
HEAD corrente: `6c44822 Add human-like pointer motion for Photos scanning`
Worktree sviluppo storico: `/home/public/googlephotos/.worktrees/verbose-runtime-diagnostics`
Commit worktree diagnostics storico: `4065d8e record chosen selector after viewport ordering`
Commit closure precedente: `2e0fc79 close runtime diagnostics state flow`
Commit terminal state finalization precedente: `51cfcde finalize terminal state journal events`
Commit handoff/summary precedente: `237122e complete handoff terminal summary context`
Commit runtime handoff final precedente: `a09cb43 finalize runtime handoff contract`
Commit outcome preservation precedente: `36ffe6e preserve cleaner safety outcomes in final journal`
Commit runtime proof audit precedente: `89922f2 complete runtime proof audit fields`
Commit Trash proof/handoff cleanup precedente: `e4b0b66 record truthful Trash proof evidence`
Commit quiet finalization precedente: `2bd3a67 quiet diagnostic artifact failure reporting`
Commit branch finalization precedente: `96da191 document safe branch finalization`
Commit integration readiness precedente: `0ba2264 document integration readiness evidence`
Commit handoff fact repair precedente: `5b57ad6 repair current handoff facts`
Commit current facts final precedente: `858fd06 finalize current handoff facts`
Commit final review evidence precedente: `aec7846 add final review evidence`
Commit final review sync precedente: `2c50f90 sync final review evidence facts`
Commit final review test sync precedente: `ae14419 update final review current commit test`
Commit handoff assertion sync precedente: `84c8b3d sync handoff current commit assertion`
Commit final review stability precedente: `f172390 test handoff status shape not commit literal`
Commit single-run-start precedente: `f321d99 avoid duplicate run started journal events`
Commit handoff sync stability precedente: `35841eb stabilize handoff current status`
Commit profile-owner dry-run result: `dc5f25f record profile-owner dry-run result`
Commit sandbox dry-run safety plan corrente: `b43a9fd document sandbox dry-run safety plan`
Live bounded dry-run attempted in isolated `/tmp/googlephotos-dryrun-20260824`; root attempt failed because sandbox; profile-owner attempt reached auth/day scan then visibility timeout; no Trash action.
Worktree `fix/verbose-runtime-diagnostics` pulito dopo commit
Branch delta vs main: 43 file, aggiornato da git diff; nessun merge eseguito
Nessun merge su `main`; main resta `fcabfe5`

## Obiettivo

Risolvere scansione Google Photos senza regressioni, senza duplicare processi, preservando profilo persistente e sicurezza Trash.

## Stato corrente

- Current main commit: `6c44822` (`Add human-like pointer motion for Photos scanning`)
- Recent integrated commits: `dff6e17` safe DOM diagnostics, `e8f66fe` quantity-first Trash popup, `8ff9181` Playwright-compatible regex flags, `6a7a86a` JavaScript-compatible numbered captures, `1be148f` stabilized fallback media selection, `6c44822` human-like pointer motion.
- `_wait_for_trash_feedback()` rejects non-positive timeout values before page access and records terminal `final=true`, `positive_feedback=false`, `feedback_source=None`, error type/message before re-raising observer failures.
- Terminal pending/destructive outcomes now explicitly record `positive_feedback=false` and `feedback_source=None`; stop state cannot be mistaken for Trash proof.
- Cleaner re-entry terminal events now record `result=already_terminal`, `positive_feedback=false`, and `feedback_source=None`.
- Public `cleaner_stopped` and `run_finished` summaries now explicitly record non-proof evidence: `positive_feedback=false`, `feedback_source=None`, with `result=terminal_summary` and `result=run_finished` respectively.
- All `Cleaner`-emitted `cleaner_terminal_state` events now receive centralized defaults: `result=terminal_state`, `positive_feedback=false`, `feedback_source=None`; explicit re-entry `result=already_terminal` is preserved.
- Checkpoint writes now preserve safe context fields `reason`, `run_id`, `pid`, `ppid`, `uid`, and `username`; sensitive keys remain excluded.
- Bounded passes now finalize checkpoint state as `bounded_stop` with `reason=max_batches`; no-photo completion uses `completed`, idle timeline uses `idle`, scan exhaustion uses `scan_failed`, pending reconciliation uses `pending`, and ambiguous Trash uses `ambiguous`.
- Public terminal lifecycle events now preserve `Cleaner.stop_requested` instead of deriving it only from exception outcomes.
- Legacy checkpoint `state=running` without `run_id` is normalized as `state=stale`, `resumable=false`, `reason=legacy_running_without_run_identity`; Cleaner emits `checkpoint_stale`, stops safely, and never resumes unknown work.
- README now documents preflight checks, `rdpuser` ownership, safe delete invocation, explicit checkpoint states, and stale checkpoint blocking.
- Error diagnostics now save screenshot only; HTML/page-content artifacts are no longer captured or reported. CLI and README descriptions match this policy.
- Debug-only policy: public client-side HTML/JavaScript may be read transiently in memory with approved browser tooling, never saved, logged, or copied into handoff/artifacts. Secrets, cookies, tokens, headers, media URLs, session data, and anti-robot challenge material remain prohibited; proprietary anti-robot controls must not be copied or reproduced.
- Positive pending reconciliation events now explicitly use `result=reconciled`, `positive_feedback=true`, and `feedback_source=browser_positive_feedback`; unresolved pending events explicitly use `positive_feedback=false`, `feedback_source=None`.
- Pending/destructive transition events now carry explicit evidence fields: `day_trash_pending` (`pending_reconciliation`), `day_trash_unresolved` (`pending_unresolved`), `destructive_action_pending` (`pending_reconciliation`), and `destructive_action_ambiguous` (`ambiguous`); non-proof transitions always use `positive_feedback=false`, `feedback_source=None`.
- Media `scan_failed` now records `result=scan_failed`, `positive_feedback=false`, `feedback_source=None`, and terminal checkpoint `state=scan_failed`, `reason=max_retries`; `main` records terminal failure checkpoints with run/process context and `run_failed` non-proof evidence.
- `main.run()` now finalizes `KeyboardInterrupt` as checkpoint `state=interrupted`, `reason=keyboard_interrupt`; browser close failures as `state=close_failed`, `reason=browser_close_failed`; terminal summaries and `run_finished` expose matching `checkpoint_state`/`checkpoint_reason` fields, preserving non-proof evidence.
- Failure mapping now preserves Cleaner terminal outcome: `pending_unresolved` → checkpoint `pending` / `pending_reconciliation_failed`; `destructive_ambiguous` → `ambiguous` / `destructive_action_ambiguous`; `stop_safe` → `bounded_stop` / `safe_stop_failed`; `run_failed` includes outcome and checkpoint context.
- Checkpoint loading now classifies `state=running` with missing, foreign, or unverified `run_id` as stale; current Cleaner run identity is required, emits `reason=run_identity_mismatch` for foreign runs or `run_identity_required` when absent, and never resumes unknown work.
- Malformed/unreadable/non-object checkpoint files now become non-resumable stale states: `invalid_checkpoint_json`, `checkpoint_unreadable`, or `invalid_checkpoint_shape`; Cleaner stops before authentication or scanning.
- Checkpoint schema now rejects missing or unknown `state` values as stale: `missing_checkpoint_state` or `unknown_checkpoint_state`; only formal states are accepted for inspection/resume.
- Pending media-batch discard events now explicitly carry `positive_feedback=false`, `feedback_source=None`, and `result=discarded_without_reconciliation`; discard is never reconciliation proof.
- `pending_loaded` now records `result=observed`, `positive_feedback=false`, and `feedback_source=None`; journal observation cannot be mistaken for Trash proof.
- Pending media unresolved and inspect events now carry `result=policy_blocked`, `positive_feedback=false`, and `feedback_source=None`; unresolved state cannot look like proof.
- Legacy pending fallback now clears journal only with `browser_positive_feedback`; missing source emits `pending_unresolved` and preserves journal.
- Pending dry-run/block events now explicitly record `result` (`policy_blocked_dry_run` or `not_attempted`), `positive_feedback=false`, and `feedback_source=None`; they cannot be mistaken for reconciliation proof.
- Explicit `pending_policy=discard` now records `positive_feedback=false`, `feedback_source=None`, and `result=discarded_without_reconciliation`; discard is never presented as Trash proof.
- Missing positive completion source now preserves pending journal and writes checkpoint `state=ambiguous` before stopping; no completion event or retry is emitted.
- Reconciled day completion requires `browser_positive_feedback`; missing source preserves pending/checkpoint state and emits no completion claim.
- Pending reconciliation now clears journal only when target absence is paired with `feedback_source=browser_positive_feedback`; block/inspect policies emit `pending_reconciliation_skipped` and preserve journal without automatic reconciliation.
- Day and media completion diagnostics propagate browser `last_feedback_source`; completion claims now fail closed as `destructive_action_ambiguous` unless source is exactly `browser_positive_feedback`.
- Reconciliation now emits one terminal `trash_reconcile_check` after timeout feedback observation; positive early exits avoid timeout summary duplication while timeout paths retain `trash_reconcile_timeout` summary.
- Reconciliation timeout diagnostics now normalize `checks` and `check` to at least `1`, matching terminal feedback polling semantics even when deadline expires before first loop iteration.
- `wait_for_target_absence()` now marks positive reconciliation checks and timeout summaries with terminal `final=true`; source remains actual observer source or null.
- `wait_for_target_absence()` now records terminal fail-closed reconciliation errors with `final=true`, preserves actual source on positive checks, and re-raises observer failures without claiming reconciliation success.
- `wait_for_target_absence()` reconciliation events now use observer's actual `last_feedback_source`; positive feedback without source stays `feedback_source=None`, never fabricated as browser proof.
- Feedback polling now emits explicit `final=true` check after bounded wait and clears previous source before each observation; stale positive state cannot leak across checks.
- `trash_feedback_check_failed` now carries `matched_count`, `visible_count`, and `feedback_source=None`, including locator enumeration failures; error diagnostics cannot imply positive evidence.
- Feedback candidate diagnostics now have deterministic coverage: one candidate event per label, actual visible/matched counts, and visible-success event ordered after candidate event.
- `trash_feedback_candidate.visible_count` now means actual visible matched locators; `matched_count` preserves raw DOM count. Hidden candidates classify as `dom_candidate_not_visible`.
- Feedback source semantics corrected: positive DOM count is labeled `dom_candidate_not_visible` until actual visibility succeeds; visible success emits `trash_feedback_candidate_visible` with `browser_positive_feedback`.
- Every `trash_feedback_candidate` diagnostic now includes visible count and source classification; positive count is not success until visibility check passes.
- Tests now cover `feedback_source=browser_positive_feedback` on day and media Trash completion evidence; production paths propagate source through confirmation, batch, and reconciliation events.
- Day Trash feedback events now include `feedback_source`; completion evidence consistently identifies browser positive feedback.
- Feedback visibility API failures now emit `trash_feedback_check_failed`, clear source, and return false; no fallback success when visibility cannot be proven.
- Browser feedback now stores `last_feedback_source=browser_positive_feedback` on visible positive evidence and includes source in reconciliation diagnostics.
- Trash feedback checks now fail closed: locator/query/visibility exceptions emit `trash_feedback_check_failed` and return no positive feedback; destructive completion cannot be claimed.
- Terminal `cleaner_stopped` and `run_finished` events now include `browser_cleanup`: `not_started`, `closed`, or `failed`; construction and close failures are distinguishable.
- Reconciliation now rejects non-positive timeout values and records `feedback_source=browser_positive_feedback` whenever positive Trash feedback confirms pending state.
- Pending-policy tests now explicitly cover `block` and `inspect`: both stop with `pending_unresolved`, preserve journal, and never invoke destructive retry. Existing production behavior already enforces this gate.
- Browser constructor now closes partial context, stops Playwright, clears references, and releases profile lock when page creation/navigation fails.
- Pending Trash retry now resolves visible current checkbox target and refuses hidden/stale retry targets before any click.
- Media Trash confirmation now requires visible confirmation locator; hidden confirmation cannot receive click. Handoff test accepts merged-main status shape.
- Visible-feedback fix committed: positive Trash feedback now requires visible feedback text, not hidden/stale DOM text; polling remains bounded and diagnostic.
- Trash feedback polling fix retained: day Trash post-click and confirmation paths poll positive Google Photos feedback before returning success; no DOM disappearance-only success.
- Trash-control fix retained: day/media Trash actions select visible buttons only, log visible button counts, and hidden buttons never receive clicks.
- Stale-target fix retained: every click resolves target from current control; previous control's SVG target cannot be reused after virtualized DOM changes.
- Selection feedback fix retained: after clicking visible SVG/icon target, verification reads clicked day control first; avoids false failure caused by virtualized list reordering. No `force=True`, JS click, or `--no-sandbox`.
- Ancestor-target fix retained: hidden day checkbox resolves visible SVG/icon target through normal Playwright locator API.
- Diagnostics now record `target_count` alongside candidate and visible counts.
- Constructor cleanup now releases profile lock if Playwright startup fails; close tolerates partial initialization.
- Current verification before merge: `197` tests OK; compileall OK; diff check OK.
- Pointer-motion verification: full suite later reached `226` tests OK; compileall and diff check remained clean. `_move_pointer_path()` now uses bounded visible `page.mouse.move()` paths before/after wheel and before checkbox materialization; diagnostics log only move counts and pauses.
- Safe dry-run produced exactly one `run_started`, one `cleaner_stopped`, and one `run_finished`; both terminal events reported `pass_done` and `browser_cleanup=closed`. Post-run safety snapshot: profile lock absent, pending journal absent, unrelated PID `1869` untouched.
- Merge completed into `main` with no conflicts. Post-fix safety snapshot: profile lock absent, pending journal absent, unrelated PID `1869` untouched.
- Root live dry-run attempt: Playwright installed in `.venv`, Chromium launch failed safely because sandbox startup under root is unsupported; journal recorded `profile_lock_acquired → browser_launch_started → browser_launch_failed`; no Trash action.
- Profile-owner bounded dry-run after stale-target fix: auth succeeded; day selection verified `aria_checked_before=false → aria_checked_after=true`; run reached `day_scan`, `day_selection`, `day_checkpoint_saved`, `batch_limit`, `browser_closed`, `cleaner_stopped=pass_done`, and `run_finished=pass_done`. No Trash action.
- Persistent profile owner: `rdpuser:rdpuser`, mode `700`; safe next live attempt must run as `rdpuser`, not root.
- Isolated dry-run: attempted; result `failed` because `Playwright missing`; journal had `run_failed → cleaner_stopped → run_finished`; no Trash action.
- Current verification count: `214` tests OK; real unbounded launch as `rdpuser` completed one day scan after scrolling from `gio 6 giu 2019` to `mar 4 giu 2019`, selected the day, and executed one Trash action. Popup was not detected by observer during reconciliation; no positive completion claim was made. Run ended `pending_unresolved`, checkpoint `state=pending`, `reason=reconciliation_unresolved`, pending journal preserved.
- Real popup verification status: user reported seeing confirmation, but current run journal contains no `trash_feedback_popup` event and no `feedback_source=browser_positive_feedback`; parser remains unverified against this exact live popup rendering.
- Explicit `--pending-action discard` was executed in dry-run mode against the canonical pending journal after ownership/lock checks. It emitted `pending_discarded_manual(result=discarded_without_reconciliation)`, performed `trash_clicks=0`, then stopped bounded with `state=bounded_stop`; canonical `data/pending-action.json` was absent at that point. This did not prove the earlier ambiguous action failed or succeeded.
- A subsequent unbounded delete launch as `rdpuser` was stopped fail-closed on the first day: one Trash interaction became `trash_confirmation_completed(result=ambiguous, positive_feedback=false, feedback_source=None)`, reconciliation timed out, and the run ended `pending_unresolved` with canonical checkpoint `state=pending`, `reason=reconciliation_unresolved`; `data/pending-action.json` was preserved. No all-photos completion claim was made and no automatic retry occurred.
- Trash feedback polling now records safe observer diagnostics on terminal checks: `feedback_category`, `elapsed_ms`, and `remaining_ms`, while preserving exact positive source requirements and fail-closed behavior. This makes missing visible feedback diagnosable without capturing page content.
- Visible quantity-bearing bottom-left toast feedback is now parsed dynamically from rendered visible text, including arbitrary counts such as `Spostate 19 foto nel Cestino` and `Moved 8 photos to Trash`; only `moved_count`, `popup_kind=bottom_left_toast`, and positive source are logged, never raw popup text. Live-region selectors are preferred, with a rendered-text fallback.
- Added explicit `--reconcile-pending` mode: it inspects the existing pending action for positive browser feedback only, never clicks Trash, clears the journal only on `feedback_source=browser_positive_feedback`, and otherwise preserves pending unresolved; without a journal it exits as `nothing_to_reconcile` and never scans/deletes.
- After explicit `--pending-action discard`, a further unbounded delete launch was attempted only after preflight/ownership checks. It discarded the prior journal without reconciliation, clicked Trash once for day `dom 9 giu 2019`, then again ended `trash_confirmation_completed(result=ambiguous)` → `trash_reconcile_timeout` → `pending_unresolved`; no positive completion evidence was observed, so the run stopped and preserved the new pending action. All-photos deletion remains unconfirmed and incomplete.
- Live delete preflight outcome: `day_trash_started → trash_click_started → trash_click_completed → trash_confirmation_completed(result=ambiguous) → trash_reconcile_timeout → day_trash_unresolved(result=pending_unresolved) → cleaner_stopped(outcome=pending_unresolved) → run_finished`; checkpoint `state=pending`, `reason=reconciliation_unresolved`; pending journal preserved for explicit reconciliation.
- The preflight used the persistent profile but an isolated `/tmp` log/diagnostics/checkpoint path; no automatic retry or second destructive action was performed. The canonical pending/checkpoint records were preserved after verification.
- Current feature worktree `fix/terminal-close-checkpoint` was merged into `main`; source worktree clean before merge.
- Main includes terminal checkpoint finalization and fail-closed checkpoint validation. No Trash completion was claimed because positive browser feedback was absent.
- Next safe step: inspect/reconcile the preserved pending action with visible Google Photos feedback; do not retry the destructive action automatically. Trash remains blocked until `feedback_source=browser_positive_feedback` is observed.

## Live run delete — 2026-08-25

- Run `run_id=5ecdbcfa7cf2455294ec0723f00106a9`, launched as `rdpuser` with persistent profile and `--exit-on-error`, completed `77` day/media actions with positive browser proof on every recorded completion: `result=confirmed`, `positive_feedback=true`, `feedback_source=browser_positive_feedback`. Popup observer recorded dynamic quantities, including `moved_count=196`.
- Run stopped fail-closed after three bounded day-scan failures: `outcome=stop_safe`, checkpoint `state=scan_failed`, `reason=max_day_scan_failures`, `processed=77`. No automatic Trash retry occurred.
- Terminal lifecycle is complete and consistent: `browser_closed`, `cleaner_stopped`, `run_finished`; `browser_cleanup=closed`, `pending_exists=false`.
- Post-run safety: PID `1656613` dead, profile lock absent, `data/pending-action.json` absent, persistent profile preserved. PID `1869` remained untouched. This run does not prove all photos were deleted; remaining work requires a new owned run after reviewing `scan_failed` checkpoint.

## Verifica run pointer-motion — 2026-08-25

- Last live run: `run_id=28b63d9997d64f58b5aa39113a0cf960`, launched as `rdpuser`, PID `1650227`; PID is now dead. No terminal lifecycle event was written after the last `day_checkpoint_saved`, so no terminal outcome is inferred.
- Last run produced six positive day completions. Each completion carried `result=confirmed`, `positive_feedback=true`, `feedback_source=browser_positive_feedback`, `reconciled=true`, and `reconciliation=feedback_confirmed`. Popup observer recorded visible quantity feedback, including `moved_count=41`, `popup_kind=bottom_left_toast`.
- Runtime snapshot after run: profile lock absent after verifying owner PID dead and removing only stale `.googlephotos.lock`; `data/pending-action.json` absent; `data/checkpoint.json` remains `state=running`, `batch=6`, `photos=6`, `reason=day_processed`, `run_id=28b63d9997d64f58b5aa39113a0cf960`. Treat checkpoint as non-terminal/stale until a future owned run validates it; do not infer all-photos completion.
- PID `1869` remains alive as unrelated `root python main.py`, cwd `/app`; it was not touched. Persistent profile was preserved and not recreated.
- Selection hardening now includes bounded pointer paths and fresh locator resolution. `trash_action_unavailable` blocks empty selection or missing visible Trash button before any click. No automatic Trash retry was run.

## Historical runtime snapshot

- Processo target associato al repo/profilo: nessuno.
- PID `1869`: `root`, comando `python main.py`, cwd `/app`; estraneo al repo/profilo, non toccato.
- Lock applicativo: assente (`data/browser-profile/.googlephotos.lock` non presente).
- Profilo persistente: `/home/public/googlephotos/data/browser-profile`, preservato; non cancellato/ricreato.
- `data/pending-action.json`: assente al controllo corrente.
- `data/checkpoint.json` corrente:

```json
{
  "batch": 1,
  "photos": 1,
  "state": "running",
  "updated_at": "2026-08-24T14:33:08.859011+00:00"
}
```

- Production journal ultimo run `1c9e1b2f002b4ecba684924ee5805864`:
  `browser_started → run_started → authenticated → pending_unresolved → cleaner_stopped`.
- Live dry-run isolato in `data/launch/run.jsonl`, ultimo run `e5ae27ba1c534801b46498d45747e80b`:
  `browser_started → run_started → authenticated → 2 timeline_advanced → day_scan riuscito → day_selection → day_checkpoint_saved → batch_limit → cleaner_stopped`.
- Live dry-run ha trovato:
  `Seleziona tutte le foto a partire da: gio 13 giu 2019`.
- Nessun Trash dichiarato completato senza feedback positivo.

## Verifiche worktree verbose diagnostics — storico

Historical verification: previous milestones 97/101/103/104/105/106/107/108 tests OK. Current single-run-start: `109` tests OK, compileall OK, diff check OK.

Comandi eseguiti:

```text
python3 -m unittest discover -s tests -p 'test_*.py'  # 101 OK
python3 -m compileall -q .                            # OK
 git diff --check                                      # OK
```

Copertura aggiunta: contesto PID/UID/user/policy, pass terminale senza loop duplicato, un solo pass in `main`, error message sanitizzato, lock owner, pending/checkpoint paths, feedback Trash e locator selezionato.

## Stato closure corrente

Correzioni in worktree, verificate e committate:

- `main.py` esegue un solo pass bounded; non riapre né ripete Cleaner dopo stop.
- `Cleaner.run()` rifiuta re-entry dopo outcome terminale.
- Journal include terminal summary unico da `main`, `run_started`/`cleaner_stopped`/`run_finished` contract, contesto processo/lock/policy/path, messaggi errore sanitizzati.
- Previous ambiguous Trash click was not retried after discard. The later all-photos launch reached a new ambiguous Trash result and was stopped; further destructive launches are blocked until explicit reconciliation with positive visible feedback.

### Rischi da chiudere prima del merge

- Eseguire review conformance manuale sul diff completo.
- Eventi terminali separati: `cleaner_terminal_state` interno Cleaner, un solo `cleaner_stopped` summary centralizzato in `main` dentro `finally`, `run_finished` finale con outcome anche su interrupt/close failure. Summary include process/profile/lock identity, pending/checkpoint paths e outcome. Media Trash completion include `positive_feedback=true`, `result=confirmed`, `feedback_source=browser_positive_feedback`; ambiguous event include error message e nessun completion. Eccezioni dopo outcome Cleaner preservano `destructive_ambiguous`/stop outcome invece di appiattire a `failed`.
- Any future delete run must start with a fresh preflight and must not assume the discarded ambiguous action was unsuccessful; use `--reconcile-pending` first. The explicit reconcile mode never performs a new destructive click.

## Problemi storici

### P0 — Pending persistente bloccava ogni nuovo run

`data/pending-action.json` contiene vecchia azione day ambigua. Ogni avvio entra in riconciliazione, attende fino a 30s, poi emette `pending_unresolved` e termina. Questo è sicuro ma impedisce test/avanzamento.

To-do:

- Definire comando/modalità esplicita per `inspect/reconcile/discard` pending, separato dal normale run.
- Non cancellare pending automaticamente.
- Consentire discard solo con flag esplicito e journal evento forte (`pending_discarded_manual`), mai su DOM absence.
- In dry-run, pending distruttivo deve fermarsi subito senza polling 30s e senza aprire loop browser inutile.
- Aggiungere test CLI e automazione per pending lifecycle.
- Decidere operativamente se l’azione `dom 16 giu 2019` è stata eseguita: solo feedback positivo Google Photos o verifica manuale account può risolvere. Non dedurre dal DOM.

### P0 — Macchina a stati implicita

`Cleaner` usa `stop_requested` booleano e molti `return 0`. Questo ha causato regressioni.

To-do:

- Sostituire con esito esplicito, ad esempio:
  - `CONTINUE`
  - `PASS_DONE`
  - `STOP_SAFE`
  - `PENDING_UNRESOLVED`
  - `DESTRUCTIVE_AMBIGUOUS`
- `main.py` deve eseguire al massimo un pass per esito e non riavviare su `STOP_SAFE`/pending.
- Emit eventi coerenti: `pass_started`, `pass_finished`, `pass_stopped`, `pending_unresolved`, `cleaner_stopped`.
- Test end-to-end del ciclo `main.run()` con fake browser, non solo test di `_run_days()`.

### P0 — Pending day/media kind e riconciliazione

Fallback single photo/video viene marcato `last_selection_kind="media"`, poi pending kind `media`; però il percorso usa ancora `delete_selected_day()` e label day-like. Questo va reso esplicito.

To-do:

- Separare API browser:
  - `delete_selected_day()` per checkbox giorno;
  - `move_selected_to_trash()` per singola foto/video e batch media.
- Restituire target strutturato, non solo stringa:
  `SelectionTarget(kind, label, media_ids/count)`.
- Journal pending con kind corretto e dati minimi.
- Riconciliazione kind-specifica senza chiamare day API per media.
- Test single photo, single video, day multi-photo.

### P0 — Trash feedback e timeout

Regola inviolabile: DOM disappearance/checkbox absence non è completamento.

To-do:

- Centralizzare `TrashResult`: `CONFIRMED`, `PENDING`, `AMBIGUOUS`, `UNAVAILABLE`.
- Ogni path Trash deve richiedere feedback positivo Google Photos.
- `wait_for_target_absence()` deve avere timeout configurabile e bounded; non deve bloccare 30s in dry-run/pending inspect.
- Dopo timeout: pending preservato, nessun secondo click, no timeline reset, stop pass.
- Test feedback positivo/assente, dialog presente/assente, checkbox stale, timeout.

### P1 — Scroll/DOM materialization osservabile

Live dry-run dimostra `timeline_advanced`, ma non journalizza conteggio DOM prima/dopo.

To-do:

- `advance_timeline()` deve riportare evidence:
  `wheel_step`, `delay_ms`, `visible_day_controls_before`, `visible_day_controls_after`, `visible_media_after`.
- Journal `timeline_advanced` con questi dati, senza dati sensibili.
- Distinguere scroll eseguito da DOM realmente cambiato.
- Se DOM non cambia dopo N scroll, stop safe con screenshot/HTML diagnostici.
- Test adapter con fake page che materializza checkbox dopo wheel.

### P1 — Cleanup/process lifecycle

Il vecchio `main.py` root PID `1869` è estraneo e resta attivo. Non avviarlo/fermarlo senza ownership verificata.

To-do:

- Aggiungere PID/run metadata in journal (`pid`, uid, profile path redacted/normalized).
- Verificare lock applicativo e Chromium lock prima di ogni start.
- Start script ufficiale eseguito come `rdpuser`, con `DISPLAY=:10.0`, `XAUTHORITY=/home/rdpuser/.Xauthority`, DBus session.
- Stop script: segnali, attesa, verifica exit; rimozione lock solo se PID morto e lock owner corrisponde.
- Non usare `kill -KILL` salvo processo owned e TERM/INT falliti dopo timeout documentato.
- Aggiungere test lock stale/live/concurrent.

### P1 — Checkpoint semantics

Checkpoint dopo dry-run bounded è `state=running` prima di `cleaner_stopped`; production pending è `state=pending`.

To-do:

- Definire stati checkpoint formali: `running`, `completed`, `bounded_stop`, `pending`, `ambiguous`, `scan_failed`, `idle`.
- Salvare `reason`, `run_id`, `pid`, `processed`, `photos`.
- Test atomicità e stato finale su ogni exit path.

### P1 — README/documentazione

README contiene ancora frase obsoleta: `target assente = azione completata`, contraria al fix positivo-feedback.

To-do:

- Correggere README:
  - assenza DOM non prova Trash;
  - pending resta finché feedback positivo;
  - come eseguire dry-run isolato;
  - come fare inspect/discard manuale pending;
  - come verificare PID/lock.
- Documentare runbook operativo con comandi esatti.

### P2 — Test di integrazione

Suite attuale è principalmente unit/mock.

To-do:

- Test `main.run()` con PlaywrightBrowser fake e fake DiagnosticLog/Checkpoint/Pending.
- Test un solo `run_started` per bounded pass.
- Test `pending_unresolved → cleaner_stopped` senza secondo `run_started`.
- Test `day_scan_failed → timeline_advanced → day_scan`.
- Test positive Trash → reset timeline.
- Test unresolved Trash → no reset/no retry/pending preserved.
- Test process lock ownership.
- Se possibile, Playwright browser test offline con HTML fixture virtualizzato; niente account reale nei test.

## Ordine consigliato

1. Non avviare modalità delete finché pending esistente non viene risolto manualmente o discard esplicito autorizzato.
2. Implementare macchina a stati e pending inspect/discard.
3. Separare selection target day/media.
4. Centralizzare TrashResult e timeout bounded.
5. Aggiungere integration tests `main.run()`.
6. Aggiungere evidence DOM nello scroll journal.
7. Correggere checkpoint e README.
8. Eseguire suite completa e dry-run isolato.
9. Solo dopo autorizzazione esplicita, avviare delete su profilo reale.

## Comandi obbligatori dopo ogni modifica

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
git diff --check
```

## Regole operative inviolabili

- Non cancellare/ricreare `/home/public/googlephotos/data/browser-profile`.
- Non leggere/gestire credenziali.
- Non avviare duplicati.
- Non dichiarare Trash completato da scomparsa DOM/checkbox.
- Riportare sempre PID, ownership lock, eventi journal, pending, checkpoint.
- TDD: test failing prima del codice.
