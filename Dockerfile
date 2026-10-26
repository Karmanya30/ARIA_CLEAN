# ARIA: one image with the API and the built web app (see docs/DEPLOYMENT.md).
# Build:  docker build -t aria .        Run:  docker compose up -d
# NOTE: written without a Docker daemon available, so the first build is the first test; see docs/DEPLOYMENT.md.

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUTF8=1 \
    ARIA_BIND_HOST=0.0.0.0 \
    DB_URL=sqlite:////var/aria/aria.db
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# CPU-only torch (the default Linux wheel pulls in gigabytes of CUDA libraries that nothing here uses).
COPY requirements.txt requirements-security.txt ./
RUN pip install torch==2.13.0 --extra-index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt

COPY . .
COPY --from=web /web/dist web/dist

# The trained models are not in git: build them here (each takes well under 5 minutes on a CPU), then the concept index
# and the free voice. FinBERT sentiment weights are optional (see docs/DEPLOYMENT.md); without them a keyword read is used.
RUN python -m scripts.generate_synthetic_transactions \
    && python -m modules.finance.train.train_xgb_risk \
    && python -m modules.finance.train.train_lstm_spend \
    && python -m scripts.build_concept_kb \
    && python -m scripts.generate_kt_sequences \
    && python -m modules.tutor.train.train_lstm_kt \
    && python -m modules.tutor.train.train_dqn_teacher \
    && (python -m ai.speech.live_tts --download || echo "voice download skipped: the browser voice is used instead")

RUN mkdir -p /var/aria
VOLUME /var/aria
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
