FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY *.py ./
# The page, its stylesheet, its script and the logos: nothing is loaded from outside.
COPY static ./static
# The tests ship in the image and run there with the app's own dependencies.
COPY tests ./tests
# The app runs as a user of its own, not as root
RUN useradd --system --uid 10001 --no-create-home app
USER app
CMD ["python", "server.py"]
