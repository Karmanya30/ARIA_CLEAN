"""ai/llm/audio_script.py's Stage 14 blocks= support -- building the
spoken summary from a response's terse structural blocks (metric/risk/
recommendation/alert) instead of compressing the full assembled prose in
`detailed_script`. See shared/blocks.py::build_audio_summary for the
extraction logic itself."""
from ai.llm.audio_script import generate_audio_script
from shared.blocks import build_audio_summary


def test_build_audio_summary_prefers_metric_over_text():
    blocks = [
        {"type": "text", "content": "A very long paragraph of narration that would otherwise need compressing."},
        {"type": "metric", "label": "Monthly SIP", "value": "10,500", "unit": "INR/month"},
    ]
    summary = build_audio_summary(blocks)
    assert "Monthly SIP: 10,500 INR/month" in summary
    assert "very long paragraph" not in summary


def test_build_audio_summary_includes_risk_and_recommendation():
    blocks = [
        {"type": "risk", "score": 0.82, "level": "Aggressive", "factors": []},
        {"type": "recommendation", "title": "Consider an index fund", "rationale": "Matches your long horizon.", "actions": []},
    ]
    summary = build_audio_summary(blocks)
    assert "Risk level: Aggressive (82% confidence)" in summary
    assert "Consider an index fund: Matches your long horizon." in summary


def test_build_audio_summary_falls_back_to_text_when_no_structural_blocks():
    blocks = [{"type": "text", "content": "Diversification means spreading your investments."}]
    assert build_audio_summary(blocks) == "Diversification means spreading your investments."


def test_build_audio_summary_empty_blocks_returns_empty_string():
    assert build_audio_summary([]) == ""


def test_generate_audio_script_uses_blocks_summary_over_detailed_script(monkeypatch):
    import ai.llm.audio_script as audio_script

    captured_prompts = []
    monkeypatch.setattr(audio_script, "generate_audio", lambda prompt: captured_prompts.append(prompt) or "spoken summary")

    generate_audio_script(
        "A very long detailed narration string that should be ignored when blocks are given.",
        blocks=[{"type": "metric", "label": "Monthly SIP", "value": "10,500", "unit": "INR/month"}],
    )
    assert any("Monthly SIP: 10,500 INR/month" in p for p in captured_prompts)
    assert not any("very long detailed narration" in p for p in captured_prompts)


def test_generate_audio_script_falls_back_to_detailed_script_when_blocks_omitted(monkeypatch):
    import ai.llm.audio_script as audio_script

    captured_prompts = []
    monkeypatch.setattr(audio_script, "generate_audio", lambda prompt: captured_prompts.append(prompt) or "spoken summary")

    generate_audio_script("Some narration text.")
    assert any("Some narration text." in p for p in captured_prompts)


def test_generate_audio_script_falls_back_when_blocks_carry_no_usable_content(monkeypatch):
    import ai.llm.audio_script as audio_script

    captured_prompts = []
    monkeypatch.setattr(audio_script, "generate_audio", lambda prompt: captured_prompts.append(prompt) or "spoken summary")

    generate_audio_script("Fallback narration.", blocks=[])
    assert any("Fallback narration." in p for p in captured_prompts)
