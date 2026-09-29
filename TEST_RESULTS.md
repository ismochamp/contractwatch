# Verification record

**Date:** 28 September 2026  
**Environment:** macOS, Python 3.14, standard library only  
**Command:** `python3 -m unittest -v test_monitor`  
**Result:** 11 tests passed; 0 failures; 0 errors; 1.648 seconds on the recorded run.

Tests use a real loopback HTTP server and isolated SQLite databases. Fixture responses are explicitly synthetic. Durations are execution evidence, not performance benchmarks.

| Check | Observed result |
|---|---|
| Valid order response | Seven checks passed |
| Missing required ID | `order.id` failed with `missing` |
| Numeric total changed to string | `order.total_minor` failed |
| Endpoint returns HTTP 503 | Actual status captured; contract failed |
| Fixture delays for one second | Measured ≥900 ms; 800 ms contract failed |
| Non-JSON response | Explicit parse error persisted |
| Changed response between two real requests | `$.order.total_minor` recorded as a type change |
| Boolean vs integer; array path lookup | Boolean rejected as integer; indexed path resolved |
| Untrusted Origin/Host and remote default | Requests rejected |
| Contract version update | New monitor created; previous configuration and run retained |
| Database reinitialization | Existing run persisted |

The comparison test changes the test monitor's endpoint between requests to reproduce a remote contract change. This is isolated test setup, not a fabricated dashboard response. Tests establish behavior for the stated cases; they do not establish cloud deployment, production uptime, load capacity or customer outcomes.
