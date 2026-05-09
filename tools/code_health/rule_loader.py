"""
rule_loader.py — Code Health Enforcement Layer v1.0
AIBA Code Health Protocol
규칙 상수 로딩 모듈
"""

# RULE-1: Legacy/Backup 패턴
RULE1_FORBIDDEN_PATTERNS = [
    "*_backup.py",
    "*_old.py",
    "*_before_fix.py",
    "*_before_*.py",
    "*_v*_backup.py",
    "patch_*.py",
    "temp_*.py",
    "misc_*.py",
]

RULE1_LEGACY_DIRS = [
    "99_LEGACY",
    "archive",
    "deprecated",
]

# RULE-2: Import 표준
RULE2_REQUIRED_PREFIX = "tools."

RULE2_BARE_IMPORT_TARGETS = [
    "r3_validator",
    "recovery_manager",
    "migration_validator",
    "mutation_gate",
]

# RULE-3: Test 위치
RULE3_CANONICAL_TEST_ROOT = "tests"

# RULE-4: Version 선언
RULE4_ACTIVE_VERSION_MARKERS = [
    "ACTIVE_VERSION",
    "VERSION_STATUS",
]

RULE4_INACTIVE_MARKERS = [
    "INACTIVE",
    "archive",
    "legacy",
    "deprecated",
]

# RULE-5: 함수 책임 한계
RULE5_FUNCTION_LINE_FAIL = 120
RULE5_FUNCTION_LINE_REVIEW = 80
RULE5_MULTI_RESPONSIBILITY_KEYWORDS = ["and", "then", "with", "plus"]

# RULE-6: Fail-Closed
RULE6_FORBIDDEN_EXCEPT_PATTERNS = [
    "pass",
    "continue",
]

RULE6_FORBIDDEN_RETURN_AFTER_EXCEPT = [
    "success=True",
    "PASS",
    "pass=True",
]

# RULE-7: Mutation 명시
RULE7_MUTATION_KEYWORDS = [
    "mutate",
    "apply",
    "write",
    "commit",
    "update",
    "recompute",
    "mark",
]

RULE7_STATE_TARGETS = [
    "SESSION_CONTEXT",
    "INDEX",
    "TX",
    "COMMIT",
    "evidence",
    "chain_tip",
]

# RULE-7: 읽기 전용 함수 whitelist (state를 참조만 하는 함수명 패턴)
RULE7_READONLY_PREFIXES = [
    "get_", "load_", "read_", "verify_", "check_", "validate_",
    "compute_", "build_", "format_", "print_", "parse_", "find_",
    "_load_", "_get_", "_validate_", "_check_", "_verify_",
    "test_", "_make_", "_base_", "_setup", "_ctx",
    "step", "main", "run", "execute", "emit",
]

# RULE-7: 생성자 예외 (Constructor Exception)
RULE7_CONSTRUCTOR_EXCEPTION = {"__init__"}

# RULE-8: TDD
RULE8_TEST_FILE_PREFIX = "test_"

# RULE-9: Domain 용어
RULE9_FORBIDDEN_GENERIC_NAMES = [
    "data",
    "item",
    "object",
    "thing",
    "process",
    "handle",
    "manager",
    "helper",
    "util",
    "temp",
    "misc",
]

RULE9_DOMAIN_KEYWORDS = {
    "governance": [
        "session_context", "constitution", "interpretation_rule",
        "ssot", "ssoi", "eag", "approval", "trust_ready", "revalidation",
    ],
    "chain": [
        "rpu", "chain", "chain_tip", "receipt", "ledger", "evidence", "hash",
    ],
    "execution": [
        "pipeline", "stage", "transaction", "tx", "commit", "index",
        "delta", "validator", "gate", "fail_closed",
    ],
    "auto_loader": [
        "load", "source", "adapter", "target", "verification",
        "mutation", "activation", "result",
    ],
}

# Severity 상수
SEVERITY_FAIL = "FAIL"
SEVERITY_REVIEW = "REVIEW_REQUIRED"
SEVERITY_PASS = "PASS"

# Gate 식별자
GATE_ID = "CODE_HEALTH"
LAYER_VERSION = "v1.0"
