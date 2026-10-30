# Generate synthetic patient records for SYNTHEA
# Usage: python generate_patients.py
# Output: data/patients_sample.csv

import csv
import random
from datetime import datetime

def generate_patients(count=100):
    patients = []
    for i in range(count):
        patient = {
            'patient_id': f'P{1000+i}',
            'age': random.randint(18, 85),
            'gender': random.choice(['M', 'F']),
            'state': random.choice(['CA', 'NY', 'TX', 'FL', 'MA']),
            'insurance': random.choice(['Aetna', 'Medicare', 'Cigna', 'UnitedHealth']),
            'created_at': datetime.now().isoformat()
        }
        patients.append(patient)
    
    # Ensure P1000 is John (age 55, CA, Aetna)
    patients[0] = {
        'patient_id': 'P1000',
        'age': 55,
        'gender': 'M',
        'state': 'CA',
        'insurance': 'Aetna',
        'created_at': datetime.now().isoformat()
    }
    
    return patients

def save_to_csv(patients, filename='data/patients_sample.csv'):
    with open(filename, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['patient_id', 'age', 'gender', 'state', 'insurance', 'created_at'])
        writer.writeheader()
        writer.writerows(patients)
    print(f"Generated {len(patients)} patients in {filename}")

if __name__ == '__main__':
    patients = generate_patients(100)
    save_to_csv(patients)
