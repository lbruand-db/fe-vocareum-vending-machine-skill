# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "4"
# ///
# MAGIC %md
# MAGIC # 1.2 Lab — First Table

# COMMAND ----------

# MAGIC %run ../Includes/Classroom-Setup-1.2

# COMMAND ----------

# MAGIC %pip install -q -r /Volumes/hello/trips/assets/requirements.txt

# COMMAND ----------

n = spark.table(f"{out}.trips").count()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Short on time?

# COMMAND ----------

# MAGIC %md
# MAGIC ## Check your work

# COMMAND ----------

# MAGIC %run ../Includes/_checks

# COMMAND ----------

finish("1.2", [("trips has rows", n > 0, f"{n} rows")])
