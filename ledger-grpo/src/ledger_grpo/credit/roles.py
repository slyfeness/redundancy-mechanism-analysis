# -*- coding: utf-8 -*-
"""Dataset-independent v2.1 reference functions; arithmetic and labels are preserved."""
from .config import PARAMS

def assign_roles(units, P, R, Y, confident=None, params=PARAMS):
    """Roles: 'F' (protected), 'C', 'R', 'K' (mixed/unknown). Returns role, weight e (π for C, r for R)."""
    def eo(u):
        return sum(m for m, t in R.get(u, []) if not t.startswith("浪费"))

    def ww(u):
        return sum(m for m, t in R.get(u, []) if t.startswith("浪费"))

    any_eo = any(eo(u) > 0 for u in units if u != "F")
    role, e = {}, {}
    for u in units:
        pi = sum(m for m, _ in P.get(u, []))
        if u == "F":
            role[u], e[u] = "F", 0.0
        elif params["gate_low_conf"] and confident is not None and not confident.get(u, True):
            role[u], e[u] = "K", 0.0
        elif pi > 0 and eo(u) == 0:
            role[u], e[u] = "C", pi                       # waste is ignored when a unit made real progress
        elif pi > 0:
            role[u], e[u] = "K", 0.0                      # mixed: unchanged
        else:
            r = eo(u) + (ww(u) if (Y or not any_eo) else params["w_fail_waste"] * ww(u))
            role[u], e[u] = ("R", r) if r > 0 else ("K", 0.0)
    return role, e
