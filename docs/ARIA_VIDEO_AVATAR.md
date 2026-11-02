# ARIA video avatar: what the sample video shows, what was built, what to improve

## What the sample video is (measured with ffprobe and frame sheets)
- 20.0 seconds, 848 x 480, 24 fps, H.264, one silent audio track. A presenter (woman, navy blazer, round glasses) in a glass office with a screen of charts behind her. A small four-point sparkle mark in the lower-right corner suggests it was made by an AI video generator; treat it as AI-generated footage.
- Two clear halves: about 0 to 9.5 s she is **speaking** (mouth moving, eyebrow raises, two hand gestures around 4 to 7 s); from about 10.5 s to 20 s she is **calm and listening** (soft smile, slow head tilt around 15 s, return to a neutral smile). Two frames (around 3.5 s and 6.5 s) show one eye squeezed shut: a squint or wink. That reads oddly for a financial assistant; check it.

## Why it looks better than the photo avatar
1. Real micro-motion everywhere at once: brows, cheeks, hair, head, shoulders and hands. The photo avatar warps a jaw on a still image, so only the mouth region moves.
2. Hands and gestures: they signal emphasis and make her read as a person explaining something.
3. A listening state: a warm smile and a small head tilt. The photo avatar has nothing equivalent between phrases.
4. Composition: eye contact, head-and-shoulders framing, shallow depth of field, soft frontal light. The chart wall ties the look to the product.

## What was built
**New ARIA Avatar** is a separate choice. The live meeting header has an Avatar selector with "ARIA Avatar" (the original, still the default and unchanged: MuseTalk on the GPU if running, else the photo, else 3D) and "New ARIA Avatar" (the video presenter). The choice is remembered on the device; `?avatar=video` selects the new one directly.

Implemented from the improvement list (all inside the new avatar only):
- **More states, from the same footage:** a calm listening loop, a warm smile, a thinking tilt (shown while ARIA is working on an answer), and a one-off greeting when the meeting starts. They rotate on their own every 7 to 12 seconds so the face never freezes. These are cut from the one supplied video; a serious or concerned state and a farewell need new footage.
- **Varied talking footage:** three talking clips (one with the hand gesture) chosen at random starting points and swapped every 4.5 to 8 seconds. They are cut around the squint frames, so those no longer appear.
- **Motion tied to speech:** a sudden jump in the voice's loudness triggers the gesture clip (at most every 3.5 s). The talking clips play only while the voice is on and ease back to the calm loop in pauses.
- **Sharper:** clips are upscaled to 1280 x 720 (Lanczos plus a light sharpen). This is an enlargement of 848 x 480 footage, not new detail.
- **Accessibility:** with "reduce motion" the face is a still image.
- Clips are served by `/avatar/presenter-<name>.mp4`. Browser tests check the default avatar is unchanged, the new one loads and plays, and the clip switches to a talking clip while a voice plays and back after.

## Real lip-sync for the New ARIA Avatar (GPU)
- Run `scripts\start_musetalk_new_avatar.bat` (port **8011**). It loads MuseTalk with `interface/avatar/presenter-lipsync.mp4` (6.2 s of the calm footage) as the source. The first start prepares the video (face tracking and masks; a few minutes) and caches it; later starts are quick.
- With that server running, choosing "New ARIA Avatar" shows **lip-synced frames**: each phrase's voice goes to the server, which returns whole frames of the presenter with the mouth matching the speech, drawn in step with the audio. Between phrases the calm loops continue. Without the server, the avatar silently falls back to the clip library above (no lip-sync).
- The original avatar's server (port 8010, the photo) is separate and is not affected. Both can be installed; run one at a time on an 8 GB GPU.
- **Measured here** (RTX 4060 Laptop, 8 GB): 150 frames of speech generated in 7.9 s (18.9 frames per second, above the 15 fps the avatar plays at), so it keeps up with the voice. With a real speech clip, frames captured from a browser run show the mouth changing shape with the speech, natural head movement, the glasses intact and consistent lighting. That was judged by looking at the frames, not with a lip-sync score. The original photo server was re-run after the server change: 150 frames in 8.0 s, same mode as before.
- The server change is small: a video source returns whole frames (the head moves, so one fixed patch position cannot be used) and the frame position carries on from phrase to phrase. A photo source behaves exactly as before.

## What this is not
- Without the GPU server it is **not lip-sync**: the mouth follows the clip, not the words.
- The lip-sync source is only 6.2 s of footage, looped; the mouth is generated, so very fast or unusual speech can look less natural than the footage.
- The sample's own generator mark is still in the footage (left in on purpose: it marks the video as AI-generated).

## What to improve next
1. **A longer lip-sync source,** and a 1080p one: 6.2 s loops visibly, and 848 x 480 is enlarged to the stage.
2. **More states, same character.** Serious (for risk warnings), concerned and farewell need new footage from the same generator, character and background. The lip-sync path has only the calm source; thinking and greeting use the loops.
3. **Longer, more varied talking footage** for the no-GPU mode: three clips repeat in a long answer.
4. **Dark-mode and mobile framing:** the crop is a centred "cover" with the face slightly above centre; check portrait phones.
