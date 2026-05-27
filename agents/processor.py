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


def _build_extraction_prompt(text_chunk: str, target_count: int) -> str:
    prompt = f"""당신은 비원어민 직장인을 위한 영어 네이티브 표현 전문가입니다.

아래 영어 텍스트에서 비원어민이 실전에서 반드시 알아야 할 실전 영어 표현을 정확히 {target_count}개 추출하세요.
각 표현이 원래 속해 있던 텍스트의 SOURCE(예: CNBC, BBC_Business, HBR, Friends)를 파악하여 결과의 "source" 필드에 정확히 기록해 주세요.

[대상 표현 유형]
1. Phrasal Verbs (구동사): 예) pull off, bring up, figure out, iron out
2. Business Collocations (비즈니스 연어): 예) raise concerns, drive growth, meet expectations
3. Daily Idioms (일상 관용구): 예) a piece of cake, break the ice, hit the nail on the head

[추출 규칙]
- go, make, have, get, take 등 기초 단어 단독 사용은 절대 제외
- 중급~고급 학습자에게 실질적으로 유용한 표현만 선별
- 원문 문장에 등장하는 SOURCE 정보를 정확하게 매칭하여 "source" 필드에 기록
- JSON 배열 형식으로만 응답하세요:
[
  {{
    "expression": "표현",
    "pos": "phrasal verb / collocation / idiom",
    "ipa": "/IPA 발음/",
    "meaning_kr": "자연스러운 한국어 의미",
    "original_text": "이 표현이 사용된 원문 문장",
    "applied_example": "새로운 맥락의 예문",
    "source": "원문 텍스트의 SOURCE 명칭"
  }}
]

[텍스트]
{text_chunk}"""
    return prompt


def _build_backfill_prompt(text_chunk: str, target_count: int, avoid_expressions: list[str]) -> str:
    avoid_str = ", ".join(avoid_expressions[:50])
    prompt = f"""당신은 비원어민 직장인을 위한 영어 네이티브 표현 전문가입니다.

아래 영어 텍스트에서 비원어민이 실전에서 알아야 할 실전 영어 표현을 추가로 {target_count}개 더 추출하세요.
단, 아래 기존에 추출된 표현들은 중복되므로 **절대 제외**하고 새로운 표현들로만 추출해야 합니다.
각 표현이 원래 속해 있던 텍스트의 SOURCE(예: CNBC, BBC_Business, HBR, Friends)를 파악하여 결과의 "source" 필드에 정확히 기록해 주세요.

[제외할 기존 표현 목록]
{avoid_str}

[대상 표현 유형]
1. Phrasal Verbs (구동사): 예) pull off, bring up
2. Business Collocations (비즈니스 연어): 예) raise concerns
3. Daily Idioms (일상 관용구): 예) a piece of cake

[추출 규칙]
- go, make, have, get, take 등 기초 단어 단독 사용은 절대 제외
- 중급~고급 학습자에게 유용한 표현만 선별
- 원문 문장에 등장하는 SOURCE 정보를 정확하게 매칭하여 "source" 필드에 기록
- JSON 배열 형식으로만 응답하세요:
[
  {{
    "expression": "표현",
    "pos": "phrasal verb / collocation / idiom",
    "ipa": "/IPA 발음/",
    "meaning_kr": "한국어 의미",
    "original_text": "원문 문장",
    "applied_example": "새로운 예문",
    "source": "원문 텍스트의 SOURCE 명칭"
  }}
]

[텍스트]
{text_chunk}"""
    return prompt


