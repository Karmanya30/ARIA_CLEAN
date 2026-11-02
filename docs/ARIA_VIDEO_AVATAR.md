# ARIA video avatar: what the sample video shows, what was built, what to improve

## What the sample video is (measured with ffprobe and frame sheets)
- 20.0 seconds, 848 x 480, 24 fps, H.264, one silent audio track. A presenter (woman, navy blazer, round glasses) in a glass office with a screen of charts behind her. A small four-point sparkle mark in the lower-right corner suggests it was made by an AI video generator; treat it as AI-generated footage.
- Two clear halves: about 0 to 9.5 s she is **speaking** (mouth moving, eyebrow raises, two hand gestures around 4 to 7 s); from about 10.5 s to 20 s she is **calm and listening** (soft smile, slow head tilt around 15 s, return to a neutral smile). Two frames (around 3.5 s and 6.5 s) show one eye squeezed shut: a squint or wink. That reads oddly for a financial assistant; check it.

## Why it looks better than the photo avatar
1. Real micro-motion everywhere at once: brows, cheeks, hair, head, shoulders and hands. The photo avatar warps a jaw on a still image, so only the mouth region moves.
2. Hands and gestures: they signal emphasis and make her read as a person explaining something.
3. A listening state: a warm smile and a small head tilt. The photo avatar has nothing equivalent between phrases.
4. Composition: eye contact, head-and-shoulders framing, shallow depth of field, soft frontal light. The chart wall ties the look to the product.

## What was built (this change)
- A new **video presenter** avatar mode in `interface/avatar/live.html`. It plays two seamless "boomerang" loops made from the sample (`presenter-idle.mp4` for listening, `presenter-talk.mp4` for speaking, about 0.7 MB each). The talking loop plays while ARIA's voice is on and eases back to the calm loop in pauses; the start point is random so phrases do not all begin on the same gesture. A reduced-motion setting shows a still face.
- Order of choice: **MuseTalk (GPU lip-sync) first, unchanged**, then the video presenter, then the old photo, then the 3D model. `?avatar=video`, `?avatar=photo` or `?avatar=3d` forces one. Clip files are served by `/avatar/presenter-idle.mp4` and `/avatar/presenter-talk.mp4`.
- A browser test checks that the live meeting uses the video presenter and that it is playing.

## What this is not
- It is **not lip-sync**. The mouth follows the clip, not ARIA's words. The video only knows "speaking" versus "not speaking", from the loudness of the voice.
- The sample's own watermark and two squint frames are in the clips as they are.

## What to improve, in order of impact
1. **Real lip-sync on this video.** MuseTalk can drive the lips of a source video, not only a photo. The server (`scripts/musetalk_server.py`) currently loads a photo. Giving it this video as the source is the biggest quality jump and needs your GPU to build and test; it was not done here.
2. **More states, same character.** Greeting, thinking (glance up, brow raise), nodding while listening, serious (for risk warnings), pleased (good news), farewell. Generate them with the same generator, character and background so they cut together.
3. **Longer, more varied talking footage.** A pool of 3 to 5 talking clips chained with cross-fades hides the repetition; a reversed hand gesture is a tell in a long answer.
4. **Higher resolution.** 848 x 480 is stretched to a full-screen stage and looks soft. Use a 1080p source, or upscale once offline on your GPU.
5. **Motion tied to speech.** Trigger gestures and brow raises from emphasis in the voice instead of only on and off.
6. **Cleaner source.** Re-export without the generator mark, and remove the squint frames, or re-generate those seconds.
7. **Dark-mode and mobile framing.** The crop is a centred "cover" with the face slightly above centre; check portrait phones.
