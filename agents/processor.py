"""
Agent 2: LLM Processor
Takes raw text chunks, sends them to Gemini to extract English native expressions,
validates results, and deduplicates against the existing index.
"""

import json
import time
import re
from google import genai
from google.genai import types
from utils.dedup import normalize_expression, is_duplicate, add_expression
from utils.logger import setup_logger

import config

logger = setup_logger('processor')

VALID_POS_TYPES = {'phrasal verb', 'collocation', 'idiom'}


def _build_extraction_prompt(text_chunk: str, target_count: int, source: str) -> str:
    """
    Build a prompt instructing Gemini to extract English native expressions.
    The prompt is in Korean with English technical terms.

    Args:
        text_chunk: The raw text to extract expressions from.
        target_count: Number of expressions to target.
        source: The source name (e.g., 'Friends', 'CNBC', 'BBC').

    Returns:
        Formatted prompt string.
    """
    # Determine context instruction based on source
    source_lower = source.lower()
    if 'friends' in source_lower or 'transcript' in source_lower:
        context_instruction = "일상적인 네이티브 대화"
    else:
        context_instruction = "글로벌 비즈니스 환경"

    prompt = f"""당신은 비원어민 직장인을 위한 영어 네이티브 표현 전문가입니다.

아래 영어 텍스트에서 비원어민이 반드시 알아야 할 실전 영어 표현을 {target_count}개 추출하세요.

[대상 표현 유형]
1. Phrasal Verbs (구동사): 예) pull off, bring up, figure out, iron out
2. Business Collocations (비즈니스 연어): 예) raise concerns, drive growth, meet expectations
3. Daily Idioms (일상 관용구): 예) a piece of cake, break the ice, hit the nail on the head

[추출 규칙]
- 기초 단어 단독 사용(go, make, have, get, take 등)은 절대 제외
- 중급~고급 학습자에게 실질적으로 유용한 표현만 선별
- 표현은 반드시 원문 텍스트에서 파생 가능해야 함
- IPA 발음 기호는 정확하게 표기
- 한국어 의미는 사전적 번역이 아닌, 실제 맥락에서의 자연스러운 의미로 작성
- Applied Example은 {context_instruction}에서 자연스럽게 사용되는 새로운 예문

반드시 아래 JSON 배열 형식으로만 응답하세요:
[
  {{
    "expression": "표현",
    "pos": "phrasal verb / collocation / idiom",
    "ipa": "/IPA 발음/",
    "meaning_kr": "자연스러운 한국어 의미",
    "original_text": "이 표현이 사용된 원문 문장",
    "applied_example": "새로운 맥락의 예문"
  }}
]

[소스: {source}]
[텍스트]
{text_chunk}"""

    return prompt


def _call_gemini(prompt: str) -> list[dict]:
    """
    Call the Gemini API with the given prompt and parse the JSON response.
    Includes retry logic with exponential backoff.

    Args:
        prompt: The formatted prompt to send to Gemini.

    Returns:
        Parsed list of expression dicts, or empty list on failure.
    """
    client = genai.Client(api_key=config.GEMINI_API_KEY)

    for attempt in range(config.API_MAX_RETRIES):
        try:
            logger.info(f"Calling Gemini API (attempt {attempt + 1}/{config.API_MAX_RETRIES})...")

            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )

            if not response or not response.text:
                logger.warning(f"Empty response from Gemini (attempt {attempt + 1})")
                if attempt < config.API_MAX_RETRIES - 1:
                    time.sleep(config.API_CALL_DELAY)
                continue

            response_text = response.text.strip()

            # Strip markdown code fences if present
            if response_text.startswith('```'):
                response_text = re.sub(r'^```(?:json)?\s*\n?', '', response_text)
                response_text = re.sub(r'\n?```\s*$', '', response_text)
                response_text = response_text.strip()

            parsed = json.loads(response_text)

            if isinstance(parsed, list):
                logger.info(f"Successfully extracted {len(parsed)} expressions from Gemini")
                return parsed
            else:
                logger.warning(f"Gemini response is not a list: {type(parsed)}")
                if attempt < config.API_MAX_RETRIES - 1:
                    time.sleep(config.API_CALL_DELAY)
                continue

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error from Gemini response (attempt {attempt + 1}): {e}")
            if attempt < config.API_MAX_RETRIES - 1:
                time.sleep(config.API_CALL_DELAY)

        except Exception as e:
            logger.warning(f"Gemini API call failed (attempt {attempt + 1}): {e}")
            if attempt < config.API_MAX_RETRIES - 1:
                wait_time = config.API_CALL_DELAY * (2 ** attempt)
                logger.info(f"Waiting {wait_time}s before retry...")
                time.sleep(wait_time)

    logger.error(f"All {config.API_MAX_RETRIES} Gemini API attempts failed")
    return []


