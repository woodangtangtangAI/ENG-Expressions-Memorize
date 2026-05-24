"""
Agent 3: Database Manager
Saves extracted expressions to either local Excel files or Google Sheets,
with automatic environment detection and robust error handling.
"""

import os
import json
import datetime
import openpyxl
from utils.logger import setup_logger
from utils.dedup import get_next_uid

import config

logger = setup_logger('db_manager')

HEADERS = [
    'UID', 'Date', 'Source', 'Expression', 'POS',
    'Pronunciation', 'Meaning_KR', 'Original_Text', 'Applied_Example'
]




def _generate_uid(date_str: str, sequence_num: int) -> str:
    """
    Generate a unique identifier for an expression entry.
    Format: ENG-YYYYMMDD-NNN

    Args:
        date_str: Date string in YYYY-MM-DD format.
        sequence_num: Sequence number for the day (1-based).

    Returns:
        Formatted UID string (e.g., "ENG-20260525-001").
    """
    date_compact = date_str.replace('-', '')
    return f"ENG-{date_compact}-{sequence_num:03d}"


def _prepare_rows(expressions: list[dict], date_str: str, index_data: dict) -> list[list]:
    """
    Convert expression dicts into row lists suitable for spreadsheet insertion.

    Args:
        expressions: List of validated expression dicts.
        date_str: Today's date in YYYY-MM-DD format.
        index_data: The deduplication index data for UID generation.

    Returns:
        List of row lists, each containing values in HEADERS order.
    """
    rows = []

    for expr in expressions:
        uid = get_next_uid(date_str, index_data)

        row = [
            uid,
            date_str,
            expr.get('source', ''),
            expr.get('expression', ''),
            expr.get('pos', ''),
            expr.get('ipa', ''),
            expr.get('meaning_kr', ''),
            expr.get('original_text', ''),
            expr.get('applied_example', '')
        ]
        rows.append(row)

    return rows


def _save_local_excel(rows: list[list], headers: list[str]) -> int:
    """
    Save expression rows to a local Excel file.
    Appends to existing file or creates a new one with headers.

    Args:
        rows: List of row data lists to write.
        headers: Column headers for the spreadsheet.

    Returns:
        Number of rows successfully added.

    Raises:
        PermissionError: If the Excel file is open in another application.
    """
    file_path = config.EXCEL_FILENAME

    try:
        if os.path.exists(file_path):
            # Open existing workbook
            wb = openpyxl.load_workbook(file_path)
            ws = wb.active
            logger.info(f"Opened existing Excel file: {file_path} (last row: {ws.max_row})")
        else:
            # Create new workbook with headers
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Expressions"
            ws.append(headers)
            logger.info(f"Created new Excel file: {file_path}")

        # Append rows
        for row in rows:
            ws.append(row)

        wb.save(file_path)
        logger.info(f"Saved {len(rows)} rows to Excel: {file_path}")
        return len(rows)

    except PermissionError as e:
        logger.error(
            f"Permission denied when saving Excel file. "
            f"The file may be open in Excel. Please close it and try again. "
            f"Path: {file_path}, Error: {e}"
        )
        raise

    except Exception as e:
        logger.error(f"Failed to save Excel file: {e}")
        raise



def save_expressions(expressions: list[dict], index_data: dict) -> int:
    """
    Main entry point for saving expressions.
    Detects environment and saves to appropriate backend.

    Args:
        expressions: List of validated expression dicts to save.
        index_data: The deduplication index data.

    Returns:
        Number of rows successfully saved.
    """
    if not expressions:
        logger.warning("No expressions to save")
        return 0

    # Get today's date
    date_str = datetime.date.today().strftime('%Y-%m-%d')

    # Prepare rows
    rows = _prepare_rows(expressions, date_str, index_data)
    logger.info(f"Prepared {len(rows)} rows for saving (date: {date_str})")

    try:
        saved_count = _save_local_excel(rows, HEADERS)
        return saved_count
    except Exception as e:
        logger.error(f"Failed to save expressions to Excel storage: {e}")
        raise
