import os
import sys
from pathlib import Path

# Setup Python Path
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from holonet.models.fractal_holonet import (
    ProductionRMSNorm,
    ComplexResonanceAssociativeCore,
    FractalHoloNetBlock,
    FractalHoloNetConfig,
    ProductionFractalHoloNet,
)
from holonet.models.multimodal import (
    ContinuousSignalEncoder,
    MultimodalSignalConfig,
    MultimodalFractalHoloNet,
)
from holonet.pipeline import SimpleProductionTokenizer, FractalHoloNetInferencePipeline
from holonet.distillation import TeacherAPIClient, FractalHoloNetDistiller

import time
from typing import List, Dict, Optional, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
import torch

TEXT_MODEL_DIR = os.getenv("TEXT_MODEL_DIR", str(ROOT_DIR / "checkpoints/fractal_holonet_base"))
SIGNAL_MODEL_DIR = os.getenv("SIGNAL_MODEL_DIR", str(ROOT_DIR / "checkpoints/fractal_holonet_multimodal"))

pipeline: Optional[FractalHoloNetInferencePipeline] = None
multimodal_model: Optional[MultimodalFractalHoloNet] = None

def init_services():
    global pipeline, multimodal_model
    # 1. Text Pipeline
    os.makedirs(TEXT_MODEL_DIR, exist_ok=True)
    cfg_path = os.path.join(TEXT_MODEL_DIR, "config.json")
    if not os.path.exists(cfg_path):
        config = FractalHoloNetConfig(vocab_size=300, d_model=128, n_layers=4, d_ff=384)
        model = ProductionFractalHoloNet(config)
        model.save_pretrained(TEXT_MODEL_DIR)
        tok = SimpleProductionTokenizer()
        tok.save(os.path.join(TEXT_MODEL_DIR, "tokenizer.json"))
    pipeline = FractalHoloNetInferencePipeline(model_dir=TEXT_MODEL_DIR, device="cpu")
    
    # 2. Multimodal Continuous Signal Model
    if os.path.exists(SIGNAL_MODEL_DIR):
        multimodal_model = MultimodalFractalHoloNet.from_pretrained(SIGNAL_MODEL_DIR, map_location="cpu")
    else:
        sig_cfg = MultimodalSignalConfig(
            input_signal_dim=1,
            output_signal_dim=1,
            patch_size=1,
            d_model=128,
            n_layers=4,
            d_ff=384,
            vocab_size=0
        )
        multimodal_model = MultimodalFractalHoloNet(sig_cfg)
        multimodal_model.save_pretrained(SIGNAL_MODEL_DIR)
    multimodal_model.eval()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_services()
    yield

app = FastAPI(
    title="Fractal-HoloNet Multimodal & Distillation AI Service",
    description="Universal continuous signal & text intelligence with Knowledge Distillation from Teacher LLMs",
    version="2.2.0",
    lifespan=lifespan
)

# Text Schemas
class GenerationRequest(BaseModel):
    prompt: str = Field(..., json_schema_extra={"example": "Fractal-HoloNet is a novel"})
    max_tokens: int = Field(default=50, ge=1, le=1024)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_k: int = Field(default=40, ge=1, le=100)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)

class GenerationResponse(BaseModel):
    prompt: str
    generated_text: str
    full_text: str
    prompt_tokens: int
    generated_tokens: int
    latency_ms: float

class EmbeddingRequest(BaseModel):
    text: str = Field(..., json_schema_extra={"example": "Signal embedding"})

class EmbeddingResponse(BaseModel):
    embedding: List[float]
    dimension: int

# Continuous Signal Schemas
class SignalForecastRequest(BaseModel):
    signal_history: List[List[float]] = Field(
        ...,
        description="Continuous raw multi-channel signal timesteps [[ch1, ch2...], ...]",
        json_schema_extra={"example": [[0.12], [0.35], [0.89], [1.45], [0.80], [0.20]]}
    )
    forecast_steps: int = Field(default=32, ge=1, le=512)

class SignalForecastResponse(BaseModel):
    forecast: List[List[float]]
    forecast_steps: int
    channels: int
    anomaly_scores: List[float]
    latency_ms: float

# Distillation Schemas
class DistillationAPIRequest(BaseModel):
    teacher_endpoint: str = Field(..., description="OpenAI-совместимый URL (e.g. https://api.openai.com/v1, https://openrouter.ai/api/v1)", json_schema_extra={"example": "https://api.openai.com/v1"})
    teacher_model: str = Field(..., description="Название модели Teacher (e.g. gpt-4o-mini, deepseek-chat, mistral-7b)", json_schema_extra={"example": "gpt-4o-mini"})
    teacher_api_key: str = Field(..., description="API-ключ доступа к Teacher модели")
    prompts: List[str] = Field(..., min_length=1, description="Список задач/промптов для генерации обучающего датасета учителем")
    system_prompt: Optional[str] = Field(default="You are an expert AI providing concise and accurate reasoning.")
    epochs: int = Field(default=5, ge=1, le=50)
    batch_size: int = Field(default=4, ge=1, le=64)
    learning_rate: float = Field(default=1e-3, ge=1e-5, le=1e-2)

