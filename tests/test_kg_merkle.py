"""test_kg_merkle.py -- KG Phase 2-A Merkle Anchor tests (EAG-S333-KG-PHASE2-001)"""
import json
import sys
from pathlib import Path

ROOT = Path("/opt/arss/engine/arss-protocol")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge_graph import merkle

NL = chr(10)


class TestMerkleRootComputation:
    def test_empty_tree_sentinel(self):
        assert merkle._merkle_root([]) == "0" * 64

    def test_single_leaf(self):
        h = "a" * 64
        assert merkle._merkle_root([h]) == h

    def test_two_leaves_deterministic(self):
        leaves = ["a" * 64, "b" * 64]
        r1 = merkle._merkle_root(leaves)
        r2 = merkle._merkle_root(leaves)
        assert r1 == r2
        assert len(r1) == 64

    def test_odd_leaf_self_pair(self):
        r2 = merkle._merkle_root(["a" * 64, "b" * 64])
        r3 = merkle._merkle_root(["a" * 64, "b" * 64, "c" * 64])
        assert r2 != r3

    def test_leaf_hash_deterministic(self):
        line = '{"node_id": "DN-1"}'
        assert merkle._leaf_hash(line) == merkle._leaf_hash(line + NL)


class TestAnchorLifecycle:
    def test_compute_and_store_returns_schema(self, tmp_path, monkeypatch):
        nip = tmp_path / "node_index.jsonl"
        anchor = tmp_path / "merkle_anchor.json"
        monkeypatch.setattr(merkle, "NODE_INDEX_PATH", nip)
        monkeypatch.setattr(merkle, "ANCHOR_PATH", anchor)
        monkeypatch.setattr(merkle, "KG_DIR", tmp_path)
        with open(nip, "w") as f:
            for i in range(3):
                f.write(json.dumps({"node_id": f"DN-{i}"}) + NL)
        result = merkle.compute_and_store_anchor()
        assert result["schema"] == "merkle_anchor_v1"
        assert result["node_count"] == 3
        assert result["merkle_root"] != "0" * 64

    def test_verify_valid_after_store(self, tmp_path, monkeypatch):
        nip = tmp_path / "node_index.jsonl"
        anchor = tmp_path / "merkle_anchor.json"
        monkeypatch.setattr(merkle, "NODE_INDEX_PATH", nip)
        monkeypatch.setattr(merkle, "ANCHOR_PATH", anchor)
        monkeypatch.setattr(merkle, "KG_DIR", tmp_path)
        with open(nip, "w") as f:
            f.write(json.dumps({"node_id": "DN-0"}) + NL)
        merkle.compute_and_store_anchor()
        v = merkle.verify_merkle_anchor()
        assert v["valid"] is True
        assert v["error"] is None

    def test_verify_detects_tamper(self, tmp_path, monkeypatch):
        nip = tmp_path / "node_index.jsonl"
        anchor = tmp_path / "merkle_anchor.json"
        monkeypatch.setattr(merkle, "NODE_INDEX_PATH", nip)
        monkeypatch.setattr(merkle, "ANCHOR_PATH", anchor)
        monkeypatch.setattr(merkle, "KG_DIR", tmp_path)
        with open(nip, "w") as f:
            f.write(json.dumps({"node_id": "DN-0"}) + NL)
        merkle.compute_and_store_anchor()
        with open(nip, "a") as f:
            f.write(json.dumps({"node_id": "DN-TAMPER"}) + NL)
        v = merkle.verify_merkle_anchor()
        assert v["valid"] is False
        assert v["error"] == "root mismatch"

    def test_verify_no_anchor(self, tmp_path, monkeypatch):
        nip = tmp_path / "node_index.jsonl"
        anchor = tmp_path / "merkle_anchor.json"
        monkeypatch.setattr(merkle, "NODE_INDEX_PATH", nip)
        monkeypatch.setattr(merkle, "ANCHOR_PATH", anchor)
        v = merkle.verify_merkle_anchor()
        assert v["valid"] is False
        assert v["error"] == "anchor not found"

    def test_history_append_on_reanchor(self, tmp_path, monkeypatch):
        nip = tmp_path / "node_index.jsonl"
        anchor = tmp_path / "merkle_anchor.json"
        monkeypatch.setattr(merkle, "NODE_INDEX_PATH", nip)
        monkeypatch.setattr(merkle, "ANCHOR_PATH", anchor)
        monkeypatch.setattr(merkle, "KG_DIR", tmp_path)
        with open(nip, "w") as f:
            f.write(json.dumps({"node_id": "DN-0"}) + NL)
        merkle.compute_and_store_anchor()
        with open(nip, "a") as f:
            f.write(json.dumps({"node_id": "DN-1"}) + NL)
        a2 = merkle.compute_and_store_anchor()
        assert len(a2["anchor_history"]) == 1

    def test_empty_node_index_root(self, tmp_path, monkeypatch):
        nip = tmp_path / "node_index.jsonl"
        monkeypatch.setattr(merkle, "NODE_INDEX_PATH", nip)
        assert merkle.compute_current_root() == "0" * 64

    def test_get_anchor_snapshot(self, tmp_path, monkeypatch):
        nip = tmp_path / "node_index.jsonl"
        anchor = tmp_path / "merkle_anchor.json"
        monkeypatch.setattr(merkle, "NODE_INDEX_PATH", nip)
        monkeypatch.setattr(merkle, "ANCHOR_PATH", anchor)
        monkeypatch.setattr(merkle, "KG_DIR", tmp_path)
        with open(nip, "w") as f:
            f.write(json.dumps({"node_id": "DN-0"}) + NL)
        merkle.compute_and_store_anchor()
        snap = merkle.get_anchor_snapshot()
        assert snap["schema"] == "merkle_anchor_v1"
