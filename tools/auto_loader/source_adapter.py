ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .field_contract import SourceType, VerificationMethod


@dataclass(frozen=True)
class AdapterRead:
    loaded: bool
    content: bytes = b""
    failure_reason: str = ""


class SourceAdapter:
    adapter_id: str
    source_type: SourceType
    read_only: bool = True
    verification_method: VerificationMethod

    def read(self, source_ref: str) -> AdapterRead:
        raise NotImplementedError


class VpsFileAdapter(SourceAdapter):
    adapter_id = "VPS_FILE"
    source_type = SourceType.VPS_FILE
    verification_method = VerificationMethod.FILE_EXISTENCE

    def read(self, source_ref: str) -> AdapterRead:
        path = Path(source_ref)
        if not path.is_file():
            return AdapterRead(False, failure_reason="resolution failure")
        return AdapterRead(True, path.read_bytes())


class GDriveFileAdapter(SourceAdapter):
    adapter_id = "GDRIVE_FILE"
    source_type = SourceType.GDRIVE_FILE
    verification_method = VerificationMethod.HASH_SHA256

    def read(self, source_ref: str) -> AdapterRead:
        return AdapterRead(False, failure_reason="resolution failure")


class GithubRawAdapter(SourceAdapter):
    adapter_id = "GITHUB_RAW"
    source_type = SourceType.GITHUB_RAW
    verification_method = VerificationMethod.HTTP_STATUS

    def read(self, source_ref: str) -> AdapterRead:
        return _read_https(source_ref)


class HttpEndpointAdapter(SourceAdapter):
    adapter_id = "HTTP_ENDPOINT"
    source_type = SourceType.HTTP_ENDPOINT
    verification_method = VerificationMethod.HTTP_STATUS

    def read(self, source_ref: str) -> AdapterRead:
        return _read_https(source_ref)


def _read_https(source_ref: str) -> AdapterRead:
    try:
        request = Request(source_ref, method="GET")
        with urlopen(request, timeout=20) as response:
            status = getattr(response, "status", 200)
            if status < 200 or status >= 300:
                return AdapterRead(False, failure_reason="resolution failure")
            return AdapterRead(True, response.read())
    except Exception:
        return AdapterRead(False, failure_reason="resolution failure")


def default_adapters() -> Dict[SourceType, SourceAdapter]:
    adapters = [
        VpsFileAdapter(),
        GDriveFileAdapter(),
        GithubRawAdapter(),
        HttpEndpointAdapter(),
    ]
    return {adapter.source_type: adapter for adapter in adapters}


def valid_source_ref(source_type: SourceType, source_ref: str) -> bool:
    if not isinstance(source_ref, str) or not source_ref:
        return False
    if source_type is SourceType.VPS_FILE:
        return Path(source_ref).is_absolute()
    if source_type is SourceType.GDRIVE_FILE:
        parsed = urlparse(source_ref)
        return not parsed.scheme and "/" not in source_ref and "\\" not in source_ref
    if source_type is SourceType.GITHUB_RAW:
        parsed = urlparse(source_ref)
        return parsed.scheme == "https" and parsed.netloc == "raw.githubusercontent.com"
    if source_type is SourceType.HTTP_ENDPOINT:
        parsed = urlparse(source_ref)
        return parsed.scheme == "https" and bool(parsed.netloc)
    return False


def resolve_adapter(
    adapters: Dict[SourceType, SourceAdapter],
    source_type: SourceType,
) -> Optional[SourceAdapter]:
    adapter = adapters.get(source_type)
    if adapter is None:
        return None
    if adapter.source_type is not source_type:
        return None
    if adapter.read_only is not True:
        return None
    return adapter
