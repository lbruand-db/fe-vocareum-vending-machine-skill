# Databricks notebook source
import json


def finish(lab, checks):
    ok = all(c[1] for c in checks)
    dbutils.notebook.exit(json.dumps({"lab": lab, "status": "PASS" if ok else "FAIL",
                                      "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in checks]}))
