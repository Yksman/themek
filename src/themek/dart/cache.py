"""DART 응답 디스크 캐시.

저장 위치:
- corp_master: <base_dir>/corp_master.json
- 보고서 raw: <base_dir>/raw/<rcept_no>/document.zip
- 보고서 본문: <base_dir>/raw/<rcept_no>/business.html
"""
from __future__ import annotations
import json
from pathlib import Path


class DartCache:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.raw_dir = self.base_dir / "raw"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._corp_master = self.base_dir / "corp_master.json"

    @property
    def corp_master_path(self) -> Path:
        return self._corp_master

    def save_corp_master(self, payload: list[dict]) -> Path:
        self._corp_master.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        return self._corp_master

    def load_corp_master(self) -> list[dict] | None:
        if not self._corp_master.exists():
            return None
        return json.loads(self._corp_master.read_text(encoding="utf-8"))

    def _rcept_dir(self, rcept_no: str) -> Path:
        d = self.raw_dir / rcept_no
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_raw_zip(self, rcept_no: str, zip_bytes: bytes) -> Path:
        p = self._rcept_dir(rcept_no) / "document.zip"
        p.write_bytes(zip_bytes)
        return p

    def save_business_html(self, rcept_no: str, html_bytes: bytes) -> Path:
        p = self._rcept_dir(rcept_no) / "business.html"
        p.write_bytes(html_bytes)
        return p

    def has_business_html(self, rcept_no: str) -> bool:
        return (self.raw_dir / rcept_no / "business.html").exists()

    def get_business_html_path(self, rcept_no: str) -> Path:
        return self.raw_dir / rcept_no / "business.html"
