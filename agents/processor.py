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
    prompt = f"""당신은 한국인을 위한 영어 네이티브 표현 교육 전문가입니다.

아래 제공된 [텍스트]를 참고하여, 비원어민이 미드, 일상 대화, 비즈니스 환경에서 반드시 알아야 할 실용적이고 세련된 영어 표현을 정확히 {target_count}개 생성 및 추출해 주세요.
텍스트에 쓰인 어휘나 맥락에서 아이디어를 얻되, 단순한 직역 단어가 아닌 실제 네이티브들이 입에 달고 사는 유용한 표현들로 업그레이드하여 엄선하세요.

[대상 표현 유형]
1. Phrasal Verbs (구동사): 예) pull off, bring up, figure out, run into, put up with
2. Daily/Business Collocations (실전 연어): 예) make a difference, raise concerns, catch someone's eye, keep in loop
3. Daily Idioms & Colloquial Phrases (일상 관용구 및 구어체): 예) call it a day, hit the nail on the head, read between the lines, speak of the devil

[중요 추출 및 생성 규칙]
- **동사원형(기본형) 규칙**: `expression` 필드에는 시제(과거형, 분사형 등)나 3인칭 단수형(-s)을 모두 제거하고, 반드시 **원형(동사원형/기본형, e.g., 'keep secret', 'double down on')**으로만 표기하세요.
- **교과서 외 실전 표현**: 한국 교과서나 수능 시험에서 외우는 평이한 단어 단독 사용은 배제하고, 실생활 및 미드(드라마/영화)에서 자주 쓰이지만 한국인들이 놓치기 쉬운 표현들을 선별하세요.
- **출처(Source) 매핑**: 텍스트 소스에 매칭되는 경우 해당 소스명(예: CNBC, BBC_Business, Friends 등)을 기록하되, 생성 및 기여의 원천이 되는 소스를 적어주세요.

반드시 아래 JSON 배열 형식으로만 응답하세요. 백틱(`) 기호나 markdown json 블록을 쓰지 말고 순수한 JSON 텍스트로만 응답하세요:
[
  {{
    "expression": "기본형(동사원형) 형태의 영어 표현",
    "pos": "phrasal verb / collocation / idiom",
    "ipa": "/정확한 IPA 발음 기호/",
    "meaning_kr": "한국어로 번역된 실제 맥락에서의 자연스러운 의미 (사전적 직역 금지)",
    "original_text": "원문 텍스트에 나타난 표현 혹은 원문의 영감을 받아 자연스럽게 재구성한 미드/대화 속 문장",
    "applied_example": "이 표현을 일상 대화나 비즈니스에서 바로 사용할 수 있는 새로운 실전 예문",
    "source": "CNBC / BBC_Business / HBR / Friends 중 연관된 출처 명칭"
  }}
]

[텍스트]
{text_chunk}"""
    return prompt


def _build_backfill_prompt(text_chunk: str, target_count: int, avoid_expressions: list[str]) -> str:
    avoid_str = ", ".join(avoid_expressions[:50])
    prompt = f"""당신은 한국인을 위한 영어 네이티브 표현 교육 전문가입니다.

아래 영어 텍스트를 기반으로, 비원어민이 실전에서 꼭 알아야 할 실전 영어 표현을 추가로 {target_count}개 더 생성 및 추출하세요.
단, 아래 기존에 추출된 표현들은 중복되므로 **절대 제외**하고 새로운 표현들로만 추출해야 합니다.

[제외할 기존 표현 목록]
{avoid_str}

[대상 표현 유형]
1. Phrasal Verbs (구동사): 예) pull off, bring up
2. Daily/Business Collocations (실전 연어): 예) raise concerns, make a difference
3. Daily Idioms & Colloquial Phrases (일상 관용구 및 구어체): 예) call it a day, speak of the devil

[중요 추출 및 생성 규칙]
- **동사원형(기본형) 규칙**: `expression` 필드에는 반드시 시제를 제외한 **원형(동사원형/기본형, e.g., 'keep secret', 'double down on')**으로만 표기하세요.
- **교과서 외 실전 표현**: 교과서용 기초 단어를 피하고, 실제 생활이나 미드 대화에서 자주 쓰이는 유용한 표현을 선별하세요.
- **출처(Source) 매핑**: CNBC / BBC_Business / HBR / Friends 중 연관된 출처 명칭을 정확히 기입하세요.

반드시 아래 JSON 배열 형식으로만 응답하세요. 백틱 기호나 markdown 블록을 쓰지 마세요:
[
  {{
    "expression": "기본형(동사원형) 형태의 영어 표현",
    "pos": "phrasal verb / collocation / idiom",
    "ipa": "/정확한 IPA 발음 기호/",
    "meaning_kr": "한국어 의미",
    "original_text": "원문 문장 또는 원문을 기반으로 재구성한 구어체 문장",
    "applied_example": "새로운 맥락의 실전 예문",
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
        "gemini-3.5-flash",
        "gemini-flash-latest",
        "gemini-3.1-flash-lite",
        "gemini-2.0-flash-lite",
        "gemini-2.5-pro"
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
