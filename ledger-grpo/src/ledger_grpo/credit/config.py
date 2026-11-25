# -*- coding: utf-8 -*-
"""Dataset-independent v2.1 reference functions; arithmetic and labels are preserved."""
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

PARAMS = dict(
    H=20, beta_n=0.2, g=0.3, eta_p=0.5, w_max=0.2,
    lam=0.05,           # waste size per unit of normalized cost
    rho_r=0.5,          # retrieval share of a condition's credit budget
    psi=1.0,            # error size multiplier
    gamma_o=0.5,        # repeat decay; omission share of a budget is (1-gamma_o)*gamma_o^(j-1)  (mu = 1-gamma_o)
    eps_x=0.25,         # exclusion/refutation budget as a fraction of eta_p*w_A
    kappa=3.0,          # receivers' per-token |A| <= kappa*|Â|
    w_fail_waste=0.1,   # weight of waste among responsibilities in failed trajectories that have E or O
    privileged=False,   # gold-dependent events (excluded the gold answer; belief-point positions)
    gate_low_conf=False,
    infeasible="drop",
)

PRESETS = {
    "A": ("outcome", "none"),
    "A_eff": ("outcome_eff", "none"),
    "B": ("progress", "none"),
    "B_W": ("progress_waste", "none"),
    "C": ("progress", "transfer"),
    "C_W": ("progress_waste", "transfer"),
    "C_uniform": ("progress_waste", "transfer_uniform"),
    "clear_only": ("progress_waste", "clear_only"),
    "D": ("progress_waste", "shuffled"),
}


@dataclass(frozen=True)
class CreditConfig(Mapping):
    """All reference parameters and independent experiment switches.

    Mapping access deliberately supports the unchanged reference functions.
    """
    H: int = 20
    beta_n: float = 0.2
    g: float = 0.3
    eta_p: float = 0.5
    w_max: float = 0.2
    lam: float = 0.05
    rho_r: float = 0.5
    psi: float = 1.0
    gamma_o: float = 0.5
    eps_x: float = 0.25
    kappa: float = 3.0
    w_fail_waste: float = 0.1
    privileged: bool = False
    gate_low_conf: bool = False
    infeasible: str = "drop"
    utility: str = "progress_waste"
    step_credit: str = "transfer"
    alpha_eff: float = 0.2
    process_sup: str = "off"
    process_tau: float = 0.05
    alpha_zs: float = 0.1
    continuation: bool = False
    ledger_sample_q: float = 1.0
    ledger_sample_correction: bool = True
    c_ref: float = 3146.0

    def __post_init__(self):
        if not self.g * self.eta_p < self.beta_n:
            raise ValueError("Credit config requires g * eta_p < beta_n")
        if not 1 - self.w_max > self.g * self.eta_p:
            raise ValueError("Credit config requires 1 - w_max > g * eta_p")
        if not isinstance(self.H, int) or self.H <= 0:
            raise ValueError("H must be a positive integer")
        if self.utility not in {"outcome", "outcome_eff", "progress", "progress_waste"}:
            raise ValueError("Unknown utility mode")
        if self.step_credit not in {"none", "transfer", "transfer_uniform", "clear_only", "shuffled", "draco"}:
            raise ValueError("Unknown step_credit mode")
        if self.infeasible not in {"drop", "abstain", "partial"}:
            raise ValueError("Unknown infeasible policy")
        if self.process_sup not in {"off", "masked_nll", "zero_sum"}:
            raise ValueError("Unknown process supervision mode")
        if not 0 < self.ledger_sample_q <= 1:
            raise ValueError("ledger_sample_q must be in (0, 1]")
        if self.kappa < 1 or self.c_ref <= 0:
            raise ValueError("kappa must be >= 1 and c_ref must be positive")
        if not 0.05 <= self.process_tau <= 0.1:
            raise ValueError("process_tau must be in [0.05, 0.1]")
        if self.alpha_zs < 0:
            raise ValueError("alpha_zs must be nonnegative")

    @classmethod
    def from_preset(cls, name: str, **overrides):
        if name not in PRESETS:
            raise ValueError("Unknown credit preset: " + str(name))
        utility, step_credit = PRESETS[name]
        return cls(**dict({"utility": utility, "step_credit": step_credit}, **overrides))

    @classmethod
    def from_params(cls, params):
        return params if isinstance(params, cls) else cls(**dict(params))

    @property
    def requires_ledger(self):
        return self.utility in {"progress", "progress_waste"} or self.step_credit != "none" or self.process_sup != "off"

    def to_params(self):
        return asdict(self)

    def __getitem__(self, key: str) -> Any:
        if key not in self.__dataclass_fields__:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self):
        return iter(self.__dataclass_fields__)

    def __len__(self):
        return len(self.__dataclass_fields__)
