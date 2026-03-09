import subprocess

SOURCE_HOST = "192.168.0.172"
DEST_HOST = "192.168.0.130"
DB_NAME = "seyo-development"

command = f"""
mongodump --host {SOURCE_HOST} --db {DB_NAME} --archive --gzip |
mongorestore --host {DEST_HOST} --db {DB_NAME} --archive --gzip --drop
"""

try:
    subprocess.run(command, shell=True, check=True)
    print("Database cloned successfully.")
except subprocess.CalledProcessError as e:
    print("Error while cloning database:", e)