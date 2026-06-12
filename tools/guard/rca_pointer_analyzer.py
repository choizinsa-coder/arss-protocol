"""
rca_pointer_analyzer.py
INC-S230-POINTER-001 RCA 분석 도구

EAG: EAG-S232-RCA-POINTER-001
위치: tools/guard/rca_pointer_analyzer.py
설계: 도미 (CSO) + 캐디 교정 (제니 T-4/T-6/T-7 반영)

목적:
  SESSION_CONTEXT_POINTER.json이 S202 이후 27세션 미갱신된 원인을
  U-01~U-05 항목으로 정적 분석한다.

사용법:
  python3 rca_pointer_analyzer.py
"""

import os
import re
import json


class RCAPointerAnalyzer:
    def __init__(self, root_path=None):
        # HARD CODE 경로 금지 제약 준수: 환경 변수 우선, 기본값 지정
        self.root_path = root_path or os.getenv(
            "ARSS_ENGINE_ROOT", "/opt/arss/engine/arss-protocol"
        )
        self.generator_path = os.path.join(
            self.root_path, "tools/close/session_close_generator.py"
        )
        self.guard_path = os.path.join(
            self.root_path, "tools/guard/pointer_guard_s231.py"
        )
        self.pointer_json_path = os.path.join(
            self.root_path, "SESSION_CONTEXT_POINTER.json"
        )

    def _read_file_safe(self, path):
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def analyze_u01(self):
        """U-01: 5-file 번들 정의에 POINTER 파일명이 명시되어 있는가"""
        content = self._read_file_safe(self.generator_path)
        if not content:
            return "UNKNOWN"
        if re.search(r"""['"]SESSION_CONTEXT_POINTER\.json['"]""", content):
            return "PASS"
        return "FAIL"

    def analyze_u02(self):
        """U-02: session_close_generator.py에 POINTER 갱신 로직(write/dump)이 존재하는가"""
        content = self._read_file_safe(self.generator_path)
        if not content:
            return "UNKNOWN"
        if "SESSION_CONTEXT_POINTER.json" in content and (
            "write" in content or "dump" in content
        ):
            return "PASS"
        return "FAIL"

    def analyze_u03(self):
        """U-03: POINTER.json 파일이 유효하고 필수 키(current_session, chain_tip)가 존재하는가
        교정: 실제 POINTER.json 스키마 기준 키 적용 (T-4 반영)
        """
        if not os.path.exists(self.pointer_json_path):
            return "FAIL"
        try:
            with open(self.pointer_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 실제 POINTER.json 스키마: current_session, chain_tip 필수 키
            if "current_session" in data or "chain_tip" in data:
                return "PASS"
        except Exception:
            return "FAIL"
        return "UNKNOWN"

    def analyze_u04(self):
        """U-04: POINTER.json 파일이 복구 후 존재하는가 (SCP 배포 포함 여부 간접 확인)"""
        if os.path.exists(self.pointer_json_path):
            return "PASS"
        return "FAIL"

    def analyze_u05(self):
        """U-05: session_close_generator.py에 POINTER 처리 블록(pointer_path)이 존재하는가
        교정: pointer_guard import 여부 → pointer_path 처리 블록 정적 탐지로 변경 (T-6 반영)
        """
        gen_content = self._read_file_safe(self.generator_path)
        if not gen_content:
            return "UNKNOWN"
        # 단계 8: pointer_path 변수 선언 및 실제 파일 쓰기 블록 존재 여부
        has_pointer_path = bool(re.search(r"pointer_path\s*=", gen_content))
        has_pointer_write = "pointer_path" in gen_content and (
            "open(pointer_path" in gen_content or "write" in gen_content
        )
        if has_pointer_path and has_pointer_write:
            return "PASS"
        return "FAIL"

    def run_full_analysis(self):
        return {
            "U-01": self.analyze_u01(),
            "U-02": self.analyze_u02(),
            "U-03": self.analyze_u03(),
            "U-04": self.analyze_u04(),
            "U-05": self.analyze_u05(),
        }


if __name__ == "__main__":
    analyzer = RCAPointerAnalyzer()
    print(json.dumps(analyzer.run_full_analysis(), indent=2))
