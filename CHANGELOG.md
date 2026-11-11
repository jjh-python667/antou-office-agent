# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
`GET /api/health` still reports version `3.2`. The notes written with the 2026-11-09 v3.1 and v3.2 work remain in `CHANGES-v3.1.md` and `CHANGES-v3.2.md`.

## [Unreleased]

## [3.2] - 2026-11-11

Repository polish on the published 3.2 tree. The only application-behavior change in this diff is the socket close below, which comes from the head of pull request #1 because this branch starts there.

### Fixed

- Close provider HTTP error responses after the body is read, including the redirect path that returns before the body is read (`providers.provider_error`). urllib can mark the client socket closed while the error body still holds the descriptor, and `raise ... from None` keeps that response on `RuntimeError.__context__`. Callers that keep the `RuntimeError` then reported `ResourceWarning` at process shutdown. Error text, key redaction, host checks, and provider selection are unchanged. The commit is `c0d74f662792c335505a32825edbcec63852b2d9` on pull request #1.

### Added

- `LICENSE`: MIT for the project code, copyright 工匠 (jjh-python667), 2026. Vendored GSAP 3.15.1 and ScrollTrigger stay under the GSAP Standard License (`assets/THIRD-PARTY.txt`).
- `CHANGELOG.md`.
- `start.sh` for macOS and Linux. It creates `.venv` when needed, installs `requirements.txt` when `openpyxl` or `python-docx` cannot be imported, and runs `app.py`. If `venv` creation fails, it prints that Debian/Ubuntu need `python3-venv` and exits.
- `docs/screenshots/history.png` is now linked from the README. The file itself was already in the tree and was recaptured; see Changed.

### Changed

- Rewrote `README.md` in Chinese and English around behavior that is in this tree: what the local assistant does, install, run, test, layout, provider presets, local HTTP, and license. The Tests badge stays because `.github/workflows/tests.yml` exists.
- Aligned `docs/PROJECT.md` with that description. The author's earlier Windows / Python 3.9 note stays in `CHANGES-v3.2.md` and is labeled there as that record.
- Replaced the page meta description in `index.html` with a description of the local assistant, the discussion mode, and Excel / Word output.
- `start.cmd` forwards extra arguments to `app.py`, including `--no-browser`, which the program already accepts.
- Expanded `.gitignore` for bytecode, tool caches, coverage data, `venv/`, packaging artifacts, editor and OS junk, and an exception so a future `.env.example` can be committed. Existing ignores for `workspace/`, `.env`, and SQLite files remain.
- `app.py` imports `sys` and uses it for the `--no-browser` check.
- `local_state.py` defines `ClosingConnection` once. Each connection still commits or rolls back and then closes. The subclass used to be created inside `connect()`.
- Recaptured `docs/screenshots/home.png`, `docs/screenshots/workbench.png`, and `docs/screenshots/history.png` on 2026-11-11 from the page served by this repository (desktop viewport, reduced motion, after the built-in demo for the workbench and history images). The total 780 in those images is the fixed demo CSV.

### Removed

- `docs/screenshots/workbench.jpg`, an unreferenced duplicate of the workbench screenshot.
