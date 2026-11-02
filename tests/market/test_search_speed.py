import time

from modules.market import instruments as I


def test_typo_search_still_finds_and_is_fast():
    I.search("tata")  # builds the catalogue and the word list
    t = time.time()
    ids = [i["id"] for i in I.search("relaince")["items"]]
    assert any("RELIANCE" in i for i in ids)
    assert time.time() - t < 0.5  # was 1.4 s: the typo check ran over every item's words
