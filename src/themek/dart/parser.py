"""DART 사업보고서 HTML → 본문 텍스트 추출."""
from __future__ import annotations
from bs4 import BeautifulSoup


def extract_business_content(html: str) -> str:
    """HTML 본문에서 사람이 읽을 수 있는 텍스트를 추출.

    - <script>, <style> 제거
    - 표(<table>)는 셀 단위로 탭 구분 + 줄바꿈
    - 블록 요소 사이 줄바꿈 유지
    """
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style"]):
        tag.decompose()

    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append("\t".join(cells))
        table.replace_with("\n".join(rows) + "\n")

    text = soup.get_text(separator="\n", strip=True)
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines)
