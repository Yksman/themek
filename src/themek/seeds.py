"""샘플 데이터 시드. Walking skeleton에서는 3개 종목만."""
from sqlalchemy.orm import Session
from themek.db.models import Stock, Corporation, Sector, Region

SECTORS = [
    {"fics_code": "G2520", "name_ko": "반도체", "name_en": "Semiconductors"},
    {"fics_code": "G2570", "name_ko": "자동차 및 부품", "name_en": "Auto Components"},
    {"fics_code": "G2030", "name_ko": "산업기계", "name_en": "Industrial Machinery"},
]

REGIONS = [
    {"code": "KR", "name_ko": "국내", "name_en": "Korea"},
    {"code": "US", "name_ko": "미주", "name_en": "Americas"},
    {"code": "EU", "name_ko": "유럽", "name_en": "Europe"},
    {"code": "CN", "name_ko": "중국", "name_en": "China"},
    {"code": "JP", "name_ko": "일본", "name_en": "Japan"},
    {"code": "ROW", "name_ko": "기타", "name_en": "Rest of World"},
]

CORPORATIONS = [
    {"dart_code": "00126380", "name_ko": "삼성전자", "in_sector_id": "G2520"},
    {"dart_code": "00164742", "name_ko": "현대자동차", "in_sector_id": "G2570"},
    {"dart_code": "01133360", "name_ko": "레인보우로보틱스", "in_sector_id": "G2030"},
]

STOCKS = [
    {"ticker": "005930", "name_ko": "삼성전자", "market": "KOSPI",
     "share_class": "common", "issued_by_id": "00126380"},
    {"ticker": "005380", "name_ko": "현대차", "market": "KOSPI",
     "share_class": "common", "issued_by_id": "00164742"},
    {"ticker": "277810", "name_ko": "레인보우로보틱스", "market": "KOSDAQ",
     "share_class": "common", "issued_by_id": "01133360"},
]


def _upsert(session: Session, model, data: dict, pk_field: str):
    pk = data[pk_field]
    existing = session.get(model, pk)
    if existing is None:
        session.add(model(**data))


def seed_basic(session: Session) -> None:
    for row in SECTORS:
        _upsert(session, Sector, row, "fics_code")
    for row in REGIONS:
        _upsert(session, Region, row, "code")
    session.flush()
    for row in CORPORATIONS:
        _upsert(session, Corporation, row, "dart_code")
    session.flush()
    for row in STOCKS:
        _upsert(session, Stock, row, "ticker")
