# One image for Render (or any container host): builds the React app, then runs
# the FastAPI server, which serves both the API and the built app.

# --- web app -----------------------------------------------------------------
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Same origin as the API, so requests go to /api/... on whatever host serves it.
ENV VITE_API_BASE_URL=""
RUN npm run build

# --- API -------------------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FRONTEND_DIST=/app/web
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist ./web
RUN useradd --create-home app && chown -R app /app
USER app
EXPOSE 8000
# Bring the schema up to date, then serve. Render sets PORT.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
