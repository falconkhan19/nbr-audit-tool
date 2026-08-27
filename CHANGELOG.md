# Changelog

All notable changes to the NBR Audit Tool are documented in this file.

## [1.5] — Docked panel, cleaner audit output
- **Docked panel instead of a popup dialog**: the tool now opens as a dock
  panel on the right side of the QGIS window (like the Layers or Processing
  panels), so it no longer floats over your site features and stays out of
  the way while you pan/zoom the map. Drag its edge to resize, or drag its
  title bar to move/float/re-dock it like any other QGIS panel.
- **Re-running the audit replaces its own output layers** instead of piling
  up duplicates: each run tracks its "Source Cell", "LTE-NR relations", and
  "NR-NR relations" layers, and removes the previous one for that slot
  before adding the new one (or just adds fresh if you'd already deleted
  it).
- **Source cell highlight**: now bright yellow `#ffe415` at 100% opacity,
  and always kept on top of the relation layers in the layer order,
  regardless of the order things were (re)created in.
- **LTE-NR relations are now blue** (`#1f77b4`) instead of green, so they're
  visually distinct from NR-NR relations (still green, `#2ca02c`).
- **New toolbar icon**: a three-sector cellsite glyph colored to match the
  audit highlight palette (blue/green/yellow).

## [1.4] — Column auto-guess fix, low-match warning
- **Fixed a bad auto-column-guess**: the "NR Cell ID" field was being
  auto-selected as `LocalCellId` instead of `CellId` in some NRNRELATIONSHIP
  exports, because the keyword match was a plain substring check and
  `LocalCellId` contains "CellId" too. `LocalCellId` is typically just a
  row sequence number, not the real Cell ID, so the built key never matched
  the 5G EP and almost every row was silently dropped. Auto-guessing now
  tries an exact column-name match first, and the Cell ID guesses
  explicitly exclude any column containing "local".
- **Low match-rate warning**: after building keys on Tab 3, if any mapping
  resolves less than half its rows, you'll get a pop-up telling you exactly
  which mapping is suspect — so a bad column pick like this is caught
  immediately instead of silently producing near-zero matches. This is a
  safety net, not a substitute for checking the drop-downs yourself —
  always confirm "NR Cell ID column" points at the real Cell ID column
  (e.g. `CellId`), not a local/sequence index column.

## [1.3] — Hybrid own/neighbor model for NRNRELATIONSHIP
NRNRELATIONSHIP is a single relation table where each row carries both an
LTE-side reference (CellName) and an NR-side reference (gNodeB ID + Cell
ID) — there's no fixed "own vs. neighbor" column. Which one is the "own"
cell and which is the "neighbor" depends entirely on which network type
you're auditing *from*:

- **Audit from a 4G cell**: the LTE CellName is the own cell (matched
  against 4G EP), and the NR gNodeB ID+Cell ID on that same row is the
  neighbor to plot (matched against 5G EP).
- **Audit from a 5G cell**: the NR gNodeB ID+Cell ID is the own cell
  (matched against 5G EP), and the LTE CellName on that same row is the
  neighbor to plot (matched against 4G EP).

Tab 3's NRNRELATIONSHIP mapping now reflects this directly — you map the
LTE CellName column and the NR gNodeB ID / Cell ID columns once, and both
an `LTEKey` and an `NRKey` are resolved on every row; the audit tab picks
whichever one is "own" vs "neighbor" based on your 4G/5G selection.
NRCELLRELATION (NR-NR) is unchanged — both sides are NR cells, identified
by IDs.

## [1.2] — Beamwidth/Radius bug fix, corrected relation model
- **Fixed the Beamwidth/Radius "manual vs column" bug** that made Create
  Sectors fail for both 4G and 5G with a "not a valid number" /
  "column not found" error — the flag was inverted.
- **NRNRELATIONSHIP mapping corrected to a hybrid model**: the own/source
  (NR) side is still identified by gNodeB ID + Cell ID and looked up
  against the 5G EP key, but the neighbor/target side is now read directly
  from a CellName column already present in the file, matched by text
  against the 4G EP CellName — this is what NRNRELATIONSHIP actually
  contains, and fixes the "zero matches" issue. NRCELLRELATION is
  unchanged (both sides identified by ID + Cell ID, resolved against the
  5G EP by key).
- **5G-cell LTE-NR audit logic corrected**: the selected 5G cell's key is
  looked up against `OwnKey` (built from the NRNRELATIONSHIP gNodeB
  ID + Cell ID columns) to find its relation rows; the CellName in those
  rows is then matched to the 4G EP to find the sectors to plot.
- **Audit result highlighting**: the cell you searched for is now plotted
  in yellow ("Source Cell - <n>" layer), and its relation cells in green
  ("LTE-NR relations" / "NR-NR relations" layers).

## [1.1] — Robustness pass
- **CSV encoding fix**: file reads now try `utf-8-sig` → `utf-8` →
  `cp1252` → `latin1` automatically, instead of failing on non-UTF-8
  exports.
- **Sector creation hardened**: invalid/blank/NaN cells are skipped
  per-row (with a count reported) instead of crashing the whole import;
  any real error is now shown to you with a readable message instead of
  failing silently.
- **No more CellName mapping on relation files.** NRNRELATIONSHIP and
  NRCELLRELATION are assumed to contain IDs only (own gNodeB/gNB ID + Cell
  ID, and neighbor eNodeB/gNB ID + Cell ID) — no CellName column. The
  plugin builds `OwnKey`/`TargetKey` from those IDs and resolves the
  CellName by looking the key up in the EP layer, rather than trying to
  text-match a CellName column that doesn't exist.
- **Multiple relation files at once**: both the NRNRELATIONSHIP and
  NRCELLRELATION importers now accept multiple files in one go (large
  exports that are split into parts) and combine them automatically.
- **Manual styling removed**: Styling tab is now automatic classification
  only (graduated: class count/method/ramp; categorized: ramp), plus
  loading a saved `.qml` style.

## [1.0] — Initial release
- Import 4G and 5G EP databases and plot sectors from
  Azimuth/Latitude/Longitude with configurable Beamwidth/Radius.
- Graduated/categorized styling.
- Import NRNRELATIONSHIP and NRCELLRELATION exports and run a neighbor
  audit for a chosen 4G or 5G cell.
