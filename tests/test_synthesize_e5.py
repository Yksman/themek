from themek.query.e5 import E5Result, SegmentSummary, CustomerSummary, RegionSummary
from themek.query.synthesize import synthesize_e5_answer


def _sample_result():
    return E5Result(
        stock_ticker="005930", stock_name="삼성전자",
        corporation_dart_code="00126380", corporation_name="삼성전자",
        sector_name="반도체",
        period="2023",
        segments=[
            SegmentSummary("메모리반도체", 42.5, "DRAM/NAND 등"),
            SegmentSummary("스마트폰/네트워크", 38.0, "갤럭시"),
            SegmentSummary("디스플레이", 15.5, "OLED"),
        ],
        top_customers=[
            CustomerSummary("Apple Inc.", 18.0, "1차"),
            CustomerSummary("주요 글로벌 IT 고객사 (비공개)", None, "unknown"),
        ],
        top_regions=[
            RegionSummary("US", "미주", 35.0),
            RegionSummary("CN", "중국", 20.0),
            RegionSummary("KR", "국내", 18.0),
        ],
        source_report_rcept_no="20240314000123",
        source_report_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314000123",
    )


def test_synthesize_basic():
    answer = synthesize_e5_answer(_sample_result())
    assert "삼성전자" in answer
    assert "메모리반도체" in answer
    assert "42.5%" in answer
    assert "Apple Inc." in answer
    assert "미주" in answer or "US" in answer
    assert "20240314000123" in answer
    assert "dart.fss.or.kr" in answer


def test_synthesize_handles_missing_report():
    result = E5Result(
        stock_ticker="999999", stock_name="가상종목",
        corporation_dart_code="00999999", corporation_name="가상법인",
        sector_name=None, period=None,
    )
    answer = synthesize_e5_answer(result)
    assert "가상종목" in answer
    assert "보고서" in answer
    assert "없" in answer or "찾지 못" in answer or "ingest되지 않았" in answer


def test_synthesize_handles_no_customers():
    r = _sample_result()
    r.top_customers = []
    answer = synthesize_e5_answer(r)
    assert "고객" in answer
