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


def test_synthesize_segments_each_on_own_line():
    answer = synthesize_e5_answer(_sample_result())
    # 사업 부문 3개가 각각 별 줄에 와야 함
    seg_lines = [line for line in answer.splitlines() if line.startswith("- ")
                 and any(name in line for name in ["메모리반도체", "스마트폰", "디스플레이"])]
    assert len(seg_lines) == 3, f"Expected 3 segment lines, got: {seg_lines}"


def test_synthesize_customers_each_on_own_line():
    answer = synthesize_e5_answer(_sample_result())
    cust_lines = [line for line in answer.splitlines() if line.startswith("- ")
                  and any(name in line for name in ["Apple Inc.", "주요 글로벌 IT 고객사"])]
    assert len(cust_lines) == 2


def test_synthesize_regions_each_on_own_line():
    answer = synthesize_e5_answer(_sample_result())
    region_lines = [line for line in answer.splitlines() if line.startswith("- ")
                    and any(name in line for name in ["미주", "중국", "국내"])]
    assert len(region_lines) == 3


def test_synthesize_url_on_own_line():
    answer = synthesize_e5_answer(_sample_result())
    lines = answer.splitlines()
    # "링크:"가 자체 줄에 와야 함 (출처: 와 한 줄로 붙으면 안 됨)
    link_line = next((l for l in lines if l.startswith("링크:")), None)
    assert link_line is not None, f"링크: line missing — full output:\n{answer}"


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
