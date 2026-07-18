import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

class TestJavLibraryScraper(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script_path = Path(__file__).parent / "JavLibrary_python.py"
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

    def test_search_name_cleanup_and_cache(self):
        # Run search with an uploader prefix and raw keyword
        stdin_data = {"name": "uploader@lulu00424_8k"}
        code, stdout, stderr = self.run_scraper(["searchName"], stdin_data)
        
        self.assertEqual(code, 0, f"Scraper failed with: {stderr}")
        
        # Verify the returned result has the search result
        result = json.loads(stdout)
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        self.assertEqual(result[0]["title"], "LULU-424")

        # Verify that the cache file LULU-424_searchName.json was created
        cache_file = self.cache_dir / "LULU-424_searchName.json"
        self.assertTrue(cache_file.exists(), "Cache file was not created with correct clean studio code prefix")

        # Verify cache hit with dynamic details
        stdin_data_2 = {"name": "uploader@lulu00424_8k", "files": [{"id": "999", "path": "/other/path"}]}
        code_2, stdout_2, stderr_2 = self.run_scraper(["searchName"], stdin_data_2)
        self.assertEqual(code_2, 0)
        self.assertIn("Returning cached result for LULU-424", stderr_2)
        
        result_2 = json.loads(stdout_2)
        self.assertEqual(result, result_2)

    def test_filename_scrape_cleanup_and_title_retention(self):
        # Run a standard scrape with a filename input
        stdin_data = {"title": "some_uploader@lulu00424_2_8k_cut_1.mp4"}
        code, stdout, stderr = self.run_scraper([], stdin_data)
        
        self.assertEqual(code, 0, f"Scraper failed with: {stderr}")
        
        # Verify that uploader prefix is stripped and title contains remaining parts
        result = json.loads(stdout)
        self.assertEqual(result.get("code"), "LULU-424")
        self.assertEqual(result.get("title"), "LULU-424 2 8k cut 1")

        # Verify that the cache file LULU-424.json was created
        cache_file = self.cache_dir / "LULU-424.json"
        self.assertTrue(cache_file.exists(), "Cache file was not created with correct clean studio code prefix")

        # Verify cache hit with different dynamic details
        stdin_data_2 = {"title": "some_uploader@lulu00424_2_8k_cut_1.mp4", "id": "123"}
        code_2, stdout_2, stderr_2 = self.run_scraper([], stdin_data_2)
        self.assertEqual(code_2, 0)
        self.assertIn("Returning cached result for LULU-424", stderr_2)

        result_2 = json.loads(stdout_2)
        self.assertEqual(result, result_2)

    def test_clear_cache(self):
        # Generate a cache file first
        stdin_data = {"name": "uploader@lulu00424_8k"}
        self.run_scraper(["searchName"], stdin_data)
        self.assertTrue((self.cache_dir / "LULU-424_searchName.json").exists())

        # Clear cache using CLI option
        code, stdout, stderr = self.run_scraper(["--clear-cache"], {})
        self.assertEqual(code, 0)
        self.assertIn("Cache cleared successfully.", stdout)
        self.assertFalse(self.cache_dir.exists(), "Cache directory was not deleted")

if __name__ == "__main__":
    unittest.main()
