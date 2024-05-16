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
from textual.widgets import Button, Header, Label, Log, Markdown, Select

root_dir = os.path.dirname(__file__)  # <-- absolute dir the script is in
config_rel_path = "config.yaml"
abs_config_file_path = os.path.join(root_dir, config_rel_path)
client = boto3.client('kms', region_name='us-east-2')

with open(abs_config_file_path, "r") as file:
    config = yaml.safe_load(file)
    LINES = list(config["dbs"].keys())


class SelectApp(App):
    CSS_PATH = "select.tcss"
    CMD = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(Select(((line, line) for line in LINES), prompt="Select database"), Button.success("Migrate", id="migrate", disabled=True))
        yield Markdown(id="db_config_markdown", markdown="")
        yield Label("#source Running connection test...", id="source", classes="invisible")
        yield Label("#target Running connection test...", id="target", classes="invisible")
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
            self.query_one(Button).disabled = False
            self.CMD = self.generate_pg_dump_and_restore_cmd(event)

    def clean_old_dumps(self, db):
        self.query_one(Log).clear()
        os.system(f"rm -rf {db['source']['db_database_name']}")

    def display_db_config(self, db):

        DB_CONFIG_MARKDOWN = f"""\
# Database Configuration
| key | source | target |
| --- | --- | --- |
| db_connection_host | {db["source"]["db_connection_host"]} | {db["target"]["db_connection_host"]} |
| db_database_name   | {db["source"]["db_database_name"]}   | {db["target"]["db_database_name"]}   |
| db_username | {db["source"]["db_username"]}               | {db["target"]["db_username"]}        |
| db_password | {db["source"]["db_password"] if "db_password" in db["source"].keys() else None }   | {db["target"]["db_password"] if "db_password" in db["target"].keys() else None} |
"""

        self.query_one(Markdown).update(DB_CONFIG_MARKDOWN)

    async def check_db_connection(self, event: Select.Changed) -> bool:
        db = config["dbs"][event.value]
        source_ok = await self.check_connection_for_db(db["source"], "#source")
        target_ok = await self.check_connection_for_db(db["target"], "#target")

        return source_ok and target_ok

    async def check_connection_for_db(self, db, label) -> bool:
        db_password = db["db_password"] if "db_password" in db.keys() and db["db_password"] else \
            await self.decrypt_password(db, label) if "db_password_encrypted" in db.keys() else None
        
        db["db_password"] = db_password

        if not db_password:
            return False
        
        self.query_one(label).set_class(False, 'invisible')
        self.query_one(label).update(f"{label} Running connection test...")

        try:
            await asyncpg.connect(
                timeout=5,
                database=db["db_database_name"],
                user=db["db_username"],
                password=db_password,
                host=db["db_connection_host"],
            )
            self.query_one(label).update(f"{label} {db["db_connection_host"]} connection successful.")
            return True
        except PostgresError as e:
            self.query_one(label).update(f"{label} {db["db_connection_host"]} connection failed: {e}")
            return False
        except TimeoutError as e:
            self.query_one(label).update(f"{label} {db["db_connection_host"]} connection timed out.")
            return False
        
    async def decrypt_password(self, db, label) -> str:
        self.query_one(label).update(f"{label} Decrypting db password...")
        self.query_one(label).set_class(False, 'invisible')

        try:
            response = await asyncio.to_thread(client.decrypt, CiphertextBlob=base64.b64decode(db["db_password_encrypted"]), KeyId=config["common"]["kms_key_id"])
            decrypted_password = response['Plaintext'].decode('utf-8')

            db["db_password"] = decrypted_password

            return decrypted_password
        except Exception as e:
            self.query_one(label).update(f'{label} Failed to decrypt password with kms key \'{config["common"]["kms_key_id"]}\': {e}')
            return None
        
    def generate_pg_dump_and_restore_cmd(self, event: Select.Changed)-> str:
        db = config["dbs"][event.value]
        pg_dump_cmd = f'PGPASSWORD="{db['source']['db_password']}" pg_dump -h {db['source']['db_connection_host']} -U {db['source']['db_username']} -d {db['source']['db_database_name']} --create --clean --encoding utf8 --format directory --jobs 16 -Z 0 -v --file={db['source']['db_database_name']}'
        drop_db_cmd = f'PGPASSWORD="{db['target']['db_password']}" psql -h {db['target']['db_connection_host']} -U {db['target']['db_username']} -c "DROP DATABASE IF EXISTS {db['target']['db_database_name']};"'
        pg_restore_cmd = f'PGPASSWORD="{db['target']['db_password']}" pg_restore -h {db['target']['db_connection_host']} -U {db['target']['db_username']} -d "{db['target']['db_database_name']}" -vv {root_dir}/{db['source']['db_database_name']}'

        cmd = " && /\n ".join([pg_dump_cmd, drop_db_cmd, pg_restore_cmd])
        self.query_one(Log).write_line("The following migration commands will be executed:\n" + cmd)
        print(cmd)
        return cmd
    
    @on(Button.Pressed)
    def migrate(self, event: Button.Pressed):
        if event.button.id == "migrate":
            event.button.disabled = True
            self.query_one(Select).disabled = True
            self.begin_capture_print(self, True, True)
            self.run_cmd(self.CMD)

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
