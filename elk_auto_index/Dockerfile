FROM python:3.11-slim

WORKDIR /usr/src/app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY elk_auto_index.py .

CMD ["python3", "elk_auto_index.py"]
