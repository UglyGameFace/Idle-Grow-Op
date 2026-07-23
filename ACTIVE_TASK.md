# Active Task: Economy and Inventory Integrity

## Scope
Audit and correct every player-value mutation before adding new gameplay systems.

## Confirmed Findings
- Harvesting credited the same output as both cash and flower.
- Mixed-strain harvests redistributed aggregate yield incorrectly.
- Unknown legacy plant records could be deleted during harvest.
- Dice accepted zero or negative bets.
- Concentrate calculations can accept invalid output amounts or undercharge flower through floor rounding.
- Pot upgrade purchase limits were not enforced.
- Auctions accepted invalid prices, allowed expired bids, lacked reliable expiry settlement, and mishandled bidder escrow.
- Crew deposits accepted negative amounts.
- Daily rewards and crew operations were vulnerable to overlapping command mutations.
- Support/vote XP ignored configured cooldowns and trusted any bot account in the support channel.

## Changes Completed So Far
- Added deterministic per-strain harvest accounting with no cash mutation.
- Preserved unknown plants and verified seed consumption before planting.
- Added canonical positive-amount, flower-cost, auction-price, bid, and pot-limit validators.
- Hardened transfers, buying, flower sales, concentrate sales, slots, and dice under the database mutation lock.
- Enforced pot upgrade limits.
- Added auction price validation, expiry settlement, bidder escrow/refunds, incremental rebids, and exact buyout charging.
- Made daily rewards, crew creation/join/deposits, and district ownership mutations atomic.
- Enforced positive crew deposits.
- Enforced configured support-service identities and per-service reward cooldowns.
- Added targeted regression tests for harvest accounting and canonical economy validators.

## Validation Status
- Branch remains draft.
- CI is running against the latest mutation-layer changes.
- Full lab, crime, admin, and remaining reward-path inspection is still required.

## Cleanup Status
- No monkey patches, startup guards, compatibility shims, or duplicate command implementations were introduced.
- Conflicting mutation paths were replaced instead of hidden behind fallback behavior.

## Remaining Work
- Wire canonical flower-cost validation into queued and manual lab extraction.
- Audit crime/heist/raid/steal/launder/bail payout paths.
- Harden admin balance and item mutation commands.
- Inspect auction/task interactions and persistence behavior.
- Run full tests, extension registration smoke test, compilation, conflict inspection, and cleanup.

## Backlog Locked Behind This Task
- Guild/global data architecture.
- Persistence scalability and transactional database redesign.
- Player onboarding and Discord-native control panel.
- Admin setup and server customization.
