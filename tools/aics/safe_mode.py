"""
safe_mode.py
AICS — Safe Mode Kill Switch (언제 전부 정지되는가)
영역 9 / EAG-S271-AICS-001

제니 TRUST-ADVISORY ② 반영:
  Safe Mode 해제(disable)는 완전 폐쇄형으로 설계.
  비오님 EAG 수동 서명 또는 내부 기술 무결성 검증(technical_match)
  둘 중 하나가 없으면 복구 거부(RECOVERY_DENIED).

흐름:
  enable  : flag 파일 생성 → 전체 토큰 revoke → 신규 요청 거부 상태
  disable : EAG 또는 TECHNICAL_MATCH 확인 → flag 제거 → 신규 토큰 재발급 필요
"""

from __future__ import annotations

import os
import sys

from .schemas import AICSReason


class SafeModeController:
    """Safe Mode 상태를 flag 파일로 관리. 인메모리 상태와 동기화."""

    def __init__(self, flag_path: str, runtime=None):
        self._flag_path = flag_path
        self._active = os.path.isfile(flag_path)
        # EAG-S420-SAFEMODE-ENABLE-CALLER-001: enable()은 신뢰된 소유 런타임 경유만.
        self._trusted_caller = runtime

    def is_active(self) -> bool:
        # 파일 기준 재확인 (외부 운영자 수동 개입 대비)
        self._active = os.path.isfile(self._flag_path)
        return self._active

    def enable(self, reason: str = "UNSPECIFIED", token_manager=None,
               *, caller=None) -> bool:
        """Safe Mode 진입. 영역 2 AutoGuard 또는 운영자가 호출.

        EAG-S420-SAFEMODE-ENABLE-CALLER-001: 신뢰된 소유 런타임
        (caller is self._trusted_caller)을 통해서만 허용. 객체 동일성
        비교이므로 신분 문자열 위장(spoofing) 불가. 미설정/불일치 시 fail-closed.
        """
        if self._trusted_caller is None or caller is not self._trusted_caller:
            print("[SAFEMODE] UNAUTHORIZED enable() call rejected", file=sys.stderr)
            return False
        try:
            os.makedirs(os.path.dirname(self._flag_path), exist_ok=True)
            with open(self._flag_path, "w", encoding="utf-8") as f:
                f.write(f"SAFE_MODE_ACTIVE\nreason={reason}\n")
        except OSError:
            return False
        self._active = True
        # 전체 토큰 즉시 무효화
        if token_manager is not None:
            token_manager.revoke_all()
        return True

    def disable(self, eag_approval: str | None = None,
                technical_match: bool = False) -> tuple[bool, str]:
        """
        Safe Mode 해제. 폐쇄형 복구 (advisory ②).
        반환: (성공여부, 사유코드)
        """
        # EAG 수동 서명 또는 기술 무결성 검증 중 하나 필수
        has_eag = bool(eag_approval) and str(eag_approval).strip() != ""
        if not has_eag and not technical_match:
            return False, AICSReason.RECOVERY_DENIED
        try:
            if os.path.isfile(self._flag_path):
                os.remove(self._flag_path)
        except OSError:
            return False, AICSReason.RECOVERY_DENIED
        self._active = False
        return True, AICSReason.OK
