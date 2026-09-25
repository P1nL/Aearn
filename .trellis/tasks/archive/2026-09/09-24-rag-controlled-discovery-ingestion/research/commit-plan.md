# One-shot commit proposal

Commit: `feat: implement guarded RAG discovery and quarantine`

Task-owned dirty files only (no commit/push yet):

- D:\works\Aearn\Aearn\.trellis\spec\backend\grounding-material-contracts.md
- D:\works\Aearn\Aearn\.trellis\spec\backend\index.md
- D:\works\Aearn\Aearn\aearn\services\api\app\db\schema\__init__.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\repositories\local_user_data_repository.py
- D:\works\Aearn\Aearn\aearn\services\api\pyproject.toml
- D:\works\Aearn\Aearn\aearn\services\api\tests\database\test_schema_manifest.py
- D:\works\Aearn\Aearn\aearn\services\api\uv.lock
- D:\works\Aearn\Aearn\aearn\services\worker\aearn_worker\worker_app.py
- D:\works\Aearn\Aearn\docs\architecture\database-schema.md
- D:\works\Aearn\Aearn\.trellis\spec\backend\grounding-controlled-discovery.md
- D:\works\Aearn\Aearn\aearn\infra\rag-b-egress\Dockerfile
- D:\works\Aearn\Aearn\aearn\infra\rag-b-egress\README.md
- D:\works\Aearn\Aearn\aearn\infra\rag-b-egress\attestor.py
- D:\works\Aearn\Aearn\aearn\infra\rag-b-egress\config.example.json
- D:\works\Aearn\Aearn\aearn\infra\rag-b-egress\run.py
- D:\works\Aearn\Aearn\aearn\infra\rag-b-egress\tests\test_attestor.py
- D:\works\Aearn\Aearn\aearn\infra\rag-b-egress\worker_entry.py
- D:\works\Aearn\Aearn\aearn\services\api\app\db\schema\270_rag_discovery_jobs.sql
- D:\works\Aearn\Aearn\aearn\services\api\app\db\schema\280_rag_candidate_staging.sql
- D:\works\Aearn\Aearn\aearn\services\api\app\db\schema\290_rag_discovery_context.sql
- D:\works\Aearn\Aearn\aearn\services\api\app\db\schema\300_rag_candidate_policy.sql
- D:\works\Aearn\Aearn\aearn\services\api\app\db\schema\310_rag_campaign_authority.sql
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\budget.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\campaign_authority.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\candidate_parser.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\candidate_policy_repository.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\candidate_repository.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\context_repository.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\discovery_broker.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\discovery_work.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\hop_policy.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\intake_leases.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\intake_service.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\jobs.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\live_egress.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\pinned_tls_connector.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\provenance.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\public_dns.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\qualified_corpus.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\query_projection.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\retention.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\safe_fetch.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\search_port.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\staging.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\tavily_search.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\tavily_usage_authority.py
- D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\autonomous\worker_composition.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_budget_jobs.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_campaign_authority.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_candidate_parser.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_candidate_policy.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_context_repository.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_discovery_broker.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_discovery_work.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_hop_policy.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_intake_leases.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_intake_service.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_inventory.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_live_egress.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_pinned_tls_connector.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_public_dns.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_qualified_corpus.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_retention.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_safe_fetch.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_search_port.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_staging.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_tavily_usage_authority.py
- D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_rag_b_worker_composition.py
- D:\works\Aearn\Aearn\aearn\services\worker\tests\test_rag_b_worker_routes.py

All listed paths belong to this B task; no unrelated dirty file identified. Stage narrowly and verify `git diff --cached --check` before commit. No push. Trellis archive/journal commits remain separate after approval.
