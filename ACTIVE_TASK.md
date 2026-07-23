# Active Task: Economy and Inventory Integrity

## Scope
Audit and correct every player-value mutation before adding new gameplay systems.

## Confirmed Findings
- Harvesting credited the same output as both cash and flower.
- Mixed-strain harvests redistributed aggregate yield incorrectly.
- Unknown legacy plant records could be deleted during harvest.
- Dice accepted zero or negative bets.
- Concentrate calculations accepted invalid output amounts and undercharged flower through floor rounding.
- Queued lab batches consumed flower but had no player collection path.
- Manual lab extraction checked inventory before an animation and consumed it afterward, allowing an inventory race.
- Pot upgrade purchase limits were not enforced.
- Auctions accepted invalid prices, allowed expired bids, lacked reliable expiry settlement, and mishandled bidder escrow.
- Expired auctions were settled only when a player manually used an auction command.
- Crew deposits accepted negative amounts.
- Daily rewards and crew operations were vulnerable to overlapping command mutations.
- Support/vote XP ignored configured cooldowns and trusted any bot account in the support channel.
- Admin maintenance commands accepted negative balances, item quantities, and invalid levels.
- Crime payouts, robbery transfers, laundering, and crew-bank raids mutated related balances without one atomic accounting path.
- Crew-heist integer division discarded payout remainders without explicitly accounting for them.
- Notification tasks changed `notified` flags before confirming that the alert was delivered.

## Changes Completed So Far
- Added deterministic per-strain harvest accounting with no cash mutation.
- Preserved unknown plants and verified seed consumption before planting.
- Added canonical positive-amount, flower-cost, reservation/refund, auction-price, bid, and pot-limit validators.
- Hardened transfers, buying, flower sales, concentrate sales, slots, and dice under the database mutation lock.
- Enforced pot upgrade limits.
- Added auction price validation, expiry settlement, bidder escrow/refunds, incremental rebids, and exact buyout charging.
- Reused the Economy cog's canonical auction settlement from the background game cycle so expired assets settle without player activity.
- Made world-cycle and notification state mutations atomic.
- Notification flags now commit only after successful delivery; failed DMs remain eligible for retry.
- Made daily rewards, crew creation/join/deposits, and district ownership mutations atomic.
- Enforced positive crew deposits.
- Enforced configured support-service identities and per-service reward cooldowns.
- Hardened admin balance, item, level, and wipe mutations.
- Queued lab processing now reserves the exact rounded-up flower cost atomically.
- Added `collect` so completed queued batches credit concentrates exactly once.
- Manual extraction reserves flower before gameplay, consumes it on success, refunds it on timeout, and returns all but the intended penalty on failure.
- Added pure crime accounting helpers for laundering, robbery transfers, crew payout splits, raid transfers, and capped losses.
- Replaced scattered crime balance mutations with one locked command implementation while retaining the existing public commands and aliases.
- Solo/crew heists, raids, stealing, laundering, and heist-channel configuration now save related state together.
- Crew payout remainders are explicitly assigned to the crew bank so the rolled payout is fully accounted for.
- Added targeted regression tests for harvest, validators, flower reservation, rollback, crime value conservation, raid fees, capped losses, background auction settlement, and notification ordering.

## Validation Status
- Branch remains draft.
- Latest CI run is pending discovery for commit `e937435`.
- Compilation, full pytest, real extension registration, CI review, diff review, and cleanup must all pass before completion.

## Cleanup Status
- Removed obsolete lab inventory loops and unused imports.
- Replaced the old scattered crime mutation implementation rather than leaving a duplicate cog or fallback path.
- Background auction settlement calls the existing canonical Economy implementation; no second settlement algorithm was added.
- No monkey patches, startup guards, compatibility shims, or duplicate command implementations were introduced.

## Remaining Work
- Inspect the latest CI results and correct any failures.
- Run final command-surface and changed-file conflict inspection.
- Confirm compilation, full pytest, and real extension registration pass.
- Update PR record and mark ready only after every validation gate passes.

## Backlog Locked Behind This Task
- Guild/global data architecture.
- Persistence scalability and transactional database redesign.
- Player onboarding and Discord-native control panel.
- Admin setup and server customization.
