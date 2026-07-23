"""
ollama_log_analyzer.py
AIBA 로그 이상 패턴 분석 스크립트 -- S315 Step 3
EAG-S315-OLLAMA-STEP3-001

동작: phi4-mini로 caddy_errors.jsonl + wf05_audit.log 요약/이상 감지.
타이머: systemd 타이머 또는 cron으로 주기 실행.
출력: runtime/governance/audit/ollama_analysis_latest.json
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

ROOT = '/opt/arss/engine/arss-protocol'
ERROR_LOG = ROOT + '/tools/caddy_error_log/caddy_errors.jsonl'
AUDIT_LOG = ROOT + '/runtime/governance/audit/wf05_audit.log'
OUTPUT = ROOT + '/runtime/governance/audit/ollama_analysis_latest.json'
OLLAMA_BASE = 'http://127.0.0.1:11434'
OLLAMA_TIMEOUT = 240
MAX_ENTRIES = 12
KST = timezone(timedelta(hours=9))


def read_jsonl_tail(path, n):
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
    return entries[-n:]


def build_prompt(errors, audits):
    parts = ['[AIBA 로그 요약 요청]']
    parts.append(f'\ncaddy_errors.jsonl 최근 {len(errors)}건:')
    for e in errors:
        ts = e.get('timestamp', '')[:19]
        desc = e.get('description', '')
        cat = e.get('category', '')
        parts.append(f'  [{ts}] [{cat}] {desc}')
    parts.append(f'\nwf05_audit.log 최근 {len(audits)}건:')
    for a in audits:
        ts = a.get('ts', '')[:19]
        stage = a.get('stage', '')
        status = a.get('status', '')
        detail = a.get('detail', '')
        parts.append(f'  [{ts}] {stage}/{status} {detail}')
    parts.append('\n위 로그를 분석하십시오. 이상 패턴, 반복 실패, 주목할 건을 한 문단으로 요약하십시오.')
    return '\n'.join(parts)


def ask_ollama(prompt):
    body = json.dumps({
        'model': 'phi4-mini',
        'prompt': prompt,
        'stream': False,
        'keep_alive': '10m',
        'options': {'num_predict': 200, 'temperature': 0.1}
    }).encode()
    req = urllib.request.Request(
        OLLAMA_BASE + '/api/generate',
        data=body,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
        data = json.loads(resp.read().decode())
        return data.get('response', '').strip()


def main():
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    errors = read_jsonl_tail(ERROR_LOG, MAX_ENTRIES)
    audits = read_jsonl_tail(AUDIT_LOG, MAX_ENTRIES)
    prompt = build_prompt(errors, audits)
    try:
        summary = ask_ollama(prompt)
        ok = True
        err_msg = ''
    except Exception as e:
        summary = ''
        ok = False
        err_msg = str(e)
    result = {
        'ts': datetime.now(KST).isoformat(),
        'ok': ok,
        'error_entries_analyzed': len(errors),
        'audit_entries_analyzed': len(audits),
        'summary': summary,
        'error': err_msg
    }
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
