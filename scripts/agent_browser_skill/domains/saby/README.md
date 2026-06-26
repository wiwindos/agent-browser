# Saby Domain Package

This package holds the Saby/SBIS-specific export implementation used by `action=saby_tenders_csv`.

Files:

- `collector.js`: browser-side DOM collector executed through CDP.
- `selectors.json`: explicit selector contract injected into the collector.
- `csv.py`: deterministic CSV serialization for exported items.
- `state.py`: collector loading, options building, continuation state, and stabilized metadata helpers.
- `fixture_runner.js`: offline runner that executes the real collector against saved HTML fixtures without a live browser.

The active skill path should read the collector and selector config from this package, not from ad hoc root-level files.
