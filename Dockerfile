FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ARG INSTALL_VOICE=false
COPY requirements-voice.txt .
RUN if [ "$INSTALL_VOICE" = "true" ]; then pip install --no-cache-dir -r requirements-voice.txt; fi
RUN useradd --uid 10001 --create-home lumia && mkdir -p /app/data && chown -R lumia:lumia /app
COPY --chown=lumia:lumia . .
USER lumia
EXPOSE 8080
CMD ["python", "launch.py"]
