import os
import time
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
import torch

from fractal_holonet_prod import ProductionFractalHoloNet, FractalHoloNetConfig
from pipeline import SimpleProductionTokenizer, FractalHoloNetInferencePipeline

MODEL_DIR = os.getenv("MODEL_DIR", "./checkpoints/fractal_holonet_base")

# Global pipeline instance
pipeline: Optional[FractalHoloNetInferencePipeline] = None

def init_pipeline():
    global pipeline
    os.makedirs(MODEL_DIR, exist_ok=True)
    cfg_path = os.path.join(MODEL_DIR, "config.json")
    if not os.path.exists(cfg_path):
        config = FractalHoloNetConfig(vocab_size=300, d_model=128, n_layers=4, d_ff=384)
        model = ProductionFractalHoloNet(config)
        model.save_pretrained(MODEL_DIR)
        tok = SimpleProductionTokenizer()
        tok.save(os.path.join(MODEL_DIR, "tokenizer.json"))
        
    pipeline = FractalHoloNetInferencePipeline(model_dir=MODEL_DIR, device="cpu")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pipeline()
    yield

app = FastAPI(
    title="Fractal-HoloNet AI Inference Service",
    description="High-performance production API for Fractal Gated Holographic Resonance Network",
    version="1.0.0",
    lifespan=lifespan
)

class GenerationRequest(BaseModel):
    prompt: str = Field(..., json_schema_extra={"example": "Hello AI"})
    max_tokens: int = Field(default=50, ge=1, le=1024)
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
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
    text: str = Field(..., json_schema_extra={"example": "Sequence to embed"})

class EmbeddingResponse(BaseModel):
    embedding: List[float]
    dimension: int

class ModelInfoResponse(BaseModel):
    architecture: str
    config: dict
    device: str
    status: str

@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    return {"status": "healthy", "service": "Fractal-HoloNet Inference Service", "timestamp": time.time()}

@app.get("/info", response_model=ModelInfoResponse)
def model_info():
    global pipeline
    if pipeline is None:
        init_pipeline()
    return {
        "architecture": "Fractal Gated Holographic Resonance Network (Fractal-HoloNet)",
        "config": pipeline.model.config.to_dict(),
        "device": str(pipeline.device),
        "status": "ready"
    }

@app.post("/v1/generate", response_model=GenerationResponse)
def generate_text(req: GenerationRequest):
    global pipeline
    if pipeline is None:
        init_pipeline()
    
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
        init_pipeline()
        
    emb = pipeline.get_embeddings(req.text)
    return {
        "embedding": emb,
        "dimension": len(emb)
    }
