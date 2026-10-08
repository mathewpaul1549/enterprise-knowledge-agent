# Verification record

Verified 8 October 2026 (Asia/Kolkata).

- Python regression tests: **11 passed** using Python 3.14.6.
- Reproducible synthetic evaluation: see `evaluation.json`, including per-case results and limitations.
- Browser walkthrough: local UI renders and the primary flow completes.
- Browser: API rate-limit question returned a citation; local draft saved; unsupported question abstained.
- TypeScript typecheck and Eve production build passed. No live model call has been tested.
- Remaining moderate dependency advisories are described in dependency-notes.md.

CI is included. Remote CI status must be checked separately after pushing.
