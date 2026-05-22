from pathlib import Path
from themek.dart.parser import extract_business_content


FIXTURE = Path(__file__).parent / "fixtures" / "samsung_business_report_excerpt.html"


def test_extract_business_content_returns_text():
    html = FIXTURE.read_text(encoding="utf-8")
    text = extract_business_content(html)
    assert isinstance(text, str)
    assert len(text) > 200
    assert any(token in text for token in ["매출", "사업", "제품"])


def test_extract_business_content_strips_html_tags():
    html = "<html><body><h1>제목</h1><p>내용입니다</p><table><tr><td>표</td></tr></table></body></html>"
    text = extract_business_content(html)
    assert "<" not in text
    assert "제목" in text
    assert "내용입니다" in text


def test_extract_business_content_preserves_whitespace_reasonably():
    html = "<html><body><p>줄1</p><p>줄2</p></body></html>"
    text = extract_business_content(html)
    assert "줄1" in text
    assert "줄2" in text
    assert text.find("줄1") != text.find("줄2")
