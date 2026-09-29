# ContractWatch — API Contracts & Change Detection

**Experience:** API & System Integration  
**Project type:** Independent, newly built working application  
**Author:** Ismail Habib  
**Stack:** Python standard library, SQLite, HTTP, JSON validation, HTML, CSS, JavaScript

## The problem addressed

An API can return HTTP 200 while removing a required field or changing a numeric value into text. A basic availability check does not explain this kind of integration failure. Developers need explicit expectations and a record of what changed.

## What was built

ContractWatch requests configured JSON endpoints and checks HTTP status, elapsed response time and required typed fields. Results persist with the returned JSON, individual checks and changed response paths. The dashboard connects a failing endpoint to its exact violated rule, while CSV export and a command-line check entry point make evidence reusable.

The application supports real operator-configured endpoints. It also includes clearly labeled local verification scenarios for missing fields, type changes, unavailable responses, invalid JSON and latency overruns. These generate actual HTTP requests and actual failed checks rather than precomputed display values.

## Engineering decisions

- Explicit rules keep requirements reviewable and make failure explanations concrete.
- Booleans are distinguished from JSON integers to avoid a common type-validation mistake.
- Comparison retains the preceding valid response as evidence and caps the number of changed paths.
- Contract updates create a new monitor version through the API, preserving interpretation of older runs.
- Timeouts, body/depth limits, restricted destinations and one-at-a-time execution keep local operation bounded.

## Verified evidence

Eleven automated tests passed on 28 September 2026, covering successful contracts, missing fields, changed types, actual HTTP 503 responses, a measured one-second delay, invalid JSON, response differences, request restrictions and persisted records. See `TEST_RESULTS.md` for the recorded run. Screenshot numbers represent local verification requests and are not production performance metrics.

## Scope and honest limits

This is a working independent project, not a claim of previous client delivery. Checks run on demand, through the dashboard or the included command-line entry point. There is no hosted monitoring service, automatic alert distribution, distributed scheduler or customer uptime history. The field-rule system is intentionally smaller than full JSON Schema. Remote authenticated use requires trusted configured endpoints because the optional bearer token is shared by the instance.

## Suggested screenshots

1. Overview with a passing contract alongside deliberately failing verification endpoints.
2. Missing-field inspection showing `order.id` as the exact failed requirement.
3. Stored response evidence, including individual checks and response JSON.

Caption each capture as **Local verification run using synthetic input; real HTTP execution and persisted results**.
