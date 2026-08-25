 # Medical Appointment and Patient Reception System with IoT

## Research Project

### Vietnamese Title

> Giải pháp tích hợp đặt lịch khám và tiếp nhận bệnh nhân bằng ứng dụng di động và thiết bị IoT

### English Title

> An Integrated Solution for Medical Appointment Scheduling and Patient Reception Using Mobile Applications and IoT Devices

---

## Overview

This project was developed as part of a student scientific research project focused on improving the appointment and patient reception process in healthcare environments.

The system combines a web-based management platform with an IoT-based QR check-in system. Patients can be registered for appointments, checked in at reception, and assigned to an examination queue. Medical staff can then monitor appointments, manage queues, and update examination progress through the web application.

The complete research project consists of three components:

* Mobile Application
* Web Application
* IoT System

This repository contains the **Web Application** and **IoT System** that I developed.

---

## My Contribution

I was primarily responsible for the development of the **Web Application** and **IoT System**.

My work included:

* Developing the Django-based web application
* Implementing appointment and patient queue management
* Developing doctor and patient workflows
* Integrating Firebase Realtime Database
* Implementing QR-based patient check-in
* Building the IoT scanning interface with PySide6 and OpenCV
* Implementing appointment and check-in validation
* Handling queue assignment and duplicate check-in prevention


The **Mobile Application** was developed by another team member and is not included in this repository.

---

## System Overview

The system is divided into three main components:

```text
                    ┌─────────────────────┐
                    │   Mobile Application│
                    │   (Other Member)    │
                    └──────────┬──────────┘
                               │
                               ▼
┌─────────────────┐     ┌─────────────────────┐
│   IoT Device    │────▶│  Firebase / Backend │
│ QR Check-in     │     │       Services      │
└─────────────────┘     └──────────┬──────────┘
                                   │
                                   ▼
                         ┌─────────────────────┐
                         │    Web Application  │
                         │ Django Management   │
                         └─────────────────────┘
```

The IoT device handles patient check-in at the reception area. After a successful QR scan and validation, the patient's appointment and queue information is updated and becomes available to the web application.

---

## Features

### Web Application

The web application is built with Django and acts as the main management platform for the appointment and examination workflow.

Key features include:

* Appointment creation and management
* Patient and doctor information management
* Doctor dashboard with daily patient lists
* Appointment filtering by date and status
* Patient record search and examination workflow
* Appointment status tracking:

  * Scheduled
  * Arrived
  * No-show
  * In progress
  * Completed
* Patient queue management
* Priority handling for urgent or high-priority patients
* Doctor access control for patient information
* Reception dashboard and patient flow monitoring
* Queue status synchronization
* TTS-based patient calling and reminders
* Referral and appointment history tracking
* Firebase Realtime Database integration

### IoT System

The IoT component is designed for patient reception and automated check-in using QR codes.

Key features include:

* Camera-based QR code scanning
* QR decoding with OpenCV and Pyzbar
* QR payload validation
* Appointment date and status validation
* Patient and appointment matching
* Automatic queue assignment
* Duplicate check-in prevention
* Appointment cancellation and eligibility checks
* Patient and appointment status updates
* Firebase Realtime Database synchronization
* PySide6 interface for reception staff
* Camera configuration for IoT deployment

---

## Main Workflow

### 1. Appointment

A patient creates or receives an appointment through the system. The appointment contains the information required for later check-in and queue management.

### 2. Patient Check-in

When the patient arrives, the QR code associated with the appointment is scanned by the IoT device.

The system checks:

* QR data validity
* Appointment date
* Appointment status
* Patient information
* Previous check-in status
* Appointment eligibility

If the validation succeeds, the patient is checked in and added to the examination queue.

### 3. Queue Management

The web application receives the updated information and manages the patient's position in the queue.

Priority rules can be applied to urgent or high-priority patients.

### 4. Examination

Doctors can view their assigned patient list, access relevant patient information, update examination progress, and complete appointments.

### 5. Patient Calling

The system provides notification and TTS-based calling support to help guide patients from the waiting area to the appropriate consultation room.

---

## Technologies

### Web Application

* Python
* Django
* Firebase Realtime Database
* HTML
* CSS
* JavaScript

### IoT System

* Python
* PySide6
* OpenCV
* Pyzbar
* QR Code
* Firebase Realtime Database
* Raspberry Pi / IoT device integration

---

## Repository Structure

```text
medical-appointment-patient-reception-iot/
│
├── web/
│   ├── appointments/
│   ├── doctors/
│   ├── patients/
│   ├── services/
│   ├── templates/
│   ├── doctor_portal/
│   ├── manage.py
│   └── requirements.txt
│
├── iot/
│   ├── qr_scan.py
│   ├── firebase_conn.py
│   ├── logging_utils.py
│   ├── test_qr_scan.py
│   ├── requirements.txt
│   └── pyside6_app/
```

---

## Project Highlights

The main technical focus of my work was connecting the **web management workflow** with the **IoT check-in process**.

Instead of treating check-in as a separate process, the IoT device validates the patient's appointment and updates the corresponding data so that the reception and medical staff can see the patient's status and queue position through the web application.

This allowed the project to demonstrate an end-to-end workflow:

```text
Appointment
     ↓
Patient Arrival
     ↓
QR Check-in
     ↓
Validation
     ↓
Queue Assignment
     ↓
Doctor Dashboard
     ↓
Examination
     ↓
Appointment Completion
```

---

## Project Scope

This repository covers the components developed by me:

* Web Application
* IoT QR Check-in System

The mobile application is part of the overall research project but was developed separately by another team member.

---

## Research Context

This project was developed as a student scientific research project exploring the use of web applications and IoT devices to support appointment scheduling, patient reception, and queue management in healthcare environments.
