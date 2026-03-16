INSERT INTO audit_logs (id, actor_type, actor_id, action, target_type, target_id, metadata)
VALUES ('00000000-0000-0000-0000-000000000001', 'system', NULL, 'bootstrap_completed', 'system', NULL, '{"source":"sql_seed"}'::jsonb)
ON CONFLICT (id) DO NOTHING;
