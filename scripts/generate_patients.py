import csv
import random
from datetime import datetime

def generate_patients(count=100):
    patients = []
    for i in range(count):
        # Split patients: 70% SampleCommercial, 30% Medicare
        insurance = random.choice(['SampleCommercial'] * 70 + ['Medicare'] * 30)
        
        # Medicare patients in MA/NY (Yashasvi's policy region JK), commercial anywhere
        if insurance == 'Medicare':
            state = random.choice(['MA', 'NY', 'CT', 'ME', 'NH', 'RI', 'VT'])
        else:
            state = random.choice(['CA', 'NY', 'TX', 'FL', 'MA', 'OH', 'IL', 'PA', 'NJ'])
        
        patient = {
            'patient_id': f'P{1000+i}',
            'age': random.randint(18, 85),
            'gender': random.choice(['M', 'F']),
            'state': state,
            'insurance': insurance,
            'created_at': datetime.now().isoformat()
        }
        patients.append(patient)
    
    # Ensure P1000 is John (age 55, CA, SampleCommercial - matches Yashasvi's policy)
    patients[0] = {
        'patient_id': 'P1000',
        'age': 55,
        'gender': 'M',
        'state': 'CA',
        'insurance': 'SampleCommercial',
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