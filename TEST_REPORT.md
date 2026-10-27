# DevAgent AI — Deep Audit and Verification Report

Audit date: 2026-10-12

## Summary

This audit reviewed the backend API, task-state transitions, repository access, patch parsing/application, Ollama adapter, test runner, frontend action gating, setup instructions, and packaging. The backend test suite currently passes **53 tests** in the available environment. A deterministic randomized patch round-trip check also passed 500 cases during this audit; a 50-case version is included in the committed pytest suite.

This report deliberately separates verified results from integrations that could not be executed in this environment.

## Checks completed

- Backend automated tests: **53 passed** (`python -m pytest -q`).
- Python syntax/bytecode compilation: passed (`python -m compileall -q app tests`).
- Editable package metadata/install check without dependency resolution: passed (`python -m pip install -e . --no-build-isolation --no-deps`).
- Frontend TS/TSX syntax transpilation: passed for `App.tsx`, `api.ts`, `main.tsx`, and `vite.config.ts` using the globally available TypeScript compiler.
- Randomized patch round-trips: **500 passed** in an audit-only stress check; the repeatable pytest suite includes 50 deterministic cases.
- Final ZIP integrity: passed; the archive was extracted to a clean temporary directory and the full backend test suite passed from that extracted copy.

## Issues found and corrected in this audit

1. **Dashboard action gating:** the frontend previously showed the test action for `completed` and `needs_review` tasks even though the backend only accepts tests for `applied` tasks. The button now appears only when the task status is `applied`.
2. **Portable Docker workspace mount:** changed the test runner from `-v host:container:ro` to Docker's explicit `--mount type=bind,source=...,target=/workspace,readonly` form to handle host paths more robustly across platforms.
3. **Defense-in-depth in test container:** explicitly sets `--user 65534:65534` at container runtime in addition to the non-root Dockerfile user.
4. **Credential filtering:** added `.envrc`, `.git-credentials`, common credential/secret directories, `.config`, `.terraform`, and private-key filename variants to the denylist. This remains a denylist, not a guarantee that every possible secret format is detected.
5. **Repository picker:** symlinked top-level directories are no longer presented as valid repositories.
6. **Patch edge cases:** added deterministic randomized round-trip coverage for mixed LF/CRLF, empty text, no final newline, Unicode, whitespace, and source lines that resemble diff headers.
7. **Continuous integration:** added `.github/workflows/ci.yml` to install dependencies, run backend tests and Ruff, and run the frontend production build on GitHub Actions.
8. **Documentation:** clarified that the initial version edits existing files only and added a PowerShell activation troubleshooting note.

Earlier fixes retained in this package include:

- Avoiding truncated source files as editable context, preventing accidental deletion of unseen file suffixes.
- Strict unified-diff hunk-count parsing, duplicate section rejection, context matching, and CRLF/no-final-newline preservation.
- Staging multi-file changes before replacement and best-effort rollback on write failures.
- Repository traversal/symlink checks, bounded file/patch sizes, and common secret exclusions.
- Fixed-command Docker test execution with network disabled, read-only root filesystem and workspace mount, dropped capabilities, resource limits, bounded output, timeouts, and cleanup attempts.
- Bounded repair attempts, task-aware context selection, startup recovery for interrupted tasks, and atomic status claims against duplicate task starts and patch approvals.
- Mocked end-to-end API lifecycle test from task creation through patch approval, test execution, and completion.

## Verification still outstanding

- **Frontend production build/type-check:** `npm install` could not resolve `registry.npmjs.org` in this environment (`EAI_AGAIN` DNS resolution error). Syntax transpilation is not equivalent to `tsc -b && vite build`. The new GitHub Actions workflow will run the real build when dependency registry access is available.
- **Ruff lint:** Ruff is not installed in this environment, and registry access was unavailable to install it. CI runs `ruff check app tests`.
- **Live Ollama inference:** Ollama was not installed/available here. Real model responses and task generation need to be verified locally.
- **LangGraph-installed path:** LangGraph was not installed in this environment, so backend tests exercised the deterministic fallback graph. The regular project install declares LangGraph; CI installs dependencies, but a live local Ollama workflow still needs a smoke test.
- **Docker image build and live sandbox execution:** Docker was not available here. Command construction is unit-tested, but the image and real container execution must be checked on the user's computer.
- **End-to-end browser test:** no browser session with installed frontend dependencies was available.

