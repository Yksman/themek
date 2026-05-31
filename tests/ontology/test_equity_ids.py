from themek.ontology.core.ids import (
    person_id, canonical_person_id, external_company_id)


def test_person_id_is_company_namespaced():
    assert person_id("이재용", "00126380") == "person:00126380:이재용"


def test_canonical_person_id_is_global():
    assert canonical_person_id("이재용") == "person:이재용"


def test_canonical_differs_from_namespaced():
    assert person_id("이재용", "00126380") != canonical_person_id("이재용")


def test_external_company_id_prefixed():
    assert external_company_id("삼성생명보험(주)") == "company:ext:삼성생명보험-주"
