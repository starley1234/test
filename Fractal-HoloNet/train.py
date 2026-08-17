import os
import time
import math
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

from fractal_holonet_prod import ProductionFractalHoloNet, FractalHoloNetConfig
from pipeline import SimpleProductionTokenizer, FractalHoloNetInferencePipeline

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


class FractalHoloNetTrainer:
    def __init__(
        self,
        model: ProductionFractalHoloNet,
        tokenizer: SimpleProductionTokenizer,
        lr: float = 1e-3,
        weight_decay: float = 0.01,
        device: str = "cpu"
    ):
        self.device = torch.device(device)
        self.model = model.to(self.device)
        self.tokenizer = tokenizer
        
        decay_params = [p for p in model.parameters() if p.requires_grad and p.dim() >= 2]
        nodecay_params = [p for p in model.parameters() if p.requires_grad and p.dim() < 2]
        optim_groups = [
            {'params': decay_params, 'weight_decay': weight_decay},
            {'params': nodecay_params, 'weight_decay': 0.0}
        ]
        self.optimizer = torch.optim.AdamW(optim_groups, lr=lr)
        self.criterion = nn.CrossEntropyLoss()

    def train(
        self,
        text_data: str,
        epochs: int = 20,
        batch_size: int = 8,
        block_size: int = 64,
        save_dir: str = "./checkpoints/fractal_holonet_base"
    ):
        dataset = TextDataset(text_data, self.tokenizer, block_size=block_size)
        dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
        
        print(f"\n🚀 Запуск обучения Fractal-HoloNet на корпусе текстов...")
        print(f"📊 Размер словаря: {self.model.config.vocab_size} | Символов: {len(text_data):,}")
        print(f"⚙️ Параметров модели: {sum(p.numel() for p in self.model.parameters() if p.requires_grad):,}")
        print("-" * 65)
        
        self.model.train()
        start_time = time.time()
        
        for epoch in range(epochs):
            total_loss = 0.0
            batches = 0
            
            for x, y in dataloader:
                x, y = x.to(self.device), y.to(self.device)
                self.optimizer.zero_grad()
                
                logits, _ = self.model(x, states=None, use_step=False)
                loss = self.criterion(logits.view(-1, logits.size(-1)), y.view(-1))
                loss.backward()
                
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                self.optimizer.step()
                
                total_loss += loss.item()
                batches += 1
                
            avg_loss = total_loss / max(1, batches)
            if (epoch + 1) % 4 == 0 or epoch == epochs - 1:
                print(f"  Эпоха [{epoch+1:02d}/{epochs:02d}] | Loss: {avg_loss:.4f} | Perplexity: {math.exp(min(avg_loss, 20)):.2f}")
                
        duration = time.time() - start_time
        print(f"✅ Обучение завершено за {duration:.2f} сек!")
        
        os.makedirs(save_dir, exist_ok=True)
        self.model.save_pretrained(save_dir)
        self.tokenizer.save(os.path.join(save_dir, "tokenizer.json"))
        print(f"💾 Обученный чекпоинт сохранен в: {save_dir}\n")


if __name__ == "__main__":
    corpus = """
Fractal-HoloNet is a novel AI architecture.
It uses holographic complex phase resonance.
The context complexity is linear O(N) and inference state memory is constant O(1).
Autonomous agents operate continuously without memory overflow.
""" * 40

    tokenizer = SimpleProductionTokenizer()
    config = FractalHoloNetConfig(vocab_size=300, d_model=128, n_layers=4, d_ff=384)
    model = ProductionFractalHoloNet(config)
    
    trainer = FractalHoloNetTrainer(model, tokenizer, lr=2e-3, device="cpu")
    trainer.train(corpus, epochs=20, batch_size=8, block_size=64)
    
    pipe = FractalHoloNetInferencePipeline("./checkpoints/fractal_holonet_base")
    res = pipe.generate("Fractal-HoloNet is a novel", max_new_tokens=45, temperature=0.5)
    print("--- 🌟 Тест генерации обученной модели ---")
    print(f"Промпт: '{res['prompt']}'")
    print(f"Результат: '{res['generated_text']}'")
    print(f"Полный текст: '{res['full_text']}'")
