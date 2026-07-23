import pytest

from crime_integrity import (
    calculate_capped_loss,
    calculate_crew_payout,
    calculate_launder_outcome,
    calculate_raid_outcome,
    calculate_robbery_transfer,
)


def test_laundering_conserves_value_except_for_fee():
    result = calculate_launder_outcome(1_000, dirty_balance=2_000, fee_rate=0.20)
    assert result.dirty_spent == 1_000
    assert result.fee == 200
    assert result.clean_received == 800
    assert result.fee + result.clean_received == result.dirty_spent


def test_laundering_rejects_invalid_or_overdrawn_amounts():
    with pytest.raises(ValueError):
        calculate_launder_outcome(0, dirty_balance=100)
    with pytest.raises(ValueError, match="more than"):
        calculate_launder_outcome(101, dirty_balance=100)


def test_robbery_transfer_never_exceeds_victim_wallet():
    assert calculate_robbery_transfer(1_000, 0.20) == 200
    assert calculate_robbery_transfer(100, 1.0) == 100
    with pytest.raises(ValueError):
        calculate_robbery_transfer(99, 0.20)


def test_crew_payout_never_mints_more_than_total():
    result = calculate_crew_payout(10_001, 3, bank_rate=0.30)
    assert result.crew_bank_gain == 3_000
    assert result.member_gain == 2_333
    assert result.distributed_total == 9_999
    assert result.remainder == 2
    assert result.distributed_total + result.remainder == 10_001


def test_raid_transfer_preserves_expected_fee_and_nonnegative_banks():
    result = calculate_raid_outcome(
        100_000,
        5_000,
        steal_rate=0.18,
        steal_cap=25_000,
        attacker_keep_rate=0.85,
    )
    assert result.stolen == 18_000
    assert result.attacker_gain == 15_300
    assert result.destroyed_fee == 2_700
    assert result.defender_balance == 82_000
    assert result.attacker_balance == 20_300
    assert result.attacker_gain + result.destroyed_fee == result.stolen


def test_capped_loss_cannot_drive_balance_negative():
    assert calculate_capped_loss(500, 1_000) == 500
    assert calculate_capped_loss(500, -1) == 0
