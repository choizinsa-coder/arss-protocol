"""공통 픽스처 — Area 12 테스트용."""

VALID_HASH = "sha256:" + "a" * 64
VALID_HASH_2 = "sha256:" + "b" * 64
BAD_HASH = "sha256:zzz"  # 형식 불일치


def make_approval(approval_id="EAG-S271-AICS-001", stage="EAG-2",
                  approved_by="Beo", event_hash=VALID_HASH,
                  approval_hash=VALID_HASH_2):
    return {
        "type": "eag_approval",
        "stage": stage,
        "approval_id": approval_id,
        "approved_by": approved_by,
        "approved_at_kst": "2026-06-20T01:57:08+09:00",
        "session_id": "AIBA-2026-06-20-S272",
        "event_hash": event_hash,
        "approval_hash": approval_hash,
    }


def make_context(eag_chain, session="S272"):
    return {"session": session, "eag_chain": eag_chain}
