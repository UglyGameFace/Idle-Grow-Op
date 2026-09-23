"""Pure casino escrow contracts shared by gameplay and persistence."""

from __future__ import annotations

from typing import Any, MutableMapping


CASINO_ESCROW_KEY = "casino_escrow"
BLACKJACK_ESCROW_GAME = "blackjack"
BLACKJACK_ESCROW_TTL_SECONDS = 120


def make_blackjack_escrow(amount: int, *, now: float) -> dict[str, Any]:
    wager = int(amount)
    if wager <= 0:
        raise ValueError("blackjack escrow amount must be positive")
    return {
        "game": BLACKJACK_ESCROW_GAME,
        "amount": wager,
        "expires_at": float(now) + BLACKJACK_ESCROW_TTL_SECONDS,
    }


def blackjack_escrow_amount(profile: MutableMapping[str, Any]) -> int | None:
    escrow = profile.get(CASINO_ESCROW_KEY)
    if not isinstance(escrow, dict):
        return None
    if escrow.get("game") != BLACKJACK_ESCROW_GAME:
        return None
    try:
        amount = int(escrow.get("amount", 0))
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def reconcile_expired_casino_escrow(
    profile: MutableMapping[str, Any],
    *,
    now: float,
) -> bool:
    """Refund expired Blackjack escrow or clear malformed escrow metadata."""
    if CASINO_ESCROW_KEY not in profile:
        return False

    escrow = profile.get(CASINO_ESCROW_KEY)
    if not isinstance(escrow, dict):
        profile.pop(CASINO_ESCROW_KEY, None)
        return True

    if escrow.get("game") != BLACKJACK_ESCROW_GAME:
        return False

    try:
        amount = int(escrow.get("amount", 0))
        expires_at = float(escrow.get("expires_at", 0))
    except (TypeError, ValueError):
        profile.pop(CASINO_ESCROW_KEY, None)
        return True

    if amount <= 0:
        profile.pop(CASINO_ESCROW_KEY, None)
        return True
    if float(now) < expires_at:
        return False

    profile["grams"] = max(0, int(profile.get("grams", 0) or 0)) + amount
    profile.pop(CASINO_ESCROW_KEY, None)
    return True
