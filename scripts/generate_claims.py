# Generate synthetic claims records
# Usage: python generate_claims.py
# Output: data/claims_sample.csv

import csv
import random
from datetime import datetime, timedelta

def generate_claims(patients_count=100):
    diagnoses = ['M54.16', 'M54.17', 'M51.16', 'M42.90', 'M47.91', 'M53.0']
    procedures = ['72148', '72149', '72158', '99213', '99214']
    
    claims = []
    
    # Select 7-10 random patients to have red flags
    red_flag_patients = set(random.sample(range(patients_count), k=random.randint(7, 10)))
    
    for i in range(patients_count):
        patient_id = f'P{1000+i}'
        num_claims = random.randint(1, 5)
        
        # Determine if this patient has red flags
        has_red_flag = i in red_flag_patients
        
        for j in range(num_claims):
            claim = {
                'claim_id': f'C{10000+len(claims)}',
                'patient_id': patient_id,
                'procedure_code': random.choice(procedures),
                'diagnosis_code': random.choice(diagnoses),
                'date_of_service': (datetime.now() - timedelta(days=random.randint(1, 365))).strftime('%Y-%m-%d'),
                'conservative_treatment_weeks': random.randint(2, 12),  # NEW: 2-12 weeks
                'red_flag_present': 'TRUE' if has_red_flag else 'FALSE',  # NEW: TRUE for 7-10 patients
                'created_at': datetime.now().isoformat()
            }
            claims.append(claim)
    
    return claims

def save_to_csv(claims, filename='data/claims_sample.csv'):
    with open(filename, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['claim_id', 'patient_id', 'procedure_code', 'diagnosis_code', 'date_of_service', 'conservative_treatment_weeks', 'red_flag_present', 'created_at'])
        writer.writeheader()
        writer.writerows(claims)
    print(f"Generated {len(claims)} claims in {filename}")

if __name__ == '__main__':
    claims = generate_claims(100)
    save_to_csv(claims)