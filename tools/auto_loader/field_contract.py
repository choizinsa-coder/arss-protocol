from dataclasses import dataclass
from enum import Enum


class SourceType(str, Enum):
    VPS_FILE = "VPS_FILE"
    GDRIVE_FILE = "GDRIVE_FILE"
    GITHUB_RAW = "GITHUB_RAW"
    HTTP_ENDPOINT = "HTTP_ENDPOINT"


class LoadScope(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    METADATA_ONLY = "METADATA_ONLY"


class VerificationMethod(str, Enum):
    HASH_SHA256 = "HASH_SHA256"
    HTTP_STATUS = "HTTP_STATUS"
    FILE_EXISTENCE = "FILE_EXISTENCE"


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    DENY = "DENY"
    TIMEOUT = "TIMEOUT"
    EXCEPTION = "EXCEPTION"
    UNDEFINED_TARGET = "UNDEFINED_TARGET"
    FORBIDDEN_OPERATION = "FORBIDDEN_OPERATION"
    SOURCE_INVALID = "SOURCE_INVALID"
    PARTIAL = "PARTIAL"


@dataclass(frozen=True)
class LoadTarget:
    id: str
    source_type: SourceType
    source_ref: str
    load_scope: LoadScope
    required: bool
    fail_closed: bool


@dataclass(frozen=True)
class SourceAdapterContract:
    adapter_id: str
    source_type: SourceType
    read_only: bool
    verification_method: VerificationMethod
