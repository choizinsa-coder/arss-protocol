import pytest
from tools.eps_v1_4.segmenter import bind_proposed_blocks, segment_statements


# ── 기존 테스트 ────────────────────────────────────────────────
def test_basic_sentence_split():
    segs = segment_statements(["Hello. World."])
    assert len(segs) >= 1


def test_proposal_block_binding():
    text = "Wrapper integration is required.\nNext Action: implement build_wrapper_payload()."
    blocks = bind_proposed_blocks(text)
    combined = " ".join(blocks)
    assert "Next Action" in combined
    assert "Wrapper integration" in combined


def test_isolated_next_action():
    blocks = bind_proposed_blocks("Next Action: do something.")
    assert any("Next Action" in b for b in blocks)


def test_empty_fragments_removed():
    blocks = bind_proposed_blocks("  \n  \n실행합니다.")
    assert all(b.strip() for b in blocks)


def test_proposed_block_intact_after_segment():
    raw = "수정하겠습니다.\nNext Action: 패키지 작성."
    blocks = bind_proposed_blocks(raw)
    segs = segment_statements(blocks)
    assert any("Next Action" in s for s in segs)


# ── failure path ───────────────────────────────────────────────
def test_bind_empty_string_returns_empty():
    """빈 문자열 입력 — 빈 리스트 반환"""
    blocks = bind_proposed_blocks("")
    assert blocks == []


def test_segment_empty_list_returns_empty():
    """빈 blocks 리스트 — 빈 리스트 반환"""
    segs = segment_statements([])
    assert segs == []


def test_segment_blank_strings_filtered():
    """공백·빈 문자열 블록 — strip 후 필터링으로 결과 없음"""
    segs = segment_statements(["   ", ""])
    assert segs == []


def test_bind_multi_next_action_binds_each():
    """연속 두 쌍의 (line, Next Action) — 각각 독립 블록으로 바인딩"""
    text = "Line1.\nNext Action: step1.\nLine2.\nNext Action: step2."
    blocks = bind_proposed_blocks(text)
    assert len(blocks) == 2
    assert all("Next Action" in b for b in blocks)
