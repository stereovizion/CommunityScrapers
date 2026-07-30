"""JAVLibrary python scraper"""
import base64
import json
import re
import socket
import subprocess
import sys
from pathlib import Path
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
import threading
import time
# import webbrowser
from urllib.parse import urlparse

from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

import undetected_chromedriver as uc

try:
    from py_common import log
    from py_common.config import get_config
except ModuleNotFoundError:
    print("You need to download the folder 'py_common' from the community repo! (CommunityScrapers/tree/master/scrapers/py_common)", file=sys.stderr)
    sys.exit()

try:
    import lxml.html
except ModuleNotFoundError:
    print("You need to install the lxml module. (https://lxml.de/installation.html#installation)",
     file=sys.stderr)
    print("If you have pip (normally installed with python), run this command in a terminal (cmd): pip install lxml",
     file=sys.stderr)
    sys.exit()

try:
    import requests
except ModuleNotFoundError:
    print("You need to install the requests module. (https://docs.python-requests.org/en/latest/user/install/)",
     file=sys.stderr)
    print("If you have pip (normally installed with python), run this command in a terminal (cmd): pip install requests",
     file=sys.stderr)
    sys.exit()

try:
    import selenium
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ModuleNotFoundError:
    SELENIUM_AVAILABLE = False
    log.debug("Selenium not available. Install it for interactive captcha solving: pip install selenium")


# GLOBAL VAR ######
JAV_DOMAIN = "Check"
###################

COOKIES_FILE = "javlib_cookies.json"

import os
import json
from pathlib import Path

# Add this near the top with other globals
COOKIES_FILE = "javlib_cookies.json"

def clean_query(query):
    if not query:
        return query
    # Strip everything before and including the @ sign
    if "@" in query:
        query = query.split("@", 1)[1]
    
    # Strip file extension if present
    query = os.path.splitext(query)[0]
    
    # Extract studio code
    parts = re.split(r'[-_ ]', query)
    if not parts or parts[0] == '':
        return query
    
    # Check if first part contains both letters and numbers (with optional leading digits)
    combomatch = re.match(r'^\d*([A-Za-z]+)(\d+)', parts[0])
    if combomatch:
        studio = combomatch.group(1)
        seq_nr = combomatch.group(2)
    else:
        if len(parts) >= 2:
            studio = parts[0]
            seq_nr = parts[1]
        else:
            return query
            
    # Validate studio and seq_nr are alphanumeric
    if re.match(r'^[A-Za-z]+$', studio) and re.match(r'^\d+$', seq_nr):
        stripped = seq_nr.lstrip('0')
        if len(stripped) >= 3:
            return f"{studio.upper()}-{stripped}"
        else:
            return f"{studio.upper()}-{seq_nr}"
    return query

def get_query_prefix(fragment):
    val = fragment.get("name") or fragment.get("title") or fragment.get("url")
    if not val:
        return "query"
    if not str(val).startswith("http"):
        # Extract clean studio code if possible
        val = clean_query(str(val))
    else:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(str(val))
            path = parsed.path.strip("/")
            if path:
                parts = path.split("/")
                val = parts[-1]
        except Exception:
            pass
    # Clean the value to make it safe for filenames
    import re
    cleaned = re.sub(r'[^a-zA-Z0-9\-_]', '_', str(val))
    return cleaned[:50]

def cache_get(filename):
    try:
        cache_file = CACHE_DIR / filename
        if cache_file.exists():
            return cache_file.read_text(encoding='utf-8')
    except Exception as e:
        log.warning(f"Failed to read cache: {e}")
    return None

def cache_save(filename, content):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = CACHE_DIR / filename
        temp_file = cache_file.with_suffix(".tmp")
        temp_file.write_text(content, encoding='utf-8')
        temp_file.replace(cache_file)
    except Exception as e:
        log.warning(f"Failed to write cache: {e}")

def is_cacheable(result):
    if not result:
        return False
    if isinstance(result, list) and len(result) == 1:
        title = result[0].get("title", "")
        if "Protected by Cloudflare" in title or "failed to get the page" in title or "doesn't return any result" in title:
            return False
    return True

def print_and_cache(result, filename):
    output = json.dumps(result)
    print(output)
    if is_cacheable(result):
        cache_save(filename, output)

def load_cookies_from_file():
    """Load cookies from persistent storage"""
    try:
        if os.path.exists(COOKIES_FILE):
            with open(COOKIES_FILE, 'r') as f:
                cookies = json.load(f)
                log.info(f"Loaded {len(cookies)} cookies from {COOKIES_FILE} cookies:{cookies}")
                return cookies
    except Exception as e:
        log.warning(f"Failed to load cookies from file: {e}")
    return {}

def save_cookies_to_file(cookies):
    """Save cookies to persistent storage"""
    try:
        with open(COOKIES_FILE, 'w') as f:
            json.dump(cookies, f, indent=2)
            log.info(f"Saved {len(cookies)} cookies to {COOKIES_FILE}")
    except Exception as e:
        log.error(f"Failed to save cookies to file: {e}")

def add_cookies_to_driver(driver, cookies):
    """Add cookies to the driver before navigating"""
    try:
        # First navigate to the domain so cookies can be set
        # domain = urlparse(driver.current_url).netloc or "javlibrary.com"
        domain = "javlibrary.com"
        log.info(f"Adding {len(cookies)} cookies to {domain}")
        driver.get(f"https://{domain}")

        # Add each cookie
        for cookie_name, cookie_value in cookies.items():
            try:
                driver.add_cookie({
                    'name': cookie_name,
                    'value': cookie_value,
                    'domain': domain
                })
                log.debug(f"Added cookie: {cookie_name}")
            except Exception as e:
                log.debug(f"Could not add cookie {cookie_name}: {e}")
                # Some cookies might fail due to domain restrictions
    except Exception as e:
        log.warning(f"Error adding cookies to driver: {e}")

JAV_SEARCH_HTML = None
JAV_MAIN_HTML = None
PROTECTION_CLOUDFLARE = False

# scraped output to be sent back to stash
scrape = {}

# Flaresolverr
FLARESOLVERR_ENABLED = False
FLARESOLVERR_URL = "http://localhost:8191/v1"
FLARESOLVERR_TIMEOUT_MAX = 60000

