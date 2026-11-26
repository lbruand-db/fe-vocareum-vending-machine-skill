# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "4"
# ///

# COMMAND ----------

spark.table("samples.nyctaxi.trips").write.mode("overwrite").saveAsTable("hello.trips.trips")
