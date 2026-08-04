-- V012: Ensure reports and actions inherit their owning Run subject.
-- Contract runs created before subject-aware persistence otherwise look like projects.

UPDATE agent_report rp
JOIN agent_run r ON r.id = rp.run_id
SET rp.subject_type = COALESCE(r.subject_type, 'PROJECT'),
    rp.subject_id = COALESCE(r.subject_id, r.project_id)
WHERE rp.subject_type IS NULL
   OR rp.subject_id IS NULL
   OR rp.subject_type <> COALESCE(r.subject_type, 'PROJECT')
   OR rp.subject_id <> COALESCE(r.subject_id, r.project_id);

UPDATE agent_action a
JOIN agent_run r ON r.id = a.run_id
SET a.subject_type = COALESCE(r.subject_type, 'PROJECT'),
    a.subject_id = COALESCE(r.subject_id, r.project_id)
WHERE a.subject_type IS NULL
   OR a.subject_id IS NULL
   OR a.subject_type <> COALESCE(r.subject_type, 'PROJECT')
   OR a.subject_id <> COALESCE(r.subject_id, r.project_id);
