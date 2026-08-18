import os
import sys
from pathlib import Path

# Setup Python Path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

import time
import math
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

from holonet import (
    ProductionFractalHoloNet,
    FractalHoloNetConfig,
    SimpleProductionTokenizer,
    FractalHoloNetInferencePipeline
)

class TextDataset(Dataset):
    def __init__(self, text: str, tokenizer: SimpleProductionTokenizer, block_size: int = 64):
        self.block_size = block_size
        encoded = tokenizer.encode(text, add_bos=False)
        self.data = torch.tensor(encoded, dtype=torch.long)
        
    def __len__(self):
        return max(1, (len(self.data) - 1) // self.block_size)
        
    def __getitem__(self, idx):
        start_idx = idx * self.block_size
        end_idx = start_idx + self.block_size + 1
        chunk = self.data[start_idx:end_idx]
        
        if len(chunk) < self.block_size + 1:
            pad_len = self.block_size + 1 - len(chunk)
            chunk = torch.cat([chunk, torch.zeros(pad_len, dtype=torch.long)])
            
        x = chunk[:-1]
        y = chunk[1:]
        return x, y


def train():
    corpus = """
Fractal-HoloNet is a linear complexity foundation architecture.
It replaces standard quadratic self-attention with complex-phase associative holographic memory.
By using geometric frequency bands and holographic resonance, it retains long-range context in O(1) state memory.
Streaming inference achieves constant step time and constant memory footprint.
This enables unbounded context processing on edge devices, continuous sensor streaming, and real-time generation.
""" * 50

    print("=" * 60)
    print("  🚀 Training Production Fractal-HoloNet (Language Modeling)")
    print("=" * 60)
    print(f"Corpus size: {len(corpus)} characters")

    # 1. Tokenizer
    tokenizer = SimpleProductionTokenizer()
    
    # 2. Dataset
    block_size = 64
    batch_size = 8
    dataset = TextDataset(corpus, tokenizer, block_size=block_size)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    # 3. Model
    config = FractalHoloNetConfig(
        vocab_size=300,
        d_model=128,
        n_layers=4,
        d_ff=384,
        dropout=0.0
    )
    model = ProductionFractalHoloNet(config)
    print(f"Model parameters: {sum(p.numel() for p in model.parameters() if p.requires_grad):,}")

    # 4. Optimizer & Loss
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-3, weight_decay=0.01)
    criterion = nn.CrossEntropyLoss()

    # 5. Training Loop
    epochs = 10
    save_dir = "./checkpoints/fractal_holonet_base"
    
    start_time = time.time()
    model.train()
    
    for epoch in range(epochs):
        total_loss = 0.0
        batches = 0
        for x, y in loader:
            optimizer.zero_grad()
            logits, _ = model(x, states=None, use_step=False)
            loss = criterion(logits.view(-1, logits.size(-1)), y.view(-1))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            
            total_loss += loss.item()
            batches += 1
            
        avg_loss = total_loss / max(1, batches)
        ppl = math.exp(min(avg_loss, 20))
        print(f"Epoch [{epoch+1:02d}/{epochs:02d}] | Loss: {avg_loss:.4f} | Perplexity: {ppl:.2f}")

    total_time = time.time() - start_time
    print(f"\n✅ Training completed in {total_time:.2f} seconds!")

    # 6. Save Model
    os.makedirs(save_dir, exist_ok=True)
    model.save_pretrained(save_dir)
    tokenizer.save(os.path.join(save_dir, "tokenizer.json"))
    print(f"💾 Saved production checkpoint to: {save_dir}")

    # 7. Test Inference Pipeline
    print("\n--- 🧪 Testing Inference Pipeline ---")
    pipe = FractalHoloNetInferencePipeline(save_dir)
    prompt = "Fractal-HoloNet is"
    res = pipe.generate(prompt, max_new_tokens=30, temperature=0.7)
    print(f"Prompt: '{prompt}'")
    print(f"Generated text: '{res['generated_text']}'")
    print(f"Full text: '{res['full_text']}'")

if __name__ == "__main__":
    train()
