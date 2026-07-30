"""
JAVLibrary Python Scraper Engine and Remote Desktop HTTP Server.
Serves as the single source of truth for scraping logic and Cloudflare browser solving.
"""
import argparse
import base64
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

CACHE_DIR = Path(__file__).parent / ".javlibrary_cache"
COOKIES_FILE = Path(__file__).parent / "javlib_cookies.json"

from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
import undetected_chromedriver as uc

try:
    from py_common import log
    from py_common.config import get_config
except ModuleNotFoundError:
    class DummyLog:
        def info(self, msg): print(f" i  {msg}", file=sys.stderr)
        def debug(self, msg): print(f" d  {msg}", file=sys.stderr)
        def warning(self, msg): print(f" w  {msg}", file=sys.stderr)
        def error(self, msg): print(f" e  {msg}", file=sys.stderr)
    log = DummyLog()
    def get_config(default=""):
        class DummyConfig:
            RETURN_TAGS = False
        return DummyConfig()

try:
    import lxml.html
except ModuleNotFoundError:
    log.error("lxml module is required on the server!")

try:
    import requests
except ModuleNotFoundError:
    log.error("requests module is required on the server!")

try:
    import selenium
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ModuleNotFoundError:
    SELENIUM_AVAILABLE = False
    log.debug("Selenium not available.")

# Globals
JAV_DOMAIN = "Check"
FLARESOLVERR_ENABLED = False
FLARESOLVERR_URL = "http://localhost:8191/v1"
FLARESOLVERR_TIMEOUT_MAX = 60000

INTERACTIVE_CAPTCHA = True
CAPTCHA_TIMEOUT = 300
PERSISTENT_BROWSER = True
REMOTE_DEBUGGING_PORT = 9222

JAV_HEADERS = {
    "User-Agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    "Referer": "http://www.javlibrary.com/"
}

config = get_config()
RETURN_TAGS = getattr(config, 'RETURN_TAGS', False)
STASH_SUPPORTED = False
STASH_SUPPORT_LABELS = False
STASH_SUPPORT_NAME_ORDER = False
IGNORE_TAGS = [
    "Features Actress", "Hi-Def", "Beautiful Girl", "Blu-ray",
    "Featured Actress", "VR Exclusive", "MOODYZ SALE 4"
]
NAME_ORDER_JAPANESE = False
IGNORE_PERF_REVERSE = ["Lily Heart"]
LEGACY_FIELDS = True
KEEP_CODE_IN_TITLE = True
FIXED_TAGS = ""
SPLIT_TAGS = False
IGNORE_ALIASES = False
WAIT_FOR_ALIASES = False
SITE_JAVLIB = ["javlibrary"]

BANNED_WORDS = {
    "A******ation": "Asphyxiation", "A*****t": "Assault", "A*****ts": "Assaults",
    "A*****ted": "Assaulted", "A*****ting": "Assaulting", "A****p": "Asleep",
    "A***e": "Abuse", "A***ed": "Abused", "A***es": "Abuses", "B*****k": "Berserk",
    "B*****p": "Bang Up", "B***d": "Blood", "B***dcurdling": "Bloodcurdling",
    "B***dline": "Bloodline", "B***dy": "Bloody", "B*******y": "Brutality",
    "B****y": "Bloody", "C***m": "Chasm", "D***g": "Drowning", "D***n": "Drown",
    "E*****e": "Explode", "F***e": "Force", "F***ed": "Forced", "F***ing": "Forcing",
    "F****r": "Fetish", "F****ry": "Forcery", "H*****e": "Hostage",
    "H***d": "Horrid", "I*****t": "Incest", "I****t": "Incest", "K*****p": "Kidnap",
    "K*****ped": "Kidnapped", "K*****ping": "Kidnapping", "K***l": "Kill",
    "K***led": "Killed", "K***ling": "Killing", "M*****r": "Murder",
    "M*****red": "Murdered", "M***t": "Molest", "M***ted": "Molested",
    "M***ting": "Molesting", "P****n": "Poison", "P****ned": "Poisoned",
    "R**e": "Rape", "R**ed": "Raped", "R**ing": "Raping", "R**ist": "Rapist",
    "S***e": "Slave", "S***es": "Slaves", "S****y": "Slavery", "S***t": "Shoot",
    "S***ting": "Shooting", "S*****e": "Suicide", "S****m": "Scrotum",
    "T*****e": "Torture", "T*****ed": "Tortured", "T*****ing": "Torturing",
    "V*****e": "Violence", "V*****t": "Violent"
}

class ResponseHTML:
    content = ""
    html = ""
    status_code = 0
    url = ""

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
            parsed = urlparse(str(val))
            path = parsed.path.strip("/")
            if path:
                val = path.split("/")[-1]
        except Exception:
            pass
    # Clean the value to make it safe for filenames
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

