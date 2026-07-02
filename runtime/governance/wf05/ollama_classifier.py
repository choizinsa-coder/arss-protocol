"""
ollama_classifier.py
WF-05 앞단 Ollama 분류레이어 -- S315 Step 3
EAG-S315-OLLAMA-STEP3-001
ᙺ트리거: phi4-mini로 작업 복잡도를 SIMPLE/COMPLEX로 분류.
Ollama 장애 시 COMPLEX 폴백 -- DEP 루프 보존 (가용성 우선).
"""
import json
import urllib.request

OLLAMA_BASE = 'http://127.0.0.1:11434'
OLLAMA_TIMEOUT = 60


def classify_task(task: str) -> dict:
    """
    phi4-mini로 작업 복잡도 분류.

    Returns:
        dict:
          ok      (bool) : Ollama 통신 성공 여부
          verdict (str)  : 'SIMPLE' | 'COMPLEX'
          raw     (str)  : phi4-mini 원본 응답
          error   (str)  : 실패 시 오류 메시지
    """
    prompt = (
        'You are a task complexity classifier for an AI governance system. '
        'Reply with exactly one word only: SIMPLE (can be answered directly '
        'without multi-agent design review) or COMPLEX (requires governance '
        'design and approval by multiple agents).\n\nTask: ' + task
    )
    body = json.dumps({
        'model': 'phi4-mini',
        'prompt': prompt,
        'stream': False,
        'options': {'num_predict': 5, 'temperature': 0}
    }).encode()
    req = urllib.request.Request(
        OLLAMA_BASE + '/api/generate',
        data=body,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
            text = data.get('response', '').strip().upper()
            verdict = 'SIMPLE' if 'SIMPLE' in text else 'COMPLEX'
            return {'ok': True, 'verdict': verdict, 'raw': text}
    except Exception as e:
        # Ollama 장애 시 COMPLEX 폴백 -- DEP 루프 보존
        return {'ok': False, 'verdict': 'COMPLEX', 'raw': '', 'error': str(e)}
