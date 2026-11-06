FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 \n    STREAMLIT_SERVER_HEADLESS=true \n    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \n    PSX_PUBLIC_VIEW=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["sh", "-c", "exec streamlit run app.py --server.address=0.0.0.0 --server.port=${PORT:-8080} --server.headless=true --server.enableCORS=true --server.enableXsrfProtection=true"]
