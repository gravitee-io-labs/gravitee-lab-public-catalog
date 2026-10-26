FROM python:3.14-slim@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
# pip leaves with the build: the app never runs it, and what it vendors (certifi, urllib3) would stay in the image unpatched
RUN pip install -r requirements.txt \
 && pip uninstall -y pip
COPY *.py ./
# The page, its stylesheet, its script and the logos: nothing is loaded from outside.
COPY static ./static
# The tests ship in the image and run there with the app's own dependencies.
COPY tests ./tests
# The app runs as a user of its own, not as root
RUN useradd --system --uid 10001 --no-create-home app
USER app
CMD ["python", "server.py"]
