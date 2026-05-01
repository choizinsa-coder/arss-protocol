import pytest
from tools.eps_v1_4.segmenter import bind_proposed_blocks, segment_statements

def test_basic_sentence_split():
    segs = segment_statements(["Hello. World."])
    assert len(segs) >= 1

def test_proposal_block_binding():
    text = "Wrapper integration is required.\nNext Action: implement build_wrapper_payload()."
    blocks = bind_proposed_blocks(text)
    # Next Action should be bound with preceding line
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
    # Proposed block must stay as one segment
    assert any("Next Action" in s for s in segs)
