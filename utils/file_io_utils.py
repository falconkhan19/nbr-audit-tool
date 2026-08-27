"""
file_io_utils.py

Loads EP databases and relationship export files (CSV or Excel, single or
multiple at once) into pandas DataFrames, and provides helpers for building
join keys and resolving CellName by Key lookup against the EP layers
(relation files carry no CellName column - only IDs).
"""

import os
import pandas as pd

# Encodings tried in order for text-based files (csv/txt/tsv). Handles the
# common "UnicodeDecodeError ... invalid start byte" seen with exports saved
# as Windows-1252/Latin-1 or with a UTF-8 BOM.
_CSV_ENCODINGS = ["utf-8-sig", "utf-8", "cp1252", "latin1"]


def _read_csv_like(path, sep=None):
    last_err = None
    for enc in _CSV_ENCODINGS:
        try:
            return pd.read_csv(path, sep=sep, engine="python", encoding=enc)
        except UnicodeDecodeError as e:
            last_err = e
            continue
        except Exception as e:
            # Non-encoding errors (bad delimiter, etc.) - keep trying remaining
            # encodings too, since a wrong-encoding read can also surface as a
            # parser error rather than a UnicodeDecodeError.
            last_err = e
            continue
    raise RuntimeError(
        f"Could not read '{os.path.basename(path)}' with any of the tried "
        f"encodings {_CSV_ENCODINGS}. Last error: {last_err}"
    )


def read_table(path, sheet_name=0):
    """Read a single .csv/.txt/.tsv or .xlsx/.xls file into a pandas DataFrame."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls", ".xlsm"):
        df = pd.read_excel(path, sheet_name=sheet_name)
    else:
        # csv / txt / tsv / unknown -> try as delimited text with encoding fallback
        df = _read_csv_like(path)

    df.columns = [str(c).strip() for c in df.columns]
    return df


def read_multiple_tables(paths, sheet_name=0):
    """
    Read several files (same schema expected) and concatenate them into one
    DataFrame. Columns are unioned (missing columns become NaN) so files with
    slightly different column sets don't hard-fail the whole import.

    Returns (combined_df, per_file_errors) where per_file_errors is a list of
    (path, error_message) for files that failed to load; those are skipped.
    """
    frames = []
    errors = []
    for p in paths:
        try:
            frames.append(read_table(p, sheet_name=sheet_name))
        except Exception as e:
            errors.append((p, str(e)))

    if not frames:
        return None, errors

    combined = pd.concat(frames, ignore_index=True, sort=False)
    return combined, errors


def make_key(df, id_col, cell_col, new_col="Key"):
    """
    Create a join key column of the form '<ID>_<CELLID>' (both stripped and
    upper-cased for robust matching) in-place on df. Returns the column name used.
    """
    def _norm(v):
        s = str(v).strip()
        if s.endswith(".0"):
            s = s[:-2]
        return s.upper()

    df[new_col] = df[id_col].map(_norm) + "_" + df[cell_col].map(_norm)
    return new_col


def resolve_cellname_by_key(relation_df, relation_key_col, ep_df, ep_key_col, ep_cellname_col,
                             out_col):
    """
    Resolves the CellName for each relation row by looking up its already-built
    Key against the EP layer's Key column (which was built the same way:
    ID + CellID), and writes it into `out_col`. Used for the "own/source" side
    of a relation file, which is identified only by IDs.

    Returns (relation_df, match_count, total_count).
    """
    lookup = dict(zip(ep_df[ep_key_col].astype(str), ep_df[ep_cellname_col].astype(str)))
    keys = relation_df[relation_key_col].astype(str)
    resolved = keys.map(lookup)
    match_count = int(resolved.notna().sum())
    relation_df[out_col] = resolved.fillna("")
    return relation_df, match_count, len(relation_df)


def resolve_key_by_cellname(relation_df, relation_cellname_col, ep_df, ep_cellname_col,
                             ep_key_col, out_col):
    """
    Resolves the EP Key for each relation row by text-matching a CellName
    column already present in the relation file against the EP layer's
    CellName column. Used for the "neighbor/target" side of NRNRELATIONSHIP,
    which is given directly as a CellName rather than as IDs.

    Matching is exact (trimmed, case-insensitive) first, then falls back to
    a "loose" match that ignores spacing/punctuation differences between
    OSS exports.

    Returns (relation_df, match_count, total_count).
    """
    import re

    def norm_exact(s):
        return str(s).strip().upper()

    def norm_loose(s):
        return re.sub(r"[^A-Z0-9]", "", str(s).strip().upper())

    exact_lookup = {}
    loose_lookup = {}
    for cname, key in zip(ep_df[ep_cellname_col].astype(str), ep_df[ep_key_col].astype(str)):
        exact_lookup.setdefault(norm_exact(cname), key)
        loose_lookup.setdefault(norm_loose(cname), key)

    resolved = []
    match_count = 0
    for rname in relation_df[relation_cellname_col].astype(str):
        key = exact_lookup.get(norm_exact(rname))
        if key is None:
            key = loose_lookup.get(norm_loose(rname))
        if key is not None:
            match_count += 1
            resolved.append(key)
        else:
            resolved.append("")

    relation_df[out_col] = resolved
    return relation_df, match_count, len(relation_df)
