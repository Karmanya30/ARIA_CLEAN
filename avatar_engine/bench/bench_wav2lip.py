import os, sys, time, pickle, json
sys.path.insert(0, r"E:\avatar_bench\Wav2Lip")
import numpy as np, torch, cv2, librosa
import audio as wa
from models import Wav2Lip
dev = torch.device("cuda")
m = Wav2Lip(); ck = torch.load(r"E:\avatar_bench\wav2lip_gan.pth", map_location="cpu")
sd = {k.replace("module.", ""): v for k, v in ck["state_dict"].items()}; m.load_state_dict(sd); m = m.to(dev).half().eval()
torch.backends.cudnn.benchmark = True
A = pickle.load(open(r"E:\MuseTalk\MuseTalk\results\v15\avatars\aria_88d2a6e97401.pkl", "rb"))
frame = A["frames"][0]; x1, y1, x2, y2 = A["coords"][0]
face = cv2.resize(frame[y1:y2, x1:x2], (96, 96))
wav = librosa.load(r"E:\avatar_bench\para.wav", sr=16000)[0]
mel = wa.melspectrogram(wav); fps = 25
chunks = []; i = 0
while True:
    s = int(80.0 / fps * i)
    if s + 16 > mel.shape[1]: break
    chunks.append(mel[:, s:s + 16]); i += 1
n = len(chunks); print("frames", n)
masked = face.copy(); masked[48:] = 0
img = np.concatenate([masked, face], axis=2) / 255.
bs = int(sys.argv[1]) if len(sys.argv) > 1 else 32
res = {}
for bs in (8, 16, 32):
    for rep in range(3):
        torch.cuda.synchronize(); t = time.perf_counter(); outs = []
        for k in range(0, n, bs):
            mb = torch.from_numpy(np.stack(chunks[k:k + bs])[:, None]).to(dev).half()
            ib = torch.from_numpy(np.stack([img] * mb.shape[0])).permute(0, 3, 1, 2).to(dev).half()
            with torch.no_grad(): p = m(mb, ib)
            outs.append((p.float().cpu().numpy().transpose(0, 2, 3, 1) * 255).astype(np.uint8))
        torch.cuda.synchronize(); dt = time.perf_counter() - t
    res[f"bs{bs}"] = {"gpu_fps_incl_copy": round(n / dt, 1)}
res["peak_vram_mb"] = round(torch.cuda.max_memory_allocated() / 2**20)
res["vram_reserved_mb"] = round(torch.cuda.memory_reserved() / 2**20)
print(json.dumps(res))
outs = np.concatenate(outs)
# paste back with light feather and write a sample (crop around the face)
os.makedirs(r"E:\avatar_bench\w2l", exist_ok=True)
H, W = frame.shape[:2]; mask = np.zeros((y2 - y1, x2 - x1), np.float32); mask[:] = 1
mask = cv2.GaussianBlur(cv2.copyMakeBorder(mask[8:-8, 8:-8], 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=0), (0, 0), 6)[..., None]
for k in (20, 45, 90, 130):
    f = frame.copy(); p = cv2.resize(outs[k][:, :, ::1], (x2 - x1, y2 - y1), interpolation=cv2.INTER_CUBIC)
    f[y1:y2, x1:x2] = (p * mask + f[y1:y2, x1:x2] * (1 - mask)).astype(np.uint8)
    cv2.imwrite(rf"E:\avatar_bench\w2l\f{k}.png", f[y1 - 60:y2 + 60, x1 - 60:x2 + 60])
