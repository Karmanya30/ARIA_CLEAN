# Avatar asset attribution

`model.glb` is the example avatar bundled with the
[met4citizen/TalkingHead](https://github.com/met4citizen/TalkingHead) project
(`avatars/vroid.glb` in that repo), created with
[VRoid Studio](https://vroid.com/en/studio).

Per that project's README: "Example avatar 'vroid.glb' was created using
VRoid Studio for non-commercial use." Fine for this BTP demo; replace with a
different TalkingHead-compatible avatar (see the TalkingHead README's
"Creating your own avatar" section) before any commercial use.

The TalkingHead (`talkinghead.mjs`, `lipsync-en.mjs`) and HeadAudio
(`headaudio.min.mjs`, `headworklet.min.mjs`, `model-en-mixed.bin`) libraries
themselves are loaded at runtime from jsdelivr's CDN (see `avatar.html`),
not vendored here — both are MIT licensed, free, and require no API key.
