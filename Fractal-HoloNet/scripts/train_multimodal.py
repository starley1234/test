import os
import sys
from pathlib import Path

# Setup Python Path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

import math
import time
import torch
import torch.nn as nn
import matplotlib.pyplot as plt

from holonet.models.multimodal import MultimodalFractalHoloNet, MultimodalSignalConfig

def generate_synthetic_continuous_signals(num_samples=1000, seq_len=128, channels=1):
    t = torch.linspace(0, 8 * math.pi, seq_len)
    signals = []
    anomaly_labels = []
    
    for _ in range(num_samples):
        freq = 1.0 + 0.3 * torch.randn(1).item()
        phase = torch.rand(1).item() * 2 * math.pi
        
        base_wave = torch.sin(freq * t + phase)
        harmonic = 0.3 * torch.sin(2.5 * freq * t + phase)
        noise = 0.05 * torch.randn(seq_len)
        sig = base_wave + harmonic + noise
        
        anom = torch.zeros(seq_len)
        if torch.rand(1).item() > 0.5:
            start_anom = torch.randint(seq_len // 4, 3 * seq_len // 4, (1,)).item()
            dur = torch.randint(5, 15, (1,)).item()
            end_anom = min(seq_len, start_anom + dur)
            sig[start_anom:end_anom] += torch.randn(end_anom - start_anom) * 1.5
            anom[start_anom:end_anom] = 1.0
            
        signals.append(sig.unsqueeze(-1))
        anomaly_labels.append(anom.unsqueeze(-1))
        
    return torch.stack(signals), torch.stack(anomaly_labels)


def train_multimodal():
    print("=" * 70)
    print("  🌊 ОБУЧЕНИЕ МУЛЬТИМОДАЛЬНОЙ FRACTAL-HOLONET (НЕПРЕРЫВНЫЕ СИГНАЛЫ)")
    print("=" * 70)
    
    seq_len = 128
    channels = 1
    num_train = 800
    
    train_sig, train_anom = generate_synthetic_continuous_signals(num_train, seq_len, channels)
    val_sig, val_anom = generate_synthetic_continuous_signals(200, seq_len, channels)
    
    config = MultimodalSignalConfig(
        input_signal_dim=channels,
        output_signal_dim=channels,
        patch_size=1,
        d_model=128,
        n_layers=4,
        d_ff=384,
        use_learnable_fourier_filter=True,
        num_fourier_filters=32,
        vocab_size=0
    )
    
    model = MultimodalFractalHoloNet(config)
    print(f"📊 Конфигурация: d_model={config.d_model}, слоев={config.n_layers}, patch_size={config.patch_size}")
    print(f"⚙️ Параметров модели: {sum(p.numel() for p in model.parameters() if p.requires_grad):,}")
    
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-3, weight_decay=1e-4)
    mse_loss_fn = nn.MSELoss()
    bce_loss_fn = nn.BCELoss()
    
    batch_size = 32
    epochs = 10
    save_dir = "./checkpoints/fractal_holonet_multimodal"
    
    start_time = time.time()
    model.train()
    
    for epoch in range(epochs):
        permutation = torch.randperm(num_train)
        epoch_sig_loss = 0.0
        epoch_anom_loss = 0.0
        batches = 0
        
        for i in range(0, num_train, batch_size):
            indices = permutation[i:i + batch_size]
            batch_x = train_sig[indices]
            batch_anom = train_anom[indices]
            
            target_next = torch.roll(batch_x, -1, dims=1)
            target_next[:, -1, :] = target_next[:, -2, :]
            
            optimizer.zero_grad()
            pred_sig, anom_scores, _ = model.forward_continuous(batch_x)
            
            loss_forecasting = mse_loss_fn(pred_sig, target_next)
            loss_anomaly = bce_loss_fn(anom_scores, batch_anom)
            total_loss = loss_forecasting + 2.0 * loss_anomaly
            
            total_loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            
            epoch_sig_loss += loss_forecasting.item()
            epoch_anom_loss += loss_anomaly.item()
            batches += 1
            
        print(f"  Эпоха [{epoch+1:02d}/{epochs:02d}] | Forecast MSE: {epoch_sig_loss/batches:.5f} | Anomaly BCE: {epoch_anom_loss/batches:.5f}")
        
    duration = time.time() - start_time
    print(f"\n✅ Мультимодальное обучение завершено за {duration:.2f} сек!")
    
    os.makedirs(save_dir, exist_ok=True)
    model.save_pretrained(save_dir)
    print(f"💾 Мультимодальный чекпоинт сохранен в: {save_dir}")
    
    # Генерация графиков в assets/
    model.eval()
    with torch.no_grad():
        test_sig = val_sig[:1]
        history = test_sig[:, :64, :]
        ground_truth_future = test_sig[:, 64:, :]
        forecast = model.forecast_stream(history, forecast_steps=64)
        _, anom_scores, _ = model.forward_continuous(test_sig)
        
    plt.figure(figsize=(12, 6))
    plt.subplot(2, 1, 1)
    plt.plot(range(64), history[0, :, 0].numpy(), label="История (64 отсчета)", color="blue")
    plt.plot(range(64, 128), ground_truth_future[0, :, 0].numpy(), label="Истинный сигнал", color="gray", alpha=0.6)
    plt.plot(range(64, 128), forecast[0, :, 0].numpy(), label="O(1) Прогноз Fractal-HoloNet", color="green", linestyle="--")
    plt.title("Непрерывный авторегрессионный прогноз без токенизации")
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plt.subplot(2, 1, 2)
    plt.plot(range(128), test_sig[0, :, 0].numpy(), label="Входной сигнал", color="purple")
    plt.plot(range(128), anom_scores[0, :, 0].numpy(), label="Оценка аномальности", color="red")
    plt.title("Детекция аномалий в реальном времени")
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    os.makedirs("./assets", exist_ok=True)
    plot_path = "./assets/multimodal_signal_forecast.png"
    plt.tight_layout()
    plt.savefig(plot_path, dpi=150)
    plt.close()
    print(f"📈 График сохранен в {plot_path}")

if __name__ == "__main__":
    train_multimodal()
