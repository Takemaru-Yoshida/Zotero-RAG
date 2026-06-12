#!/usr/bin/env python3
"""Zotero-RAG entry point.

Usage:
  python app.py            # launch the GUI
  python app.py --sync     # headless: build/update the index, then exit
  python app.py --search "query text"   # headless search (prints results)
  python app.py --status   # show index/backend status
"""
from __future__ import annotations

import argparse
import sys

from src.config import Config


def _headless_sync(config: Config):
    from src.indexer import Indexer

    def cb(msg, frac):
        print(f"[{int(frac*100):3d}%] {msg}")

    indexer = Indexer(config)
    result = indexer.sync(progress=cb)
    print("\nSync complete:")
    print(f"  backend     : {result.backend}")
    print(f"  added       : {result.added}")
    print(f"  updated     : {result.updated}")
    print(f"  removed     : {result.removed}")
    print(f"  unchanged   : {result.skipped}")
    print(f"  papers      : {result.total_papers}")
    print(f"  vectors     : {result.total_vectors}")
    print(f"  index kind  : {result.index_kind}")


def _headless_search(config: Config, query: str):
    from src.embedder import Embedder
    from src.search import SearchEngine
    from src.vector_store import VectorStore

    store = VectorStore(config)
    if not store.load() or store.n_vectors == 0:
        print("Index is empty. Run `python app.py --sync` first.")
        return
    engine = SearchEngine(config, Embedder(config), store)
    hits = engine.search(query)
    if not hits:
        print("No results above the similarity threshold.")
        return
    print(f"\nTop {len(hits)} results for: {query!r}\n")
    for i, h in enumerate(hits, 1):
        authors = ", ".join(h.authors[:3]) + (" et al." if len(h.authors) > 3 else "")
        print(f"{i:2d}. [{h.score:.3f}] {h.title}")
        if authors or h.year:
            print(f"      {authors} ({h.year})")
        print(f"      {h.zotero_uri}")


def _status(config: Config):
    from src.vector_store import VectorStore
    from src.zotero_client import ZoteroClient

    store = VectorStore(config)
    store.load()
    client = ZoteroClient(config)
    print(f"Zotero data dir : {config.zotero_data_dir}")
    print(f"Backend         : {client.backend_name()}")
    print(f"Embedding model : {config.embedding_model}")
    print(f"Indexed papers  : {store.n_papers}")
    print(f"Vectors         : {store.n_vectors}")
    print(f"Index file      : {config.index_path}")


def main():
    parser = argparse.ArgumentParser(description="Zotero-RAG semantic search")
    parser.add_argument("--sync", action="store_true",
                        help="update the index and exit")
    parser.add_argument("--search", metavar="QUERY",
                        help="run a search and print results")
    parser.add_argument("--status", action="store_true",
                        help="print index/backend status")
    args = parser.parse_args()

    config = Config.load()

    if args.sync:
        _headless_sync(config)
    elif args.search:
        _headless_search(config, args.search)
    elif args.status:
        _status(config)
    else:
        from src.gui import run
        run()


if __name__ == "__main__":
    main()
