# Alert relay (#53): Python standard library only, no package installed. No secret and no data file
# is copied in: the two tokens reach the container at run time from Secret Manager, by name.
# Same base image and digest as the backend image (backend/Dockerfile).
FROM python:3.13.16-slim-trixie@sha256:cf50a4f6ac4f026458b08d5222023d700ac806410dff5e9ca8728fa44f2b850f

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY relay.py /app/relay.py
USER 65534:65534
EXPOSE 8080
CMD ["python", "/app/relay.py"]
