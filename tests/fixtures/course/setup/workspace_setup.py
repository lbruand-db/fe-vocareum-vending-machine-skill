# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "4"
# ///

# COMMAND ----------

spark.sql("CREATE CATALOG IF NOT EXISTS hello")
dbutils.notebook.run("./00_data_load", 3600)
