-- Onboarding conversation tables
CREATE TABLE IF NOT EXISTS onboarding_conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'plan_proposed', 'confirmed', 'abandoned')),
  extracted_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS onboarding_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL REFERENCES onboarding_conversations(id) ON DELETE RESTRICT,
  role text NOT NULL CHECK (role IN ('user', 'agent')),
  content text NOT NULL,
  client_message_id text,
  metadata jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  review_session_id uuid NOT NULL REFERENCES learning_sessions(id) ON DELETE RESTRICT,
  role text NOT NULL CHECK (role IN ('user', 'agent')),
  content text NOT NULL,
  client_message_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS learning_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES learning_sessions(id) ON DELETE RESTRICT,
  knowledge_point_id uuid NOT NULL REFERENCES knowledge_points(id) ON DELETE RESTRICT,
  role text NOT NULL CHECK (role IN ('user', 'agent')),
  content text NOT NULL,
  client_message_id text,
  metadata jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_conversations_user ON onboarding_conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_messages_conversation ON onboarding_messages(conversation_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_onboarding_messages_client_id ON onboarding_messages(client_message_id) WHERE client_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_review_messages_session ON review_messages(review_session_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_review_messages_client_id ON review_messages(client_message_id) WHERE client_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_learning_messages_kp_session_created ON learning_messages(knowledge_point_id, session_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_learning_messages_client_id ON learning_messages(client_message_id) WHERE client_message_id IS NOT NULL;

DROP TRIGGER IF EXISTS trg_onboarding_conversations_updated_at ON onboarding_conversations;
CREATE TRIGGER trg_onboarding_conversations_updated_at BEFORE UPDATE ON onboarding_conversations
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
