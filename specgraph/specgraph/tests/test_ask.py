from specgraph.retrieval.ask import classify


def test_classify():
    assert classify("Какие документы загружены?") == "catalog"
    assert classify("Сколько требований в Документе 1") == "count"
    assert classify("Найди требование MK-114.OPPO.DATA.001") == "lookup"
    assert classify("Найди все зависимые требования") == "dependents"
    assert classify("Найди требования, информация о которых не подгружена") == "stubs"
    assert classify("Найди требования в которых есть упоминания про вольты") == "rag"
