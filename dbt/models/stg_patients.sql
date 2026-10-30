SELECT 
    patient_id,
    CAST(age AS INT) as age,
    gender,
    state,
    insurance as insurance_company,
    CURRENT_TIMESTAMP as loaded_at
FROM {{ source('raw', 'patients_csv') }}
WHERE patient_id IS NOT NULL
  AND age > 0
  AND age < 150
  AND gender IN ('M', 'F')
QUALIFY ROW_NUMBER() OVER (PARTITION BY patient_id ORDER BY patient_id) = 1