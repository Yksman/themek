from themek.seeds import seed_basic
from themek.db.models import Stock, Corporation, Region


def test_seed_basic_creates_entities(db_session):
    seed_basic(db_session)
    db_session.commit()
    assert db_session.get(Stock, "005930").name_ko == "삼성전자"
    assert db_session.get(Stock, "277810").name_ko == "레인보우로보틱스"
    assert db_session.get(Region, "KR").name_ko == "국내"
    assert db_session.get(Corporation, "00126380").name_ko == "삼성전자"


def test_seed_basic_is_idempotent(db_session):
    seed_basic(db_session)
    db_session.commit()
    seed_basic(db_session)
    db_session.commit()
    count = db_session.query(Stock).count()
    assert count == 3