def _call_gemini(prompt: str) -> list[dict]:
    """
    Call the Gemini API with automatic failover across different models.
    """
    # List of models to try in order
    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash"
    ]
    
    # Prioritize config.GEMINI_MODEL if specified
    if config.GEMINI_MODEL and config.GEMINI_MODEL not in models_to_try:
        models_to_try.insert(0, config.GEMINI_MODEL)
    elif config.GEMINI_MODEL:
        # Move configured model to the front of the list
        models_to_try.remove(config.GEMINI_MODEL)
        models_to_try.insert(0, config.GEMINI_MODEL)

    client = genai.Client(api_key=config.GEMINI_API_KEY)

    try:
        available_models = [m.name for m in client.models.list()]
        logger.info(f"Available models for this API key: {available_models}")
    except Exception as list_err:
        logger.warning(f"Failed to list models: {list_err}")

    for model_name in models_to_try:
        logger.info(f"Attempting API call with model: {model_name}...")
        for attempt in range(config.API_MAX_RETRIES):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )

                if not response or not response.text:
                    logger.warning(f"Empty response from {model_name} (attempt {attempt + 1})")
                    time.sleep(5)
                    continue

                response_text = response.text.strip()
                if response_text.startswith('```'):
                    response_text = re.sub(r'^```(?:json)?\s*\n?', '', response_text)
                    response_text = re.sub(r'\n?```\s*$', '', response_text)
                    response_text = response_text.strip()

                parsed = json.loads(response_text)
                if isinstance(parsed, list):
                    logger.info(f"Successfully extracted {len(parsed)} expressions using {model_name}")
                    # Update config.GEMINI_MODEL to save it for subsequent steps in this run
                    config.GEMINI_MODEL = model_name
                    return parsed
                else:
                    logger.warning(f"Response from {model_name} is not a list: {type(parsed)}")
                    time.sleep(5)

            except Exception as e:
                logger.warning(f"API call failed with model {model_name} (attempt {attempt + 1}): {e}")
                
                # Immediate failover for quota/rate limit errors
                err_str = str(e).upper()
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "QUOTA" in err_str:
                    logger.warning(f"Quota limits hit for {model_name}. Transitioning to next model...")
                    break  # Break attempts loop to try next model
                
                if attempt < config.API_MAX_RETRIES - 1:
                    time.sleep(5)

    logger.error("All models in failover chain failed to return a valid response.")
    return []


def _validate_expression(expr_dict: dict) -> bool:
    required_keys = ['expression', 'pos', 'ipa', 'meaning_kr', 'original_text', 'applied_example']
    for key in required_keys:
        if key not in expr_dict or not expr_dict[key]:
            return False
            
    # Check expression length
    expression = str(expr_dict['expression']).strip()
    if len(expression) < 2:
        return False
        
    # Check POS
    pos = str(expr_dict['pos']).strip().lower()
    if pos not in VALID_POS_TYPES:
         return False
         
    return True


def process_and_extract(raw_texts: list[dict], index_data: dict, daily_target: int) -> list[dict]:
    """
    Consolidates raw text chunks and extracts daily expressions in exactly 1 call (with max 1 backfill call).
    """
    if not raw_texts:
        logger.warning("No raw texts provided for processing")
        return []

    # 1. Combine all raw texts into a single annotated corpus
    combined_text = ""
    for text_data in raw_texts:
        source = text_data.get('source', 'Unknown')
        text = text_data.get('raw_text', '').strip()
        if text:
            combined_text += f"--- SOURCE: {source} ---\n{text}\n\n"

    # Truncate text to a safe size of 60,000 characters to keep prompt size efficient
    if len(combined_text) > 60000:
        logger.info(f"Combined text size ({len(combined_text)} chars) is large. Slicing to 60,000 characters for token efficiency.")
        combined_text = combined_text[:60000]

    results = []
    batch_seen = set()

    # Call 1: Primary Extraction
    logger.info(f"Call 1: Extracting up to {daily_target} expressions...")
    prompt = _build_extraction_prompt(combined_text, daily_target)
    extracted = _call_gemini(prompt)

    for expr in extracted:
        if not _validate_expression(expr):
            continue
        expression_text = str(expr['expression']).strip()
        normalized = normalize_expression(expression_text)
        if normalized in batch_seen or is_duplicate(normalized, index_data):
            continue

        results.append(expr)
        batch_seen.add(normalized)

    logger.info(f"Call 1 complete. Collected {len(results)} / {daily_target} valid expressions.")

    # Call 2 (Optional Backfill): If we didn't meet the target, make one more call requesting the difference
    shortfall = daily_target - len(results)
    if shortfall > 0:
        logger.info(f"Target shortfall of {shortfall} expressions detected. Initiating Call 2 (Backfill)...")
        avoid_list = [r['expression'] for r in results]
        
        backfill_prompt = _build_backfill_prompt(combined_text, shortfall, avoid_list)
        
        # Pause briefly to prevent transient rate limits
        time.sleep(5)
        
        extracted_backfill = _call_gemini(backfill_prompt)
        backfill_added = 0
        for expr in extracted_backfill:
            if not _validate_expression(expr):
                continue
            expression_text = str(expr['expression']).strip()
            normalized = normalize_expression(expression_text)
            if normalized in batch_seen or is_duplicate(normalized, index_data):
                continue

            results.append(expr)
            batch_seen.add(normalized)
            backfill_added += 1
            if len(results) >= daily_target:
                break
        logger.info(f"Call 2 (Backfill) complete. Added {backfill_added} expressions.")

    # Trim to daily target
    if len(results) > daily_target:
        logger.info(f"Trimming results from {len(results)} to target {daily_target}")
        results = results[:daily_target]

    logger.info(f"Extraction complete. Total collected: {len(results)} expressions.")
    return results
