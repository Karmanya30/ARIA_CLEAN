"""Streamlit UI for ARIA — chat (all 4 modules, auto-routed) plus a
profile panel (Module 1) and a progress panel (Module 2)."""

import json
import re
import sys
from importlib import import_module, reload
from pathlib import Path
from uuid import uuid4

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _handle_query(query: str, session_id: str, mode: str) -> dict:
    """Load the orchestrator after Streamlit reruns so local pipeline edits apply."""
    for module_name in (
        "modules.finance.pipeline",
        "modules.equity_research.investment",
        "modules.equity_research.pipeline",
        "modules.market.pipeline",
        "modules.tutor.pipeline",
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


# Section definitions: (label, icon) -- Modules 1/3/4 all use this contract.
_SECTIONS = [
    ("Insight", "\U0001f4a1"),
    ("Analysis", "\U0001f4ca"),
    ("Recommendation", "✅"),
    ("Risk", "⚠️"),
]

# Module 2's TAXAL structure -- different labels, same card pattern.
_TAXAL_SECTIONS = [
    ("Cognitive", "\U0001f9e0"),
    ("Functional", "⚙️"),
    ("Causal", "\U0001f517"),
]

_CARD_COLORS = {
    "Insight": ("#4ade80", "#1a2a1a"),
    "Analysis": ("#60a5fa", "#1a1e2e"),
    "Recommendation": ("#34d399", "#1a2820"),
    "Risk": ("#f87171", "#2a1e1a"),
    "Cognitive": ("#4ade80", "#1a2a1a"),
    "Functional": ("#60a5fa", "#1a1e2e"),
    "Causal": ("#f59e0b", "#1a2820"),
}


def _parse_sections(response: str, section_defs: list[tuple[str, str]]) -> dict[str, str]:
    """
    Parse a structured LLM response with the given section labels.
    Works whether the labels are separated by newlines or run together inline.
    """
    labels = [s[0] for s in section_defs]
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
    """Render the LLM response as styled section cards -- tries the
    Insight/Analysis/Recommendation/Risk format first (Modules 1/3/4), then
    TAXAL's Cognitive/Functional/Causal (Module 2), then a plain fallback.
    Both Groq and Gemini failing gets a clear error banner instead of a
    raw "Error: ..." string leaking into the chat as if it were an answer.
    """
    import streamlit as st

    text = str(response or "")

    if text.startswith("Error:"):
        st.error(
            "ARIA's language model is temporarily unavailable (both Groq and "
            "Gemini failed to respond). Any numbers shown separately are still "
            "real and computed locally -- only the narration is missing. "
            "Try again in a moment."
        )
        with st.expander("Technical details"):
            st.code(text)
        return

    sections = _parse_sections(text, _SECTIONS)
    section_defs = _SECTIONS
    if not sections:
        sections = _parse_sections(text, _TAXAL_SECTIONS)
        section_defs = _TAXAL_SECTIONS

    if not sections:
        st.markdown(text)
        return

    st.markdown(
        """
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
    """,
        unsafe_allow_html=True,
    )

    for label, icon in section_defs:
        value = sections.get(label, "")
        if not value:
            continue
        border_color, bg = _CARD_COLORS[label]
        st.markdown(
            f"""
        <div class="aria-card" style="background:{bg}; border-left-color:{border_color};">
            <div class="aria-card-label" style="color:{border_color};">{icon} {label}</div>
            {value}
        </div>
        """,
            unsafe_allow_html=True,
        )


# ── Module 1: profile panel ─────────────────────────────────────────────
def render_profile_panel(session_id: str) -> None:
    import streamlit as st
    from shared import user_store

    st.subheader("Your Financial Profile")
    st.caption("Powers Module 1's risk profile, budget, and SIP recommendations.")

    profile = user_store.get_financial_profile(session_id) or {}

    with st.form("profile_form"):
        col1, col2 = st.columns(2)
        with col1:
            income = st.number_input(
                "Monthly income (₹)",
                min_value=0.0,
                value=float(profile.get("monthly_income") or 0.0),
                step=1000.0,
            )
            age = st.number_input(
                "Age", min_value=18, max_value=100, value=int(profile.get("age") or 30)
            )
            dependents = st.number_input(
                "Dependents", min_value=0, max_value=10, value=int(profile.get("dependents") or 0)
            )
            city_tier = st.selectbox(
                "City tier", [1, 2, 3], index=[1, 2, 3].index(int(profile.get("city_tier") or 1))
            )
        with col2:
            emi = st.number_input(
                "Existing EMI (₹/month)",
                min_value=0.0,
                value=float(profile.get("existing_emi") or 0.0),
                step=500.0,
            )
            emergency_months = st.number_input(
                "Emergency fund (months of expenses covered)",
                min_value=0.0,
                value=float(profile.get("emergency_fund_months") or 0.0),
                step=0.5,
            )
            tax_regime = st.selectbox(
                "Tax regime",
                ["new", "old"],
                index=["new", "old"].index(profile.get("tax_regime") or "new"),
            )

        submitted = st.form_submit_button("Save profile")
        if submitted:
            user_store.save_financial_profile(
                session_id,
                monthly_income=income,
                age=int(age),
                dependents=int(dependents),
                existing_emi=emi,
                emergency_fund_months=emergency_months,
                city_tier=int(city_tier),
                tax_regime=tax_regime,
            )
            st.success("Profile saved. Ask ARIA a finance question in the Chat tab to see it applied.")
            st.rerun()

    if profile.get("risk_label"):
        st.divider()
        st.metric(
            "Current risk profile",
            profile["risk_label"],
            f"{profile.get('risk_confidence', 0):.0%} confidence",
        )


# ── Module 2: progress panel ────────────────────────────────────────────
_concept_names_cache: dict[str, str] | None = None


def _load_concept_names() -> dict[str, str]:
    global _concept_names_cache
    if _concept_names_cache is None:
        from config.paths import CONCEPTS_KB_FILE

        concepts = json.loads(CONCEPTS_KB_FILE.read_text(encoding="utf-8"))
        _concept_names_cache = {c["id"]: c["canonical_name"] for c in concepts}
    return _concept_names_cache


def render_progress_panel(session_id: str) -> None:
    import streamlit as st
    from shared import user_store

    st.subheader("Your Learning Progress")
    st.caption("Module 2's per-concept mastery, estimated by the DKT model from your quiz answers.")

    state = user_store.get_learning_state(session_id)
    mastery = state.get("mastery", {})
    history = state.get("history", [])

    if not history:
        st.info("Ask ARIA to explain a financial concept in the Chat tab to start building your progress here.")
        return

    engaged = sorted(
        ((cid, score) for cid, score in mastery.items() if score > 0),
        key=lambda kv: kv[1],
        reverse=True,
    )
    if not engaged:
        st.info("No mastery recorded yet -- answer a quiz question to see progress here.")
        return

    names = _load_concept_names()
    for concept_id, score in engaged:
        label = names.get(concept_id, concept_id)
        st.write(f"**{label}**")
        st.progress(min(max(score, 0.0), 1.0), text=f"{score:.0%} mastery")

    st.caption(f"{len(history)} total interactions recorded this session.")


# ── Example queries, one row per module ─────────────────────────────────
_EXAMPLE_QUERIES = {
    "\U0001f4b0 Personal Finance": [
        "I earn 95000 a month, pay 8500 EMI, should I start a SIP?",
        "How much tax will I pay on 12 lakhs under the new regime?",
    ],
    "\U0001f4da Tutor": [
        "What is compound interest?",
        "Quiz me on mutual funds",
    ],
    "\U0001f4ca Market Analysis": [
        "How did the Nifty do this week?",
        "How is the IT sector performing?",
    ],
    "\U0001f3e2 Equity Research": [
        "What is Reliance Industries' debt to equity ratio?",
        "What is TCS's current stock price?",
    ],
}


def _render_example_queries() -> None:
    import streamlit as st

    with st.expander("Not sure what to ask? Try these", expanded=False):
        for module_label, examples in _EXAMPLE_QUERIES.items():
            st.caption(module_label)
            cols = st.columns(len(examples))
            for col, example in zip(cols, examples):
                with col:
                    if st.button(example, key=f"example_{example}", use_container_width=True):
                        st.session_state.pending_query = example
                        st.rerun()


def _render_chat_tab(session_id: str) -> None:
    import streamlit as st

    col1, col2 = st.columns([4, 1])
    with col1:
        mode = st.selectbox("Chat Mode", ["Normal Mode", "Conversational Mode"])
    with col2:
        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
        if st.button("Clear Chat", use_container_width=True):
            from core.session import clear_session

            clear_session(session_id)
            st.rerun()

    _render_example_queries()
    st.divider()

    from core.session import get_session

    session = get_session(session_id)
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
    if st.session_state.get("pending_query"):
        st.session_state.query_text = st.session_state.pending_query
        st.session_state.pending_query = None

    query = st.text_input("Ask ARIA", key="query_text")
    submitted = st.button("Submit")

    if submitted and query.strip():
        with st.spinner("Analyzing..."):
            result = _handle_query(query.strip(), session_id=session_id, mode=mode)
            response = result.get("response", "No response generated.")

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


def run() -> None:
    import streamlit as st

    st.set_page_config(page_title="ARIA", page_icon="A")
    st.title("ARIA")

    # Each browser tab gets its own session id so concurrent public visitors
    # never share chat history or profile state with each other.
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid4())
    session_id = st.session_state.session_id

    if "query_text" not in st.session_state:
        st.session_state.query_text = ""

    chat_tab, profile_tab, progress_tab = st.tabs(
        ["\U0001f4ac Chat", "\U0001f464 Your Profile", "\U0001f4c8 Your Progress"]
    )
    with chat_tab:
        _render_chat_tab(session_id)
    with profile_tab:
        render_profile_panel(session_id)
    with progress_tab:
        render_progress_panel(session_id)


if __name__ == "__main__":
    run()
