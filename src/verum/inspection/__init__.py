"""Inspection actions: catalog, workflow, outcome models and a synthetic history.

The service reads the evaluator file of true quantities and returns only results that have passed
the closed schemas of the agent-visible interface. The gateway imports the catalog and the asset
list from here and nothing that reads the truth. No agent can dispatch an action: the approval
emulator is the only actor.
"""
