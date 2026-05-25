"""Minimal Streamlit UI for ARIA."""

import re
import sys
from importlib import import_module, reload
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

def _handle_query(query: str, session_id: str, mode: str) -> dict:
    """Load the orchestrator after Streamlit reruns so local pipeline edits apply."""
    for module_name in (
        "modules.finance.pipeline",
        "modules.market.investment",
        "modules.market.pipeline",
        "core.orchestrator",
    ):
        if module_name in sys.modules:
            reload(sys.modules[module_name])

    orchestrator = import_module("core.orchestrator")
    return orchestrator.handle_query(query, session_id=session_id, mode=mode)


def _speech_text(text: str) -> str:
    """Convert Markdown-ish assistant output into text that sounds natural."""
    cleaned = str(text or "")
    cleaned = re.sub(r"```.*?```", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"(^|\s)[*_]{1,3}([^*_]+)[*_]{1,3}(:?)", r"\1\2\3", cleaned)
    cleaned = re.sub(r"^\s*#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*(\d+)\.\s+", r"\1. ", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.replace("*", "").replace("_", "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


# Section definitions: (label, icon, background color)
_SECTIONS = [
    ("Insight",        "💡", "#1a2a1a"),
    ("Analysis",       "📊", "#1a1e2e"),
    ("Recommendation", "✅", "#1a2820"),
    ("Risk",           "⚠️", "#2a1e1a"),
]


def _parse_sections(response: str) -> dict[str, str]:
    """
    Parse a structured LLM response with Insight/Analysis/Recommendation/Risk labels.
    Works whether the labels are separated by newlines or run together inline.
    """
    labels = [s[0] for s in _SECTIONS]
    # Insert a newline before each label so split works on inline responses too
    normalized = response
    for label in labels:
        normalized = re.sub(rf"(?<!\n){re.escape(label)}:", f"\n{label}:", normalized)

    result: dict[str, str] = {}
    pattern = "(" + "|".join(re.escape(l) for l in labels) + r"):\s*"
    parts = re.split(pattern, normalized)

    current_key = None
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part in labels:
            current_key = part
        elif current_key:
            result[current_key] = part
            current_key = None

    return result


def render_response(response: str) -> None:
    """Render the LLM response as styled section cards."""
    import streamlit as st

    sections = _parse_sections(response)

    if not sections:
        # Fallback: plain markdown if no structured sections found
        st.markdown(response)
        return

    st.markdown("""
    <style>
    .aria-card {
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 12px;
        font-size: 15px;
        line-height: 1.6;
        border-left: 4px solid;
    }
    .aria-card-label {
        font-weight: 700;
        font-size: 13px;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        margin-bottom: 6px;
        opacity: 0.75;
    }
    </style>
    """, unsafe_allow_html=True)

    colors = {
        "Insight":        ("#4ade80", "#1a2a1a"),
        "Analysis":       ("#60a5fa", "#1a1e2e"),
        "Recommendation": ("#34d399", "#1a2820"),
        "Risk":           ("#f87171", "#2a1e1a"),
    }
    icons = {
        "Insight": "💡",
        "Analysis": "📊",
        "Recommendation": "✅",
        "Risk": "⚠️",
    }

    for label, _, _ in _SECTIONS:
        text = sections.get(label, "")
        if not text:
            continue
        border_color, bg = colors[label]
        icon = icons[label]
        st.markdown(f"""
        <div class="aria-card" style="background:{bg}; border-left-color:{border_color};">
            <div class="aria-card-label" style="color:{border_color};">{icon} {label}</div>
            {text}
        </div>
        """, unsafe_allow_html=True)


def run() -> None:
    import streamlit as st

    st.set_page_config(page_title="ARIA", page_icon="A")
    st.title("ARIA")

    if "query_text" not in st.session_state:
        st.session_state.query_text = ""

    # Mode Selector & Clear Chat
    col1, col2 = st.columns([4, 1])
    with col1:
        mode = st.selectbox("Chat Mode", ["Normal Mode", "Conversational Mode"])
    with col2:
        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
        if st.button("Clear Chat", use_container_width=True):
            from core.session import clear_session
            clear_session("streamlit")
            st.rerun()
            
    st.divider()

    # Render Chat History (Top)
    from core.session import get_session
    session = get_session("streamlit")
    history = session.get("history", [])

    for turn in history:
        with st.chat_message("user"):
            st.write(turn["query"])
        with st.chat_message("assistant"):
            response = turn["response"].get("response", "")
            render_response(response)
            
            domain = turn["response"].get("domain", "general")
            company = turn["response"].get("company", "")
            badge = f"Domain: **{domain}**"
            if company:
                badge += f"  ·  Company: **{company}**"
            st.caption(badge)

            audio_path = turn.get("audio_path")
            if audio_path:
                suffix = Path(audio_path).suffix.lower()
                audio_format = "audio/wav" if suffix == ".wav" else "audio/mp3"
                st.audio(audio_path, format=audio_format)

    # Input Area (Bottom)
    st.write("")
    audio_file = st.audio_input("Ask ARIA by voice")
    if audio_file is not None and st.button("Use voice input"):
        try:
            from ai.speech.stt import transcribe
            with st.spinner("Transcribing..."):
                transcript = transcribe(
                    audio_file.getvalue(),
                    filename=getattr(audio_file, "name", None),
                    raise_errors=True,
                )
            if transcript:
                st.session_state.query_text = transcript
                st.rerun()
            else:
                st.warning("Could not transcribe the audio.")
        except Exception as exc:
            st.error(f"Audio input failed: {exc}")

    if st.session_state.get("clear_query"):
        st.session_state.query_text = ""
        st.session_state.clear_query = False

    query = st.text_input("Ask ARIA", key="query_text")
    submitted = st.button("Submit")

    # Handle Submission
    if submitted and query.strip():
        with st.spinner("Analyzing..."):
            result = _handle_query(query.strip(), session_id="streamlit", mode=mode)
            response = result.get("response", "No response generated.")

            # Generate TTS Audio
            try:
                from ai.llm.audio_script import generate_audio_script
                from ai.speech.tts import synthesize
                audio_script = generate_audio_script(response)
                audio_path = synthesize(_speech_text(audio_script))
                if audio_path and session.get("history"):
                    session["history"][-1]["audio_path"] = audio_path
            except Exception:
                pass
                
        st.session_state.clear_query = True
        st.rerun()


if __name__ == "__main__":
    run()
