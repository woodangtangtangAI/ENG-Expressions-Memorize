"""
Deduplication module for the English Expression Database.

Provides functions to load/save the expression index, normalize expressions,
check for duplicates using exact and fuzzy matching, and manage UID generation.
"""

import json
import os
import re
from difflib import SequenceMatcher


def load_index(filepath):
    """Load the expression index from a JSON file.

    Args:
        filepath (str): Path to the index JSON file.

    Returns:
        dict: Index data with keys:
            - total_count (int): Total number of stored expressions.
            - expressions (list[str]): List of normalized expression strings.
            - daily_uid_counter (dict): Mapping of date string → last used UID number.
            - used_episodes (list[str]): List of URLs already processed.
            - last_updated (str): ISO timestamp of the last update.
    """
    if not os.path.exists(filepath):
        return {
            "total_count": 0,
            "expressions": [],
            "daily_uid_counter": {},
            "used_episodes": [],
            "last_updated": ""
        }

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Ensure all expected keys exist
    data.setdefault("total_count", 0)
    data.setdefault("expressions", [])
    data.setdefault("daily_uid_counter", {})
    data.setdefault("used_episodes", [])
    data.setdefault("last_updated", "")

    return data


def save_index(filepath, index_data):
    """Save the expression index to a JSON file.

    Args:
        filepath (str): Path to the index JSON file.
        index_data (dict): The index data to persist.
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    import datetime
    index_data["last_updated"] = datetime.datetime.now().isoformat()

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)


def normalize_expression(expr):
    """Normalize an expression for consistent comparison.

    Steps:
        1. Convert to lowercase.
        2. Strip leading/trailing whitespace.
        3. Remove leading articles (a, an, the).
        4. Collapse multiple whitespace into a single space.

    Args:
        expr (str): The raw expression string.

    Returns:
        str: The normalized expression.
    """
    if not expr:
        return ""

    # Lowercase and strip
    result = expr.lower().strip()

    # Remove leading articles
    result = re.sub(r"^(a|an|the)\s+", "", result)

    # Collapse extra whitespace
    result = re.sub(r"\s+", " ", result)

    return result.strip()


def is_duplicate(expr, index_data, threshold=0.85):
    """Check if an expression is a duplicate of any existing expression.

    Uses a two-pass strategy:
        1. Exact match against normalized expressions (fast).
        2. Fuzzy match using SequenceMatcher ratio (slower, more tolerant).

    Args:
        expr (str): The expression to check.
        index_data (dict): The current index data.
        threshold (float): Minimum similarity ratio for fuzzy match (0.0–1.0).

    Returns:
        bool: True if the expression is considered a duplicate.
    """
    normalized = normalize_expression(expr)
    existing = index_data.get("expressions", [])

    if not normalized:
        return True  # Empty expressions are always considered duplicates

    # Pass 1: Exact match
    if normalized in existing:
        return True

    # Pass 2: Fuzzy match
    for existing_expr in existing:
        ratio = SequenceMatcher(None, normalized, existing_expr).ratio()
        if ratio >= threshold:
            return True

    return False


def add_expression(expr, index_data):
    """Add a new expression to the index.

    The expression is normalized before storage. The total_count is incremented.

    Args:
        expr (str): The expression to add.
        index_data (dict): The current index data (modified in place).

    Returns:
        str: The normalized expression that was added.
    """
    normalized = normalize_expression(expr)
    index_data["expressions"].append(normalized)
    index_data["total_count"] = len(index_data["expressions"])
    return normalized


def get_total_count(index_data):
    """Return the total number of expressions in the index.

    Args:
        index_data (dict): The current index data.

    Returns:
        int: Total count of stored expressions.
    """
    return index_data.get("total_count", 0)


def get_next_uid(index_data, date_str):
    """Get the next UID number for a given date and update the counter.

    For example, if date_str is '20260525' and the counter for that date is
    currently 50, this function returns 51 and updates the counter to 51.

    Args:
        index_data (dict): The current index data (modified in place).
        date_str (str): The date string used as a key, e.g. '20260525'.

    Returns:
        int: The next sequential UID number for that date.
    """
    counters = index_data.setdefault("daily_uid_counter", {})
    current = counters.get(date_str, 0)
    next_uid = current + 1
    counters[date_str] = next_uid
    return next_uid
