"""Advisory agents, one subpackage per role, with the helpers they share.

Each role implements the run interface of the versioned message contract. Role packages import only
the contract package and the shared helpers, so owners can work in parallel without waiting on one
another. Until a role is implemented, its package holds a placeholder that answers conservatively.
"""
