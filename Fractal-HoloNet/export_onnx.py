from scripts.export_onnx import export_to_onnx

if __name__ == "__main__":
    from holonet import FractalHoloNetConfig, ProductionFractalHoloNet
    checkpoint_dir = "./checkpoints/fractal_holonet_base"
    config = FractalHoloNetConfig(vocab_size=300, d_model=128, n_layers=4, d_ff=384)
    m = ProductionFractalHoloNet(config)
    m.save_pretrained(checkpoint_dir)
    export_to_onnx(checkpoint_dir, "./exports/fractal_holonet.onnx")
