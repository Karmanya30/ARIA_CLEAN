from modules.qa.trust import ungrounded


def test_figures_written_in_words_are_checked_like_digits():
    assert ungrounded("The fund returned twelve percent last year.", "The fund returned 8 percent.")
    assert ungrounded("The loan is five lakh.", "Loan: 3 lakh")
    assert not ungrounded("The fund returned twelve percent last year.", "The fund returned 12 percent.")
    assert not ungrounded("Twenty five percent of it is debt.", "debt share 25 %")
