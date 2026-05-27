"""DART OpenAPI HTTP client."""
from __future__ import annotations
import httpx


class DartApiError(RuntimeError):
    pass


class DartAuthError(DartApiError):
    pass


class DartRateLimitError(DartApiError):
    pass


class DartClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://opendart.fss.or.kr/api",
        timeout_sec: int = 60,
    ):
        if not api_key:
            raise DartAuthError("DART_API_KEY 미설정")
        self._key = api_key
        self._base = base_url
        self._timeout = timeout_sec
        self._client = httpx.Client(timeout=timeout_sec)

    def fetch_corp_code_zip(self) -> bytes:
        r = self._client.get(
            f"{self._base}/corpCode.xml", params={"crtfc_key": self._key}
        )
        self._raise_on_error(r)
        return r.content

    def list_periodic_reports(
        self, *, corp_code: str, bgn_de: str, end_de: str
    ) -> dict:
        r = self._client.get(
            f"{self._base}/list.json",
            params={
                "crtfc_key": self._key,
                "corp_code": corp_code,
                "bgn_de": bgn_de,
                "end_de": end_de,
                "pblntf_ty": "A",
                "page_count": 100,
            },
        )
        self._raise_on_error(r)
        payload = r.json()
        if payload.get("status") not in ("000", "013"):
            raise DartApiError(
                f"list.json status={payload.get('status')} "
                f"message={payload.get('message')}"
            )
        return payload

    def fetch_document_zip(self, *, rcept_no: str) -> bytes:
        r = self._client.get(
            f"{self._base}/document.xml",
            params={"crtfc_key": self._key, "rcept_no": rcept_no},
        )
        self._raise_on_error(r)
        return r.content

    def _raise_on_error(self, r: httpx.Response) -> None:
        if r.status_code in (401, 403):
            raise DartAuthError(f"HTTP {r.status_code}: {r.text[:200]}")
        if r.status_code == 429:
            raise DartRateLimitError("rate limit")
        if r.status_code >= 500:
            raise DartApiError(f"HTTP {r.status_code}")
        if r.status_code >= 400:
            raise DartApiError(f"HTTP {r.status_code}: {r.text[:200]}")
