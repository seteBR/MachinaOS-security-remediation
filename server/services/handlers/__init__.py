"""Cross-cutting node-handler machinery.

Per-plugin handler bodies were inlined into their plugin files during
Wave 11.D / 11.E and the self-contained plugin folders (Wave 11.H/I)
absorbed the rest. What remains in this package is the work that
doesn't belong to any single plugin:

- ``tools.py``     — AI-tool dispatcher + plugin fast-path + Android
                      toolkit + agent delegation.
- ``triggers.py``  — generic trigger-node handler (cron / event waiters
                      flow through here regardless of which plugin
                      registered the trigger).
- ``todo.py``      — writeTodos execution shim used by every agent's
                      ``write_todos`` tool call.

The package ``__init__.py`` deliberately stays empty: nothing imports
from ``services.handlers`` at the package level — every consumer
imports the specific submodule it needs.
"""
