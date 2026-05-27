"""
Agent 3: Database Manager
Saves extracted expressions to:
  1. Master Excel DB (01_Database/english_expressions_db.xlsx)
  2. Daily Excel Sheet (02_Daily_Sheets/Expressions_YYYY-MM-DD.xlsx)
  3. Study Markdown Note (03_Print_PDF/Study_Note_YYYY-MM-DD.md)
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
    """Generate a unique identifier for an expression entry: ENG-YYYYMMDD-NNN"""
    date_compact = date_str.replace('-', '')
    return f"ENG-{date_compact}-{sequence_num:03d}"


def _prepare_rows(expressions: list[dict], date_str: str, index_data: dict) -> list[list]:
    """Convert expression dicts into row lists suitable for spreadsheet insertion."""
    rows = []

    for expr in expressions:
        seq_num = get_next_uid(index_data, date_str)
        uid = _generate_uid(date_str, seq_num)
        
        # Attach the UID back to the expression dictionary for markdown generation
        expr['uid'] = uid

        row = [
            uid,
            date_str,
            expr.get('source', 'Inspiration'),
            expr.get('expression', ''),
            expr.get('pos', ''),
            expr.get('ipa', ''),
            expr.get('meaning_kr', ''),
            expr.get('original_text', ''),
            expr.get('applied_example', '')
        ]
        rows.append(row)

    return rows


def _save_master_excel(rows: list[list], headers: list[str]) -> int:
    """Save expression rows to the master Excel file (01_Database/english_expressions_db.xlsx)."""
    file_path = config.EXCEL_FILENAME
    os.makedirs(config.DB_DIR, exist_ok=True)

    try:
        if os.path.exists(file_path):
            wb = openpyxl.load_workbook(file_path)
            ws = wb.active
            logger.info(f"Opened master Excel: {file_path} (last row: {ws.max_row})")
        else:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Expressions"
            ws.append(headers)
            logger.info(f"Created new master Excel: {file_path}")

        for row in rows:
            ws.append(row)

        wb.save(file_path)
        logger.info(f"Appended {len(rows)} expressions to master Excel.")
        return len(rows)

    except Exception as e:
        logger.error(f"Failed to save master Excel: {e}")
        raise


def _save_daily_excel(rows: list[list], headers: list[str], date_str: str) -> None:
    """Save daily expression rows to a dedicated sheet (02_Daily_Sheets/Expressions_YYYY-MM-DD.xlsx)."""
    os.makedirs(config.DAILY_DIR, exist_ok=True)
    file_path = os.path.join(config.DAILY_DIR, f"Expressions_{date_str}.xlsx")

    try:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = f"Daily_{date_str}"
        ws.append(headers)

        for row in rows:
            ws.append(row)

        wb.save(file_path)
        logger.info(f"Saved daily Excel sheet: {file_path}")

    except Exception as e:
        logger.error(f"Failed to save daily Excel: {e}")
        raise


def _save_markdown_note(expressions: list[dict], date_str: str) -> None:
    """Save daily expressions to a beautifully formatted markdown note (03_Print_PDF/Study_Note_YYYY-MM-DD.md)."""
    os.makedirs(config.PRINT_DIR, exist_ok=True)
    file_path = os.path.join(config.PRINT_DIR, f"Study_Note_{date_str}.md")

    try:
        # Build Table rows
        table_rows_str = ""
        for i, expr in enumerate(expressions, 1):
            uid = expr.get('uid', 'ENG-000')
            expression = expr.get('expression', '')
            pos = expr.get('pos', '')
            meaning = expr.get('meaning_kr', '')
            table_rows_str += f"| {i:03d} | **{expression}** | `{pos}` | {meaning} |\n"

        # Build detailed section
        details_str = ""
        for i, expr in enumerate(expressions, 1):
            expression = expr.get('expression', '')
            pos = expr.get('pos', '')
            ipa = expr.get('ipa', '')
            meaning = expr.get('meaning_kr', '')
            orig_txt = expr.get('original_text', '')
            appl_ex = expr.get('applied_example', '')
            source = expr.get('source', 'Inspiration')

            details_str += f"### {i}. **{expression}** `[{pos}]` ` {ipa} `\n"
            details_str += f"*   **의미**: {meaning}\n"
            details_str += f"*   **원문 Context**: *\"{orig_txt}\"* (출처: `{source}`)\n"
            details_str += f"*   **실전 예문 (Applied Example)**:\n"
            details_str += f"    > **{appl_ex}**\n\n"
            details_str += "---\n\n"

        # Assemble markdown contents
        markdown_content = f"""# 📝 Daily English Native Expressions Study Note ({date_str})

오늘 학습할 핵심 영어 표현 **{len(expressions)}개**입니다. 
눈으로 소리 내어 읽고, 아래 발음 기호와 예문을 보며 내 손으로 직접 뜻과 쓰임새를 익혀보세요!

---

## 📂 학습 표현 목록
| 번호 | 표현 (Expression) | 품사 (POS) | 의미 (Meaning) |
| :---: | :--- | :--- | :--- |
{table_rows_str}
---

## 🔍 세부 표현 및 실전 예문 학습

{details_str}"""

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        logger.info(f"Saved daily study markdown note: {file_path}")

    except Exception as e:
        logger.error(f"Failed to save daily markdown note: {e}")
        raise


def save_expressions(expressions: list[dict], index_data: dict) -> int:
    """
    Main entry point for saving expressions.
    Saves to master Excel DB, daily Excel sheets, and markdown notes.
    """
    if not expressions:
        logger.warning("No expressions to save")
        return 0

    date_str = datetime.date.today().strftime('%Y-%m-%d')

    # 1. Convert expressions list of dicts to rows lists
    rows = _prepare_rows(expressions, date_str, index_data)
    logger.info(f"Prepared {len(rows)} rows for saving (date: {date_str})")

    # 2. Save master Excel database (append mode)
    saved_count = _save_master_excel(rows, HEADERS)

    # 3. Save daily-only Excel sheet (new file)
    _save_daily_excel(rows, HEADERS, date_str)

    # 4. Save daily markdown study note (new file)
    _save_markdown_note(expressions, date_str)

    return saved_count
