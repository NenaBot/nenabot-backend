FROM python:3.10-slim

WORKDIR /app

# System deps:
#  - libgomp1: numpy may need it
#  - libqt5serialport5: Dobot DLL links against Qt 5 Serial Port
#  - libqt5core5a, libqt5network5: transitive Qt deps for Dobot DLL
#  - libv4l-dev, v4l-utils: Video4Linux — lets OpenCV access USB cameras
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libqt5serialport5 \
    libqt5core5a \
    libqt5network5 \
    libv4l-dev \
    v4l-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persistent volume for SQLite DB and captured images
VOLUME /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
