import os
import sys
from pathlib import Path

# Setup Python Path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

import time
import math
import urllib.request
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
    def __init__(self, token_ids, block_size: int = 128):
        self.block_size = block_size
        self.data = torch.tensor(token_ids, dtype=torch.long)
        
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


def download_benchmark_data(data_path="data/tiny_shakespeare.txt"):
    os.makedirs(os.path.dirname(data_path), exist_ok=True)
    if not os.path.exists(data_path):
        print(f"📥 Загрузка эталонного датасета TinyShakespeare в {data_path}...")
        url = "https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt"
        urllib.request.urlretrieve(url, data_path)
    with open(data_path, "r", encoding="utf-8") as f:
        text = f.read()
    return text


def train_benchmark():
    print("=" * 75)
    print("  🎭 БЕНЧМАРК ОБУЧЕНИЯ FRACTAL-HOLONET (TINYSHAKESPEARE CORPUS)")
    print("=" * 75)
    
    text = download_benchmark_data()
    print(f"📊 Размер датасета: {len(text):,} символов ({len(text.encode('utf-8')):,} UTF-8 байт)")
    
    tokenizer = SimpleProductionTokenizer()
    tokens = tokenizer.encode(text, add_bos=False)
    
    n_train = int(len(tokens) * 0.9)
    train_tokens = tokens[:n_train]
    val_tokens = tokens[n_train:]
    
    block_size = 128
    batch_size = 32
    
    train_dataset = TextDataset(train_tokens, block_size=block_size)
    val_dataset = TextDataset(val_tokens, block_size=block_size)
    
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)
    
    config = FractalHoloNetConfig(
        vocab_size=300,
        d_model=128,
        n_layers=4,
        d_ff=384,
        dropout=0.05
    )
    model = ProductionFractalHoloNet(config)
    print(f"⚙️ Параметров архитектуры: {sum(p.numel() for p in model.parameters() if p.requires_grad):,}")
    print("-" * 75)
    
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=0.01)
    criterion = nn.CrossEntropyLoss()
    
    epochs = 3
    save_dir = "./checkpoints/fractal_holonet_benchmark"
    
    start_time = time.time()
    
    for epoch in range(epochs):
        model.train()
        total_loss = 0.0
        batches = 0
        
        for x, y in train_loader:
            optimizer.zero_grad()
            logits, _ = model(x, states=None, use_step=False)
            loss = criterion(logits.view(-1, logits.size(-1)), y.view(-1))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            
            total_loss += loss.item()
            batches += 1
            
        train_loss = total_loss / max(1, batches)
        
        # Validation
        model.eval()
        val_loss = 0.0
        val_batches = 0
        with torch.no_grad():
            for vx, vy in val_loader:
                v_logits, _ = model(vx, states=None, use_step=False)
                v_loss = criterion(v_logits.view(-1, v_logits.size(-1)), vy.view(-1))
                val_loss += v_loss.item()
                val_batches += 1
                
        avg_val_loss = val_loss / max(1, val_batches)
        print(f"  Эпоха [{epoch+1:02d}/{epochs:02d}] | Train Loss: {train_loss:.4f} (PPL: {math.exp(min(train_loss, 20)):.2f}) | Val Loss: {avg_val_loss:.4f} (Val PPL: {math.exp(min(avg_val_loss, 20)):.2f})")

    duration = time.time() - start_time
    print(f"\n✅ Бенчмарк-обучение завершено за {duration:.2f} сек!")
    
    os.makedirs(save_dir, exist_ok=True)
    model.save_pretrained(save_dir)
    tokenizer.save(os.path.join(save_dir, "tokenizer.json"))
    print(f"💾 Чекпоинт бенчмарка сохранен в: {save_dir}")

if __name__ == "__main__":
    train_benchmark()
