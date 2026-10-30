SELECT 
    claim_id,
    patient_id,
    procedure_code,
    diagnosis_code,
    CAST(date_of_service AS DATE) as date_of_service,
    CURRENT_TIMESTAMP as loaded_at
FROM {{ source('raw', 'claims_csv') }}
WHERE claim_id IS NOT NULL
  AND patient_id IS NOT NULL
  AND procedure_code IS NOT NULL