def load_cookies_from_file():
    """Load cookies from persistent storage"""
    try:
        if COOKIES_FILE.exists():
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
                driver.add_cookie({'name': cookie_name, 'value': cookie_value, 'domain': domain})
                log.debug(f"Added cookie: {cookie_name}")
            except Exception as e:
                log.debug(f"Could not add cookie {cookie_name}: {e}")
                # Some cookies might fail due to domain restrictions
    except Exception as e:
        log.warning(f"Error adding cookies to driver: {e}")

def get_chrome_version():
    commands = [
        ["google-chrome", "--version"],
        ["chrome", "--version"],
        ["chromium", "--version"],
        ["chromium-browser", "--version"],
    ]
    for cmd in commands:
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode('utf-8')
            match = re.search(r'(\d+\.\d+\.\d+\.\d+)', output)
            if match:
                return match.group(1)
        except Exception:
            continue
    return None

def is_port_open(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False

def is_cloudflare_challenge_solved(driver):
    try:
        cookies = driver.get_cookies()
        cookie_names = [c['name'] for c in cookies]
        if 'cf_clearance' in cookie_names:
            log.debug("cf_clearance cookie found - challenge solved!")
            return True
    except Exception as e:
        log.debug(f"Error checking challenge status: {e}")
    return False

def interactive_captcha_solve(url):
    if not INTERACTIVE_CAPTCHA or not SELENIUM_AVAILABLE:
        return None
    driver = None
    try:
        log.info(f"Opening browser for interactive captcha solving at: {url}")
        chrome_version = get_chrome_version()
        main_version = int(chrome_version.split('.')[0]) if chrome_version else None
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
                service = Service(executable_path=patcher.executable_path)
                driver = webdriver.Chrome(service=service, options=options)
            except Exception as attach_err:
                log.warning(f"Failed to attach to persistent Chrome: {attach_err}")
                log.info("Falling back to non-persistent ChromeDriver launch...")
                options = uc.ChromeOptions()
                driver = uc.Chrome(options=options, version_main=main_version, user_data_dir="/tmp/javlib_chrome_profile")
        else:
            driver = uc.Chrome(options=options, version_main=main_version, user_data_dir="/tmp/javlib_chrome_profile")

        persistent_cookies = load_cookies_from_file()
        if persistent_cookies:
            add_cookies_to_driver(driver, persistent_cookies)

        driver.get(url)
        log.info("Browser window opened. Please solve captcha manually if prompted.")
        log.info(f"Waiting for {CAPTCHA_TIMEOUT} seconds for captcha to be solved...")
        WebDriverWait(driver, CAPTCHA_TIMEOUT).until(lambda d: is_cloudflare_challenge_solved(d))

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
        if not PERSISTENT_BROWSER and driver:
            try: driver.quit()
            except: pass
            driver = None

        return {'cookies': cookies_dict, 'content': page_content, 'url': current_url}
    except Exception as e:
        log.error(f"Error during interactive captcha solving: {e}")
        return None
    finally:
        if driver and not PERSISTENT_BROWSER:
            try: driver.quit()
            except: pass

def bypass_protection(url, retries=4):
    url_domain = re.sub(r"www\.|\.com", "", urlparse(url).netloc)
    log.debug("=== Checking Status of Javlib site ===")
    response_html = ResponseHTML
    site = "javlibrary"
    url_n = url.replace(url_domain, site)
    cookies = {'over18': '18'}
    try:
        if FLARESOLVERR_ENABLED:
            headers = {"Content-Type": "application/json"}
            data = {
                "cmd": "request.get", "url": url_n, "session": "2",
                "session_ttl_minutes": 120, "maxTimeout": FLARESOLVERR_TIMEOUT_MAX,
                "set-cookie": "over18=18",
            }
            responseJson = requests.post(FLARESOLVERR_URL, cookies=cookies, headers=headers, json=data)
            json_input = responseJson.json()
            response_html.content = json_input['solution']['response']
            response_html.html = json_input['solution']['response']
            response_html.status_code = json_input['solution']['status']
            response_html.url = json_input['solution']['url']
        else:
            # Try regular request first
            response = requests.get(url_n, cookies=cookies, headers=JAV_HEADERS, timeout=10)

            # Check if we got a captcha challenge
            if response.status_code in (403, 503) or "captcha" in response.text.lower() or "challenge" in response.text.lower():
                log.warning("Captcha/Challenge detected. Attempting interactive solve...")
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
    if response_html.status_code == 200:
        return site, response_html
    return None, None

def send_request(url, head, retries=0, delay=2.5):
    global JAV_DOMAIN
    log.info(f"Sending request to {url}, delay {delay} seconds")
    if retries > 3:
        log.warning(f"Scrape for {url} failed after retrying {retries} times")
        return None
    if delay != 0:
        log.info(f"Delaying request by {delay} seconds to prevent Cloudflare rate limiting")
        time.sleep(delay)
    url_domain = re.sub(r"www\.|\.com", "", urlparse(url).netloc)
    response = None
    if url_domain in SITE_JAVLIB:
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
    except Exception as exc_req:
        log.error(f"scrape error exception {exc_req}")
        return send_request(url, head, retries + 1)
    if response.status_code != 200:
        log.debug(f"[Request] Error, Status Code: {response.status_code}")
        response = None
    return response

def replace_banned_words(matchobj):
    return BANNED_WORDS.get(matchobj.group(0), matchobj.group(0))

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

def regexreplace(input_replace):
    word_pattern = re.compile(r'(\w|\*)+')
    output = word_pattern.sub(replace_banned_words, input_replace)
    return re.sub(r"[\[\]\"]", "", output)

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

def run_scraper(argv, stdin_data):
    """
    Main scraping engine entry point.
    Takes argv list and stdin_data dict, performs scraping, and returns result dict/list.
    """
    global JAV_DOMAIN
    JAV_DOMAIN = "Check"

    query_prefix = get_query_prefix(stdin_data)
    args_suffix = "_".join(argv[1:]) if len(argv) > 1 else ""
    cache_filename = f"{query_prefix}_{args_suffix}.json" if args_suffix else f"{query_prefix}.json"

    cached_output = cache_get(cache_filename)
    if cached_output is not None:
        log.info(f"Returning cached result for {query_prefix}")
        try:
            data = json.loads(cached_output)
            scene_title_input = stdin_data.get("title")
            if scene_title_input:
                clean_code = cleanup_filename(scene_title_input)
                if isinstance(data, dict):
                    parts = re.split(r'[-_ ]', os.path.splitext(scene_title_input)[0])
                    tp = [p for p in parts if p.lower() in ("cut", "8k", "2") or clean_query(p) == clean_code]
                    data["title"] = " ".join(tp) if tp else clean_code
                    return data
            return data
        except Exception as e:
            log.warning(f"Failed to parse cache: {e}")

    SEARCH_TITLE = cleanup_title(stdin_data.get("name"))
    if SEARCH_TITLE:
        SEARCH_TITLE = clean_query(SEARCH_TITLE)
    SCENE_URL = stdin_data.get("url")
    SCENE_TITLE = cleanup_filename(stdin_data["title"]) if stdin_data.get("title") else None

    if "validSearch" in argv and SCENE_URL is None:
        return {}

    JAV_SEARCH_HTML = None
    JAV_MAIN_HTML = None

    if "searchName" in argv:
        log.debug(f"Using search with Title: {SEARCH_TITLE}")
        JAV_SEARCH_HTML = send_request(f"https://www.javlibrary.com/en/vl_searchbyid.php?keyword={SEARCH_TITLE}", JAV_HEADERS, delay=0)
    else:
        if SCENE_URL:
            scene_domain = re.sub(r"www\.|\.com", "", urlparse(SCENE_URL).netloc)
            if scene_domain in SITE_JAVLIB:
                JAV_MAIN_HTML = send_request(SCENE_URL, JAV_HEADERS, delay=0)
        if JAV_MAIN_HTML is None and SCENE_TITLE:
            JAV_SEARCH_HTML = send_request(f"https://www.javlibrary.com/en/vl_searchbyid.php?keyword={SCENE_TITLE}", JAV_HEADERS, delay=0)

    jav_xPath_search = {
        'url': '//div[@class="videos"]/div/a[not(contains(@title,"(Blu-ray"))]/@href',
        'title': '//div[@class="videos"]/div/a[not(contains(@title,"(Blu-ray"))]/@title',
        'image': '//div[@class="videos"]/div/a[not(contains(@title,"(Blu-ray"))]//img/@src'
    }
    jav_xPath = {
        "code": '//td[@class="header" and text()="ID:"]/following-sibling::td/text()',
        "title": '//td[@class="header" and text()="ID:"]/following-sibling::td/text()' if LEGACY_FIELDS else '//div[@id="video_title"]/h3/a/text()',
        "details": None if not LEGACY_FIELDS else '//div[@id="video_title"]/h3/a/text()',
        "url": '//meta[@property="og:url"]/@content',
        "date": '//td[@class="header" and text()="Release Date:"]/following-sibling::td/text()',
        "director": '//div[@id="video_director"]//td[@class="text"]/span[@class="director"]/a/text()',
        "tags": '//td[@class="header" and text()="Genre(s):"]/following::td/span[@class="genre"]/a/text()',
        "performers": '//td[@class="header" and text()="Cast:"]/following::td/span[@class="cast"]/span/a/text()',
        "performers_url": '//td[@class="header" and text()="Cast:"]/following::td/span[@class="cast"]/span/a/@href',
        "studio": '//td[@class="header" and text()="Maker:"]/following-sibling::td/span[@class="maker"]/a/text()',
        "image": '//div[@id="video_jacket"]/img/@src'
    }

    jav_result = {}

    if "searchName" in argv:
        if JAV_SEARCH_HTML:
            if "/en/jav" in JAV_SEARCH_HTML.url:
                log.debug(f"Scraping the movie page directly ({JAV_SEARCH_HTML.url})")
                jav_tree = lxml.html.fromstring(JAV_SEARCH_HTML.content)
                jav_result["title"] = getxpath(jav_xPath["title"], jav_tree)
                jav_result["details"] = getxpath(jav_xPath["details"], jav_tree)
                jav_result["url"] = getxpath(jav_xPath["url"], jav_tree)
                jav_result["image"] = getxpath(jav_xPath["image"], jav_tree)
                for key, value in jav_result.items():
                    if isinstance(value, list) and value:
                        jav_result[key] = value[0]
                    if key in ["image", "url"] and jav_result.get(key):
                        jav_result[key] = f"https:{jav_result[key]}".replace("https:https:", "https:")
                result = [jav_result]
            else:
                result = jav_search_by_name(JAV_SEARCH_HTML, jav_xPath_search)
        else:
            result = [{"title": "The search doesn't return any result."}]

        if is_cacheable(result):
            cache_save(cache_filename, json.dumps(result))
        return result

    if JAV_SEARCH_HTML:
        JAV_MAIN_HTML = jav_search(JAV_SEARCH_HTML, jav_xPath_search)

    if JAV_MAIN_HTML:
        jav_tree = lxml.html.fromstring(JAV_MAIN_HTML.content)
        if jav_tree is not None:
            for key, value in jav_xPath.items():
                jav_result[key] = getxpath(value, jav_tree)
            if jav_result.get("image"):
                tmp = re.sub(r"(http:|https:)", "", jav_result["image"][0])
                jav_result["image"] = "https:" + tmp

    scrape = {}
    if jav_result.get('code'):
        scrape['code'] = jav_result['code'][0]
    if jav_result.get('title'):
        scrape['title'] = jav_result['title'][0] if isinstance(jav_result['title'], list) else jav_result['title']
    if jav_result.get('date'):
        scrape['date'] = jav_result['date'][0]
    if jav_result.get('director'):
        scrape['director'] = jav_result['director'][0] if isinstance(jav_result['director'], list) else jav_result['director']
    if jav_result.get('url'):
        scrape['url'] = "https:" + jav_result['url'][0] if isinstance(jav_result['url'], list) else jav_result['url']
    if jav_result.get('details'):
        raw_det = jav_result['details'][0] if isinstance(jav_result['details'], list) else jav_result['details']
        scrape['details'] = cleanup_details2(raw_det)
    if jav_result.get('studio'):
        scrape['studio'] = {'name': jav_result['studio'][0]}
    scrape['performers'] = buildlist_tagperf(jav_result, "perf_jav")
    if RETURN_TAGS:
        scrape['tags'] = buildlist_tagperf(jav_result.get('tags', []), "tags")

    if is_cacheable(scrape):
        cache_save(cache_filename, json.dumps(scrape))

    return scrape


class ScraperHTTPRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        log.info(f"[Server HTTP] {self.address_string()} - {format % args}")

    def do_GET(self):
        if self.path in ("/health", "/status"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "selenium": SELENIUM_AVAILABLE}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/scrape":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            try:
                payload = json.loads(post_data.decode("utf-8"))
                argv = payload.get("argv", [])
                stdin_data = payload.get("input", {})

                result = run_scraper(argv, stdin_data)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response = {"status": "success", "result": result}
                self.wfile.write(json.dumps(response).encode("utf-8"))
            except Exception as e:
                log.error(f"Error handling /scrape request: {e}")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response = {"status": "error", "error": str(e)}
                self.wfile.write(json.dumps(response).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def start_server(host="0.0.0.0", port=8000):
    server_address = (host, port)
    httpd = HTTPServer(server_address, ScraperHTTPRequestHandler)
    log.info(f"Starting JavLibrary Desktop Scraping Server on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Stopping server...")
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JavLibrary Remote Desktop Scraping Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    args = parser.parse_args()

    start_server(host=args.host, port=args.port)
