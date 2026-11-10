# Imagem única, usada tanto pelo serviço "manager" (API/coordenador) quanto
# pelo serviço "worker" (processamento) — o papel é definido pelo comando
# executado em cada serviço do docker-compose.yml / stack do Swarm.
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 lspa \
    && mkdir -p /app/database /app/logs \
    && chown -R lspa:lspa /app
USER lspa

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:5000/api/status || exit 1

# Papel padrão: coordenador (manager). O serviço worker sobrescreve o comando.
CMD ["gunicorn", "app:create_app()", "--bind", "0.0.0.0:5000", "--workers", "2", "--access-logfile", "-"]
