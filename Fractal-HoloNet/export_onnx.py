import os
import torch
import onnx
import onnxruntime as ort
from fractal_holonet_prod import ProductionFractalHoloNet, FractalHoloNetConfig

class FractalHoloNetSequenceWrapper(torch.nn.Module):
    def __init__(self, model: ProductionFractalHoloNet):
        super().__init__()
        self.model = model

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        logits, _ = self.model(input_ids, states=None, use_step=False)
        return logits

def export_to_onnx(model_dir: str, output_onnx_path: str):
    os.makedirs(os.path.dirname(output_onnx_path) or ".", exist_ok=True)
    
    # Load model
    model = ProductionFractalHoloNet.from_pretrained(model_dir, map_location="cpu")
    model.eval()
    
    wrapper = FractalHoloNetSequenceWrapper(model)
    wrapper.eval()
    
    dummy_input = torch.randint(0, model.config.vocab_size, (1, 16), dtype=torch.long)
    
    print(f"[ONNX Export] Exporting model to: {output_onnx_path}...")
    torch.onnx.export(
        wrapper,
        dummy_input,
        output_onnx_path,
        export_params=True,
        opset_version=17,
        input_names=['input_ids'],
        output_names=['logits'],
        dynamo=False
    )
    print(f"[ONNX Export] Successfully exported model.")
    
    # Verify ONNX model
    onnx_model = onnx.load(output_onnx_path)
    onnx.checker.check_model(onnx_model)
    print("[ONNX Check] Model integrity verified.")
    
    # Test ONNX Runtime session
    session = ort.InferenceSession(output_onnx_path)
    ort_inputs = {session.get_inputs()[0].name: dummy_input.numpy()}
    ort_outputs = session.run(None, ort_inputs)
    print(f"[ONNX Runtime] Inference test successful! Logits shape: {ort_outputs[0].shape}")

if __name__ == "__main__":
    checkpoint_dir = "./checkpoints/fractal_holonet_base"
    config = FractalHoloNetConfig(vocab_size=300, d_model=128, n_layers=4, d_ff=384)
    m = ProductionFractalHoloNet(config)
    m.save_pretrained(checkpoint_dir)
    export_to_onnx(checkpoint_dir, "./exports/fractal_holonet.onnx")
