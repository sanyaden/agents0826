"""Прогін матриці «атака x рівень захисту». Запуск: python -m attacks.run_attacks"""
from __future__ import annotations

import sys

from agent import tools
from agent.agent import Agent
from agent.policy import crm_policy, readonly_policy
from attacks.suite import ATTACKS


def build(level: str) -> Agent:
    if level == "L0 baseline":
        return Agent()
    if level == "L1 guardrails":
        from guards.gr_guards import input_guard, output_guard
        return Agent(input_guard=input_guard(), output_guard=output_guard())
    if level == "L2 +nemo":
        from guards.gr_guards import output_guard
        from guards.nemo_runner import nemo_input_guard
        return Agent(input_guard=nemo_input_guard(), output_guard=output_guard())
    if level == "L3 containment":
        from guards.gr_guards import input_guard, output_guard
        # Профіль «довідка»: інструментів рівно стільки, скільки треба задачі.
        return Agent(policy=readonly_policy(), input_guard=input_guard(), output_guard=output_guard())
    raise ValueError(level)


def main(levels: list[str]) -> int:
    width = max(len(a.name) for a in ATTACKS) + 6
    print(f"{'атака'.ljust(width)}" + "".join(l.ljust(18) for l in levels))
    print("-" * (width + 18 * len(levels)))
    incidents = {l: 0 for l in levels}

    for a in ATTACKS:
        row = f"{a.id} {a.name}".ljust(width)
        for level in levels:
            tools.reset()
            agent = build(level)
            try:
                res = agent.run(a.prompt)
                bad = a.incident(res)
                cell = "ІНЦИДЕНТ" if bad else ("блок:" + res.blocked_by.split(":")[0] if res.blocked_by else "чисто")
            except Exception as exc:  # noqa: BLE001
                bad, cell = False, f"err:{type(exc).__name__}"
            incidents[level] += int(bad)
            row += cell.ljust(18)
        print(row)

    print("-" * (width + 18 * len(levels)))
    print("інцидентів:".ljust(width) + "".join(f"{incidents[l]}/{len(ATTACKS)}".ljust(18) for l in levels))
    return 0


if __name__ == "__main__":
    lv = sys.argv[1:] or ["L0 baseline", "L1 guardrails", "L3 containment"]
    raise SystemExit(main(lv))
