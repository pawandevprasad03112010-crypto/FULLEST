FROM python:3.9-slim
WORKDIR /app
RUN apt-get update && apt-get install -y build-essential cmake libopencv-dev g++ && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN g++ -O3 main.cpp `pkg-config --cflags --libs opencv4` -o process_image || g++ -O3 main.cpp `pkg-config --cflags --libs opencv` -o process_image
EXPOSE 8000
CMD ["python", "run.py"]
