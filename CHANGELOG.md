# Changelog

All notable changes to FastFrame are documented here.

## [Unreleased]

- Added production quality gates with Ruff, mypy, Hypothesis, and pytest-cov.
- Added GitHub Actions checks for linting, typing, coverage, Docker build, and
  the network-disabled Docker test.
- Hardened the Docker image with a non-root user, `fastframe` entrypoint, and
  `.dockerignore`.
- Added strict subprocess verification of original variables, stdout, relative
  paths, and `__file__` behavior.
- Added recursive Python/notebook scanning, suppressions, rule selection, rule
  explanations, and a pre-commit hook.

## [0.1.0]

- Added deterministic LibCST detection and rewrites for AP001–AP005.
- Added AP006 report-only dtype downcast recommendations.
- Added `scan`, `fix`, `verify`, `bench`, and `report` commands.
- Added per-pattern verification, benchmark metrics, and self-contained HTML
  reports.
- Added seeded 200,000-row sales analysis example.
- Added reproducible Python 3.12, uv lockfile, Docker, README, and MIT license.
