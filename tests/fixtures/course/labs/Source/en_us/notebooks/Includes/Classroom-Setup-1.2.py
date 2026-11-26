# Databricks notebook source
# MAGIC %run ./_common

# COMMAND ----------

ensure_schema()
ensure_table("trips", f"{source}.trips")
