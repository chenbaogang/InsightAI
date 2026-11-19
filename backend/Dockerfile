FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

COPY requirements.txt ./
RUN pip install typing-extensions \
    && pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.1+cpu \
    && pip install -r requirements.txt \
    && pip install sentence-transformers

COPY app ./app
COPY scripts ./scripts

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=4 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/healthz',timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
