FROM python:3.15-slim@sha256:533b0b2f9b5d46fd097091cf826f27902f1d6c3bca714b6dc74551356aa97a51
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
# pip leaves with the build: the app never runs it, and what it vendors (certifi, urllib3) would stay in the image unpatched
RUN pip install -r requirements.txt \
 && pip uninstall -y pip
COPY *.py openapi.json ./
# The tests ship in the image and run there with the app's own dependencies.
COPY tests ./tests
# The app runs as a user of its own, not as root
RUN useradd --system --uid 10001 --no-create-home app
USER app
CMD ["python", "server.py"]
