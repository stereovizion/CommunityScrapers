import json
import sys
from JavLibrary_server import scrape

if __name__ == "__main__":
    stdin_content = sys.stdin.read()
    stash_request = {}
    if stdin_content:
        try:
            stash_request = json.loads(stdin_content)
        except Exception:
            pass
    scrape(stash_request)
