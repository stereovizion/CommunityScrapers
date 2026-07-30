import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

# Add parent directory to sys.path so py_common is found
sys.path.append(str(Path(__file__).parent.parent))

from javlib_server import clean_query, cleanup_filename, run_scraper

CLEAN_QUERY_TEST_CASES = [
    # (input_query, expected_clean_code)
    ("uploader@savr01088_2_8k_cut_1", "SAVR-1088"),
    ("SAVR-1088", "SAVR-1088"),
    ("savr01088", "SAVR-1088"),
    ("lulu00424_8k", "LULU-424"),
    ("some_user@abc00123_4k", "ABC-123"),
    ("abc-123", "ABC-123"),
    ("4k2.me@1sbgvr00002_2_8k_cut_1", "SBGVR-00002"),
]

FILENAME_SCRAPE_TEST_CASES = [
    # (input_filename, expected_code)
    ("some_uploader@lulu00424_2_8k_cut_1.mp4", "LULU-424"),
    ("abc-123_some_details.mp4", "ABC-123"),
    ("uploader@xyz00099_details_here.avi", "XYZ-00099"),
    ("def00555.mp4", "DEF-555"),
    ("4k2.me@1sbgvr00002_2_8k_cut_1.mp4", "SBGVR-00002"),
]

class TestOfflineCleanup(unittest.TestCase):
    def test_clean_query_cases(self):
        for query_input, expected_code in CLEAN_QUERY_TEST_CASES:
            with self.subTest(query_input=query_input, expected_code=expected_code):
                self.assertEqual(clean_query(query_input), expected_code)

    def test_filename_cleanup_cases(self):
        for filename_input, expected_code in FILENAME_SCRAPE_TEST_CASES:
            with self.subTest(filename_input=filename_input, expected_code=expected_code):
                code = cleanup_filename(filename_input)
                self.assertEqual(code, expected_code)

class TestServerAndClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script_path = Path(__file__).parent / "JavLibrary_python.py"
        cls.server_script_path = Path(__file__).parent / "javlib_server.py"
        cls.cache_dir = Path(__file__).parent / ".javlibrary_cache"
        cls.env = os.environ.copy()
        # Ensure PYTHONPATH points to scrapers directory so py_common is found
        cls.env["PYTHONPATH"] = str(Path(__file__).parent.parent)

    def setUp(self):
        # Clear cache before each test
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

    def tearDown(self):
        # Clear cache after each test
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

    def test_clear_cache_cli(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        dummy_file = self.cache_dir / "test.json"
        dummy_file.write_text("{}", encoding="utf-8")
        self.assertTrue(dummy_file.exists())

        proc = subprocess.Popen(
            [sys.executable, str(self.script_path), "--clear-cache"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = proc.communicate()
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Cache cleared successfully.", stdout)
        self.assertFalse(self.cache_dir.exists())

    def test_client_server_http_communication(self):
        test_port = 8999
        # Start desktop server in background process
        server_proc = subprocess.Popen(
            [sys.executable, str(self.server_script_path), "--port", str(test_port)],
            env=self.env
        )
        time.sleep(1) # Allow server to bind

        try:
            # Create temporary config file with REMOTE_SERVER_ENABLED=True
            config_file = Path(__file__).parent / "config.ini"
            orig_config = config_file.read_text() if config_file.exists() else ""
            
            client_config = f"REMOTE_SERVER_ENABLED = True\nREMOTE_SERVER_URL = http://127.0.0.1:{test_port}\n"
            config_file.write_text(client_config)

            # Pre-seed cache on server so remote request doesn't hit live Cloudflare
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = self.cache_dir / "LULU-424_searchName.json"
            cache_payload = [{"url": "https://www.javlibrary.com/en/javme3j5ru.html", "title": "LULU-424", "image": "http://img"}]
            cache_file.write_text(json.dumps(cache_payload))

            # Run client script
            client_proc = subprocess.Popen(
                [sys.executable, str(self.script_path), "searchName"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env,
                text=True
            )
            stdout, stderr = client_proc.communicate(input=json.dumps({"name": "uploader@lulu00424_8k"}))
            self.assertEqual(client_proc.returncode, 0)
            result = json.loads(stdout)
            self.assertEqual(result, cache_payload)

        finally:
            server_proc.terminate()
            server_proc.wait()
            # Restore original config.ini
            config_file.write_text(orig_config)

if __name__ == "__main__":
    unittest.main()