class DistillationResponse(BaseModel):
    status: str
    teacher_model: str
    samples_distilled: int
    epochs: int
    final_loss: float
    duration_sec: float
    checkpoint_dir: str

class ModelInfoResponse(BaseModel):
    architecture: str
    modalities: List[str]
    features: List[str]
    device: str
    status: str

@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    return {"status": "healthy", "service": "Fractal-HoloNet Multimodal & Distillation Inference", "timestamp": time.time()}

@app.get("/info", response_model=ModelInfoResponse)
def model_info():
    return {
        "architecture": "Multimodal Fractal Gated Holographic Resonance Network",
        "modalities": ["text", "raw_audio", "ecg_biomedical", "iot_telemetry", "continuous_streams"],
        "features": ["O(N) context", "O(1) step inference", "continuous signal forecasting", "knowledge distillation"],
        "device": "cpu",
        "status": "ready"
    }

@app.post("/v1/generate", response_model=GenerationResponse)
def generate_text(req: GenerationRequest):
    global pipeline
    if pipeline is None:
        init_services()
    t0 = time.time()
    res = pipeline.generate(
        prompt=req.prompt,
        max_new_tokens=req.max_tokens,
        temperature=req.temperature,
        top_k=req.top_k,
        top_p=req.top_p
    )
    latency_ms = (time.time() - t0) * 1000.0
    return {
        "prompt": res["prompt"],
        "generated_text": res["generated_text"],
        "full_text": res["full_text"],
        "prompt_tokens": res["prompt_tokens"],
        "generated_tokens": res["generated_tokens"],
        "latency_ms": round(latency_ms, 2)
    }

@app.post("/v1/embeddings", response_model=EmbeddingResponse)
def get_embeddings(req: EmbeddingRequest):
    global pipeline
    if pipeline is None:
        init_services()
    emb = pipeline.get_embeddings(req.text)
    return {"embedding": emb, "dimension": len(emb)}

@app.post("/v1/signal/forecast", response_model=SignalForecastResponse)
def forecast_signal(req: SignalForecastRequest):
    global multimodal_model
    if multimodal_model is None:
        init_services()
        
    t0 = time.time()
    sig_tensor = torch.tensor([req.signal_history], dtype=torch.float32)
    
    with torch.no_grad():
        _, anom_scores_tensor, _ = multimodal_model.forward_continuous(sig_tensor)
        anom_scores = anom_scores_tensor[0, :, 0].cpu().tolist()
        forecast_tensor = multimodal_model.forecast_stream(sig_tensor, forecast_steps=req.forecast_steps)
        forecast_list = forecast_tensor[0].cpu().tolist()
        
    latency_ms = (time.time() - t0) * 1000.0
    
    return {
        "forecast": forecast_list,
        "forecast_steps": len(forecast_list),
        "channels": len(forecast_list[0]) if forecast_list else 1,
        "anomaly_scores": anom_scores,
        "latency_ms": round(latency_ms, 2)
    }

@app.post("/v1/distill", response_model=DistillationResponse)
def distill_model(req: DistillationAPIRequest):
    global pipeline
    if pipeline is None:
        init_services()
        
    try:
        teacher_client = TeacherAPIClient(
            endpoint=req.teacher_endpoint,
            api_key=req.teacher_api_key,
            model_name=req.teacher_model
        )
        distiller = FractalHoloNetDistiller(
            student_model=pipeline.model,
            tokenizer=pipeline.tokenizer,
            teacher_client=teacher_client,
            lr=req.learning_rate,
            device="cpu"
        )
        result = distiller.distill_from_teacher_api(
            prompts=req.prompts,
            system_prompt=req.system_prompt,
            epochs=req.epochs,
            batch_size=req.batch_size,
            save_dir=TEXT_MODEL_DIR
        )
        
        pipeline = FractalHoloNetInferencePipeline(model_dir=TEXT_MODEL_DIR, device="cpu")
        
        return {
            "status": "success",
            "teacher_model": req.teacher_model,
            "samples_distilled": len(req.prompts),
            "epochs": result["epochs"],
            "final_loss": result["final_loss"],
            "duration_sec": result["duration_sec"],
            "checkpoint_dir": result["save_dir"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Distillation failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
