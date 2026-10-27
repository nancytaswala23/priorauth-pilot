# Generate synthetic claims records
# Usage: python generate_claims.py
# Output: data/claims_sample.csv

import csv
import random
from datetime import datetime, timedelta

def generate_claims(patients_count=100):
    diagnoses = ['M51.26', 'M51.27', 'M42.90', 'M47.91', 'M53.0', 'M54.5']
    procedures = ['72148', '72149', '72150', '99213', '99214']
    
    claims = []
    for i in range(patients_count):
        patient_id = f'P{1000+i}'
        num_claims = random.randint(1, 5)
        
        for j in range(num_claims):
            claim = {
                'claim_id': f'C{10000+len(claims)}',
                'patient_id': patient_id,
                'procedure_code': random.choice(procedures),
                'diagnosis_code': random.choice(diagnoses),
                'date_of_service': (datetime.now() - timedelta(days=random.randint(1, 365))).strftime('%Y-%m-%d'),
                'created_at': datetime.now().isoformat()
            }
            claims.append(claim)
    
    return claims

def save_to_csv(claims, filename='data/claims_sample.csv'):
    with open(filename, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['claim_id', 'patient_id', 'procedure_code', 'diagnosis_code', 'date_of_service', 'created_at'])
        writer.writeheader()
        writer.writerows(claims)
    print(f"Generated {len(claims)} claims in {filename}")

if __name__ == '__main__':
    claims = generate_claims(100)
    save_to_csv(claims)
