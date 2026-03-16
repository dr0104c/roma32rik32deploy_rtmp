INSERT INTO audit_log (actor_type, actor_id, action, target_type, target_id, payload_json)
VALUES ('system', NULL, 'bootstrap_completed', 'system', NULL, '{"source":"sql_seed"}')
ON CONFLICT DO NOTHING;
