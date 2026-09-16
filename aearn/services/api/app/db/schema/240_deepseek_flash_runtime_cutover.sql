-- DeepSeek Flash Codex Runtime identity cutover (2026-09-16).
-- Historical V4 thread rows remain immutable evidence; active rows are retired so
-- the next eligible turn creates a fresh deepseek-flash Runtime thread.

ALTER TABLE tutor_conversation_runtime_threads
  DROP CONSTRAINT IF EXISTS tutor_conversation_runtime_threads_model_check;
ALTER TABLE tutor_conversation_runtime_threads
  ADD CONSTRAINT tutor_conversation_runtime_threads_model_check
  CHECK (model IN ('deepseek-v4-flash', 'deepseek-flash'));

UPDATE tutor_conversation_runtime_threads
SET state = 'retired'
WHERE state = 'active' AND model = 'deepseek-v4-flash';
