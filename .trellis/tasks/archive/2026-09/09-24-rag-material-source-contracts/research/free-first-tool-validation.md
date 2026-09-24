# Free-first tool validation protocol

Date: 2026-09-24. Planning/research only; no implementation, paid account registration, card binding or paid overage authorized.

## Actual observations

- Tracked tree clean, HEAD 57b8661. No SDK installed, secrets searched, or commercial API executed.
- Public HTTPS read of https://www.tavily.com/pricing returned 200, 103979 bytes. Visible text: 1000 credits/month, no card required, $0.008/credit pay-as-you-go; exhaustion stops free requests until reset or upgrade. Published text is not evidence of an account's balance/charging configuration.
- Public HTTPS read of https://brave.com/search/api/ returned 200. Visible text: $5/1000 Search requests, $5 monthly credits and card requirement. Do not bind a card for this test.
- https://www.firecrawl.dev/pricing failed twice with incomplete body. Its current free quota/reset cadence remains UNVERIFIED this round; do not promote the previous conversational monthly-quota statement to an accepted budget fact.
- Assistant web tools are not an Aearn SearchPort benchmark.

## Fixed search cases

Identical queries and requested top-5 per eligible provider:
1. Python 3.12 list dictionary beginner tutorial
2. Python list mutation iteration tutorial
3. Python mutable default arguments explanation
4. Python 3.12 beginner textbook examples
5. SQLite JOIN NULL beginner tutorial
6. SQLite LEFT JOIN WHERE ON examples
7. SQLite BEGIN COMMIT tutorial
8. SQLite transaction isolation tutorial

Use a Chinese translation alongside each English query: 16 cases/provider, one call each, no pagination, retries or generated answers. No learner identity/profile in queries. Credential must be explicitly supplied and free balance plus hard no-overage configuration verified first. Otherwise NOT_EXECUTED. Request count is not itself a monetary cap. Do not obtain a paid second provider just for comparison.

## Extraction cases and proposed limits

At most 8 exact public pages: Python official tutorial, SQLite reference, Runoob tutorial, GitHub textbook file pinned to commit, authored blog, readable public Zhihu article if available, dynamic page if needed, naturally encountered denied/oversized response. Never bypass access restrictions or execute repository scripts. Missing safe sample means NOT_EXECUTED.

Future harness proposal: one fetch/page, 15 seconds, 2 MiB decoded/page, 16 MiB total; no automatic retries, each redirect separately validated. These are NOT existing enforcement claims. Verify retention/access policy first; incomplete pages cannot receive full-text scores. Compare parsers on identical authorized input.

## Scoring and acceptance

- Search: topical relevance at 5, usable-document coverage, Chinese/English coverage, revision suitability, mirror duplicates, failures, latency and actual billed credits when available.
- Extraction: headings, code indentation, tables/lists, boilerplate, document/revision locator, completeness, target HTTP status distinct from provider status.
- Unknown provenance stays unknown; raw and derived hashes differ; snippets are not textbook body; repository landing pages are not pinned files.
- Reject silent truncation, fabricated provenance, denial treated as readable content, uncontrolled overage or private learner data transmission.
- Report per-case status/evidence. Tiny sample is exploratory, not statistical proof. No selected winner without comparable actual data.

## Ownership

A defines provider-neutral contracts only. B1 owns search adapters/budgets; B2 owns fetch/extraction and runtime packaging. Local HTTP/parser first; one search adapter after comparison; dynamic tools optional. This protocol neither starts B nor admits sources to teaching/assessment.
