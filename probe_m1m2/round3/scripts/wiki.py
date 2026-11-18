"""Local DeepSearch-World Search/Open service using the published index and corpus."""

from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import sys
from threading import Lock
from urllib.parse import unquote

from pyserini.pyclass import autoclass


def write_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


class Wiki:
    def __init__(self, root):
        self.root = root
        self.db_uri = (root / "visit_sqlite/visit_offsets.sqlite").as_uri() + "?mode=ro&immutable=1"
        self.corpus = root / "visit_sqlite/wikiextractor_v1.jsonl"
        self.searcher = autoclass("io.anserini.search.SimpleSearcher")(str(root / "web_search_index"))
        self.search_lock = Lock()

    def search(self, query):
        if not isinstance(query, str) or not query.strip():
            return {"error": "query must be nonempty"}
        with self.search_lock:
            found = {}
            for hit in self.searcher.search(query, 50):
                if hit.docid not in found:
                    raw = json.loads(self.searcher.doc(hit.docid).get("raw"))
                    found[hit.docid] = {"docid": hit.docid, "caption": raw.get("caption", ""),
                                        "score": float(hit.score)}
                if len(found) == 5:
                    break
        return {"results": list(found.values())}

    def open(self, docid, start=0):
        if not isinstance(docid, str) or not docid or type(start) is not int or start < 0:
            return {"error": "use a Search docid and a nonnegative integer start"}
        candidates = (docid, unquote(docid), unquote(docid).replace("_", " "))
        with closing(sqlite3.connect(self.db_uri, uri=True)) as db:
            for title in dict.fromkeys(candidates):
                row = db.execute("SELECT offset FROM offsets WHERE keyword = ? LIMIT 1", (title,)).fetchone()
                if row is not None:
                    break
            else:
                return {"error": "document not found"}
        with self.corpus.open("rb") as stream:
            stream.seek(row[0])
            item = json.loads(stream.readline())
        text = item.get("text") or item.get("content") or item.get("passage")
        if not isinstance(text, str) or not text:
            raise ValueError("Indexed page has no text")
        end = min(start + 8000, len(text))
        return {"docid": docid, "start": start, "text": text[start:end],
                "next_start": end if end < len(text) else None}


def smoke(wiki):
    queries = ("Eustahija Arsić Serbian writer born Irig", "Brazilian forward Kansai region Japan 1990s footballer",
               "ZIP4 gene wheat seed production")
    checks = []
    for query in queries:
        hits = wiki.search(query)["results"]
        if not hits or hits != wiki.search(query)["results"]:
            raise RuntimeError("Search returned no hits or was nondeterministic")
        for hit in hits:
            page = wiki.open(hit["docid"])
            if page.get("text"):
                assert page == wiki.open(hit["docid"])
                checks.append({"query": query, "hits": len(hits), "opened_docid": hit["docid"],
                               "text_chars": len(page["text"])})
                break
        else:
            raise RuntimeError("Search hits failed to resolve to local pages")
    return checks


def main():
    root, ready = map(Path, sys.argv[1:3])
    manifest = json.loads((root / "MANIFEST.json").read_bytes())
    receipt = json.loads((root / "ASSETS_READY.json").read_bytes())
    assert receipt["revision"] == manifest["revision"]
    assert set(receipt["files"]) == {entry["path"] for entry in manifest["files"]}
    assert all((root / entry["path"]).stat().st_size == entry["size"] for entry in manifest["files"])
    wiki = Wiki(root)
    checks = smoke(wiki)
    if "--probe-only" in sys.argv:
        write_json(ready, {"revision": manifest["revision"], "smoke": checks})
        return
    serve(wiki, ready, manifest["revision"], checks)


def serve(wiki, ready, revision, checks):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                size = int(self.headers["Content-Length"])
                if not 0 < size <= 32768:
                    raise ValueError("Tool payload too large")
                args = json.loads(self.rfile.read(size))
                handler = {"/search": wiki.search, "/open": wiki.open}[self.path]
                result = handler(**args)
                status = 200
            except (TypeError, KeyError, ValueError) as exc:
                result, status = {"error": str(exc)}, 400
            except Exception as exc:
                print(type(exc).__name__, str(exc), flush=True)
                result, status = {"error": "local retrieval failed"}, 500
            payload = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        write_json(ready, {"port": server.server_port, "revision": revision, "smoke": checks})
        server.serve_forever()


if __name__ == "__main__":
    main()
