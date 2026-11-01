from modules.market import pipeline, analyzer


def test_spoken_rewrite_cannot_drop_snapshot_date(monkeypatch):
    from modules.qa import present
    from modules.qa.models import QARequest, ChatMode, Channel
    monkeypatch.setattr(present, 'spoken_text', lambda q, text: 'The index rose.')
    note = 'Available index snapshots are dated 2026-10-29; these are delayed observations, not verified live prices.'
    result = present.present({'response': note + ' The index rose.', 'freshness_note': note},
                             QARequest(query='Market today?', session_id='test', mode=ChatMode.LIVE, channel=Channel.AVATAR))
    assert result['spoken'].startswith(note)


def test_snapshot_date_survives_market_answer(monkeypatch):
    monkeypatch.setattr(pipeline, 'build_context', lambda q: {'nifty': {'as_of': '2026-10-29', 'current_level': 22936.75}})
    monkeypatch.setattr(pipeline, 'generate_response', lambda p: 'The latest available index rose.')
    monkeypatch.setattr(pipeline.personal, 'profile', lambda: {})
    monkeypatch.setattr(pipeline.personal, 'market_caption', lambda p: None)
    result = pipeline.run_pipeline('How is the market today?')
    assert '2026-10-29' in result['freshness_note']
    assert result['response'].startswith(result['freshness_note'])
    assert result['context']['freshness_note'] == result['freshness_note']


def test_broad_market_news_excludes_generic_keyword_matches(monkeypatch):
    queries = []
    def fetch(q, limit):
        queries.append(q)
        return [{'title': 'Lifestyle factors influence health'}, {'title': 'Nifty rises on earnings'}]
    monkeypatch.setattr(analyzer, 'fetch_news', fetch)
    monkeypatch.setattr(analyzer, 'format_headlines', lambda items: [i['title'] for i in items])
    monkeypatch.setattr(analyzer.sentiment, 'tone', lambda titles: {})
    headlines, _ = analyzer.get_market_news_with_tone("What factors influence today's Indian stock market?")
    assert headlines == ['Nifty rises on earnings']
    assert queries == ['Nifty Sensex Indian stock market']
