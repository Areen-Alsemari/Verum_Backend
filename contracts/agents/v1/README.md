# Verum agent message contracts v1

The eight schemas define closed request and response messages. Common evidence, causal observation and provenance types live in the common schema. The manifest lists role identities and connection examples. Existing frozen observation, inspection and history schema identifiers resolve from the repository; validation never retrieves a remote schema.

See `docs/agent_interfaces.md` for the workflow, data-to-model boundary, all role fields and independent implementation responsibilities. Run `uv run python tools/check_agent_interfaces.py` from the repository root to validate the definitions and example pairs. The schemas and checks implement no agent, model or service.
