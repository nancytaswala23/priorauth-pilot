CREATE TABLE PATIENTS (
  patient_id STRING PRIMARY KEY,
  age INT,
  gender STRING,
  state STRING
);

CREATE TABLE CLAIMS (
  claim_id STRING PRIMARY KEY,
  patient_id STRING,
  diagnosis_code STRING,
  procedure_code STRING,
  date_of_service DATE
);

CREATE TABLE POLICIES (
  policy_id STRING PRIMARY KEY,
  payer_name STRING,
  procedure_code STRING,
  coverage_text STRING
);
