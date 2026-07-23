# Active Task: Economy and Inventory Integrity

## Scope
Audit and correct every player-value mutation before adding new gameplay systems. The current implementation must not duplicate, destroy, or misclassify cash, flower, items, XP, crew funds, auction assets, or processing output.

## Current Findings
- `grams` is the clean-cash balance throughout the economy commands.
- Harvest incorrectly credited `grams` as cash while also adding the same output to `flower_stash`.
- Mixed-strain harvests divided aggregate yield evenly, producing incorrect per-strain inventory.
- Unknown legacy plant records risked being lost during harvest processing.
- Additional mutation paths still requiring inspection: buying, transfers, gambling, concentrates, auctions, crew deposits, daily rewards, crime rewards, and admin mutations.

## Changes So Far
- Added a deterministic, side-effect-free harvest accounting helper.
- Harvest now produces flower only; selling remains the cash-credit path.
- Yield is recorded per plant and per strain instead of redistributed from one aggregate total.
- Unknown plant records are preserved rather than deleted.
- Seed removal is rechecked before planting commits state.
- Added targeted regression tests for mixed strains, duplicate cash prevention, unknown records, multipliers, and invalid negative multipliers.

## Validation Status
- Branch CI is pending for the current commits.
- Full economy mutation audit is still in progress.

## Cleanup Status
- Removed ambiguous harvest comments and the obsolete cash-credit line.
- Removed unused farming imports while preserving command behavior.
- No monkey patches, startup guards, or compatibility shims introduced.

## Blockers
- None currently.

## Backlog Locked Behind This Task
- Guild/global data architecture.
- Persistence scalability and transactional database redesign.
- Player onboarding and Discord-native control panel.
- Admin setup and server customization.
