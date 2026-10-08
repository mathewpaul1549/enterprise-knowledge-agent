# Dependency verification

The Eve app builds and its TypeScript checks pass with the committed lockfile. `just-bash` is an explicit build dependency because Eve initializes its default local sandbox even when general-purpose model tools are disabled.

The initial audit identified a high-severity advisory in guarded-fetch's pinned Undici dependency. The override pins Undici 7.29.1, the patched release reported by npm. A subsequent install reports four moderate advisories through the sprintf-js → just-bash → Eve chain; no non-breaking fix was offered. General-purpose tools are disabled, and the authored tools do not call sprintf or execute shell commands. This reduces the demonstrated surface but is not proof of non-exploitability. Do not treat this local demo as an audited production deployment; revisit upstream patches before hosting it publicly.

The lockfile is committed for reproducibility. Avoid `npm audit fix --force`, which proposed downgrading Eve across incompatible releases.
