FROM python:3.9.7-slim
RUN mkdir -p /defog/src
WORKDIR /defog/src
COPY requirements.txt /defog/src/
RUN pip install -r requirements.txt
COPY . /defog/src/
CMD ["taskset", "-a", "-c", "0,1", "python3", "Scheduler.py"]
