# ARIA video avatar ("New ARIA Avatar")

## What it is
A second avatar next to the original. The live meeting header has an **Avatar** selector: "ARIA Avatar" (the original, still the default and unchanged) and "New ARIA Avatar". The choice is remembered on the device.

The New ARIA Avatar uses the **original avatar's scene**: the same bright office (window with the city view, plants, shelves, desk), the same navy blazer and white blouse, with the **moving presenter from the supplied video**. The video itself was generated in a different, dark office, so the clips are rebuilt (`scripts/build_new_avatar_scene.py`, run with the MuseTalk Python environment; it reads the video from `.audit/src.mp4` or `ARIA_AVATAR_VIDEO`):
- The presenter is cut out of every frame (MuseTalk's face-parsing network), moved and scaled so her face lands on the old avatar's face, and blended over the **whole** old photo.
- Only her head, neck and hair come from the video. Below the chin the old photo's own blazer, blouse and hands take over (fading over about half a face height). Her open collar and body used to show as an orange patch and a "second person" there.
- The clips use the old photo's proportions (1440 x 616). The page frames them exactly like the old avatar, so the whole office is visible. The earlier 16:9 clips were cropped to the face in wide windows.
- Source windows avoid the thumbs-up gesture in the supplied video (about 12.7 s to 14.8 s): calm 10.6 to 12.5 s, attentive 15.2 to 17.0 s. The earlier windows touched it.

## How it behaves
- **Stable** when nothing is happening and after she has finished speaking: one held frame (eyes open, calm smile), no random movement.
- **Attentive only while the client is speaking:** a slight head tilt and a smile, then she settles again. The signal is the microphone's voice detection or the browser recogniser's words.
- **Speaking, with the GPU server:** real lip-sync; the mouth follows the words (below).
- **Speaking, without the GPU server:** she keeps the stable face and the page shows a note saying how to start the server. Generic talking clips were removed: their mouth movement had no relation to the words.
- **Reduce motion:** always the held frame.

## Real lip-sync (GPU): the answer as a video
- One server serves **both** avatars. `Launch_ARIA.bat gpu` (or `aria://launch-gpu`; `gpu-new` is an alias) starts `scripts/musetalk_server.py` with the original photo and `--source-video interface/avatar/presenter-lipsync.mp4`; the models are loaded once. A server started before this avatar existed is restarted once by the launcher.
- Each phrase's voice WAV goes to `POST /lipsync_video?avatar=video&fps=12`. The server generates the mouth, composes whole frames and returns **one silent 25 fps H.264 clip** for the phrase. The page plays it in a plain `<video>` on top of the held frame, started just ahead of the voice and kept on the audio clock (re-seeked if it drifts more than 0.15 s). There is no per-frame drawing in the page.
- The head moves at the source's own 25 fps (every source frame). The mouth is generated at 12 frames per second of speech and each mouth frame is held for about two output frames; `fps` (10 to 25) trades speed for finer mouth movement. Consecutive phrases of one answer continue the head movement; every answer starts from the held frame, and she fades back to it when she stops.
- The original avatar's `POST /lipsync` is unchanged (patch frames, 15 fps). `POST /lipsync` with `avatar=video` still streams JPEG frames for any other client.
- **Measured here** (RTX 4060 Laptop 8 GB, headless Edge, no screenshots running): a 9.8 s sentence is ready 7.5 s after it is sent (0.76 x the speech length; a 3 s sentence is ready in about 2.3 s). Playback: 241 frames, 2 dropped to 9 dropped, median 34 to 41 ms between presented frames, worst gap under 100 ms apart from the first frame of a clip. The first request after the server starts is slower (GPU kernels are tuned once). Frames captured during speech show one person, the same office, the mouth moving, no hand.
- Latency is the cost of a video: the first phrase starts playing only after it has been rendered. Short sentences keep it small. Lip-sync accuracy was judged by looking at the frames, not with a lip-sync score.

## Launching
- `Launch_ARIA.bat` starts ARIA and opens Edge; `Launch_ARIA.bat gpu` also starts the lip-sync server. If the backend from before an update is still running, the launcher restarts it.
- The page quietly falls back to the old avatar if the new clips are missing (an outdated backend returns 404 for them). After updating, hard-refresh the page (Ctrl+Shift+R) so the old clips are not served from the cache.

## Limits and what to improve next
- Her head is composited on the old photo's body, so only the head moves; the head is a little larger than the old avatar's.
- The calm source is only 2 s of footage, so speech repeats a small range of head movement. A longer calm take, or a clip generated directly from the old avatar image (image to video, same scene), would remove the compositing.
- No serious, concerned or farewell expressions: those need new footage.
- If you hear no voice at the start of a meeting with a Bluetooth headset: opening the microphone switches many Bluetooth headsets to a low-quality call mode, which makes the output quiet or garbled. This is a device behaviour, not tested here.
