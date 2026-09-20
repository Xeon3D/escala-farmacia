FROM python:3.13-alpine

LABEL org.opencontainers.image.title="Escala da Farmácia" \
      org.opencontainers.image.description="Gestão de equipa, turnos, plantão e horas de uma farmácia (SQLite, sem dependências)." \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app
COPY server.py ./
COPY public/ ./public/
COPY CHANGELOG.md ./

# A base de dados vive num volume, fora da imagem.
ENV ESCALA_DB=/data/escala.db \
    ESCALA_HOST=0.0.0.0 \
    ESCALA_PORT=8765 \
    ESCALA_NO_BROWSER=1 \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=4).status==200 else 1)"

CMD ["python", "server.py"]
