"""What one row of a parsed frame stands for.

Most readers produce a row per record, which is what the metrics assume. A grid
read produces a row per cell of a simulation or observation grid instead, and a
count of duplicate rows means something quite different there. Readers record
the unit on the frame so a metric can qualify its answer rather than leave the
caller to guess.
"""

ROW_UNIT_ATTR = "aidrin_row_unit"


def row_unit(frame):
    """Return what one row stands for, or None when rows are ordinary records."""
    try:
        return frame.attrs.get(ROW_UNIT_ATTR)
    except AttributeError:
        return None
