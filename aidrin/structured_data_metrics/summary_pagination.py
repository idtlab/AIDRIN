"""Page the Data Overview feature list.

The ordered list is numerical features, then categorical features, matching
the order the Data Overview already uses.

``start`` and ``end`` are one-based, inclusive positions in that ordered list.

``total_pages = max(1, ceil(total_features / page_size))``, so page 1 is
always valid.

An empty dataset has ``total_features = 0``, ``total_pages = 1``,
``start = end = 0``, and empty feature lists.

An out-of-range page is not an error. The call succeeds with empty lists,
``pagination.page`` echoes the request, and ``start = end = 0``. The page is
not clamped, so a cache key matches the page that was requested.
"""

import math

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


def _parse_positive_int(value, name):
    """Return a positive int, or None when the caller should use the default."""
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"{name} must be a positive integer")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        raise ValueError(f"{name} must be a positive integer")
    if number < 1:
        raise ValueError(f"{name} must be a positive integer")
    return number


def parse_page_params(page, page_size):
    """Validate a Data Overview page request.

    ``None`` uses the default. Both values must be positive integers. Bools,
    floats (including ``1.5``), zero, negatives, and non-numeric text are
    rejected. ``page_size`` must be at most ``MAX_PAGE_SIZE``.

    Query strings arrive as text, so only a digit string is accepted. JSON
    booleans are rejected because ``bool`` is a subclass of ``int``.
    """
    parsed_page = _parse_positive_int(page, "page")
    parsed_size = _parse_positive_int(page_size, "page_size")
    if parsed_page is None:
        parsed_page = DEFAULT_PAGE
    if parsed_size is None:
        parsed_size = DEFAULT_PAGE_SIZE
    if parsed_size > MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be at most {MAX_PAGE_SIZE}")
    return parsed_page, parsed_size


def paginate_features(numerical, categorical, page, page_size):
    """Return one page of features plus the pagination block.

    ``numerical`` and ``categorical`` are the dataset-wide lists. The page
    lists preserve that order and contain only the requested slice.
    """
    numerical = list(numerical)
    categorical = list(categorical)
    ordered = numerical + categorical
    total_features = len(ordered)
    total_pages = max(1, math.ceil(total_features / page_size))
    start_index = (page - 1) * page_size

    if total_features == 0 or start_index >= total_features:
        page_numerical = []
        page_categorical = []
        start = 0
        end = 0
    else:
        page_items = ordered[start_index:start_index + page_size]
        numerical_count = len(numerical)
        page_numerical = []
        page_categorical = []
        for offset, name in enumerate(page_items):
            if start_index + offset < numerical_count:
                page_numerical.append(name)
            else:
                page_categorical.append(name)
        start = start_index + 1
        end = start_index + len(page_items)

    return {
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "total_features": total_features,
            "start": start,
            "end": end,
        },
        "numerical": page_numerical,
        "categorical": page_categorical,
    }
