import os
import psycopg2

from flask import Flask, render_template, request
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date

import calendar

app = Flask(__name__)

conn = psycopg2.connect("postgresql://postgres.mggobpvspdsuimokmlwc:EyEcansEEoptical@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres")
cursor = conn.cursor(cursor_factory=RealDictCursor)


@app.route('/')
def index():
    today_str = date.today()

    # Count patients added/registered today (assumes 'created_at' is a DATE or TIMESTAMP column)
    cursor.execute("SELECT COUNT(*) FROM patient WHERE date = %s", (today_str,))
    patients_today = cursor.fetchone()['count']

    # Count appointments scheduled today
    cursor.execute("SELECT COUNT(*) FROM appointment WHERE appointment_date = %s", (today_str,))
    appointments_today = cursor.fetchone()['count']

    # Count invoices for today with no payment marked as 'Paid'
    cursor.execute("""
        SELECT COUNT(*) FROM invoice
        WHERE transaction_date = %s
        AND NOT EXISTS (
            SELECT 1 FROM unnest(payment) AS p
            WHERE p->>'payment_status' = 'Paid'
        )
    """, (today_str,))
    pending_payments = cursor.fetchone()['count']

    # Count invoices for today with at least one payment marked as 'Paid'
    cursor.execute("""
        SELECT COUNT(*) FROM invoice
        WHERE transaction_date = %s
        AND EXISTS (
            SELECT 1 FROM unnest(payment) AS p
            WHERE p->>'payment_status' = 'Paid'
        )
    """, (today_str,))
    sales_today = cursor.fetchone()['count']

    return render_template('index.html', dashboard={
        'patients': patients_today,
        'appointments': appointments_today,
        'pending_payments': pending_payments,
        'sales': sales_today
    })


@app.route('/appointments')
def appointments():
    cursor.execute("SELECT * FROM appointment")
    appointments = cursor.fetchall()
    return render_template("appointment.html", appointments=appointments)

@app.route('/filter_appointments')
def filter_appointments():
    status = request.args.get('status')
    appt_date = request.args.get('appointment_date')
    query = "SELECT * FROM appointment WHERE 1=1"
    params = []

    if status and status.lower() != "all":
        query += " AND status = %s"
        params.append(status)
    if appt_date:
        query += " AND appointment_date = %s"
        params.append(appt_date)

    cursor.execute(query, tuple(params))
    appointments = cursor.fetchall()
    return render_template("appointment.html", appointments=appointments)


@app.route('/patients')
def patient_records():
    status = request.args.get('status', 'All')
    if status == 'All':
        cursor.execute("SELECT * FROM patient")
    else:
        cursor.execute("SELECT * FROM patient WHERE status = %s", (status,))
    patients = cursor.fetchall()
    return render_template("tables.html", patients=patients, status=status)


@app.route('/invoices')
def invoices():
    cursor.execute("SELECT * FROM invoice")
    invoices = cursor.fetchall()

    total_earnings = 0
    overdue_count = 0
    today = date.today()

    for inv in invoices:
        total_earnings += inv['total_price'] or 0

        payments = inv.get('payment') or []
        if payments:
            latest_payment = payments[-1]
            inv['payment_method'] = latest_payment.get('payment_method')
            inv['payment_status'] = latest_payment.get('payment_status')
        else:
            inv['payment_method'] = None
            inv['payment_status'] = None

        if inv.get('payment_status') == 'Partial':
            overdue_count += 1

    # Get most frequent patient based on number_of_visit in patient table
    cursor.execute("""
        SELECT * FROM patient
        ORDER BY number_of_visit DESC
        LIMIT 1
    """)
    most_frequent_patient = cursor.fetchone()

    return render_template('invoice.html',
                           invoices=invoices,
                           total_earnings=total_earnings,
                           overdue_count=overdue_count,
                           most_frequent_patient=most_frequent_patient)



@app.route('/patient/<patient_id>')
def patient_details(patient_id):
    cursor.execute("SELECT * FROM patient WHERE patient_id = %s", (patient_id,))
    patient = cursor.fetchone()
    if not patient:
        return "Patient not found", 404

    cursor.execute("SELECT * FROM eyeresult WHERE patient_id = %s", (patient_id,))
    eye_results = cursor.fetchall()

    cursor.execute("SELECT * FROM prescription WHERE patient_id = %s", (patient_id,))
    prescriptions = cursor.fetchall()

    cursor.execute("SELECT * FROM invoice WHERE patient_id = %s", (patient_id,))
    invoices = cursor.fetchall()

    return render_template("patient details.html",
                           patient=patient,
                           eye_results=eye_results,
                           prescriptions=prescriptions,
                           invoices=invoices)

@app.route('/patient/<patient_id>/history')
def patient_history(patient_id):
    cursor.execute("SELECT * FROM patient WHERE patient_id = %s", (patient_id,))
    patient = cursor.fetchone()
    if not patient:
        return "Patient not found", 404

    cursor.execute("SELECT * FROM appointment WHERE patient_id = %s", (patient_id,))
    appointments = cursor.fetchall()

    cursor.execute("SELECT * FROM prescription WHERE patient_id = %s", (patient_id,))
    prescriptions = cursor.fetchall()

    presc_lookup = {
        p['prescription_date']: {
            'Eye_Exam_Results': p.get('va_od', 'N/A'),
            'Vision_Prescription': f"{p.get('sph_od', '')}/{p.get('sph_os', '')}"
        }
        for p in prescriptions
    }

    history_data = []
    for appt in appointments:
        date_str = appt['appointment_date']
        history_data.append({
            'appointment_id': appt.get('appointment_id', 'N/A'),
            'appointment_date': date_str,
            'purpose': appt.get('purpose', 'N/A'),
            'status': appt.get('status', 'N/A'),
        })

    return render_template("patient history.html", patient=patient, history_data=history_data)

if __name__ == '__main__':
    app.run(debug=True)
