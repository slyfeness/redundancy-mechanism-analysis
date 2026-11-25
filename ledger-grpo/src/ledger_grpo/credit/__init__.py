"""Event-grounded credit v2.1; importing this package performs no model I/O."""

from .config import CreditConfig, PARAMS
from .group import credit_for_group
from .schema import Group, Trajectory, Unit

__all__ = ['CreditConfig', 'PARAMS', 'Group', 'Trajectory', 'Unit', 'credit_for_group']
