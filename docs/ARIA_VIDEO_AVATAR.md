# ARIA video avatar ("New ARIA Avatar")

## What it is
A second avatar next to the original. The live meeting header has an **Avatar** selector: "ARIA Avatar" (the original, still the default and unchanged) and "New ARIA Avatar". The choice is remembered on the device.

The New ARIA Avatar uses the **original avatar's scene**: the same bright office (window with the city view, plants, shelves, desk), the same seated figure and the same navy blazer and white blouse, with the **moving presenter from the supplied video** on top. The video itself was generated with a different background (a dark office with a charts wall), so the clips are rebuilt: the presenter is cut out of every frame (MuseTalk's face-parsing network), moved and scaled so her face lands on the old avatar's face, and blended with a soft edge over a 16:9 crop of the old photo. Her hands and body are the old photo's, so only the head moves. The video's corner mark is not in the result because the whole background is replaced. Build script: `scripts/build_new_avatar_scene.py` (run it with the MuseTalk Python environment; it reads the video from `.audit/src.mp4` or `ARIA_AVATAR_VIDEO`).

## How it behaves
- **Stable** when nothing is happening and after she has finished speaking: one held frame (eyes open, calm smile), no random movement.
- **Attentive only while the client is speaking:** a slight head tilt and a smile, then she settles again. The signal is the microphone's voice detection or the browser recogniser's words.
- **Speaking, with the GPU server:** real lip-sync; the mouth follows the words.
- **Speaking, without the GPU server:** she keeps the stable face and the page shows a note saying how to start the server. An earlier version played generic talking clips here; their mouth movement had no relation to the words, so they were removed.
- **Reduce motion:** always the held frame.

## Real lip-sync (GPU)
- One server serves **both** avatars. `Launch_ARIA.bat gpu` (or `aria://launch-gpu`) starts `scripts/musetalk_server.py` with the original photo and `--source-video interface/avatar/presenter-lipsync.mp4`; the models are loaded once (`/lipsync` = original avatar, `/lipsync?avatar=video` = New ARIA Avatar). `gpu-new` is an alias. If a lip-sync server that was started before this avatar existed is still running, the launcher restarts it once.
- Each phrase's voice goes to the server, which returns whole 1280 x 720 frames of the presenter in the old scene with the mouth matching the speech; the page draws them in step with the audio. Every phrase starts from the held frame, and she returns to it when she stops.
- **Measured here** (RTX 4060 Laptop, 8 GB): 150 frames in 7.9 s (19 frames per second, above the 15 fps it plays at). The original avatar's output from the same server is unchanged (150 frames, same protocol). Frames captured from a browser run with real speech show the mouth following the words, the same office in idle and speech, and the attentive tilt while the client speaks. That was judged by looking at the frames, not with a lip-sync score.

## Launching
- `Launch_ARIA.bat` starts ARIA and opens Edge; `Launch_ARIA.bat gpu` also starts the lip-sync server. If the backend from before an update is still running, the launcher restarts it (an earlier version stopped with "ARIA could not start" because it could not identify the port's owner).
- The page quietly falls back to the old avatar if the new clips are missing (an outdated backend returns 404 for them).

## Limits and what to improve next
- The presenter's head is composited on the old photo's body. Her head moves slightly more than the old avatar's, and where the head meets the shoulders the blend relies on both being the same blazer; look for a seam at the collar on very large screens.
- The calm source is only 2.4 s of footage, so speech repeats a small range of head movement. A longer calm take, or a clip generated directly from the old avatar image (image to video, same scene) would remove the compositing.
- No serious, concerned or farewell expressions: those need new footage.
- If you hear no voice at the start of a meeting with a Bluetooth headset: opening the microphone switches many Bluetooth headsets to a low-quality call mode, which makes the output quiet or garbled. This is a device behaviour, not tested here; try a wired headset or mute the microphone at the start.
