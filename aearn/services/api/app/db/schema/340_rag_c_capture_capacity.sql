-- Upgrade C's previously bootstrapped 1 MiB physical checks to the formal
-- 8 MiB ceiling. Existing source policies still retain their own lower cap.
-- Preserve 320 as the historical bootstrap fragment: reapplying all fragments
-- on an already bootstrapped database must not leave the old checks in place.
ALTER TABLE rag_registered_source_policies
  DROP CONSTRAINT IF EXISTS rag_registered_source_policies_max_captured_bytes_check;
ALTER TABLE rag_registered_fetch_attempts
  DROP CONSTRAINT IF EXISTS rag_registered_fetch_attempts_response_bytes_check;
ALTER TABLE rag_registered_source_captures
  DROP CONSTRAINT IF EXISTS rag_registered_source_captures_captured_bytes_check;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
      WHERE conrelid = 'rag_registered_source_policies'::regclass
        AND conname = 'chk_rag_c_policy_capture_8m') THEN
    ALTER TABLE rag_registered_source_policies ADD CONSTRAINT chk_rag_c_policy_capture_8m
      CHECK (max_captured_bytes BETWEEN 1 AND 8388608);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
      WHERE conrelid = 'rag_registered_fetch_attempts'::regclass
        AND conname = 'chk_rag_c_attempt_response_8m') THEN
    ALTER TABLE rag_registered_fetch_attempts ADD CONSTRAINT chk_rag_c_attempt_response_8m
      CHECK (response_bytes BETWEEN 0 AND 8388608);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
      WHERE conrelid = 'rag_registered_source_captures'::regclass
        AND conname = 'chk_rag_c_capture_body_8m') THEN
    ALTER TABLE rag_registered_source_captures ADD CONSTRAINT chk_rag_c_capture_body_8m
      CHECK (captured_bytes BETWEEN 1 AND 8388608);
  END IF;
END $$;
