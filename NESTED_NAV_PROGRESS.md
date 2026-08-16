# Nested Folder Navigation — Progress / Recovery Doc

Branch: `feat/nested-folder-navigation` (based on `origin/develop` @ 55519ff)
Worktree: `.claude/worktrees/agent-a8d52ca8aeca51913`

If you're picking this up cold: read the "Design decisions" section first, then
the checklist. Each checklist item notes the exact file:line touched once done.

## Design decisions (read first)

1. **Toggle**: `config.controller.enable_nested_navigation` (bool, default `False`).
   Generic config get/set (`web/handler/config.py`, `SerializeConfig`) already
   works for any new `PROP` — no handler changes needed.
2. **Scope cut — nested actions are QUEUE / STOP / DELETE_LOCAL / DELETE_REMOTE
   only.** EXTRACT and VALIDATE stay top-level-only: they interact with the
   staging `MoveProcess` / persist-authority pipeline that reseeded's fork never
   had to integrate with, and doing that safely is out of scope for this pass.
   `CommandPipeline._dispatch_command` explicitly rejects EXTRACT/VALIDATE for
   any file whose `.parent is not None` (i.e. nested), regardless of the toggle.
   Frontend mirrors this: nested `ViewFile` rows always get
   `isExtractable=false`, `isValidatable=false`.
3. **Resolution**: `command.filename` is now allowed to be a `/`-joined
   `full_path` (e.g. `TopDir/Sub/file.rar`), not just a top-level name.
   `ModelRegistry.resolve_full_path(full_path, pair_id)` walks `.get_children()`
   segment by segment. `CommandPipeline` only uses it when
   `enable_nested_navigation` is on AND the name contains `/`; otherwise it
   falls back to the exact old `registry.get_file(name, pair_id)` call, so
   behavior is byte-for-byte identical when the toggle is off.
