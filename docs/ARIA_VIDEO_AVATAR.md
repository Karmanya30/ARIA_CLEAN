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

## What this is not
- It is **not lip-sync**. The mouth follows the clip, not ARIA's words. The video only knows "speaking" versus "not speaking", from the loudness of the voice.
- The sample's own watermark and two squint frames are in the clips as they are.

## What to improve, in order of impact
1. **Real lip-sync on this video.** MuseTalk can drive the lips of a source video, not only a photo. The server (`scripts/musetalk_server.py`) currently loads a photo. Giving it this video as the source is the biggest quality jump and needs your GPU to build and test; it was not done here.
2. **More states, same character.** Serious (for risk warnings), concerned and farewell need new footage from the same generator, character and background.
3. **Longer, more varied talking footage.** A pool of 3 to 5 talking clips chained with cross-fades hides the repetition; a reversed hand gesture is a tell in a long answer.
4. **Higher resolution.** 848 x 480 is stretched to a full-screen stage and looks soft. Use a 1080p source, or upscale once offline on your GPU.
5. **Motion tied to speech.** Trigger gestures and brow raises from emphasis in the voice instead of only on and off.
6. **Cleaner source.** Re-export without the generator mark, and remove the squint frames, or re-generate those seconds.
7. **Dark-mode and mobile framing.** The crop is a centred "cover" with the face slightly above centre; check portrait phones.
