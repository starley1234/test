from setuptools import setup, find_packages

setup(
    name="fractal-holonet",
    version="2.2.0",
    description="Production Fractal-HoloNet: O(N) linear context, O(1) step inference, multimodal signals & knowledge distillation",
    author="AgentHaus Research Team",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.9",
    install_requires=[
        "torch>=2.0.0",
        "fastapi>=0.100.0",
        "uvicorn>=0.22.0",
        "pydantic>=2.0.0",
        "numpy>=1.24.0",
        "onnx>=1.14.0",
        "onnxruntime>=1.15.0",
        "matplotlib>=3.7.0"
    ],
)
