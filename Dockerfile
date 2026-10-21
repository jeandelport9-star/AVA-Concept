# Runs AVA on any container host (Railway, Fly.io, Koyeb, Azure, a VPS…).
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV AVA_NO_BROWSER=1 PORT=8780
EXPOSE 8780
CMD ["python", "run.py"]
