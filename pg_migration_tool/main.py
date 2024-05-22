import asyncio
import base64
import os
import subprocess
import threading

import boto3
import asyncpg
import yaml
from asyncpg.exceptions._base import PostgresError
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.events import Print
from textual.widgets import Button, Header, Log, Markdown, Select, Label, Input
from textual.widgets import Checkbox

root_dir = os.path.dirname(__file__)  # <-- absolute dir the script is in
config_rel_path = "config.yaml"
abs_config_file_path = os.getenv("PG_MIGRATION_TOOL_CONFIG", os.path.join(root_dir, config_rel_path))
client = boto3.client('kms', region_name='us-east-2')

with open(abs_config_file_path, "r") as file:
    config = yaml.safe_load(file)
    LINES = list(config["dbs"].keys())
    LINES.sort()


class SelectApp(App):
    CSS_PATH = "select.tcss"
    CMD = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(Select(((line, line) for line in LINES), prompt="Select database"), 
                         Button.success("Migrate", id="migrate", disabled=True),
                         Button.success("Validate", id="validate", disabled=True),
                         Label("--jobs"),
                         Input(placeholder="16"))
        yield Horizontal(
            Checkbox(id="no_owner", label="Discard owner information in dump and restore all objects to be owned by the target user", value=True),
            Checkbox(id="no_privileges", label="Discard privileges information in dump and don't try to restore it", value=True),
        )
        yield Markdown(id="db_config_markdown", markdown="")
        yield Log(auto_scroll=True)

    @on(Select.Changed)
    async def select_changed(self, event: Select.Changed) -> None:
        if event.value == "Select database": return
        self.title = str(event.value)
        self.clean_old_dumps(config["dbs"][event.value])
        
        self.display_db_config(config["dbs"][event.value])
        connections_ok = await self.check_db_connection(event)
        self.display_db_config(config["dbs"][event.value])

        if connections_ok:
            self.query_one("#migrate").disabled = False
            self.query_one("#validate").disabled = False
            self.CMD = self.generate_pg_dump_and_restore_cmd(event)

    def clean_old_dumps(self, db):
        self.query_one(Log).clear()
        dump_path = self.construct_path_to_dump(db)
        os.system(f"rm -rf {dump_path}")

    def display_db_config(self, db):

        DB_CONFIG_MARKDOWN = f"""\
# Database Configuration
| key | source | target |
| --- | --- | --- |
| db_connection_host | {db["source"]["db_connection_host"]} | {db["target"]["db_connection_host"]} |
| db_database_name   | {db["source"]["db_database_name"]}   | {db["target"]["db_database_name"]}   |
| db_username | {db["source"]["db_username"]}               | {db["target"]["db_username"]}        |
| db_password | {db["source"]["db_password"] if "db_password" in db["source"].keys() else None }   | {db["target"]["db_password"] if "db_password" in db["target"].keys() else None} |
| port | {db["source"].get("port", 5432)} | {db["target"].get("port", 5432)} |
"""

        self.query_one(Markdown).update(DB_CONFIG_MARKDOWN)

    async def check_db_connection(self, event: Select.Changed) -> bool:
        db = config["dbs"][event.value]
        source_ok = await self.check_connection_for_db(db["source"], "[source]")
        target_ok = await self.check_connection_for_db(db["target"], "[target]")

        return source_ok and target_ok

    async def check_connection_for_db(self, db, label) -> bool:
        self.query_one(Log).write_line(f"{label} Running DB connection test...")
        db_password = db["db_password"] if "db_password" in db.keys() and db["db_password"] else \
            await self.decrypt_password(db, label) if "db_password_encrypted" in db.keys() else None
        
        db["db_password"] = db_password

        try:
            await asyncpg.connect(
                timeout=5,
                database=db["db_database_name"],
                user=db["db_username"],
                password=db_password,
                host=db["db_connection_host"],
                port=db.get("port", 5432),
            )
            self.query_one(Log).write_line(f"{label} {db["db_connection_host"]} connection successful.")
            return True
        except PostgresError as e:
            self.query_one(Log).write_line(f"{label} {db["db_connection_host"]} connection failed: {e}")
            return False
        except TimeoutError as e:
            self.query_one(Log).write_line(f"{label} {db["db_connection_host"]} connection timed out.")
            return False
        
    async def decrypt_password(self, db, label) -> str:
        self.query_one(Log).write_line(f"{label} Decrypting db password...")

        try:
            response = await asyncio.to_thread(client.decrypt, CiphertextBlob=base64.b64decode(db["db_password_encrypted"]), KeyId=config["common"]["kms_key_id"])
            decrypted_password = response['Plaintext'].decode('utf-8')

            db["db_password"] = decrypted_password

            return decrypted_password
        except Exception as e:
            self.query_one(Log).write_line(f'{label} Failed to decrypt password with kms key \'{config["common"]["kms_key_id"]}\': {e}')
            return None

    def construct_path_to_dump(self, db) -> str:
        path = config["common"]["dumps_working_directory"]
        db_name = db["source"]["db_database_name"]
        return f"{path}/{db_name}"


    def construct_dump_command(self, db) -> str:
        dump_path = self.construct_path_to_dump(db)
        jobs = self.query_one(Input).value or 16

        environment = []

        if db['source']['db_password']:
            environment.append(f"PASSWORD='${db['source']['db_password']}'")

        command = "pg_dump"
        arguments = [
            f"-h {db['source']['db_connection_host']}",
            f"-p {db['source'].get('port', 5432)}",
            f"-U {db['source']['db_username']}",
            f"-d {db['source']['db_database_name']}",
            "-T '*awsdms*'",
            "--create",
            "--clean",
            "--encoding utf8",
            "--format directory",
            f"--jobs {jobs}",
            "-Z 0",
            "-v",
            f"--file={dump_path}"
        ]

        if self.query_one("#no_owner").value:
            arguments.append("--no-owner")

        if self.query_one("#no_privileges").value:
            arguments.append("--no-privileges")

        return " ".join(environment + [command] + arguments)


    def construct_restore_command(self, db) -> str:
        dump_path = self.construct_path_to_dump(db)

        environment = []

        if db['source']['db_password']:
            environment.append(f"PASSWORD='${db['source']['db_password']}'")

        command = "pg_restore"
        arguments = [
            f"-h {db['source']['db_connection_host']}",
            f"-p {db['source'].get('port', 5432)}",
            f"-U {db['source']['db_username']}",
            f"-d {db['source']['db_database_name']}",
            "--clean",
            "--if-exists",
            "--single-transaction",
            "--exit-on-error",
            "--format directory",
            "-vv",
        ]

        if self.query_one("#no_owner").value:
            arguments.append("--no-owner")

        if self.query_one("#no_privileges").value:
            arguments.append("--no-privileges")

        arguments.append(dump_path)

        return " ".join(environment + [command] + arguments)

    def generate_pg_dump_and_restore_cmd(self, event: Select.Changed)-> str:
        jobs = self.query_one(Input).value or 16
        db = config["dbs"][event.value]
        dump_path = self.construct_path_to_dump(db)
        pg_dump_cmd = self.construct_dump_command(db)
        pg_restore_cmd = self.construct_restore_command(db)
        finished_cmd = 'echo "THE MIGRATION HAS FINISHED!!! pg_restore exit code: $?"'

        cmd = " && /\n ".join([pg_dump_cmd, pg_restore_cmd])
        cmd += " ; " + finished_cmd
        self.query_one(Log).write_line("The following migration commands will be executed:\n" + cmd)

        print(cmd)
        return cmd
    
    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed):
        if event.button.id == "migrate":
            event.button.disabled = True
            self.query_one(Select).disabled = True
            self.begin_capture_print(self, True, True)
            self.run_cmd(self.CMD)
            self.query_one(Log).focus()
            self.query_one(Select).disabled = False
            event.button.disabled = False
        elif event.button.id == "validate":
            event.button.disabled = True
            asyncio.create_task(self.validate_migration())

    def run_cmd(self, cmd):
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def stream_output(process):
            for line in iter(process.stdout.readline, b''):
                line = line.decode('utf-8').rstrip()
                print(line)

        def stream_error(process):
            for line in iter(process.stderr.readline, b''):
                line = line.decode('utf-8').rstrip()
                print(line)

        thread_out = threading.Thread(target=stream_output, args=(process,))
        thread_err = threading.Thread(target=stream_error, args=(process,))
        thread_out.start()
        thread_err.start()

    async def validate_migration(self):
            self.query_one(Log).write_line("Starting validation...")

            db = config["dbs"][self.title]

            source_conn = await asyncpg.connect(
                database=db["source"]["db_database_name"],
                user=db["source"]["db_username"],
                password=db["source"]["db_password"],
                host=db["source"]["db_connection_host"],
                port=db.get('port', 5432),
            )

            target_conn = await asyncpg.connect(
                database=db["target"]["db_database_name"],
                user=db["target"]["db_username"],
                password=db["target"]["db_password"],
                host=db["target"]["db_connection_host"],
                port=db.get('port', 5432),
            )

            source_tables = await source_conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' AND schemaname NOT LIKE 'awsdms_%';")
            target_tables = await target_conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' AND schemaname NOT LIKE 'awsdms_%';")

            validation_results = "| Table | Source Rows | Target Rows | Match |\n"
            validation_results += "| --- | --- | --- | --- |\n"

            for table in source_tables:
                table_name = table["tablename"]
                source_count = await source_conn.fetchval(f"SELECT COUNT(*) FROM {table_name};")
                target_count = await target_conn.fetchval(f"SELECT COUNT(*) FROM {table_name};")

                match = "Yes" if source_count == target_count else "No"
                validation_results += f"| {table_name} | {source_count} | {target_count} | {match} |\n"

            self.query_one(Markdown).update(validation_results)

            await source_conn.close()
            await target_conn.close()


    @on(Print)
    def log_printed(self, event: Print):
        # time_str = datetime.datetime.now().strftime('%H:%M:%S')
        if not event.text:
            return

        self.query_one(Log).write_line(event.text)

        # Save event.text to file
        with open("log.log", "a") as file:
            file.write(event.text)


if __name__ == "__main__":
    app = SelectApp()
    app.run()
