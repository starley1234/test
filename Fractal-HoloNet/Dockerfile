FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    MODEL_DIR=/app/checkpoints/fractal_holonet_base \
    PORT=8000

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependencies and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and checkpoints
COPY . .

# Pre-export model and verify
RUN python -c "from fractal_holonet_prod import ProductionFractalHoloNet, FractalHoloNetConfig; import os; os.makedirs('./checkpoints/fractal_holonet_base', exist_ok=True); ProductionFractalHoloNet(FractalHoloNetConfig(vocab_size=300, d_model=128, n_layers=4, d_ff=384)).save_pretrained('./checkpoints/fractal_holonet_base')"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "serve:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
