"""
JAVLibrary Python Scraper Stash Plugin Entry Point.

Acts as a lightweight forwarding client when REMOTE_SERVER_ENABLED = True,
or runs the scraping engine in-process by loading javlib_server when REMOTE_SERVER_ENABLED = False.
"""
import configparser
import json
import os
import re
import sys
import threading
import urllib.request
import urllib.parse
from pathlib import Path

try:
    from py_common import log
except ModuleNotFoundError:
    class DummyLog:
        def info(self, msg): print(f" i  {msg}", file=sys.stderr)
        def debug(self, msg): print(f" d  {msg}", file=sys.stderr)
        def warning(self, msg): print(f" w  {msg}", file=sys.stderr)
        def error(self, msg): print(f" e  {msg}", file=sys.stderr)
    log = DummyLog()

try:
    from javlib_server import (
        run_scraper, cache_get, cache_save, cleanup_title,
        jav_search, jav_search_by_name
    )
    import javlib_server
except ImportError:
    javlib_server = None

scrape = {}

def clean_query(query):
    if javlib_server:
        return javlib_server.clean_query(query)
    return query

def cleanup_filename(filename):
    if filename is None:
        return filename
    log.info(f"Starting filename cleanup for: {filename}")
    if "@" in filename:
        filename = filename.split("@", 1)[1]
        log.info(f"Stripped @ prefix. New filename: {filename}")
    filename = os.path.splitext(filename)[0]
    parts = re.split(r'[-_ ]', filename)
    combomatch = re.match(r'^\d*([A-Za-z]+)(\d+)', parts[0])
    if combomatch:
        studio = combomatch.group(1)
        seq_nr = combomatch.group(2)
        remaining_parts = parts[1:]
    else:
        if len(parts) >= 2:
            studio = parts[0]
            seq_nr = parts[1]
            remaining_parts = parts[2:]
        else:
            return filename
    if studio == '' or seq_nr == '':
        return filename
    remaining_parts = [p for p in remaining_parts if p.lower() != '8k']
    stripped = seq_nr.lstrip('0')
    if len(stripped) >= 3:
        code = f"{studio.upper()}-{stripped}"
    else:
        code = f"{studio.upper()}-{seq_nr}"
    log.info(f"Resulting studio code: {code}")
    scrape['title'] = f"{code} {' '.join(remaining_parts)}".strip()
    log.info(f"Resulting title: {scrape['title']}")
    return code

log.debug(f"[DEBUG] Main Thread: {threading.get_ident()}")

# Handle --clear-cache flag early
CACHE_DIR = Path(__file__).parent / ".javlibrary_cache"
if "--clear-cache" in sys.argv:
    try:
        import shutil
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR)
        print("Cache cleared successfully.")
        sys.exit(0)
    except Exception as e:
        print(f"Failed to clear cache: {e}", file=sys.stderr)
        sys.exit(1)

def load_ini_config():
    """Load configuration from config.ini using standard library."""
    config_file = Path(__file__).parent / "config.ini"
    cfg = {
        "REMOTE_SERVER_ENABLED": False,
        "REMOTE_SERVER_URL": "http://127.0.0.1:8000"
    }
    if config_file.exists():
        try:
            content = config_file.read_text(encoding='utf-8')
            if not content.startswith("["):
                content = "[DEFAULT]\n" + content
            cp = configparser.ConfigParser()
            cp.read_string(content)
            sec = cp["DEFAULT"]
            if "remote_server_enabled" in sec:
                cfg["REMOTE_SERVER_ENABLED"] = sec.getboolean("remote_server_enabled")
            if "remote_server_url" in sec:
                cfg["REMOTE_SERVER_URL"] = sec.get("remote_server_url")
        except Exception as e:
            print(f"Warning: Failed to parse config.ini: {e}", file=sys.stderr)
    return cfg

cfg = load_ini_config()
REMOTE_SERVER_ENABLED = cfg["REMOTE_SERVER_ENABLED"]
REMOTE_SERVER_URL = cfg["REMOTE_SERVER_URL"]

# Read stdin content
stdin_content = sys.stdin.read() if not sys.stdin.isatty() else ""
stdin_data = {}
if stdin_content.strip():
    try:
        stdin_data = json.loads(stdin_content)
    except Exception:
        pass

if REMOTE_SERVER_ENABLED:
    # -------------------------------------------------------------
    # CLIENT FORWARDING MODE (Lightweight, zero extra dependencies)
    # -------------------------------------------------------------
    target_url = f"{REMOTE_SERVER_URL.rstrip('/')}/scrape"
    payload = {
        "argv": sys.argv,
        "input": stdin_data
    }
    try:
        req_data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            target_url,
            data=req_data,
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=300) as response:
            res_body = response.read().decode('utf-8')
            res_json = json.loads(res_body)
            if res_json.get("status") == "success":
                print(json.dumps(res_json.get("result", {})))
                sys.exit(0)
            else:
                print(f"Remote Server Error: {res_json.get('error')}", file=sys.stderr)
                sys.exit(1)
    except Exception as e:
        print(f"Error communicating with Remote Desktop Server at {target_url}: {e}", file=sys.stderr)
        sys.exit(1)
else:
    # -------------------------------------------------------------
    # LOCAL IN-PROCESS MODE (Lazy import of scraping engine)
    # -------------------------------------------------------------
    result = run_scraper(sys.argv, stdin_data)
    print(json.dumps(result))
    sys.exit(0)
