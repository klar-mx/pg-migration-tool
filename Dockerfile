FROM python:3.12.3-slim-bookworm

ARG CONFIG_PATH=pg-migration-tool/config.example.yaml

ENV TERM=xterm-256color

ENV COLORTERM=truecolor

RUN apt-get update && apt-get -y upgrade

RUN apt-get install -y libpq-dev gcc xterm postgresql-client postgresql-client-common

RUN pip install pipenv

RUN useradd -m pgmigrator

USER pgmigrator

WORKDIR /app

COPY Pipfile ./

COPY Pipfile.lock ./

COPY pg-migration-tool/main.py ./pg-migration-tool/

COPY pg-migration-tool/select.tcss ./pg-migration-tool/

COPY $CONFIG_PATH ./pg-migration-tool/config.yaml

RUN pipenv install

ENTRYPOINT ["pipenv", "run", "python"]

CMD ["pg-migration-tool/main.py"]
