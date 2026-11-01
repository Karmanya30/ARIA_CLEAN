# Seated avatar validation — 31 October 2026

## Wide office and glasses update — 1 November 2026

The active photo is now `interface/avatar/office-wide-glasses.webp`, a wide, continuous office scene with thin round glasses and both hands visible. Artificial blur was removed from the side-extension renderer. The original `seated-office.webp`, `face.png` and `glasses.png` are preserved. The glasses are part of the new photo; the legacy overlay was tied to a different image size and is not drawn over this scene.

The built-in image-generation tool edited the seated office using the original portrait as an identity reference. Prompt: preserve the seated woman, identity, hair, navy suit and both hands; expand into a seamless ultra-wide, detailed office with windows, plants, shelving and desk; restore thin round silver glasses with transparent lenses; no mirrored objects, logos, text or extra people. Generated source: `C:/Users/jtmah/.codex/generated_images/01a18d19-d352-71d1-98cb-9d004c71fb7e/exec-46dfbf7c-566c-4520-9be4-685ee28854e8.png`. The project copy is an optimized WebP.

The wide composition initially failed full-image face detection. The renderer now detects the central face region and maps landmarks back to the complete scene. The actual browser check loaded the photo renderer, received a real spoken audio response, displayed captions and reported no page errors. Desktop and mobile evidence is in `.audit/avatar-wide/`. Blinks, subtle facial deformation and audio-driven mouth motion remain available. The hands and office are still images, not generated body or hand animation. The optional GPU launcher now points to the same scene, but GPU playback with this new asset has not been retested.

The material below records the prior seated-scene implementation and its earlier GPU test.

The live photo and MuseTalk renderers now use `interface/avatar/seated-office.webp`: a coherent seated office composition with both hands resting on the desk. The shoulders, hands and desk remain still; facial animation stays local. This does not synthesize hand gestures. Narrow screens preserve the center of the composition. Wide screens extend the same office using softly blurred, mirrored edge crops, feathered into the original without copying the person. A subtle shifting daylight effect animates the extensions. The canvas enters with a 500 ms opacity transition; both entrance and daylight motion respect reduced-motion settings.

## Asset provenance

- Generated source: `C:\Users\jtmah\.codex\generated_images\01a18e7d-a9fb-7c40-a57d-b23e92c658cc\exec-222aeb89-f68c-48f0-8acf-6e17d087b667.png`.
- Runtime WebP SHA256: `D1FE810F5454B110148997863D7913DFDD2138E1C746BDF361B349DB7B914500`.
- Original `interface/avatar/face.png` is preserved; SHA256: `CC091A4C7F1E0C39BEDE8B1EE181B055555EAFEC4F3D29813D066FC3E3D2593C`.
- GPU launcher and its prerequisite check use the same seated asset. The browser rejects a running GPU service whose reported source differs, then falls back to the seated photo.

## Actual browser verification

Ran `.audit/avatar-hands/visual.mjs` against the running local app with Chromium, normal QA registration and the required legal acknowledgment checkbox. No authentication bypass or mocked renderer was used. MediaPipe successfully detected the face in the full composition. The earlier timeout was an unauthenticated request returning “Please sign in to ARIA,” not a face-detection failure.

Evidence in `.audit/avatar-hands/`:

- `desktop.png`: photo renderer at 1496 × 648; both hands, desk and full head visible.
- `mobile.png`: photo renderer at 370 × 648; both hands and head visible, with intentional top/bottom matte space.
- `gpu-mobile.png`: actual automatically selected MuseTalk renderer at 370 × 648.
- `browser.json`: photo and MuseTalk renderer identities and zero JavaScript page errors.
- `desktop-surround.png` and `mobile-surround.png`: latest authenticated photo-renderer verification after the wide-stage office extensions; both hands and head remain visible and desktop side bars are filled.
- `browser-surround.json`: latest photo renderer identity, detected face pose, dimensions and zero JavaScript page errors. GPU was not rerun during the surround update; the prior GPU test below remains the evidence for its render pipeline.

Screenshots were visually inspected. This probe checks renderer initialization and framing; it does not exercise a human microphone, assess perceived voice quality, or measure the entrance animation over time. Conversation/caption verification belongs to the separate live meeting dry run.

## Actual GPU render

The existing local MuseTalk environment on the RTX 4060 was used without a new model installation. `.audit/avatar-hands/gpu_probe.py` submitted the saved real TTS WAV from `.audit/live3/real-tts-sample.wav` to `/lipsync`.

`gpu-render.json` records 26 expected and 26 received JPEG frames, all distinct, for 1.788 seconds of audio at 15 fps. Render time was 3.886 seconds. Selected actual outputs are `gpu-frame-0.jpg`, `gpu-frame-13.jpg`, and `gpu-frame-25.jpg`. This measured run is slower than realtime; do not describe it as realtime GPU generation. The browser buffers audio/video together for playback.

The resumed GPU service loaded successfully on CUDA in 41 seconds, and the authenticated browser selected it. Its `/health` scene size is 1440 × 960 with normalized patch coordinates, preserving alignment with the larger original WebP.
