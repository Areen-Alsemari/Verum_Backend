"""Runner that connects the eight agents on one analysis snapshot.

The runner builds each role's request from a snapshot, calls the agent found by convention,
validates both messages, registers the report as evidence and carries on when an agent fails. It
holds no role logic, and agents are replaced without any change here.
"""
