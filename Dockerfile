
#FROM python:3.9-alpine
FROM python:3.11-alpine

# #note https://github.com/docker-library/python/issues/318
# RUN apk add --no-cache --virtual .build-deps gcc musl-dev libffi-dev \
#      && pip install poetry==1.1.3 \
#      && apk del .build-deps gcc musl-dev


# #RUN apk add --no-cache --virtual .build-deps gcc musl-dev libffi-dev
# #RUN pip install poetry==1.1.3

# COPY poetry.lock pyproject.toml ./
# #RUN poetry config virtualenvs.create false --local && \
# #    poetry install

# RUN apk add --no-cache --virtual .build-deps gcc musl-dev \
#      && poetry config virtualenvs.create false --local && \
#      poetry install \
#      && apk del .build-deps gcc musl-dev

#RUN pip install paho-mqtt==1.6.1
RUN pip install paho-mqtt==2.1.0

COPY *.py *.json ./
CMD ["python", "-u", "dbus_mapper.py"]
