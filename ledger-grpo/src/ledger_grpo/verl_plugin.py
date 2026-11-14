"""Opt-in hook for VERL_USE_EXTERNAL_MODULES=ledger_grpo.verl_plugin.

Normal imports of ledger_grpo or verl_adapter do not install this hook.
"""

from .verl_adapter import register_verl_bridge

register_verl_bridge()
