FROM python:3.12-slim

WORKDIR /app
ENV TZ=Asia/Seoul \
    PYTHONUNBUFFERED=1 \
    SUMPATH_DATA_DIR=/data

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py core.py sumpath_license.py admin.html ./

EXPOSE 8765
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8765"]
