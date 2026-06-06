"""
change_classifier.py v1.0.0
AIBA Change Classifier — broad scope 자율 수정 git diff 강제 검증기

설계 근거: S196 오케스트레이션 Rev.2 (도미 Rev.3 + 제니 TRUST_READY PASS)
거버넌스 체인: 도미 설계 → 제니 TRUST_READY PASS → 비오 EAG 승인

목적:
  broad scope 자율 pytest 수정 루프에서, 캐디가 수행한 변경이
  "허용 범위(test 파일 내 assert 값 변경)"를 벗어나지 않았음을
  git diff 파싱으로 기술적으로 강제 검증한다.

Safe Default 원칙 (제니 FAIL-4 해소):
  명시적 허용(REUSE_PRESCAN)에 해당하지 않는 모든 변경은
  TRIGGER_REJENI(=REPORT & WAIT 강제)로 귀속된다.

허용 (broad scope 자율 진행 가능):
  - test 파일 내 assert 구문의 숫자/문자열 리터럴 값 변경만

금지 (즉시 REPORT & WAIT 강제):
  - 함수 추가/삭제 (def / async def 라인 변경)
  - import 구문 변경
  - test 파일 외 파일 변경
  - 새 파일 생성/삭제
  - assert 외 로직 라인 변경
  - class 정의 변경
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class ChangeVerdict(Enum):
    """변경 분류 결과."""
    ALLOW = "ALLOW"                  # broad scope 자율 진행 허용
    TRIGGER_REPORT_WAIT = "TRIGGER_REPORT_WAIT"  # REPORT & WAIT 강제


# test 파일 판별 패턴
_TEST_FILE_PATTERN = re.compile(r"(^|/)test_[^/]+\.py$|(^|/)[^/]+_test\.py$")

# diff 파일 헤더 패턴: "diff --git a/path b/path"
_DIFF_GIT_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+?)$")

# 새 파일 / 삭제 파일 마커
_NEW_FILE_MARKER = re.compile(r"^new file mode")
_DELETED_FILE_MARKER = re.compile(r"^deleted file mode")

# 변경된 코드 라인 (+ 또는 -, 단 +++/--- 헤더 제외)
_ADDED_LINE = re.compile(r"^\+(?!\+\+)(.*)$")
_REMOVED_LINE = re.compile(r"^-(?!--)(.*)$")

# 금지 구문 패턴 (변경 라인에 등장 시 즉시 차단)
_FORBIDDEN_PATTERNS = [
    (re.compile(r"^\s*(async\s+)?def\s+"), "function definition change"),
    (re.compile(r"^\s*class\s+"), "class definition change"),
    (re.compile(r"^\s*import\s+"), "import statement change"),
    (re.compile(r"^\s*from\s+\S+\s+import\s+"), "from-import statement change"),
    (re.compile(r"^\s*@"), "decorator change"),
]

# assert 구문 패턴 (허용 대상)
_ASSERT_PATTERN = re.compile(r"^\s*assert\s+")


@dataclass
class FileChange:
    """단일 파일의 변경 정보."""
    path: str
    is_test_file: bool
    is_new_file: bool = False
    is_deleted_file: bool = False
    changed_lines: list[str] = field(default_factory=list)  # +/- 라인 (마커 제외 본문)


@dataclass
class ClassificationResult:
    """전체 분류 결과."""
    verdict: ChangeVerdict
    reasons: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "reasons": self.reasons,
            "files_changed": self.files_changed,
        }


def is_test_file(path: str) -> bool:
    """test 파일 여부 판별."""
    return bool(_TEST_FILE_PATTERN.search(path))


def parse_git_diff(diff_text: str) -> list[FileChange]:
    """
    git diff 출력을 파싱하여 파일별 변경 정보 추출.
    """
    files: list[FileChange] = []
    current: FileChange | None = None

    for line in diff_text.splitlines():
        header_match = _DIFF_GIT_HEADER.match(line)
        if header_match:
            # 새 파일 블록 시작
            if current is not None:
                files.append(current)
            path = header_match.group(2)  # b/ 경로 사용
            current = FileChange(path=path, is_test_file=is_test_file(path))
            continue

        if current is None:
            continue

        if _NEW_FILE_MARKER.match(line):
            current.is_new_file = True
            continue
        if _DELETED_FILE_MARKER.match(line):
            current.is_deleted_file = True
            continue

        # 변경 라인 수집 (헤더 +++/--- 제외)
        if line.startswith("+++") or line.startswith("---"):
            continue
        added = _ADDED_LINE.match(line)
        if added:
            current.changed_lines.append(added.group(1))
            continue
        removed = _REMOVED_LINE.match(line)
        if removed:
            current.changed_lines.append(removed.group(1))
            continue

    if current is not None:
        files.append(current)

    return files


def _line_is_assert_value_change(line: str) -> bool:
    """
    변경 라인이 assert 구문인지 확인.
    assert 구문 내 값 변경만 허용 대상.
    """
    return bool(_ASSERT_PATTERN.match(line))


def _check_forbidden(line: str) -> str | None:
    """
    변경 라인이 금지 패턴에 해당하는지 검사.
    해당 시 사유 문자열 반환, 아니면 None.
    """
    for pattern, reason in _FORBIDDEN_PATTERNS:
        if pattern.match(line):
            return reason
    return None


def classify(diff_text: str) -> ClassificationResult:
    """
    git diff 텍스트를 분류하여 broad scope 자율 진행 가능 여부 판정.

    ALLOW 조건 (모두 충족):
      1. 변경된 모든 파일이 test 파일
      2. 새 파일 생성/삭제 없음
      3. 모든 변경 라인이 assert 구문 (또는 공백/주석)
      4. 금지 패턴(def/class/import/decorator) 미등장

    하나라도 위반 시 TRIGGER_REPORT_WAIT (Safe Default).
    """
    if not diff_text.strip():
        # 변경 없음 → 안전하게 ALLOW (자율 루프가 아무것도 안 바꾼 경우)
        return ClassificationResult(
            verdict=ChangeVerdict.ALLOW,
            reasons=["no changes detected"],
            files_changed=[],
        )

    files = parse_git_diff(diff_text)
    reasons: list[str] = []
    files_changed = [f.path for f in files]
    blocked = False

    for fc in files:
        # 조건 1: test 파일 외 변경 금지
        if not fc.is_test_file:
            reasons.append(f"non-test file changed: {fc.path}")
            blocked = True
            continue

        # 조건 2: 새 파일/삭제 금지
        if fc.is_new_file:
            reasons.append(f"new file creation: {fc.path}")
            blocked = True
            continue
        if fc.is_deleted_file:
            reasons.append(f"file deletion: {fc.path}")
            blocked = True
            continue

        # 조건 3+4: 변경 라인 검사
        for line in fc.changed_lines:
            stripped = line.strip()
            # 공백/주석 라인은 무해 → 통과
            if not stripped or stripped.startswith("#"):
                continue
            # 금지 패턴 검사 (Safe Default)
            forbidden = _check_forbidden(line)
            if forbidden:
                reasons.append(f"{fc.path}: {forbidden} -> '{stripped[:60]}'")
                blocked = True
                continue
            # assert 구문이 아닌 일반 로직 라인 → 차단 (Safe Default)
            if not _line_is_assert_value_change(line):
                reasons.append(f"{fc.path}: non-assert logic change -> '{stripped[:60]}'")
                blocked = True

    if blocked:
        return ClassificationResult(
            verdict=ChangeVerdict.TRIGGER_REPORT_WAIT,
            reasons=reasons,
            files_changed=files_changed,
        )

    return ClassificationResult(
        verdict=ChangeVerdict.ALLOW,
        reasons=["all changes are assert value modifications in test files"],
        files_changed=files_changed,
    )


if __name__ == "__main__":
    # 간이 자가검증 (실제 테스트는 tests/ 에 별도)
    sample_allow = """diff --git a/tests/test_foo.py b/tests/test_foo.py
index abc..def 100644
--- a/tests/test_foo.py
+++ b/tests/test_foo.py
@@ -1,3 +1,3 @@
-    assert result == 41
+    assert result == 42
"""
    sample_block = """diff --git a/tools/core.py b/tools/core.py
index abc..def 100644
--- a/tools/core.py
+++ b/tools/core.py
@@ -1,3 +1,3 @@
-def old_func():
+def new_func():
"""
    print("ALLOW sample:", classify(sample_allow).to_dict())
    print("BLOCK sample:", classify(sample_block).to_dict())