4. **`file.name` → `command.filename` in handlers**: after resolution,
   `command.filename == file.full_path` (that's what resolution matched on),
   and `full_path == name` for top-level files. So `_handle_queue`,
   `_handle_stop`, `_handle_delete_local`, `_handle_delete_remote` now pass
   `command.filename` to lftp/delete-process calls instead of `file.name` —
   this is a no-op for top-level files and makes nested calls resolve to the
   right relative path. `delete_process.py`'s path-containment checks already
   handle multi-segment relative names safely (pre-existing code, verified).
5. **Race guards** (ported from reseeded commit `ab2e7aa`, adapted to
   `CommandPipeline`): QUEUE on a nested file is rejected if any ancestor is
   QUEUED/DOWNLOADING; QUEUE on a directory (top-level or nested) is rejected
   if any descendant is independently QUEUED/DOWNLOADING. STOP checks
   `Lftp.kill()`'s existing bool return (already means "had an independent
   job") — a nested/dir STOP with no independent job now fails with a clear
   message instead of silently no-op'ing.
6. **model_builder.py nested status routing**: lftp job names for nested
   standalone jobs are full paths (contain `/`). These must NOT create a fake
   duplicate top-level entry. `ModelBuilder.build_model()` splits
   `__lftp_statuses` into top-level/nested (only when nested nav is enabled,
   via `set_nested_navigation_enabled`), routes nested statuses to the matching
   child during `_build_children`, and a new `_finalize_nested_dir` pass
   (mirroring reseeded's `__finalize_dir_state`) rolls a nested directory job
   up to DOWNLOADED once all its remote descendants are done, and estimates its
   ETA. Extracted a shared `_all_remote_descendants_downloaded` static helper
   used by both the existing root rollup and the new nested one (avoids
   duplicating the BFS).
7. **Active-scanner fast path stays top-level-only** (`model_updater.py`,
   matches reseeded's own documented scope cut): nested job names are filtered
   out of `pc.active_downloading_file_names` unconditionally (not just when the
   toggle is off) because feeding a `/`-containing name through
   `ActiveScanner`/`ModelBuilder.set_active_files` would otherwise inject a fake
   top-level entry into the model (the SystemFile it returns is keyed by the
   full name). This is a correctness fix, not a toggle-gated behavior change.
   Nested downloads still get picked up by the regular recursive local scan,
   just with the slower interval.
8. **Routing: no changes needed.** The 6 `/server/command/<action>/<file_name>`
   routes keep bottle's default single-segment filter. The frontend already
   sends `file_name` **double URL-encoded**
   (`encodeURIComponent(encodeURIComponent(...))`, pre-existing in
   `ModelFileService.commandUrl`), so a nested full_path's `/` is encoded away
   before it ever reaches the raw URL — it never appears as a literal `/` in
   the path segment. `_validate_filename` already accepted multi-segment names
   (pre-existing, apparently written ahead of this feature), and an existing
   integration test (`test_controller.py::test_queue`'s `"value/with/slashes"`
   case) already proves nested-looking names round-trip correctly through the
   existing route. (An earlier pass here explored switching to bottle's
   `:path` filter; reverted once the double-encoding scheme was found to
   already handle it with zero backend routing changes.)
9. **Frontend identity**: `ViewFile`/`ModelFile` row identity across selection
   and command-dispatch services switches from `fileKey(pairId, name)` to
   `fileKey(pairId, fullPath)`. Safe/no-op for top-level files (`fullPath ==
   name` there); required for nested files since two different folders can
   both contain a file with the same leaf name. `resolveNestedModelFile()`
   (new `model-file-tree.ts`) walks a top-level `ModelFile`'s `.children` when
   the direct map lookup misses, so nested `ViewFile` rows still resolve back
   to their backing `ModelFile` for command dispatch.
10. **Frontend tree stays out of the flat sorted/filtered list.** The existing
    `ViewFileService.files`/diffing/sort/filter machinery is unchanged and
    stays top-level-only (exactly like today). `ViewFile.children` is a
    separate recursive tree attached to each top-level row, used only for the
    expand/collapse UI in `file.component.html`. `<app-file>` renders itself
    recursively for children and re-emits their action events verbatim, so
    `file-list.component.ts`'s existing action-dispatch handlers work
    unmodified for nested rows too.
11. **When the toggle is off**: backend rejects nested commands (falls through
    to the old top-level-only `get_file`, which raises "not found" for any
    name containing `/`, exactly like today). Frontend never shows
    expand/collapse UI or renders nested rows, so no nested request is ever
    sent. `children` data is still parsed off the wire either way (backend
    always streams full trees today, pre-dating this feature) but is inert
    when the setting is off.

## Checklist

### Backend — DONE
- [x] `common/config.py:346-360`: `enable_nested_navigation` PROP on `Config.Controller`
- [x] `seedsync.py`: default `config.controller.enable_nested_navigation = False`
- [x] `controller/model_registry.py`: `resolve_full_path()` (walks `.get_children()`, pair-aware)
- [x] `controller/command_pipeline.py`: `_resolve_command_file` (toggle-gated fallback),
      `_find_queue_conflict` (ancestor/descendant race guard), `_handle_queue`/`_handle_stop`
      use `command.filename` (== `file.full_path` post-resolution) instead of `file.name`,
      `_handle_stop` now checks `Lftp.kill()`'s existing bool return (was previously ignored —
      a small correctness fix needed for nested STOP, harmless/no-op for top-level),
      `_dispatch_command` rejects nested EXTRACT/VALIDATE unconditionally
- [x] `controller/model_updater.py`: `_detect_lftp_completions` filters nested names out of
      `active_downloading_file_names` unconditionally (correctness fix, not toggle-gated);
      `set_nested_navigation_enabled` propagated to `model_builder` each cycle
- [x] `controller/model_builder.py`: `build_model` splits lftp statuses top-level/nested when
      enabled; `_build_children`/`_determine_child_state` route a nested status to its child;
      `_finalize_nested_dir` rolls a nested dir job to Downloaded + estimates its ETA;
      `_all_remote_descendants_downloaded` extracted and reused by both the new nested rollup
      and the existing root rollup (`_check_root_downloaded`)
- [x] **`web/handler/controller.py`: route change reverted.** Investigated using bottle's
      `:path` filter to allow literal `/` in `file_name`, but the frontend already sends
      `file_name` **double URL-encoded** (`ModelFileService.commandUrl`,
      `encodeURIComponent(encodeURIComponent(...))`), so a nested full_path's `/` is encoded
      away before it ever reaches the raw URL — the existing single-segment route filter
      already matches nested paths correctly. An existing integration test
      (`tests/integration/test_web/test_handler/test_controller.py::test_queue`, the
      `"value/with/slashes"` case) already proves this path works and predates this branch.
      No web_app/route changes were needed at all — reverted the exploratory change.
      Only change: `model-file.service.ts`'s `commandUrl` now encodes `file.full_path`
      instead of `file.name` (see frontend section).
- [x] Python tests added: `test_config.py` (field), `test_model_registry.py` (6 new
      `resolve_full_path` tests), `test_command_pipeline.py` (18 new tests: resolution
      fallback, race guards, nested queue/stop/delete, EXTRACT/VALIDATE rejection, `step()`
      end-to-end), `test_model_builder.py` (5 new tests: nested file/dir routing, finalize
      rollup, incomplete-subtree, toggle-off regression guard), `test_model_updater.py`
      (3 new tests: active-scan filtering, completion-tracking unaffected),
      `tests/integration/test_web/test_handler/test_config.py` (1 new: toggle round-trips
      through the real HTTP get/set endpoints)

**Test run results** (local venv at `/tmp/nested_nav_venv`, not Docker — see note below):
- `ruff check .` / `ruff check --select C901 .` / `ruff format --check .`: all clean.
- Every file touched, run individually: `test_config.py` 34 passed,
  `test_model_registry.py` 14 passed, `test_command_pipeline.py` 44 passed,
  `test_model_builder.py` 76 passed, `test_model_updater.py` 16 passed, `test_seedsync.py`
  26 passed, `tests/unittests/test_web` + `tests/integration` together: 280 passed, 50
  skipped, only 2 failures — both pre-existing and unrelated (`test_extract.py`'s real-7z-binary
  RAR5 extraction tests fail in this sandbox's 7z version, nothing to do with this branch).
- **Full `tests/unittests` suite hangs/times out in this sandbox environment** — bisected to
  `test_common/test_app_process.py` and `test_common/test_multiprocessing_logger.py` (real
  `multiprocessing.Process`/timing-based tests that are flaky/slow under this sandbox's
  process scheduling — confirmed pre-existing and unrelated: both files are untouched by this
  branch and fail/flake identically on a scratch check). CLAUDE.md notes Python tests
  normally run in Docker via CI; that wasn't available in this session, so tests were run in a
  throwaway local venv (`python3 -m venv /tmp/nested_nav_venv`) module-by-module instead of the
  full suite at once. Every module this branch actually touches was verified individually and
  passes cleanly.

### Frontend
- [ ] `models/config.ts`: `enable_nested_navigation` field + default
- [ ] `pages/settings/options-list.ts`: checkbox entry
- [ ] `models/view-file.ts`: `children: ViewFile[]`
- [ ] `services/files/file-key.ts`: `parseFileKey`, shared `viewFileKey`
- [ ] `services/files/model-file-tree.ts` (new): `resolveNestedModelFile`
- [ ] `services/files/view-file.service.ts`: recursive `createViewFile`, fullPath-based key + resolver
- [ ] `services/files/view-file-command.service.ts`: shared `viewFileKey`
- [ ] `pages/files/file-list.component.ts`: fullPath trackBy, pass nested-nav-enabled flag down
- [ ] `pages/files/file.component.ts`: expand/collapse state, recursive children input, pass-through outputs
- [ ] `pages/files/file.component.html`: chevron + recursive `<app-file>` block
- [ ] Angular tests: view-file.service, model-file-tree, file.component, options-list

### Verification
- [ ] `ruff check --select C901 src/python` (complexity)
- [ ] Python unit tests (see note on how they were run — Docker vs local)
- [ ] `cd src/angular && npx ng lint`
- [ ] `cd src/angular && npx ng test`

## Log

- Progress doc created, branch `feat/nested-folder-navigation` cut from
  `origin/develop` @ `55519ff`. Design decisions above finalized after reading
  reseeded's `ab2e7aa` diff and the current (post-decomposition,
  multi-pair-aware) seedsync-new controller/model layers.
