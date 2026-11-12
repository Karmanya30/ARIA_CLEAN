from shared.understand import normalize


def test_index_and_fund_misspellings_are_fixed_even_in_hinglish():
    assert normalize("nifti kaisa hai aaj")[0].startswith("nifty")
    assert normalize("mutal fnd vs fd which is beter")[0] == "mutual fund vs fd which is better"
    assert "afford afford" not in normalize("kya main 8 lakh ki car loan afford kar sakta hu")[0]
