import duckdb

conn = duckdb.connect('priorauth.duckdb')

# Load CSVs
conn.execute("CREATE OR REPLACE TABLE patients AS SELECT * FROM read_csv_auto('data/patients_sample.csv')")
conn.execute("CREATE OR REPLACE TABLE claims AS SELECT * FROM read_csv_auto('data/claims_sample.csv')")
conn.execute("CREATE OR REPLACE TABLE policies AS SELECT * FROM read_csv_auto('data/processed/policies_metadata.csv')")

print("✅ DuckDB loaded with:")
print("Patients:", conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0])
print("Claims:", conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0])
print("Policies:", conn.execute("SELECT COUNT(*) FROM policies").fetchone()[0])

conn.close()
