import math
from typing import Optional, Tuple, List, Dict, Any, Union
import json
import torch
import torch.nn as nn
import torch.nn.functional as F

from holonet.models.fractal_holonet import (
    ProductionRMSNorm,
    ComplexResonanceAssociativeCore,
    FractalHoloNetBlock,
    FractalHoloNetConfig
)

class MultimodalSignalConfig(FractalHoloNetConfig):
    """
    Configuration for Multimodal Continuous Signal Fractal-HoloNet.
    Supports both discrete tokens and raw continuous continuous streams (Audio, ECG, IoT, Video).
    """
    def __init__(
        self,
        input_signal_dim: int = 1,
        output_signal_dim: int = 1,
        patch_size: int = 1,
        use_learnable_fourier_filter: bool = True,
        num_fourier_filters: int = 32,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.input_signal_dim = input_signal_dim
        self.output_signal_dim = output_signal_dim
        self.patch_size = patch_size
        self.use_learnable_fourier_filter = use_learnable_fourier_filter
        self.num_fourier_filters = num_fourier_filters

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "input_signal_dim": self.input_signal_dim,
            "output_signal_dim": self.output_signal_dim,
            "patch_size": self.patch_size,
            "use_learnable_fourier_filter": self.use_learnable_fourier_filter,
            "num_fourier_filters": self.num_fourier_filters,
        })
        return d


class ContinuousSignalEncoder(nn.Module):
    """
    Direct Continuous Signal Phase Encoder.
    Maps continuous multi-channel waveforms directly to complex phase embedding space
    without discrete vector quantization.
    """
    def __init__(self, config: MultimodalSignalConfig):
        super().__init__()
        self.config = config
        self.patch_size = config.patch_size
        in_dim = config.input_signal_dim * config.patch_size
        
        self.proj = nn.Linear(in_dim, config.d_model, bias=False)
        
        if config.use_learnable_fourier_filter:
            self.filter_bank = nn.Conv1d(
                in_channels=config.input_signal_dim,
                out_channels=config.num_fourier_filters,
                kernel_size=7,
                padding=3,
                bias=False
            )
            self.filter_proj = nn.Linear(config.num_fourier_filters * config.patch_size, config.d_model, bias=False)
        else:
            self.filter_bank = None
            
        self.norm = ProductionRMSNorm(config.d_model)

    def forward(self, signal: torch.Tensor) -> torch.Tensor:
        """
        signal: (B, T_raw, channels) or (B, T_raw)
        Returns: (B, T_steps, d_model)
        """
        if signal.dim() == 2:
            signal = signal.unsqueeze(-1)
            
        B, T_raw, C = signal.shape
        
        if self.patch_size > 1:
            pad_len = (self.patch_size - (T_raw % self.patch_size)) % self.patch_size
            if pad_len > 0:
                signal = F.pad(signal, (0, 0, 0, pad_len))
            T_padded = signal.size(1)
            T_steps = T_padded // self.patch_size
            signal_patches = signal.view(B, T_steps, self.patch_size * C)
        else:
            signal_patches = signal
            T_steps = T_raw

        x_emb = self.proj(signal_patches)
        
        if self.filter_bank is not None:
            sig_perm = signal.permute(0, 2, 1)
            f_out = self.filter_bank(sig_perm)
            f_out = f_out.permute(0, 2, 1)
            
            if self.patch_size > 1:
                f_patches = f_out.view(B, T_steps, self.patch_size * self.config.num_fourier_filters)
            else:
                f_patches = f_out
            x_emb = x_emb + self.filter_proj(f_patches)
            
        return self.norm(x_emb)


class MultimodalFractalHoloNet(nn.Module):
    """
    Multimodal Continuous Signal Fractal-HoloNet.
    Accepts raw signals (Audio, ECG, IoT, Video frames) and discrete tokens interchangeably.
    """
    def __init__(self, config: MultimodalSignalConfig):
        super().__init__()
        self.config = config
        
        self.signal_encoder = ContinuousSignalEncoder(config)
        
        if config.vocab_size > 0:
            self.token_emb = nn.Embedding(config.vocab_size, config.d_model)
        else:
            self.token_emb = None
            
        self.blocks = nn.ModuleList([FractalHoloNetBlock(config) for _ in range(config.n_layers)])
        self.ln_f = ProductionRMSNorm(config.d_model)
        
        self.signal_head = nn.Linear(config.d_model, config.output_signal_dim * config.patch_size, bias=False)
        
        if config.vocab_size > 0:
            self.lm_head = nn.Linear(config.d_model, config.vocab_size, bias=False)
            
        self.anomaly_head = nn.Sequential(
            nn.Linear(config.d_model, config.d_model // 2),
            nn.SiLU(),
            nn.Linear(config.d_model // 2, 1)
        )

    def forward_continuous(
        self,
        signal: torch.Tensor,
        states: Optional[List[Tuple[torch.Tensor, torch.Tensor]]] = None,
        use_step: bool = False
    ) -> Tuple[torch.Tensor, torch.Tensor, List[Tuple[torch.Tensor, torch.Tensor]]]:
        x = self.signal_encoder(signal)
        next_states = []
        
        for i, block in enumerate(self.blocks):
            layer_state = states[i] if states is not None else None
            x, next_layer_state = block(x, state=layer_state, use_step=use_step)
            next_states.append(next_layer_state)
            
        x_norm = self.ln_f(x)
        pred_signal = self.signal_head(x_norm)
        anomaly_score = torch.sigmoid(self.anomaly_head(x_norm))
        return pred_signal, anomaly_score, next_states

    @torch.no_grad()
    def forecast_stream(
        self,
        signal_history: torch.Tensor,
        forecast_steps: int = 50
    ) -> torch.Tensor:
        self.eval()
        pred_signal, _, states = self.forward_continuous(signal_history, states=None, use_step=False)
        last_step_pred = pred_signal[:, -1:, :]
        
        forecasts = [last_step_pred]
        curr_signal = last_step_pred
        
        for _ in range(forecast_steps - 1):
            pred_step, _, states = self.forward_continuous(curr_signal, states=states, use_step=True)
            curr_signal = pred_step[:, -1:, :]
            forecasts.append(curr_signal)
            
        return torch.cat(forecasts, dim=1)

    def save_pretrained(self, save_directory: str):
        import os
        os.makedirs(save_directory, exist_ok=True)
        self.config.save(os.path.join(save_directory, "config.json"))
        torch.save(self.state_dict(), os.path.join(save_directory, "pytorch_model.pt"))

    @classmethod
    def from_pretrained(cls, save_directory: str, map_location: str = "cpu") -> "MultimodalFractalHoloNet":
        import os
        config = MultimodalSignalConfig.load(os.path.join(save_directory, "config.json"))
        model = cls(config)
        state_dict = torch.load(os.path.join(save_directory, "pytorch_model.pt"), map_location=map_location)
        model.load_state_dict(state_dict)
        return model
