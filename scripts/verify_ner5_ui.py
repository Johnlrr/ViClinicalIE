#!/usr/bin/env python3
"""Simple UI server for NER-5 data verification."""
import json
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import sys

DATA_DIR = Path("data/processed/ner_v2")
MANIFEST = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
PILOT_IDS = set(MANIFEST["human_review"]["pilot_sample_ids"])

samples_data = []
for fname in ["task_aligned_train.jsonl", "noisy_train.jsonl"]:
    fpath = DATA_DIR / fname
    if not fpath.exists():
        continue
    for line in fpath.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        sample = json.loads(line)
        if sample["file_id"] in PILOT_IDS:
            samples_data.append(sample)

samples_data.sort(key=lambda x: x["file_id"])

class VerifyHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            html_path = Path(__file__).parent.parent / "templates" / "verify_ner5.html"
            html = html_path.read_text(encoding="utf-8")
            self.wfile.write(html.encode("utf-8"))
        elif self.path == "/api/samples":
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(samples_data).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    PORT = 5000
    handler = VerifyHandler
    httpd = HTTPServer(("localhost", PORT), handler)
    print(f"✅ NER-5 Verify UI running at http://localhost:{PORT}")
    print(f"📊 Loaded {len(samples_data)} pilot samples")
    print(f"👉 Open your browser and go to http://localhost:{PORT}")
    print(f"🛑 Press Ctrl+C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
