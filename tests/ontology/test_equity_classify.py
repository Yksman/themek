from themek.ontology.ingest.equity import classify_shareholder, affiliation_from_stake


def test_corp_suffix_is_company():
    assert classify_shareholder("삼성생명보험(주)", "계열회사") == "company"
    assert classify_shareholder("㈜케이씨씨", "") == "company"
    assert classify_shareholder("ABC Corp", "") == "company"
    assert classify_shareholder("미래에셋자산운용", "기관") == "company"  # 운용/투신 키워드


def test_relate_corp_keyword_is_company():
    assert classify_shareholder("국민연금공단", "계열회사") == "company"


def test_personal_name_is_person():
    assert classify_shareholder("이재용", "최대주주 본인") == "person"
    assert classify_shareholder("홍길동", "배우자") == "person"


def test_affiliation_from_stake_thresholds():
    assert affiliation_from_stake(84.78) == "자회사"   # >=50
    assert affiliation_from_stake(19.58) == "기타"  # 19.58 < 20 → 기타
    assert affiliation_from_stake(25.0) == "관계회사"
    assert affiliation_from_stake(5.0) == "기타"
    assert affiliation_from_stake(None) == "기타"
