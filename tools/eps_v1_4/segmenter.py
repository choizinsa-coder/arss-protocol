ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
import re
from .patterns import NEXT_ACTION_RE

SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?。])\s+')

def bind_proposed_blocks(text: str) -> list[str]:
    """
    Bind explanation line(s) + Next Action line into one block.
    Returns list of text blocks (proposed blocks or raw lines).
    """
    lines = text.splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # If next line is a Next Action anchor, bind together
        if i + 1 < len(lines) and NEXT_ACTION_RE.match(lines[i + 1]):
            combined = line.strip() + "\n" + lines[i + 1].strip()
            blocks.append(combined)
            i += 2
        elif NEXT_ACTION_RE.match(line):
            # Isolated Next Action line — treat as its own block
            blocks.append(line.strip())
            i += 1
        else:
            blocks.append(line.strip())
            i += 1
    return [b for b in blocks if b]

def segment_statements(blocks: list[str]) -> list[str]:
    """
    Further split non-proposed blocks by sentence boundaries.
    Proposed blocks (containing Next Action) are kept intact.
    """
    segments = []
    for block in blocks:
        if NEXT_ACTION_RE.search(block):
            segments.append(block)
        else:
            parts = SENTENCE_SPLIT_RE.split(block)
            segments.extend(p.strip() for p in parts if p.strip())
    return segments
