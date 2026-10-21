"""Piper voice latency on this CPU: warm synth time for a short and a longer clause (no audio is played)."""
import sys, time
sys.path.insert(0, r"E:\ARIA")
from avatar_engine.tts import Tts
t = Tts()
for v in t.voices():
    t.synth("Hello.", v)
    row = [v]
    for txt in ("Hello, I am ARIA,", "Your portfolio gained two point four percent this quarter,"):
        t0 = time.perf_counter(); pcm, sr = t.synth(txt, v); dt = time.perf_counter() - t0
        row.append(f"{len(txt)} chars: {dt*1000:.0f} ms for {len(pcm)/2/sr:.2f}s audio (RTF {dt/(len(pcm)/2/sr):.2f})")
    print(" | ".join(row), flush=True)
