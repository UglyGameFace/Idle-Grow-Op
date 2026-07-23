from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from economy_integrity import require_positive_amount


@dataclass(frozen=True)
class LaunderOutcome:
    dirty_spent: int
    fee: int
    clean_received: int


@dataclass(frozen=True)
class CrewPayout:
    crew_bank_gain: int
    member_gain: int
    distributed_total: int
    remainder: int


@dataclass(frozen=True)
class RaidOutcome:
    stolen: int
    attacker_gain: int
    destroyed_fee: int
    defender_balance: int
    attacker_balance: int


def calculate_launder_outcome(requested: Any, *, dirty_balance: Any, fee_rate: float = 0.20) -> LaunderOutcome:
    dirty = max(0, int(dirty_balance))
    amount = require_positive_amount(requested)
    if amount > dirty:
        raise ValueError("cannot launder more than the dirty-cash balance")
    if not 0 <= fee_rate < 1:
        raise ValueError("fee rate must be between zero and one")

    fee = int(amount * fee_rate)
    clean = amount - fee
    return LaunderOutcome(dirty_spent=amount, fee=fee, clean_received=clean)


def calculate_robbery_transfer(victim_balance: Any, fraction: float) -> int:
    wallet = max(0, int(victim_balance))
    if wallet < 100:
        raise ValueError("victim balance is below the robbery minimum")
    if not 0 < fraction <= 1:
        raise ValueError("robbery fraction must be between zero and one")

    return min(wallet, max(1, int(wallet * fraction)))


def calculate_crew_payout(total: Any, member_count: Any, *, bank_rate: float = 0.30) -> CrewPayout:
    payout = require_positive_amount(total)
    members = require_positive_amount(member_count)
    if not 0 <= bank_rate <= 1:
        raise ValueError("bank rate must be between zero and one")

    bank_gain = int(payout * bank_rate)
    available = payout - bank_gain
    member_gain = available // members
    distributed = bank_gain + member_gain * members
    return CrewPayout(
        crew_bank_gain=bank_gain,
        member_gain=member_gain,
        distributed_total=distributed,
        remainder=payout - distributed,
    )


def calculate_raid_outcome(
    defender_bank: Any,
    attacker_bank: Any,
    *,
    steal_rate: float,
    steal_cap: Any,
    attacker_keep_rate: float = 0.85,
) -> RaidOutcome:
    defender = max(0, int(defender_bank))
    attacker = max(0, int(attacker_bank))
    cap = require_positive_amount(steal_cap)
    if not 0 <= steal_rate <= 1:
        raise ValueError("steal rate must be between zero and one")
    if not 0 <= attacker_keep_rate <= 1:
        raise ValueError("attacker keep rate must be between zero and one")

    stolen = min(defender, cap, int(defender * steal_rate))
    attacker_gain = int(stolen * attacker_keep_rate)
    fee = stolen - attacker_gain
    return RaidOutcome(
        stolen=stolen,
        attacker_gain=attacker_gain,
        destroyed_fee=fee,
        defender_balance=defender - stolen,
        attacker_balance=attacker + attacker_gain,
    )


def calculate_capped_loss(balance: Any, requested_loss: Any) -> int:
    current = max(0, int(balance))
    loss = max(0, int(requested_loss))
    return min(current, loss)
