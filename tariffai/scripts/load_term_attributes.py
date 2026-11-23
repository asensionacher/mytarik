#!/usr/bin/env python3
"""Load code attributes and question templates into the termbase."""
import argparse, json, sqlite3
from pathlib import Path

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--db", default="data/termbase.sqlite")
    ap.add_argument("--attrs", default="tariffai/code_attributes.json")
    args=ap.parse_args()
    data=json.loads(Path(args.attrs).read_text(encoding="utf-8"))
    db=sqlite3.connect(args.db)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS code_attributes(
      code TEXT NOT NULL, attribute TEXT NOT NULL, value TEXT NOT NULL,
      source TEXT NOT NULL DEFAULT 'seed', confidence REAL NOT NULL DEFAULT 0.95,
      PRIMARY KEY(code, attribute)
    );
    CREATE TABLE IF NOT EXISTS question_templates(
      attribute TEXT PRIMARY KEY, question TEXT NOT NULL, options_json TEXT NOT NULL,
      source TEXT NOT NULL DEFAULT 'seed'
    );
    """)
    for code, attrs in data.get("codes", {}).items():
        for attribute, value in attrs.items():
            db.execute("INSERT OR REPLACE INTO code_attributes(code,attribute,value,source,confidence) VALUES(?,?,?,?,?)",(code,attribute,value,"seed",0.95))
    for attribute, template in data.get("templates", {}).items():
        db.execute("INSERT OR REPLACE INTO question_templates(attribute,question,options_json,source) VALUES(?,?,?,?)",(attribute,template["question"],json.dumps(template["options"],ensure_ascii=False),"seed"))
    db.commit()
    print(json.dumps({"codes":len(data.get("codes",{})),"templates":len(data.get("templates",{})),"attributes":db.execute("select count(*) from code_attributes").fetchone()[0]},ensure_ascii=False))
    db.close()
if __name__=="__main__": main()
