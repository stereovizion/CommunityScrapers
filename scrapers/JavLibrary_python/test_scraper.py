import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

# Add parent directory to sys.path so py_common is found during exec() imports
sys.path.append(str(Path(__file__).parent.parent))

# Dynamic load of JavLibrary_python functions without running its main block
script_path = Path(__file__).parent / "JavLibrary_python.py"
namespace = {"__file__": str(script_path)}
script_code = script_path.read_text(encoding='utf-8')
marker = 'log.debug(f"[DEBUG] Main Thread: {threading.get_ident()}")'
parts = script_code.split(marker, 1)
exec(parts[0], namespace)

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
    # (input_filename, expected_code, expected_title)
    ("some_uploader@lulu00424_2_8k_cut_1.mp4", "LULU-424", "LULU-424 2 cut 1"),
    ("abc-123_some_details.mp4", "ABC-123", "ABC-123 some details"),
    ("uploader@xyz00099_details_here.avi", "XYZ-00099", "XYZ-00099 details here"),
    ("def00555.mp4", "DEF-555", "DEF-555"),
    ("4k2.me@1sbgvr00002_2_8k_cut_1.mp4", "SBGVR-00002", "SBGVR-00002 2 cut 1"),
]

class TestOfflineCleanup(unittest.TestCase):
    def test_clean_query_cases(self):
        clean_query = namespace["clean_query"]
        for query_input, expected_code in CLEAN_QUERY_TEST_CASES:
            with self.subTest(query_input=query_input, expected_code=expected_code):
                self.assertEqual(clean_query(query_input), expected_code)

    def test_filename_cleanup_cases(self):
        cleanup_filename = namespace["cleanup_filename"]
        for filename_input, expected_code, expected_title in FILENAME_SCRAPE_TEST_CASES:
            with self.subTest(filename_input=filename_input, expected_code=expected_code, expected_title=expected_title):
                # Reset scraped_data dictionary
                namespace["scraped_data"] = {}
                code = cleanup_filename(filename_input)
                self.assertEqual(code, expected_code)
                self.assertEqual(namespace["scraped_data"].get("title"), expected_title)

class TestOnlineCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script_path = script_path
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

    def run_scraper(self, args, stdin_data):
        proc = subprocess.Popen(
            ["python3", str(self.script_path)] + args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            text=True
        )
        stdout, stderr = proc.communicate(input=json.dumps(stdin_data))
        return proc.returncode, stdout, stderr

    def test_search_name_cache(self):
        # Run search with an uploader prefix and raw keyword
        stdin_data = {"name": "uploader@lulu00424_8k"}
        code, stdout, stderr = self.run_scraper(["searchName"], stdin_data)
        self.assertEqual(code, 0)
        self.assertTrue((self.cache_dir / "LULU-424_searchName.json").exists())

        # Cache hit
        stdin_data_2 = {"name": "uploader@lulu00424_8k", "files": [{"id": "999", "path": "/other/path"}]}
        code_2, stdout_2, stderr_2 = self.run_scraper(["searchName"], stdin_data_2)
        self.assertEqual(code_2, 0)
        self.assertIn("Returning cached result for LULU-424", stderr_2)

    def test_filename_scrape_cache(self):
        stdin_data = {"title": "some_uploader@lulu00424_2_8k_cut_1.mp4"}
        code, stdout, stderr = self.run_scraper([], stdin_data)
        self.assertEqual(code, 0)
        self.assertTrue((self.cache_dir / "LULU-424.json").exists())

        result_1 = json.loads(stdout)
        self.assertEqual(result_1["title"], "LULU-424 2 cut 1")

        # Cache hit with a different filename under same prefix
        stdin_data_2 = {"title": "some_uploader@lulu00424_different_details_8k.mp4", "id": "123"}
        code_2, stdout_2, stderr_2 = self.run_scraper([], stdin_data_2)
        self.assertEqual(code_2, 0)
        self.assertIn("Returning cached result for LULU-424", stderr_2)

        result_2 = json.loads(stdout_2)
        # The title in result_2 should be replaced with the current cleaned-up title!
        self.assertEqual(result_2["title"], "LULU-424 different details")

    def test_clear_cache(self):
        # Generate cache
        stdin_data = {"name": "uploader@lulu00424_8k"}
        self.run_scraper(["searchName"], stdin_data)
        self.assertTrue((self.cache_dir / "LULU-424_searchName.json").exists())

        # Clear
        code, stdout, stderr = self.run_scraper(["--clear-cache"], {})
        self.assertEqual(code, 0)
        self.assertIn("Cache cleared successfully.", stdout)
        self.assertFalse(self.cache_dir.exists())

if __name__ == "__main__":
    unittest.main()