def _validate_expression(expr_dict: dict) -> bool:
    """
    Validate that an extracted expression dict has all required fields
    and meets quality criteria.

    Args:
        expr_dict: Dictionary with expression data.

    Returns:
        True if the expression is valid, False otherwise.
    """
    required_keys = ['expression', 'pos', 'ipa', 'meaning_kr', 'original_text', 'applied_example']

    # Check all required keys exist
    for key in required_keys:
        if key not in expr_dict or not expr_dict[key]:
            logger.debug(f"Expression missing required key '{key}': {expr_dict.get('expression', 'N/A')}")
            return False

    # Check expression is not empty and has at least 2 characters
    expression = str(expr_dict['expression']).strip()
    if len(expression) < 2:
        logger.debug(f"Expression too short: '{expression}'")
        return False

    # Check pos is valid
    pos = str(expr_dict['pos']).strip().lower()
    if pos not in VALID_POS_TYPES:
        logger.debug(f"Invalid POS type '{pos}' for expression '{expression}'")
        return False

    return True


def process_and_extract(raw_texts: list[dict], index_data: dict, daily_target: int) -> list[dict]:
    """
    Main entry point for LLM processing.
    Takes raw text chunks, extracts expressions via Gemini, validates and deduplicates.

    Args:
        raw_texts: List of {"source": str, "raw_text": str, "url": str} dicts.
        index_data: The current deduplication index data.
        daily_target: Target number of expressions to extract today.

    Returns:
        List of validated, deduplicated expression dicts with added "source" key.
    """
    if not raw_texts:
        logger.warning("No raw texts provided for processing")
        return []

    results = []
    batch_seen = set()  # Track expressions within this batch to avoid intra-batch duplicates

    # Calculate per-source target counts
    total_chunks = len(raw_texts)
    if total_chunks == 0:
        return []

    # Distribute targets across chunks, with a minimum of 3 per chunk
    per_chunk_target = max(3, daily_target // total_chunks)
    logger.info(f"Processing {total_chunks} text chunks, targeting ~{per_chunk_target} expressions per chunk (daily target: {daily_target})")

    for i, text_data in enumerate(raw_texts):
        source = text_data.get('source', 'unknown')
        raw_text = text_data.get('raw_text', '')

        if not raw_text or len(raw_text.strip()) < 50:
            logger.debug(f"Skipping chunk {i + 1}: text too short ({len(raw_text)} chars)")
            continue

        # Truncate very long texts to avoid token limits
        if len(raw_text) > 8000:
            raw_text = raw_text[:8000]

        logger.info(f"Processing chunk {i + 1}/{total_chunks} from source: {source} ({len(raw_text)} chars)")

        # Build prompt and call Gemini
        prompt = _build_extraction_prompt(raw_text, per_chunk_target, source)
        extracted = _call_gemini(prompt)

        # Validate, deduplicate, and collect results
        valid_count = 0
        dup_count = 0
        invalid_count = 0

        for expr in extracted:
            # Validate
            if not _validate_expression(expr):
                invalid_count += 1
                continue

            expression_text = str(expr['expression']).strip()
            normalized = normalize_expression(expression_text)

            # Check for intra-batch duplicates
            if normalized in batch_seen:
                dup_count += 1
                logger.debug(f"Intra-batch duplicate: '{expression_text}'")
                continue

            # Check against existing index
            if is_duplicate(normalized, index_data):
                dup_count += 1
                logger.debug(f"Index duplicate: '{expression_text}'")
                continue

            # Add source info and collect
            expr['source'] = source
            results.append(expr)
            batch_seen.add(normalized)
            valid_count += 1

        logger.info(
            f"Chunk {i + 1} results: {valid_count} valid, {dup_count} duplicates, "
            f"{invalid_count} invalid (out of {len(extracted)} extracted)"
        )

        # Don't process more chunks if we've already hit the target
        if len(results) >= daily_target:
            logger.info(f"Reached daily target ({daily_target}) after {i + 1} chunks")
            break

        # Polite delay between API calls
        if i < total_chunks - 1:
            time.sleep(config.API_CALL_DELAY)

    # Check if we reached the target
    if len(results) < daily_target:
        logger.warning(
            f"Shortfall: extracted {len(results)} expressions, target was {daily_target}. "
            f"Consider adding more sources or increasing per-chunk targets."
        )

    # Trim to daily target if we exceeded it
    if len(results) > daily_target:
        logger.info(f"Trimming results from {len(results)} to daily target of {daily_target}")
        results = results[:daily_target]

    logger.info(f"Processing complete. Final count: {len(results)} expressions")
    return results
