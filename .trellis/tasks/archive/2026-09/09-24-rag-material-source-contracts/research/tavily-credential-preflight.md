# Tavily credential preflight

Date: 2026-09-24. Planning/research only.

User selected Tavily free tier and explicitly configured TAVILY_API_KEY locally. Read only that key from aearn/.env in memory; never printed or persisted it. No dependency installation or product code changes.

One authenticated GET https://api.tavily.com/usage succeeded, using direct HTTPS, no proxy, no redirects, 20 second timeout, bounded response and no retries. Only allowlisted usage fields were printed.

Observed account.current_plan=Researcher, plan_usage=0, plan_limit=1000, paygo_usage=0, paygo_limit=null. Observed key.usage=0, key.limit=null. Null is not proof of disabled overage or zero budget; no such inference made.

Credential accepted; reported plan allowance available=1000 at observation time. Search POST NOT_EXECUTED because the free-first protocol requires confirmation of no paid overage. No claim that a runtime SearchPort is integrated or that learning material is admitted. Next prerequisite: verify account pay-as-you-go is disabled and/or a hard key credit limit before bounded search. User should not send secrets or unredacted screenshots.

Provider choice is now Tavily only; supersedes earlier multi-provider bake-off recommendation. A remains pure contracts; adapter/runtime work belongs to B1. Work stays in planning.
