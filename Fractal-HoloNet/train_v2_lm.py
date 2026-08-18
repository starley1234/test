"""
Train the ELAST-HOLO v2 language model on the Russian corpus (same data
and budget regime as the v1 train_russian.py run) and save the checkpoint
to ./checkpoints/fractal_holonet_v2.

    python train_v2_lm.py [--epochs N]
"""
import os
import sys
import time
import math
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

from research.arch_v2_core import ElasticHoloNet, ElasticHoloConfig
from pipeline import SimpleProductionTokenizer
from train_russian import get_russian_corpus


class ByteDataset(Dataset):
    def __init__(self, token_ids, block_size=96):
        self.block_size = block_size
        self.data = torch.tensor(token_ids, dtype=torch.long)

    def __len__(self):
        return max(1, (len(self.data) - 1) // self.block_size)

    def __getitem__(self, idx):
        start = idx * self.block_size
        chunk = self.data[start : start + self.block_size + 1]
        if len(chunk) < self.block_size + 1:
            chunk = torch.cat([chunk, torch.zeros(self.block_size + 1 - len(chunk), dtype=torch.long)])
        return chunk[:-1], chunk[1:]


def demo_generate(model, tokenizer, prompts, max_new_tokens=48):
    model.eval()
    for p in prompts:
        ids = torch.tensor([tokenizer.encode(p, add_bos=False)], dtype=torch.long)
        gen = model.generate(ids, max_new_tokens=max_new_tokens, temperature=1.0, top_k=1)
        new_ids = gen[0, ids.size(1):].tolist()
        print(f"\n[{p}]\n  -> {tokenizer.decode(new_ids, skip_special=True)}")


def greedy_accuracy(model, tokenizer, text):
    """Greedy next-byte accuracy on the corpus (memorization quality)."""
    ids = torch.tensor([tokenizer.encode(text, add_bos=False)], dtype=torch.long)
    model.eval()
    with torch.no_grad():
        logits, _ = model(ids)
    preds = logits[0].argmax(dim=-1)
    acc = (preds[:-1] == ids[0][1:]).float().mean().item()
    return acc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--save-dir", default="./checkpoints/fractal_holonet_v2")
    args = ap.parse_args()

    torch.manual_seed(42)
    print("=" * 72)
    print("  TRAIN ELAST-HOLO v2 (ElasticHoloNet) ON RUSSIAN CORPUS")
    print("=" * 72)

    corpus = get_russian_corpus()
    # CPU-бюджет: берём первые 12 копий базового корпуса (полный корпус - для GPU)
    base_len = len(corpus) // 35
    corpus = corpus[: base_len * 12]
    tokenizer = SimpleProductionTokenizer()
    tokens = tokenizer.encode(corpus, add_bos=False)
    print(f"Корпус: {len(corpus):,} символов, {len(tokens):,} токенов")

    config = ElasticHoloConfig(
        vocab_size=300, d_model=64, n_layers=4, d_ff=192,
        n_read_iters=2, use_slow_memory=True, dropout=0.0,
    )
    model = ElasticHoloNet(config)
    print(f"Параметров: {sum(p.numel() for p in model.parameters()):,}")

    # batch/block are kept small: the matrix state (B, D, D) with a sequential
    # autograd chain of length T is memory-hungry on CPU (O(T*B*D^2) activations)
    loader = DataLoader(ByteDataset(tokens, block_size=64), batch_size=16, shuffle=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=0.01)
    criterion = nn.CrossEntropyLoss(ignore_index=0)

    t0 = time.time()
    for epoch in range(args.epochs):
        model.train()
        total, batches = 0.0, 0
        for x, y in loader:
            optimizer.zero_grad()
            logits, _ = model(x)
            loss = criterion(logits.view(-1, logits.size(-1)), y.view(-1))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total += loss.item()
            batches += 1
        avg = total / max(1, batches)
        print(f"  epoch {epoch+1:02d}/{args.epochs} | loss {avg:.4f} | ppl {math.exp(min(avg, 20)):.2f}")

    print(f"Обучение завершено за {time.time()-t0:.1f}s")
    model.save_pretrained(args.save_dir)
    tokenizer.save(os.path.join(args.save_dir, "tokenizer.json"))
    print(f"Чекпоинт сохранён в {args.save_dir}")

    print(f"\nGreedy next-byte accuracy на корпусе: {greedy_accuracy(model, tokenizer, corpus):.3f}")

    print("\n--- Демо генерации (greedy) ---")
    demo_generate(model, tokenizer, [
        "Архитектура Fractal-HoloNet построена на",
        "Вопрос: Что такое фазовый резонанс?\nОтвет:",
        "Искусственный интеллект — это",
    ])


if __name__ == "__main__":
    main()
