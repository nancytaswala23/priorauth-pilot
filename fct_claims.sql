{{ config(materialized='table') }}

SELECT
  claim_id,
  patient_id,
  diagnosis_code,
  procedure_code,
  date_of_service
FROM {{ ref('stg_claims') }}
WHERE date_of_service IS NOT NULL
