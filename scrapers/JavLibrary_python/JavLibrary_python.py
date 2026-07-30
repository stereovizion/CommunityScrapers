import json
import sys
import requests
from pathlib import Path

# Add parent directory to sys.path so py_common is found
sys.path.append(str(Path(__file__).resolve().parent.parent))

try:
    from py_common import log
    from py_common.config import get_config
except ModuleNotFoundError:
    print("You need to download the folder 'py_common' from the community repo! (CommunityScrapers/tree/master/scrapers/py_common)", file=sys.stderr)
    sys.exit()

if __name__ == "__main__":
    config = get_config(
        default="""
# Return tags or not
RETURN_TAGS = False

# Remote Desktop Server configuration
REMOTE_SERVER_ENABLED = False
REMOTE_SERVER_URL = http://127.0.0.1:8000
"""
    )

    stdin_content = sys.stdin.read()
    stash_request = {}
    if stdin_content:
        try:
            stash_request = json.loads(stdin_content)
        except Exception:
            pass

    remote_enabled = getattr(config, "REMOTE_SERVER_ENABLED", False)
    if remote_enabled:
        remote_url = getattr(config, "REMOTE_SERVER_URL", "http://127.0.0.1:8000").rstrip("/")
        scrape_url = f"{remote_url}/scrape"
        log.info(f"Forwarding request to remote desktop server at {scrape_url}")
        payload = {
            "stash_request": stash_request,
            "args": sys.argv[1:]
        }
        try:
            res = requests.post(scrape_url, json=payload, timeout=300)
            if res.status_code == 200:
                print(res.text)
            else:
                log.error(f"Remote desktop server returned HTTP {res.status_code}: {res.text}")
                from JavLibrary_server import scrape
                scrape(stash_request)
        except Exception as e:
            log.error(f"Failed to communicate with remote desktop server at {scrape_url}: {e}")
            log.info("Falling back to local scraping execution...")
            from JavLibrary_server import scrape
            scrape(stash_request)
    else:
        from JavLibrary_server import scrape
        scrape(stash_request)

