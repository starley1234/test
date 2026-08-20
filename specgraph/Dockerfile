FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY specgraph ./specgraph
RUN pip install --no-cache-dir -e .
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "specgraph.main:app", "--host", "0.0.0.0", "--port", "8000"]
