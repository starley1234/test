from specgraph.retrieval.ask import classify


def test_classify():
    assert classify("Какие документы загружены?") == "catalog"
    assert classify("Сколько требований в Документе 1") == "count"
    assert classify("Найди требование MK-114.OPPO.DATA.001") == "lookup"
    assert classify("В каком требовании упоминание про надёжность") == "rag"