# Interactive Captcha Solving
INTERACTIVE_CAPTCHA = True  # Set to False to disable interactive captcha solving
CAPTCHA_TIMEOUT = 300  # 5 minutes to solve captcha
PERSISTENT_BROWSER = True  # Keep Chrome open across scraper runs
REMOTE_DEBUGGING_PORT = 9222  # Port to communicate with Chrome

JAV_HEADERS = {
    "User-Agent":
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    "Referer": "http://www.javlibrary.com/"
}
config = get_config(
    default="""
# Return tags or not
RETURN_TAGS = False
"""
)

RETURN_TAGS = config.RETURN_TAGS

# We can't add movie image atm in the same time as Scene
STASH_SUPPORTED = False
# Stash doesn't support Labels yet
STASH_SUPPORT_LABELS = False
# ...and name order too...
STASH_SUPPORT_NAME_ORDER = False
# Tags you don't want to scrape
IGNORE_TAGS = [
    "Features Actress", "Hi-Def", "Beautiful Girl", "Blu-ray",
    "Featured Actress", "VR Exclusive", "MOODYZ SALE 4"
]
# Select preferable name order
NAME_ORDER_JAPANESE = False
# Some performers don't need to be reversed
IGNORE_PERF_REVERSE = ["Lily Heart"]

# Keep the legacy field scheme:
# Actual Code -> Title, actual Title -> Details, actual Details -> /dev/null
LEGACY_FIELDS = True
# Studio Code now in a separate field, so it may (or may not) be stripped from title
# Makes sense only if not LEGACY_FIELDS
KEEP_CODE_IN_TITLE = True

# Tags you want to be added in every scrape
FIXED_TAGS = ""
# Split tags if they contain [,·] ('Best, Omnibus' -> 'Best','Omnibus')
SPLIT_TAGS = False

# Don't fetch the Aliases (Japanese Name)
IGNORE_ALIASES = False
# Always wait for the aliases to load. (Depends on network response)
WAIT_FOR_ALIASES = False
# All javlib sites
SITE_JAVLIB = ["javlibrary"]



REPLACE_TITLE = {
    "FHD_6M-": "",
    "[FHD6m]": "",
    "-uncensored": "",
    "-Uncensored": "",
    "uncensored": "",
    "Uncensored": "",
    "-uncensore": "",
    "-Uncensore": "",
    "_uncen": "",
    "_Uncen": "",
    "hd.": ".",
    "HD.": ".",
    "a.hd": "",
    "b.hd": "",
    "c.hd": "",
    "d.hd": "",
    "A.HD": "",
    "B.HD": "",
    "C.HD": "",
    "D.HD": "",
    "a.H": "",
    "b.H": "",
    "c.H": "",
    "d.H": "",
    "A.H": "",
    "B.H": "",
    "C.H": "",
    "D.H": "",
    ".hd": "",
    ".HD": "",
    "-hd": "",
    "-HD": "",
    "_hd": "",
    "_HD": "",
    "1080p": "",
    "1080P": "",
    "-4k": "",
    "-4K": "",
    ".4k": "",
    ".4K": "",
    "a.avi": ".avi",
    "b.avi": ".avi",
    "c.avi": ".avi",
    "d.avi": ".avi",
    "a.mp4": ".mp4",
    "b.mp4": ".mp4",
    "c.mp4": ".mp4",
    "d.mp4": ".mp4",
    "a.wmv": ".wmv",
    "b.wmv": ".wmv",
    "c.wmv": ".wmv",
    "d.wmv": ".wmv",  
    "A.avi": ".avi",
    "B.mp4": ".avi",
    "C.mp4": ".avi",
    "D.avi": ".avi",
    "A.mp4": ".mp4",
    "B.mp4": ".mp4",
    "C.mp4": ".mp4",
    "D.mp4": ".mp4",
    "A.wmv": ".wmv",
    "B.wmv": ".wmv",
    "C.wmv": ".wmv",
    "D.wmv": ".wmv",
    "A.AVI": ".AVI",
    "B.AVI": ".AVI",
    "C.AVI": ".AVI",
    "D.AVI": ".AVI",
    "A.MP4": ".MP4",
    "B.MP4": ".MP4",
    "C.MP4": ".MP4",
    "D.MP4": ".MP4",
    "A.WMV": ".WMV",
    "B.WMV": ".WMV",
    "C.WMV": ".WMV",
    "D.WMV": ".WMV",  
    "A.AVI": ".AVI",
    "B.MP4": ".AVI",
    "C.MP4": ".AVI",
    "D.AVI": ".AVI",
    "A.MP4": ".MP4",
    "B.MP4": ".MP4",
    "C.MP4": ".MP4",
    "D.MP4": ".MP4",
    "A.WMV": ".WMV",
    "B.WMV": ".WMV",
    "C.WMV": ".WMV",
    "D.WMV": ".WMV",
    ".3g2": "",
    ".3gp": "",
    ".amv": "",
    ".asf": "",
    ".avi": "",
    ".f4a": "",
    ".f4b": "",
    ".f4p": "",
    ".f4v": "",
    ".flv": "",
    ".flv": "",
    ".gifv": "",
    ".m4p": "",
    ".m4v": "",
    ".m4v": "",
    ".mkv": "",
    ".mng": "",
    ".mod": "",
    ".mov": "",
    ".mp2": "",
    ".mp4": "",
    ".mpe": "",
    ".mpeg": "",
    ".mpg": "",
    ".mpv": "",
    ".mxf": "",
    ".nsv": "",
    ".ogg": "",
    ".ogv": "",
    ".qt": "",
    ".rm": "",
    ".roq": "",
    ".rrc": "",
    ".svi": "",
    ".ts": "",
    ".vob": "",
    ".webm": "",
    ".wmv": "",
    ".yuv": "", 
    ".3G2": "",
    ".3GP": "",
    ".AMV": "",
    ".ASF": "",
    ".AVI": "",
    ".F4A": "",
    ".F4B": "",
    ".F4P": "",
    ".F4V": "",
    ".FLV": "",
    ".FLV": "",
    ".GIFV": "",
    ".M4P": "",
    ".M4V": "",
    ".M4V": "",
    ".MKV": "",
    ".MNG": "",
    ".MOD": "",
    ".MOV": "",
    ".MP2": "",
    ".MP4": "",
    ".MPE": "",
    ".MPEG": "",
    ".MPG": "",
    ".MPV": "",
    ".MXF": "",
    ".NSV": "",
    ".OGG": "",
    ".OGV": "",
    ".QT": "",
    ".RM": "",
    ".ROQ": "",
    ".RRC": "",
    ".SVI": "",
    ".TS": "",
    ".VOB": "",
    ".WEBM": "",
    ".WMV": "",
    ".YUV": ""
}

