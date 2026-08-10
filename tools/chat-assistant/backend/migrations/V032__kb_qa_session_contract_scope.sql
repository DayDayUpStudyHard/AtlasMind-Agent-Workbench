ALTER TABLE kb_qa_session
  ADD COLUMN IF NOT EXISTS case_id BIGINT NULL AFTER document_id;
