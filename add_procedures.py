import duckdb
conn = duckdb.connect('priorauth.duckdb')
conn.execute("""
CREATE OR REPLACE TABLE procedures AS 
SELECT '72148' as procedure_code, 'Lumbar MRI' as procedure_name, 1200 as cost UNION ALL
SELECT '72149', 'Lumbar MRI w/ Contrast', 1500 UNION ALL
SELECT '72158', 'Lumbar MRI Complete', 1800 UNION ALL
SELECT '99213', 'Office Visit', 150 UNION ALL
SELECT '99214', 'Office Visit Complex', 250
""")
print("✅ Procedures table created!")
conn.close()
