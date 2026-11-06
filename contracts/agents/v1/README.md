# Verum agent message contracts v1

The eight schemas define closed request and response messages. Common evidence, causal observation and provenance types live in the common schema. The manifest lists role identities and connection examples. Existing frozen observation, inspection and history schema identifiers resolve from the repository; validation never retrieves a remote schema.

Start with `docs/agent_interfaces.md` for the plain-language work plan. Use `docs/agent_interface_reference.md` for exact fields and detailed connection rules. Run `uv run python tools/check_agent_interfaces.py` from the repository root to validate the definitions and example pairs. The schemas and checks implement no agent, model or service.

Agent 7's additional post-assessment report format is defined separately in `contracts/reports/`. It does not alter the run-message schemas. The development guide specifies a template baseline and optional Cohere narrative; the report assembler and agents remain to be implemented.
