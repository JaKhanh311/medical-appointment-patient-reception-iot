"""
Django management command to push sample data to Firebase Firestore
Usage: python manage.py push_firebase_sample
"""
import json
import os
from django.core.management.base import BaseCommand
from services.firebase import db


class Command(BaseCommand):
    help = 'Push sample data from data/firebase/sample_data.json to Firestore'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('Starting Firebase data sync...'))
        
        # Load sample data
        sample_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'data', 'firebase', 'sample_data.json'
        )
        
        try:
            with open(sample_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f'File not found: {sample_file}'))
            return
        
        # Push doctors
        self.stdout.write(self.style.SUCCESS('\nPushing doctors...'))
        for doctor in data.get('doctors', []):
            doc_copy = doctor.copy()
            doc_id = doc_copy.pop('id')
            db.collection('doctors').document(doc_id).set(doc_copy)
            self.stdout.write(f"  ✓ {doc_id}: {doc_copy.get('name')}")
        
        # Push patients
        self.stdout.write(self.style.SUCCESS('\nPushing patients...'))
        for patient in data.get('patients', []):
            pat_copy = patient.copy()
            pat_id = pat_copy.pop('id')
            db.collection('patients').document(pat_id).set(pat_copy)
            self.stdout.write(f"  ✓ {pat_id}: {pat_copy.get('name')}")
        
        # Push appointments
        self.stdout.write(self.style.SUCCESS('\nPushing appointments...'))
        for appointment in data.get('appointments', []):
            apt_copy = appointment.copy()
            apt_id = apt_copy.pop('id')
            db.collection('appointments').document(apt_id).set(apt_copy)
            self.stdout.write(f"  ✓ {apt_id}: patient {apt_copy.get('patient_id')}")
        
        self.stdout.write(self.style.SUCCESS('\n✅ Successfully synced all data to Firebase!'))