## Installation recommendation

The project is ready for a careful local integration pass, not yet a claim of complete end-to-end verification. Before publishing to GitHub, run the frontend production build, install and check the configured Ollama model, build the Docker runner image, and complete one end-to-end task against `workspace/sample-python-project`.

This is a local-first portfolio prototype, not a hardened multi-user service. Keep it bound to localhost, use a disposable repository, review every patch, and do not expose the API to the public internet.

## Additional final-check pass

- Re-ran the backend suite after the previous audit: **53 passed**.
- Re-ran Python compilation and editable package metadata installation without dependency resolution: passed.
- Attempted the actual frontend production build; it cannot complete in this environment because frontend dependencies are not installed. `npm install` was attempted again and failed because DNS resolution for `registry.npmjs.org` returned `EAI_AGAIN`. No claim of a successful production build is made.
- A source-level unused-import scan found an obsolete `unittest.mock.patch` import in `tests/test_ollama.py`; it has been removed. Ruff itself remains unavailable here, so the official lint check is still delegated to the CI workflow.
- Ollama, LangGraph's installed execution path, and Docker remain unverified because those services/packages are unavailable in this environment. The automated suite exercises a deterministic graph fallback and mocked integrations where appropriate.
- The frontend has no `package-lock.json` because npm could not reach the registry to generate one. `npm install` is therefore required, and dependency resolution is not lockfile-reproducible yet.

## Final package verification (latest archive)

- Removed an unused `unittest.mock.patch` import found during the final source scan; this avoids a likely Ruff `F401` lint failure.
- Backend tests were rerun from a fresh extraction of the latest ZIP: **53 passed**.
- The included sample project's tests: **2 passed**.
- Python compilation from the extracted package: passed.
- Frontend TypeScript/TSX syntax transpilation: passed for the four source/config files checked. This is syntax-only and does not replace the TypeScript type-check or Vite production build.
- Repeated deterministic patch stress check: **500/500 round-trips passed**.
- ZIP integrity check: passed; the archive contains the project root directory and expected source files, with generated caches and local databases excluded.

## Explicit go/no-go status

**Go for installation and local integration testing; not yet a verified release for public publishing.** The remaining blockers are environmental rather than hidden successful tests: npm registry DNS was unavailable, Ruff is not installed here, and Ollama, installed LangGraph execution, and Docker are not available for live integration tests. Run the full CI workflow or its equivalent locally before publishing to GitHub.


## New repository verification update — 2026-10-27

This addendum records the results after publishing the prepared source snapshot to `abhinay2504/devagent-ai-verified`.

- The new repository's `main` tree was checked after publishing and contains 43 tracked source/configuration files.
- The sample project was run locally by the user with `python -m pytest -v`: **7 test functions passed**. Coverage includes `is_positive(1)`, `is_positive(0)`, and `is_positive(-1)`, plus the existing arithmetic and number-property helpers.
- GitHub Actions run [40523215843](https://github.com/abhinay2504/devagent-ai-verified/actions/runs/40523215843) completed successfully for commit `dd4b6e720bc66c071dd8bf5bb78977d2ec53d8b9`: backend dependency installation, pytest, Ruff, frontend dependency installation, and frontend build all passed.
- A subsequent sync commit (`f8d8aa1bed95d6ede2bd8bea246412595eaf4e53`) refreshed `backend/app/main.py` and `backend/tests/test_api.py` from the prepared ZIP, and aligned the README/CI workflow with `npm ci`. GitHub Actions run [40525097494](https://github.com/abhinay2504/devagent-ai-verified/actions/runs/40525097494) then completed successfully for that sync commit: backend dependency install, pytest, Ruff, frontend `npm ci`, and `npm run build` all passed. The later `main` commit only updated this report.
- The original `abhinay2504/devagent-ai` repository was left unchanged.

**Current status:** the new repository has been populated and its contents checked. The user's local dashboard, Ollama connection, Docker runner, and sample task have worked during the local session; final CI confirmation for the latest commit is still outstanding, so this is not described as a fully end-to-end verified release.
