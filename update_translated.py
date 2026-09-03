"""Compatibility wrapper for the client translation workflow.

Both workflows now use the same drawing updater. Keeping this module means old
imports and automation scripts continue to work without maintaining two copies.
"""

from update_connected import update_connected_pids

__all__ = ["update_connected_pids"]
