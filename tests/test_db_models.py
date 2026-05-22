from themek.db.models import Stock, Corporation, Sector, Region, Group


def test_stock_creation(db_session):
    sector = Sector(fics_code="G2520", name_ko="반도체")
    corp = Corporation(dart_code="00126380", name_ko="삼성전자", in_sector=sector)
    stock = Stock(ticker="005930", name_ko="삼성전자", share_class="common",
                  market="KOSPI", issued_by=corp)
    db_session.add_all([sector, corp, stock])
    db_session.commit()

    fetched = db_session.get(Stock, "005930")
    assert fetched.name_ko == "삼성전자"
    assert fetched.issued_by.dart_code == "00126380"
    assert fetched.issued_by.in_sector.fics_code == "G2520"


def test_region_enum(db_session):
    kr = Region(code="KR", name_ko="국내")
    db_session.add(kr)
    db_session.commit()
    assert db_session.get(Region, "KR").name_ko == "국내"


def test_corporation_belongs_to_group_optional(db_session):
    corp = Corporation(dart_code="00111111", name_ko="테스트법인")
    db_session.add(corp)
    db_session.commit()
    assert db_session.get(Corporation, "00111111").belongs_to_id is None


def test_group_can_be_assigned(db_session):
    group = Group(name_ko="삼성그룹")
    db_session.add(group)
    db_session.flush()
    corp = Corporation(dart_code="00126380", name_ko="삼성전자",
                       belongs_to=group)
    db_session.add(corp)
    db_session.commit()
    assert db_session.get(Corporation, "00126380").belongs_to.name_ko == "삼성그룹"
