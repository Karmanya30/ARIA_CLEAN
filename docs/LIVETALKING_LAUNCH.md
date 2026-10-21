# Launching the LiveTalking avatar (6th chat mode) and rolling it back

`Launch_ARIA.bat` (also the "Launch ARIA" shortcut) starts the API (first free port 8000..8019) and the web app (5173) only.
`Launch_ARIA.bat gpu` (the "Launch ARIA (Lip-sync GPU)" shortcut, `aria://launch-gpu`) additionally starts, one after the other:

1. the avatar engine (MuseTalk, port 8010) and waits until it is ready;
2. the LiveTalking service (Wav2Lip + Piper, port 8020, `scripts\start_livetalking.bat`), after checks below.

Every step is idempotent: a re-run reuses what is up and only starts what is missing.

## Checks before LiveTalking starts (a failed check is shown in the warning box and logs\launch.log; ARIA still opens)
- Port 8020 held by our `livetalking_adapter.serve` process, or answering `/health`: reused. Held by anything else: not started, message names the PID.
- Missing files are listed: `<dir>\env\python.exe`, `<dir>\src\app.py`, `<dir>\src\models\wav2lip.pth`, the avatar folder, the Piper voice `.onnx`, `scripts\start_livetalking.bat`.
- Free GPU memory (nvidia-smi, measured after the engine is ready) must be at least `ARIA_LT_MIN_FREE_MB` (default 2000 for Wav2Lip, 5000 for MuseTalk), otherwise it is skipped with a message. On this 8 GB card, "both" works only if the engine plus LiveTalking fit; otherwise use `ARIA_GPU_AVATARS`.
- Waits up to 300 s for `/health`; if the process exits early, the tail of `logs\livetalking.err.log` is put in the warning.

## Switches (environment variables)
| Variable | Default | Effect |
|---|---|---|
| `ARIA_LIVETALKING` | `1` | `0` = never start LiveTalking (rollback; the GPU launcher then behaves as before) |
| `ARIA_GPU_AVATARS` | `both` | `engine` = only port 8010, `livetalking` = only port 8020 |
| `LIVETALKING_DIR` | `E:\LiveTalking` | install root (the checkout is `<dir>\src`) |
| `LT_MODEL` | `wav2lip` | `musetalk` raises the VRAM gate to 5000 MiB |
| `ARIA_LT_MIN_FREE_MB` | 2000 / 5000 | free-VRAM gate |
| `ARIA_NO_BROWSER`, `ARIA_LAUNCH_NOGUI` | unset | test switches: no Edge window, no message boxes |

Logs: `logs\launch.log`, `logs\livetalking.out.log`, `logs\livetalking.err.log`.

## Rollback
- Instant, no code change: set `ARIA_LIVETALKING=0` (user environment variable), or `ARIA_GPU_AVATARS=engine`. The sixth mode then shows its fallback (voice disk) because port 8020 is down.
- Code: `git revert` the separate "wire 6th mode" commit (types.ts, ChatTab.tsx, vite proxy, `ChatMode.LIVETALKING`); the launcher block is inert without the flag. Stop a running service with the `livetalking_adapter.serve` process only (never kill other python jobs).

## Rollback rehearsal (21 Oct 2026)
- `ARIA_LIVETALKING=0` with `Launch_ARIA.bat gpu`: log shows "ARIA_LIVETALKING=0: the LiveTalking avatar is skipped." and the ready line has no port 8020; the engine path is unchanged.
- `git revert --no-commit` of the wiring commit could not be rehearsed: no such commit exists yet (changes are uncommitted). Rehearse it once the commit is made: `git revert --no-commit <sha>; git status; git revert --abort`.
- Launcher tests with the real service (RTX 4060 Laptop 8 GB): "both" works; after the engine loads about 3.1 GiB stay free, LiveTalking starts in about 11 s.
