from specgraph.ingest.extract import ExtractedDoc
from specgraph.ingest.structure import from_extracted, from_parsed_json


def test_headings_products_and_must_requirements():
    doc = ExtractedDoc(
        title="ТЗ",
        paragraphs=[
            "1 Изделие АБВГ.111111.001 Вычислитель",
            "Масса: 2 кг",
            "1.1 Модуль питания АБВГ.111111.001-01",
            "Изделие должно обеспечивать напряжение 27 В.",
            "Рисунок 1 — Вычислитель",
        ],
        tables=[],
    )
    g = from_extracted(doc)
    assert any(p.code == "АБВГ.111111.001" for p in g.products)
    assert any("должн" in r.text for r in g.requirements)
    assert g.figure_captions


def test_parsed_json_hierarchy():
    g = from_parsed_json(
        {
            "products": [
                {"code": "A", "name": "Система"},
                {"code": "A-1", "name": "Блок", "parent": "A", "level": 1, "attributes": {"u": "27"}},
            ],
            "requirements": [
                {"code": "REQ-1", "text": "Блок должен работать", "product": "A-1", "parent": None}
            ],
        }
    )
    assert any(p.code == "A" for p in g.products)
    child = next(p for p in g.products if p.code == "A-1")
    assert child.parent_code == "A"
    assert g.requirements[0].product_code == "A-1"
