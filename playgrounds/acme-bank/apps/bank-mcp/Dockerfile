FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY *.py ./
# The tests ship in the image and run there with the app's own dependencies.
COPY tests ./tests
# The app runs as a user of its own, not as root
RUN useradd --system --uid 10001 --no-create-home app
USER app
CMD ["python", "server.py"]