OBFUSCATED_TAGS = {
    "Girl": "Young Girl", # ロリ系 in Japanese
    "Tits": "Small Tits" # 微乳 in Japanese
}


class ResponseHTML:
    content = ""
    html = ""
    status_code = 0
    url = ""

def get_chrome_version():
    try:
        result = subprocess.run(['google-chrome', '--version'], capture_output=True, text=True)
        version = result.stdout.strip().split()[-1]
        return version
    except Exception as e:
        log.warning(f"Failed to get Chrome version: {e}")
        return None

def is_port_open(port):
    """Check if a local port is open."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False

def interactive_captcha_solve(url):
    """
    Opens a browser for interactive captcha solving.

    Args:
        url: The URL that requires captcha solving

    Returns:
        dict: cookies, content, and url after solving, or None if timeout/error
    """
    if not INTERACTIVE_CAPTCHA or not SELENIUM_AVAILABLE:
        return None

    driver = None
    try:
        log.info(f"Opening browser for interactive captcha solving at: {url}")


        try:
            chrome_version = get_chrome_version()
            log.debug(f"Chrome version: {chrome_version}")
            
            main_version = None
            if chrome_version:
                try:
                    main_version = int(chrome_version.split('.')[0])
                    log.debug(f"Extracted Chrome major version: {main_version}")
                except Exception as ver_err:
                    log.warning(f"Failed to parse Chrome major version: {ver_err}")

            options = uc.ChromeOptions()
            
            if PERSISTENT_BROWSER:
                if not is_port_open(REMOTE_DEBUGGING_PORT):
                    log.info(f"Port {REMOTE_DEBUGGING_PORT} is closed. Launching detached Chrome process...")
                    try:
                        subprocess.Popen([
                            "google-chrome",
                            f"--remote-debugging-port={REMOTE_DEBUGGING_PORT}",
                            "--user-data-dir=/tmp/javlib_chrome_profile",
                            "--no-first-run",
                            "--no-default-browser-check"
                        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                        
                        # Wait for the port to open
                        for _ in range(10):
                            if is_port_open(REMOTE_DEBUGGING_PORT):
                                log.debug("Chrome detached process started and port is open.")
                                break
                            time.sleep(0.5)
                        else:
                            log.warning("Timeout waiting for detached Chrome port to open.")
                    except Exception as spawn_err:
                        log.warning(f"Failed to spawn detached Chrome process: {spawn_err}")
                
                options = webdriver.ChromeOptions()
                options.debugger_address = f"127.0.0.1:{REMOTE_DEBUGGING_PORT}"
                try:
                    patcher = uc.Patcher(version_main=main_version)
                    patcher.auto()
                    patched_driver_path = patcher.executable_path
                    service = Service(executable_path=patched_driver_path)
                    driver = webdriver.Chrome(service=service, options=options)
                except Exception as attach_err:
                    log.warning(f"Failed to attach to persistent Chrome: {attach_err}")
                    log.info("Falling back to non-persistent ChromeDriver launch...")
                    options = uc.ChromeOptions()
                    if main_version:
                        driver = uc.Chrome(options=options, version_main=main_version, user_data_dir="/tmp/javlib_chrome_profile")
                    else:
                        driver = uc.Chrome(options=options, user_data_dir="/tmp/javlib_chrome_profile")
            else:
                try:
                    if main_version:
                        driver = uc.Chrome(options=options, version_main=main_version, user_data_dir="/tmp/javlib_chrome_profile")
                    else:
                        driver = uc.Chrome(options=options, user_data_dir="/tmp/javlib_chrome_profile")
                except Exception as native_err:
                    log.warning(f"Failed to launch ChromeDriver natively: {native_err}")
                    log.info("Attempting fallback with webdriver_manager Service...")
                    if chrome_version:
                        service = Service(ChromeDriverManager(driver_version=chrome_version).install())
                    else:
                        service = Service(ChromeDriverManager().install())
                    driver = uc.Chrome(service=service, options=options, user_data_dir="/tmp/javlib_chrome_profile")
        except Exception as e:
            log.warning(f"Failed to launch ChromeDriver: {e}")
            return None

        # Load and add persistent cookies before navigating
        persistent_cookies = load_cookies_from_file()
        if persistent_cookies:
            log.info("Adding persistent cookies from previous runs...")
            add_cookies_to_driver(driver, persistent_cookies)

        # Create a Chrome WebDriver
        # options = webdriver.ChromeOptions()
        # driver = webdriver.Chrome('/home/matthias/programs/chromedriver-linux64/chromedriver')
        driver.get(url)

        log.info("Browser window opened. Please solve the captcha manually.")
        log.info(f"Waiting for {CAPTCHA_TIMEOUT} seconds for captcha to be solved...")

        # Wait for the page to change (captcha solved)
        # Check if we're no longer on a captcha/challenge page
        try:
            WebDriverWait(driver, CAPTCHA_TIMEOUT).until(
                lambda d: is_cloudflare_challenge_solved(d)
            )
            log.info("Captcha solved! Extracting cookies...")
        except Exception as e:
            log.warning(f"Timeout waiting for captcha solution: {e}")
            if not PERSISTENT_BROWSER:
                try:
                    driver.quit()
                except:
                    pass
            return None

        # Wait a bit for page to fully load after captcha solve
        time.sleep(2)

        # Extract cookies after solving
        cookies_list = driver.get_cookies()
        cookies_dict = {cookie['name']: cookie['value'] for cookie in cookies_list}

        # Save cookies for next run
        save_cookies_to_file(cookies_dict)

        # Get the current page content
        page_content = driver.page_source
        current_url = driver.current_url

        log.info(f"Successfully solved captcha. Current URL: {current_url}")
        if not PERSISTENT_BROWSER:
            try:
                driver.quit()
            except:
                pass
            driver = None

        return {
            'cookies': cookies_dict,
            'content': page_content,
            'url': current_url
        }

    except Exception as e:
        log.error(f"Error during interactive captcha solving: {e}")
        return None
    finally:
        if driver and not PERSISTENT_BROWSER:
            try:
                driver.quit()
            except:
                pass


def is_cloudflare_challenge_solved(driver):
    """
    Check if Cloudflare challenge has been solved.
    Returns True if challenge is gone, False otherwise.
    """
    try:
        # # Method 1: Check for Cloudflare challenge container
        # try:
        #     # Look for the challenge iframe or container
        #     challenge_elements = driver.find_elements(By.ID, "challenge-form")
        #     if challenge_elements:
        #         log.debug("Challenge form still present")
        #         return False
        # except:
        #     pass
        #
        # # Method 2: Check for the Cloudflare "checking browser" message
        # try:
        #     checking = driver.find_elements(By.XPATH, "//*[contains(text(), 'Checking your browser')]")
        #     if checking:
        #         log.debug("Browser check still in progress")
        #         return False
        # except:
        #     pass

        # Method 3: Check for cf_clearance cookie (set after successful challenge)
        try:
            cookies = driver.get_cookies()
            cookie_names = [c['name'] for c in cookies]
            if 'cf_clearance' in cookie_names:
                log.debug("cf_clearance cookie found - challenge solved!")
                return True
        except:
            pass

        # # Method 4: Check page title/URL changed
        # try:
        #     # If we're past the challenge, we shouldn't be on a /challenge page
        #     if '/challenge' not in driver.current_url.lower():
        #         log.debug(f"URL changed to: {driver.current_url}")
        #         return True
        # except:
        #     pass
        #
        # # Method 5: Check for common Cloudflare challenge HTML elements
        # try:
        #     # These elements are present during challenge
        #     challenge_indicators = [
        #         "cf-challenge",
        #         "cf-chl-banner",
        #         "challenge-error-text"
        #     ]
        #     page_source = driver.page_source.lower()
        #     has_challenge = any(indicator in page_source for indicator in challenge_indicators)
        #
        #     if not has_challenge:
        #         log.debug("No challenge indicators found in page source")
        #         return True
        # except:
        #     pass
        #
        # return False

    except Exception as e:
        log.debug(f"Error checking challenge status: {e}")
        return False

def bypass_protection(url, retries=4):
    url_domain = re.sub(r"www\.|\.com", "", urlparse(url).netloc)
    log.debug("=== Checking Status of Javlib site ===")
    response_html = ResponseHTML
    site = "javlibrary"
    url_n = url.replace(url_domain, site)
    cookies = {'over18': '18'}
    try:
        if FLARESOLVERR_ENABLED:             
            url = FLARESOLVERR_URL
            headers = {"Content-Type": "application/json"}
            data = {
                "cmd": "request.get",
                "url": url_n,
                "session": "2",
                "session_ttl_minutes": 120,
                "maxTimeout": FLARESOLVERR_TIMEOUT_MAX,
                "set-cookie": "over18=18",
            }

            log.info(f"Using FlareSolverr: {FLARESOLVERR_URL}")
            log.info(f"Javlibrary input url: {url_n}")
            cookies = {'over18': '18'}
            responseJson = requests.post(FLARESOLVERR_URL, cookies=cookies, headers=headers, json=data)
            json_input = responseJson.json()

            response_html.content = json_input['solution']['response']
            response_html.html = json_input['solution']['response']
            response_html.status_code = json_input['solution']['status']
            response_html.url = json_input['solution']['url']

            #log.info(f"Flaresolverr response html: {response_html}")
        else:
            # Try regular request first
            response = requests.get(url_n, cookies=cookies, headers=JAV_HEADERS, timeout=10)

            # Check if we got a captcha challenge
            if response.status_code in (403, 503) or "captcha" in response.text.lower() or "challenge" in response.text.lower():
                log.warning(f"Captcha/Challenge detected. Attempting interactive solve...")
                captcha_result = interactive_captcha_solve(url_n)

                if captcha_result:
                    response_html.content = captcha_result['content'].encode('utf-8')
                    response_html.html = captcha_result['content']
                    response_html.status_code = 200
                    response_html.url = captcha_result['url']
                else:
                    log.error("Interactive captcha solving failed or timed out")
                    return None, None
            else:
                response_html.content = response.content
                response_html.html = response.text
                response_html.status_code = response.status_code
                response_html.url = response.url
                return site, response_html

    except Exception as exc_req:
        log.warning(f"Exception error {exc_req} while checking protection for {site}")
        if retries == 4:
            retries = retries -1
            log.warning(f"Retrying once normally after 7s delay [retries left: {retries}] for site: {site}")
            time.sleep(7.2)
            return bypass_protection(url_n, retries)
        else:
            return None, None
    if response_html.url == "https://www.javlib.com/maintenance.html":
        log.error(f"[{site}] Maintenance")
    elif response_html.url == "https://www.javlibrary.com/maintenance.html":
        log.error(f"[{site}] Maintenance")
    elif response_html.status_code != 200:   
        log.error(f"[{site}] Other issue ({response_html.status_code})")
    else:
        log.info(
                f"[{site}] Using this site for scraping | status code: ({response_html.status_code})"
            )
        log.debug("======================================")
        return site, response_html
    log.debug("======================================")
    return None, None


def send_request(url, head, retries=0, delay=2.5):
    log.info(f"Sending request to {url}, delay {delay} seconds")
    if retries > 3:
        log.warning(f"Scrape for {url} failed after retrying {retries} times")
        return None

    global JAV_DOMAIN

    if delay != 0:
        log.info(f"Delaying request by {delay} seconds to prevent Cloudflare rate limiting")
        time.sleep(delay)
    url_domain = re.sub(r"www\.|\.com", "", urlparse(url).netloc)
    response = None
    if url_domain in SITE_JAVLIB:
        # Javlib
        if JAV_DOMAIN == "Check":
            JAV_DOMAIN, response = bypass_protection(url)
            if response:
                return response
        if JAV_DOMAIN is None:
            return None
        url = url.replace(url_domain, JAV_DOMAIN)
    log.debug(f"[{threading.get_ident()}] Request URL: {url}")
    try:
        response = requests.get(url, headers=head, timeout=10)
    except requests.exceptions.Timeout as exc_timeout:
        log.warning(f"Timed out {exc_timeout}")
        return send_request(url, head, retries+1)
    except Exception as exc_req:
        log.error(f"scrape error exception {exc_req}")
        if delay != 0:
            error_delay = delay+2.75
            log.info(f"Delaying request by {error_delay} seconds and retrying")
            time.sleep(error_delay)
        return send_request(url, head, retries+1)
    if response.status_code != 200:
        log.debug(f"[Request] Error, Status Code: {response.status_code}")
        response = None
    return response



def cleanup_title(title):
    if title == None:
        return title

    log.info(f"Starting title cleanup for: {title}")
    cleaned_title = False
    for key, value in REPLACE_TITLE.items():
        if key in title:
            title = title.replace(key, value)
            cleaned_title = True
    
    if cleaned_title:
        title = title.strip()
        log.info(f"Found match and using new clean title: {title}")
    return title

# cleanup filename by retaining the studio code for the video.
# A studio code consists of some letters (e.g 3-4 letters) followed by a sequence number (e.g 3 digits),
# and is at the beginning of the filename. The rest of the filename is removed.
# Sometimes the letters may be concatenated with the numbers:
# e.g. from ajvr00244-3-02.mp4 to AJVR-244
# Sometimes the letters and sequence number are separated by a - or _ character:
# e.g. from VRKM-1719_C-3.mp4 to VRKM-1719
def cleanup_filename(filename):
    if filename == None:
        return filename
    log.info(f"Starting filename cleanup for: {filename}")
    # Strip everything before and including the @ sign
    if "@" in filename:
        filename = filename.split("@", 1)[1]
        log.info(f"Stripped @ prefix. New filename: {filename}")
    studio = ''
    seq_nr = ''
    remaining_parts = []
    # split filename
    filename = os.path.splitext(filename)[0]
    # split filename by - , _ or space character
    parts = re.split(r'[-_ ]', filename)
    # check if first part contains both studio prefix and sequence number and extract them
    combomatch = re.match(r'^\d*([A-Za-z]+)(\d+)', parts[0])
    if combomatch:
        studio = combomatch.group(1)
        seq_nr = combomatch.group(2)
        remaining_parts = parts[1:]
    else:
        # if not, assume first part is studio and second part is sequence number
        if len(parts) >= 2:
            studio = parts[0]
            seq_nr = parts[1]
            remaining_parts = parts[2:]
    if studio == '' or seq_nr == '':
        log.warning(f"Could not extract studio code from filename: {filename}")
        return filename

    # Filter out "8k" from title details
    remaining_parts = [p for p in remaining_parts if p.lower() != '8k']

    # code = letters + "-" + numbers (with custom rule for keeping leading zeros)
    stripped = seq_nr.lstrip('0')
    if len(stripped) >= 3:
        code = f"{studio.upper()}-{stripped}"
    else:
        code = f"{studio.upper()}-{seq_nr}"
    log.info(f"Resulting studio code: {code}")
    scrape['title'] = f"{code} {' '.join(remaining_parts)}".strip()
    log.info(f"Resulting title: {scrape['title']}")
    # scrape['code'] = code
    return code

def cleanup_details(details):
    """
    Remove common Japanese prefixes from details.

    Examples:
        "【VR】 Some title" -> "Some title"
        "【8K】 Some title" -> "Some title"
        "【4K】【VR】 Some title" -> "Some title"
    """
    if details is None:
        return details

    log.info(f"Starting details cleanup for: {details}")

    # List of prefixes to remove (with optional spaces/brackets)
    prefixes_to_remove = [
        r'【VR】\s*',
        r'【8K】\s*',
        r'【4K】\s*',
        r'【HD】\s*',
        r'【FHD】\s*',
        r'【UHD】\s*',
        r'【3D】\s*',
        r'【2D】\s*',
        r'【AI】\s*',
        # Add more prefixes as needed
    ]

    cleaned_details = details
    for prefix in prefixes_to_remove:
        if re.search(prefix, cleaned_details):
            cleaned_details = re.sub(f'^{prefix}', '', cleaned_details).strip()
            log.debug(f"Removed prefix matching: {prefix}")

    if cleaned_details != details:
        log.info(f"Details cleaned from: {details} -> {cleaned_details}")

    return cleaned_details

def cleanup_details2(details):
    """
    Remove common Japanese prefixes and format details.

    Handles multiple prefixes and variations.
    """
    if details is None or details == "":
        return details

    log.info(f"Starting details cleanup for: {details}")

    # Remove all Japanese bracket prefixes at the start
    # Matches: 【anything】 repeated one or more times
    cleaned_details = re.sub(r'^(【[^】]*】\s*)+', '', details).strip()

    # other more specific prefixes to remove
    prefixes_to_remove = [
        r'8KVR\s*',
        r'8K\s*',
        r'VR\s*',
        r'This Is 8K!\s*',
    ]
    for prefix in prefixes_to_remove:
        if re.search(prefix, cleaned_details):
            cleaned_details = re.sub(f'^{prefix}', '', cleaned_details).strip()
            log.debug(f"Removed prefix matching: {prefix}")

    # Remove any leading/trailing whitespace
    cleaned_details = cleaned_details.strip()

    if cleaned_details != details:
        log.info(f"Details cleaned from: {details} -> {cleaned_details}")
    else:
        log.debug(f"No prefixes found to remove in: {details}")

    return cleaned_details



def getxpath(xpath, tree):
    if not xpath:
        return None
    xpath_result = []
    # It handles the union strangely so it is better to split and get one by one
    if "|" in xpath:
        for xpath_tmp in xpath.split("|"):
            xpath_result.append(tree.xpath(xpath_tmp))
        xpath_result = [val for sublist in xpath_result for val in sublist]
    else:
        xpath_result = tree.xpath(xpath)
    #log.debug(f"xPATH: {xpath}")
    #log.debug(f"raw xPATH result: {xpath_result}")
    list_tmp = []
    for x_res in xpath_result:
        # for xpaths that don't end with /text()
        if isinstance(x_res,lxml.html.HtmlElement):
            list_tmp.append(x_res.text_content().strip())
        else:
            list_tmp.append(x_res.strip())
    if list_tmp:
        xpath_result = list_tmp
    xpath_result = list(filter(None, xpath_result))
    return xpath_result


# SEARCH PAGE


def jav_search(html, xpath):
    if "/en/jav" in html.url:
        log.debug(f"Using the provided movie page ({html.url})")
        return html
    jav_search_tree = lxml.html.fromstring(html.content)
    jav_url = getxpath(xpath['url'], jav_search_tree)  # ./javme5it6a
    if jav_url:
        url_domain = urlparse(html.url).netloc
        jav_url = re.sub(r"^\.", f"https://{url_domain}/en", jav_url[0])
        log.debug(f"Using API URL: {jav_url}")
        main_html = send_request(jav_url, JAV_HEADERS)
        return main_html
    log.debug("[JAV] There is no result in search")
    return None


def jav_search_by_name(html, xpath):
    jav_search_tree = lxml.html.fromstring(html.content)
    jav_url = getxpath(xpath['url'], jav_search_tree)  # ./javme5it6a
    jav_title = getxpath(xpath['title'], jav_search_tree)
    jav_image = getxpath(
        xpath['image'], jav_search_tree
    )  # //pics.dmm.co.jp/mono/movie/adult/13gvh029/13gvh029ps.jpg
    lst = []
    # Added fallback for 1 item results which redirect to video page automatically
    if(len(jav_url) == 0):
        jav_url = getxpath('//meta[@property="og:url"]/@content', jav_search_tree)
        jav_title = getxpath('//div[@id="video_title"]/h3/a/text()', jav_search_tree)
        jav_image = getxpath('//div[@id="video_jacket"]/img/@src', jav_search_tree)

        if(len(jav_url) > 0):
            for count, _ in enumerate(jav_url):
                log.debug(jav_url[count])
                lst.append({
                    "title": jav_title[count],
                    "url":
                    f"https:{jav_url[count]}",
                    "image": re.sub("^//","https://",jav_image[count])
                })
    else:
        for count, _ in enumerate(jav_url):
            lst.append({
                "title": jav_title[count],
                "url":
                f"https://www.javlibrary.com/en/{jav_url[count].replace('./', '')}",
                "image": re.sub("^//","https://",jav_image[count])
            })
    log.debug(f"There is/are {len(lst)} scene(s)")
    return lst


def buildlist_tagperf(data, type_scrape=""):
    list_tmp = []
    dict_jav = None
    if type_scrape == "perf_jav":
        dict_jav = data
        data = data["performers"]
    for idx, data_value in enumerate(data):
        p_name = data_value
        if p_name == "":
            continue
        if type_scrape == "perf_jav":
            if p_name not in IGNORE_PERF_REVERSE and not NAME_ORDER_JAPANESE:
                # Invert name (Aoi Tsukasa -> Tsukasa Aoi)
                p_name = re.sub(r"([a-zA-Z]+)(\s)([a-zA-Z]+)", r"\3 \1", p_name)
            if STASH_SUPPORT_NAME_ORDER:
                # There is such names as "Aoi." and even "@you". Indeed, JAV is fun!
                parsed_name = re.search(r"([a-zA-Z\.@]+)(\s)?([a-zA-Z]+)?", p_name)
                if not parsed_name:
                    log.debug(f"Failed to parse name: {p_name}")
                    continue
                p_name = {}
                if parsed_name[2] == ' ' and parsed_name[3]:
                    p_name[
                        "surname"] = parsed_name[1]
                    p_name[
                        "first_name"] = parsed_name[3]
                else:
                    p_name[
                        "nickname"] = parsed_name[0]
        if type_scrape == "tags" and p_name in IGNORE_TAGS:
            continue
        if type_scrape == "tags" and p_name in OBFUSCATED_TAGS:
            p_name = OBFUSCATED_TAGS[p_name]
        if type_scrape == "perf_jav" and dict_jav.get("performer_aliases"):
            try:
                list_tmp.append({
                    "name": p_name,
                    "aliases": dict_jav["performer_aliases"][idx],
                    "gender": "FEMALE"
                })
            except:
                list_tmp.append({"name": p_name, "gender": "FEMALE"})
        else:
            list_tmp.append({"name": p_name})
    # Adding personal fixed tags
    if FIXED_TAGS and type_scrape == "tags":
        list_tmp.append({"name": FIXED_TAGS})
    return list_tmp


def th_request_perfpage(page_url, perf_url):
    # vl_star.php?s=afhvw
    #log.debug("[DEBUG] Aliases Thread: {}".format(threading.get_ident()))
    javlibrary_ja_html = send_request(page_url.replace("/en/", "/ja/"),
                                      JAV_HEADERS)
    if javlibrary_ja_html:
        javlibrary_perf_ja = lxml.html.fromstring(javlibrary_ja_html.content)
        list_tmp = []
        try:
            for p_v in perf_url:
                list_tmp.append(
                    javlibrary_perf_ja.xpath('//a[@href="' + p_v +
                                             '"]/text()')[0])
            if list_tmp:
                jav_result['performer_aliases'] = list_tmp
                log.debug(f"Got the aliases: {list_tmp}")
        except:
            log.debug("Error with the aliases")
    else:
        log.debug("Can't get the Jap HTML")


def th_imageto_base64(imageurl, typevar):
    #log.debug("[DEBUG] {} thread: {}".format(typevar,threading.get_ident()))
    head = JAV_HEADERS
    if isinstance(imageurl,list):
        for image_index, image_url in enumerate(imageurl):
            try:
                img = requests.get(image_url.replace(
                    "ps.jpg", "pl.jpg"),
                                   timeout=10,
                                   headers=head)
                if img.status_code != 200:
                    log.debug(
                        "[Image] Got a bad request (status: "\
                        f"{img.status_code}) for <{image_url}>"
                    )
                    imageurl[image_index] = None
                    continue
                base64image = base64.b64encode(img.content)
                imageurl[
                    image_index] = "data:image/jpeg;base64," + base64image.decode(
                        'utf-8')
            except:
                log.debug(
                    f"[{typevar}] Failed to get the base64 of the image"
                )
    else:
        try:
            img = requests.get(imageurl.replace("ps.jpg", "pl.jpg"),
                               timeout=10,
                               headers=head)
            if img.status_code != 200:
                log.debug(
                    f"[Image] Got a bad request (status: {img.status_code}) for <{imageurl}>"
                )
                return
            base64image = base64.b64encode(img.content)
            if typevar == "JAV":
                jav_result[
                    "image"] = "data:image/jpeg;base64," + base64image.decode(
                        'utf-8')
            log.debug(f"[{typevar}] Converted the image to base64!")
        except:
            log.debug(f"[{typevar}] Failed to get the base64 of the image")
    return


log.debug(f"[DEBUG] Main Thread: {threading.get_ident()}")

import hashlib
import io

stdin_content = sys.stdin.read()
sys.stdin = io.StringIO(stdin_content)

fragment_data = {}
if stdin_content:
    try:
        fragment_data = json.loads(stdin_content)
    except Exception:
        pass

# Generate cache filename based on the query prefix and arguments
query_prefix = get_query_prefix(fragment_data)
args_suffix = "_".join(sys.argv[1:])
if args_suffix:
    cache_filename = f"{query_prefix}_{args_suffix}.json"
else:
    cache_filename = f"{query_prefix}.json"

cached_output = cache_get(cache_filename)
if cached_output is not None:
    log.info(f"Returning cached result for {query_prefix}")
    scene_title_input = fragment_data.get("title")
    if scene_title_input:
        cleanup_filename(scene_title_input)
        clean_title = scrape.get("title")
        if clean_title:
            try:
                data = json.loads(cached_output)
                if isinstance(data, dict):
                    data["title"] = clean_title
                    cached_output = json.dumps(data)
                elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    data[0]["title"] = clean_title
                    cached_output = json.dumps(data)
            except Exception as e:
                log.warning(f"Failed to update cached title: {e}")
    print(cached_output)
    sys.exit(0)

FRAGMENT = fragment_data
log.debug(f"[DEBUG] FRAGMENT: {FRAGMENT}")
# example:
# {'id': '29', 'title': 'ajvr00244-3-02.mp4', 'url': None, 'urls': [], 'date': None, 'details': '',
# 'files': [{'id': '29', 'mod_time': '2024-09-30T15:25:22+02:00', 'path': '/run/media/p/AJVR00244/ajvr00244-3-02.mp4',
# 'fingerprints': [{'type': 'oshash', 'fingerprint': 'e9c272b8125b92c2'}], 'size': 1388427025, 'format': 'mp4',
# 'width': 4096, 'height': 2048, 'duration': 391.15, 'video_codec': 'h264', 'audio_codec': 'aac', 'frame_rate': 59.94, 'bitrate': 28396936}]}

# FRAGMENT = json.loads(r'''{
#   "name": "LULU-424",
#   "url": "https://www.javlibrary.com/en/javme3j5ru.html"
# }''')

SEARCH_TITLE = FRAGMENT.get("name")
SEARCH_TITLE = cleanup_title(SEARCH_TITLE)
if SEARCH_TITLE:
    SEARCH_TITLE = clean_query(SEARCH_TITLE)
SCENE_URL = FRAGMENT.get("url")

if FRAGMENT.get("title"):
    SCENE_TITLE = FRAGMENT["title"]
    # when all fields are empty, stash passes on the filename as title
    SCENE_TITLE = cleanup_filename(SCENE_TITLE)
else:
    SCENE_TITLE = None

if "validSearch" in sys.argv and SCENE_URL is None:
    sys.exit()

if "searchName" in sys.argv:
    log.debug(f"Using search with Title: {SEARCH_TITLE}")
    JAV_SEARCH_HTML = send_request(
        f"https://www.javlibrary.com/en/vl_searchbyid.php?keyword={SEARCH_TITLE}",
        JAV_HEADERS,
        delay=0
    )
else:
    if SCENE_URL:
        scene_domain = re.sub(r"www\.|\.com", "", urlparse(SCENE_URL).netloc)
        # Url from Javlib
        if scene_domain in SITE_JAVLIB:
            log.debug(f"Using URL: {SCENE_URL}")
            JAV_MAIN_HTML = send_request(SCENE_URL, JAV_HEADERS, delay=0)
        else:
            log.warning(f"The URL is not from JavLibrary ({SCENE_URL})")
    if JAV_MAIN_HTML is None and SCENE_TITLE:
        log.debug(f"Using search with Title: {SCENE_TITLE}")
        JAV_SEARCH_HTML = send_request(
            f"https://www.javlibrary.com/en/vl_searchbyid.php?keyword={SCENE_TITLE}",
            JAV_HEADERS,
            delay=0
        )

# XPATH
jav_xPath_search = {}
jav_xPath_search[
    'url'] = '//div[@class="videos"]/div/a[not(contains(@title,"(Blu-ray"))]/@href'
jav_xPath_search[
    'title'] = '//div[@class="videos"]/div/a[not(contains(@title,"(Blu-ray"))]/@title'
jav_xPath_search[
    'image'] = '//div[@class="videos"]/div/a[not(contains(@title,"(Blu-ray"))]//img/@src'

jav_xPath = {}
jav_xPath[
    "code"] = '//td[@class="header" and text()="ID:"]/following-sibling::td/text()'
# or '//div[@id="video_id"]//td[2][@class="text"]/text()'
jav_xPath[
    "title"] = jav_xPath["code"] if LEGACY_FIELDS else '//div[@id="video_title"]/h3/a/text()'
#There are no actual Details in JavLibrary
#For legacy reasons we add the Title in Details by default
jav_xPath[
    "details"] = None if not LEGACY_FIELDS else '//div[@id="video_title"]/h3/a/text()'
jav_xPath["url"] = '//meta[@property="og:url"]/@content'
jav_xPath[
    "date"] = '//td[@class="header" and text()="Release Date:"]/following-sibling::td/text()'
jav_xPath[
    "director"] = '//div[@id="video_director"]//td[@class="text"]/span[@class="director"]/a/text()'
jav_xPath[
    "tags"] = '//td[@class="header" and text()="Genre(s):"]'\
            '/following::td/span[@class="genre"]/a/text()'
jav_xPath[
    "performers"] = '//td[@class="header" and text()="Cast:"]'\
                '/following::td/span[@class="cast"]/span/a/text()'
jav_xPath[
    "performers_url"] = '//td[@class="header" and text()="Cast:"]'\
                        '/following::td/span[@class="cast"]/span/a/@href'
jav_xPath[
    "studio"] = '//td[@class="header" and text()="Maker:"]'\
                '/following-sibling::td/span[@class="maker"]/a/text()'
#jav_xPath[
#    "label"] = '//td[@class="header" and text()="Label:"]'\
#                '/following-sibling::td/span[@class="label"]/a/text()'
jav_xPath["image"] = '//div[@id="video_jacket"]/img/@src'

jav_result = {}

if "searchName" in sys.argv:
    if JAV_SEARCH_HTML:
        if "/en/jav" in JAV_SEARCH_HTML.url:
            log.debug(f"Scraping the movie page directly ({JAV_SEARCH_HTML.url})")
            jav_tree = lxml.html.fromstring(JAV_SEARCH_HTML.content)
            jav_result["title"] = getxpath(jav_xPath["title"], jav_tree)
            jav_result["details"] = getxpath(jav_xPath["details"], jav_tree)
            jav_result["url"] = getxpath(jav_xPath["url"], jav_tree)
            jav_result["image"] = getxpath(jav_xPath["image"], jav_tree)
            for key, value in jav_result.items():
                if isinstance(value,list):
                    jav_result[key] = value[0]
                if key in ["image", "url"]:
                    jav_result[key] = f"https:{jav_result[key]}".replace("https:https:", "https:")
            jav_result = [jav_result]
        else:
            jav_result = jav_search_by_name(JAV_SEARCH_HTML, jav_xPath_search)
        if jav_result:
            print_and_cache(jav_result, cache_filename)
        else:
            print_and_cache([{"title": "The search doesn't return any result."}], cache_filename)
    else:
        if PROTECTION_CLOUDFLARE:
            print_and_cache([{
                "title": "Protected by Cloudflare, try later."
            }], cache_filename)
        else:
            print_and_cache([{
                "title": "The request has failed to get the page. Check log."
            }], cache_filename)
    sys.exit()

if JAV_SEARCH_HTML:
    JAV_MAIN_HTML = jav_search(JAV_SEARCH_HTML, jav_xPath_search)

if JAV_MAIN_HTML:
    #log.debug("[DEBUG] Javlibrary Page ({})".format(JAV_MAIN_HTML.url))
    jav_tree = lxml.html.fromstring(JAV_MAIN_HTML.content)
    # is not None for removing the FutureWarning...
    if jav_tree is not None:
        # Get data from javlibrary
        for key, value in jav_xPath.items():
            jav_result[key] = getxpath(value, jav_tree)
        # PostProcess
        if jav_result.get("image"):
            tmp = re.sub(r"(http:|https:)", "", jav_result["image"][0])
            jav_result["image"] = "https:" + tmp
            if "now_printing.jpg" in jav_result[
                    "image"] or "noimage" in jav_result["image"]:
                # https://pics.dmm.com/mono/movie/n/now_printing/now_printing.jpg
                # https://pics.dmm.co.jp/mono/noimage/movie/adult_ps.jpg
                log.debug(
                    "[Warning][Javlibrary] Image was deleted or failed to load "\
                    f"({jav_result['image']})"
                )
                jav_result["image"] = None
            else:
                imageBase64_jav_thread = threading.Thread(
                    target=th_imageto_base64,
                    args=(
                        jav_result["image"],
                        "JAV",
                    ))
                imageBase64_jav_thread.start()
        if jav_result.get("url"):
            jav_result["url"] = "https:" + jav_result["url"][0]
        if jav_result.get("details") and LEGACY_FIELDS:
            jav_result["details"] = re.sub(r"^(.*? ){1}", "",
                                           jav_result["details"][0])
        if jav_result.get("title"):
            if LEGACY_FIELDS or KEEP_CODE_IN_TITLE:
                jav_result["title"] = jav_result["title"][0]
            elif not KEEP_CODE_IN_TITLE:
                jav_result["title"] = (re.sub(jav_result['code'][0], "",
                                            jav_result["title"][0])).lstrip()
        if jav_result.get("director"):
            jav_result["director"] = jav_result["director"][0]
        #if jav_result.get("label"):
        #    jav_result["label"] = jav_result["label"][0]
        if jav_result.get("performers_url") and IGNORE_ALIASES is False:
            javlibrary_aliases_thread = threading.Thread(
                target=th_request_perfpage,
                args=(
                    JAV_MAIN_HTML.url,
                    jav_result["performers_url"],
                ))
            javlibrary_aliases_thread.daemon = True
            javlibrary_aliases_thread.start()

if JAV_MAIN_HTML is None:
    log.info("No results found")
    print_and_cache({}, cache_filename)
    sys.exit()

log.debug('[JAV] {}'.format(jav_result))

# DVD code
scrape['code'] = next(iter(jav_result.get('code', [])))
# when using SCENE_TITLE (filename when all fields are empty), the title has already been set when parsing the filename
if 'title' not in scrape:
    scrape['title'] = jav_result.get('title')
scrape['date'] = next(iter(jav_result.get('date', [])))
scrape['director'] = jav_result.get('director') or None
scrape['url'] = jav_result.get('url')
scrape['details'] = cleanup_details2(jav_result.get('details', ""))
scrape['studio'] = {
    'name': next(iter(jav_result.get('studio', []))),
}
#scrape['label'] = {
#    'name': jav_result.get('label'),
#}

if WAIT_FOR_ALIASES and not IGNORE_ALIASES:
    try:
        if javlibrary_aliases_thread.is_alive():
            javlibrary_aliases_thread.join()
    except NameError:
        log.debug("No Jav Aliases Thread")
scrape['performers'] = buildlist_tagperf(jav_result, "perf_jav")

if RETURN_TAGS:
    scrape['tags'] = buildlist_tagperf(jav_result.get('tags', []), "tags")
    scrape['tags'] = [
        {
            "name": tag_name.strip()
        } for tag_dict in scrape['tags']
        for tag_name in tag_dict["name"].replace('·', ',').split(",")
    ]

try:
    if imageBase64_jav_thread.is_alive() is True:
        imageBase64_jav_thread.join()
    if jav_result.get('image'):
        scrape['image'] = jav_result['image']
except NameError:
    log.debug("No image JAV Thread")

print_and_cache(scrape, cache_filename)
