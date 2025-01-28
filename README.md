# pg-migration-tool

Textual terminal app for automated postgres database automation using `pg_dump`, `pg_restore` and schema validation.

### How to run
```
docker run -v /mnt/data:/tmp --pull=always -it klar-mx/pg-migration-tool:latest
```
or 
```
poetry run python pg_migration_tool/main.py
```

![image](https://github.com/user-attachments/assets/487c1c7b-d178-4226-a7b5-5c0eaaa97a40)

