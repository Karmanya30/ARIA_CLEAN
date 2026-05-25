from .groq_client import generate_audio
from .prompt_templates import get_audio_script_prompt
import re


def clean_for_tts(text: str) -> str:
    text = text.strip()

    # remove extra spaces
    text = re.sub(r"\s+", " ", text)

    # add natural pauses
    text = text.replace(". ", "... ")

    return text


def generate_audio_script(detailed_script: str) -> str:
    if not detailed_script or not detailed_script.strip():
        return "Sorry, I couldn't generate the explanation."

    prompt = get_audio_script_prompt(detailed_script)

    response = generate_audio(prompt)

    if response.startswith("Error"):
        return "Sorry, something went wrong while generating audio."

    return clean_for_tts(response)