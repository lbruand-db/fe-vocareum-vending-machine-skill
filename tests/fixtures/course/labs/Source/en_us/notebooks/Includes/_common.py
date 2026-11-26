# Databricks notebook source
# MAGIC %md
# MAGIC # Common lesson setup (fixture)

# COMMAND ----------

dbutils.widgets.text("catalog", "hello")
dbutils.widgets.text("schema", "trips")
dbutils.widgets.text("user_catalog", "")
dbutils.widgets.text("user_schema", "")
source = f'{dbutils.widgets.get("catalog")}.{dbutils.widgets.get("schema")}'
out = f'{dbutils.widgets.get("user_catalog") or "hello"}.{dbutils.widgets.get("user_schema") or "me"}'
COURSE_BUILD = "{{build_id}}"


def ensure_schema():
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {out}")


def ensure_table(name, src):
    spark.table(src).write.mode("overwrite").saveAsTable(f"{out}.{name}")
