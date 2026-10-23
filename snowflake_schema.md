# Snowflake Schema Documentation

## PATIENTS Table
Stores patient demographics and baseline information.

Columns:
- patient_id: STRING - Unique patient identifier (PRIMARY KEY)
- age: INT - Patient age in years
- gender: STRING - Patient gender (M/F/Other)
- state: STRING - Patient state of residence

## CLAIMS Table
Stores medical claims and procedures performed.

Columns:
- claim_id: STRING - Unique claim identifier (PRIMARY KEY)
- patient_id: STRING - References PATIENTS.patient_id
- diagnosis_code: STRING - ICD-10 diagnosis code
- procedure_code: STRING - HCPCS procedure code
- date_of_service: DATE - Date procedure was performed

## POLICIES Table
Stores insurance coverage policies and rules.

Columns:
- policy_id: STRING - Unique policy identifier (PRIMARY KEY)
- payer_name: STRING - Insurance company name (Medicare, Aetna, etc.)
- procedure_code: STRING - HCPCS procedure code covered
- coverage_text: STRING - Policy coverage language and requirements

## Relationships
- CLAIMS joins PATIENTS on patient_id
- CLAIMS joins POLICIES on procedure_code + payer_name
- This allows joining patient history with applicable coverage policies
