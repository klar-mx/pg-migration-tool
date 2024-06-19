FROM python:3.12-slim

RUN apt-get update && apt-get -y upgrade
RUN apt-get install -y libpq-dev gcc xterm wget postgresql-client postgresql-client-common time

# Don't run as root
RUN useradd -m pgmigrator && \
    # Set the working directory in the container
    mkdir -p /home/pgmigrator/pg-migration-tool && \
    chown pgmigrator:pgmigrator /home/pgmigrator/pg-migration-tool && \
    # Use wget instead of curl since curl is external package in alpine
    # https://python-poetry.org/docs/#installation
    wget -O get-poetry.py https://install.python-poetry.org && \
    POETRY_HOME=/home/pgmigrator/.poetry python3 get-poetry.py && \
    rm get-poetry.py

USER pgmigrator

# Add Poetry to PATH
ENV PATH="/home/pgmigrator/.poetry/bin:${PATH}"

# Install dependencies
COPY poetry.lock pyproject.toml README.md ./
RUN poetry install

WORKDIR /home/pgmigrator

COPY pg_migration_tool/__init__.py ./pg-migration-tool/
COPY pg_migration_tool/main.py ./pg-migration-tool/
COPY pg_migration_tool/select.tcss ./pg-migration-tool/

ARG CONFIG_PATH=pg_migration_tool/config.example.yaml
COPY $CONFIG_PATH ./pg-migration-tool/config.yaml

ENV TERM=xterm-256color
ENV COLORTERM=truecolor

ENTRYPOINT ["poetry", "run", "python"]

CMD ["pg-migration-tool/main.py"]
