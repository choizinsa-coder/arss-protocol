import re

EXPLORATION_PATTERNS = [
    re.compile(r'가능성이\s*있', re.IGNORECASE),
    re.compile(r'[일ᆯ]\s*수\s*있', re.IGNORECASE),
    re.compile(r'로\s*보입니다', re.IGNORECASE),
    re.compile(r'추정됩니다', re.IGNORECASE),
    re.compile(r'가설입니다', re.IGNORECASE),
    re.compile(r'아이디어입니다', re.IGNORECASE),
    re.compile(r'생각됩니다', re.IGNORECASE),
    re.compile(r'추측됩니다', re.IGNORECASE),
    re.compile(r'것\s*같습니다', re.IGNORECASE),
    re.compile(r'수\s*있을\s*것', re.IGNORECASE),
]

UNCERTAINTY_PATTERNS = [
    re.compile(r'가능성'),
    re.compile(r'추정'),
    re.compile(r'가설'),
    re.compile(r'것\s*같'),
    re.compile(r'일\s*수\s*있'),
    re.compile(r'추측'),
    re.compile(r'보입니다'),
    re.compile(r'생각됩니다'),
]

PROPOSED_ACTION_PATTERNS = [
    re.compile(r'제안합니다', re.IGNORECASE),
    re.compile(r'하겠습니다', re.IGNORECASE),
    re.compile(r'필요합니다', re.IGNORECASE),
    re.compile(r'다음\s*단계', re.IGNORECASE),
    re.compile(r'수정하겠습니다', re.IGNORECASE),
    re.compile(r'진행하겠습니다', re.IGNORECASE),
]

ASSERTION_PATTERNS = [
    re.compile(r'완료되었습니다', re.IGNORECASE),
    re.compile(r'완료됨', re.IGNORECASE),
    re.compile(r'정상\s*작동합니다', re.IGNORECASE),
    re.compile(r'확인되었습니다', re.IGNORECASE),
    re.compile(r'검증\s*PASS', re.IGNORECASE),
    re.compile(r'ALL\s*PASS', re.IGNORECASE),
    re.compile(r'성공했습니다', re.IGNORECASE),
    re.compile(r'반영되었습니다', re.IGNORECASE),
    re.compile(r'적용되었습니다', re.IGNORECASE),
    re.compile(r'문제\s*없습니다', re.IGNORECASE),
    re.compile(r'현재\s*상태는.+입니다', re.IGNORECASE),
]

AUTO_ASSERTION_PATTERNS = [
    re.compile(r'사실상.+(완료|상태|확인)', re.IGNORECASE),
    re.compile(r'거의.+(검증|완료|확인).+(수준|상태)', re.IGNORECASE),
    re.compile(r'준\s*완료\s*상태', re.IGNORECASE),
]

NEXT_ACTION_RE = re.compile(
    r'(?im)^\s*next\s*action\s*:?\s*(?P<body>.+?)\s*$'
)

PLACEHOLDER_RE = re.compile(
    r'^[\s\W_]+$|^(tbd|todo|n/a|placeholder|없음|미정|추후|나중에)$',
    re.IGNORECASE
)


def has_uncertainty_marker(text: str) -> bool:
    return any(p.search(text) for p in UNCERTAINTY_PATTERNS)

def matches_exploration(text: str) -> bool:
    return any(p.search(text) for p in EXPLORATION_PATTERNS)

def matches_proposed_action(text: str) -> bool:
    return any(p.search(text) for p in PROPOSED_ACTION_PATTERNS)

def matches_assertion_state(text: str) -> bool:
    return any(p.search(text) for p in ASSERTION_PATTERNS)

def matches_auto_assertion(text: str) -> bool:
    return any(p.search(text) for p in AUTO_ASSERTION_PATTERNS)

def has_next_action(text: str) -> bool:
    m = NEXT_ACTION_RE.search(text)
    if not m:
        return False
    body = m.group('body').strip()
    if not body:
        return False
    if PLACEHOLDER_RE.match(body):
        return False
    return True
