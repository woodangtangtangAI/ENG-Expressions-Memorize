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

아래 텍스트에서 비원어민이 실전에서 반드시 알아야 할 실전 영어 표현을 정확히 {target_count}개 추출하세요.

[대상 표현 유형]
1. Phrasal Verbs (구동사): 예) pull off, bring up
2. Business Collocations (비즈니스 연어): 예) raise concerns
3. Daily Idioms (일상 관용구): 예) a piece of cake

[추출 규칙]
- go, make, have, get, take 등 기초 단어 단독 사용은 절대 제외
- 중급~고급 학습자에게 유용한 표현만 선별
- JSON 배열 형식으로만 응답하세요:
[
  {{
    "expression": "표현",
    "pos": "phrasal verb / collocation / idiom",
    "ipa": "/IPA 발음/",
    "meaning_kr": "한국어 의미",
    "original_text": "원문 문장",
    "applied_example": "새로운 예문"
  }}
]

[텍스트]
{text_chunk}"""
    return prompt

def _call_gemini(prompt: str) -> list[dict]:
    client = genai.Client(api_key=config.GEMINI_API_KEY)

    for attempt in range(config.API_MAX_RETRIES):
        try:
            logger.info(f"Calling Gemini API (attempt {attempt + 1})...")
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )

            if not response or not response.text:
                time.sleep(30)
                continue

            response_text = response.text.strip()
            if response_text.startswith('```'):
                response_text = re.sub(r'^```(?:json)?\s*\n?', '', response_text)
                response_text = re.sub(r'\n?```\s*$', '', response_text)
                response_text = response_text.strip()

            parsed = json.loads(response_text)
            if isinstance(parsed, list):
                return parsed
        except Exception as e:
            logger.warning(f"Gemini API error: {e}")
            time.sleep(60) # Wait 60s on failure
            
    return []

def _validate_expression(expr_dict: dict) -> bool:
    required_keys = ['expression', 'pos', 'ipa', 'meaning_kr', 'original_text', 'applied_example']
    for key in required_keys:
        if key not in expr_dict or not expr_dict[key]:
            return False
    return len(str(expr_dict['expression']).strip()) >= 2

def process_and_extract(raw_texts: list[dict], index_data: dict, daily_target: int) -> list[dict]:
    if not raw_texts:
        return []

    # 근본적인 해결책: 모든 텍스트를 하나로 합치고, 딱 5번만 API를 호출합니다.
    combined_text = ""
    for text_data in raw_texts:
        combined_text += text_data.get('raw_text', '') + "\n\n"
        
    chunk_size = 35000 # 35,000 characters per chunk
    text_chunks = [combined_text[i:i+chunk_size] for i in range(0, len(combined_text), chunk_size)]
    
    if not text_chunks:
        return []

    target_per_call = (daily_target // 5) + 5 # 중복 대비 약간 여유있게 요청
    num_calls = min(5, len(text_chunks))
    
    results = []
    batch_seen = set()
    
    logger.info(f"Consolidated into massive chunks. Will make exactly {num_calls} API calls.")

    for i in range(num_calls):
        logger.info(f"Processing chunk {i+1}/{num_calls} ({len(text_chunks[i])} chars)...")
        prompt = _build_extraction_prompt(text_chunks[i], target_per_call)
        extracted = _call_gemini(prompt)
        
        for expr in extracted:
            if not _validate_expression(expr): continue
            normalized = normalize_expression(expr['expression'])
            if normalized in batch_seen or is_duplicate(normalized, index_data): continue
            
            expr['source'] = "Mixed Sources" # 출처는 통합됨
            results.append(expr)
            batch_seen.add(normalized)
            
        logger.info(f"Total collected so far: {len(results)} / {daily_target}")
        
        if len(results) >= daily_target:
            break
            
        if i < num_calls - 1:
            logger.info("Sleeping for 60 seconds to absolutely avoid rate limits...")
            time.sleep(60)

    if len(results) > daily_target:
        results = results[:daily_target]

    logger.info(f"Processing complete. Final count: {len(results)} expressions")
    return results
