import os
from multiprocessing import connection

import psycopg2

from flask import Flask, render_template, request, json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date, timedelta, time
from flask import request, redirect, url_for, flash
from dotenv import load_dotenv

import pytz
import calendar

from werkzeug.security import generate_password_hash

app = Flask(__name__)

conn = psycopg2.connect("postgresql://postgres.mggobpvspdsuimokmlwc:EyEcansEEoptical@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres")
cursor = conn.cursor(cursor_factory=RealDictCursor)

# ✅ Set a unique and secret key
app.secret_key = os.environ.get('SECRET_KEY', 'fallback_dev_key')


@app.route('/')
def index():
    tz = pytz.UTC  # Change this to your DB timezone if different

    today = date.today()
    today_start = tz.localize(datetime.combine(today, time.min))
    today_end = tz.localize(datetime.combine(today, time.max))

    print("today_start:", today_start)
    print("today_end:", today_end)

    # Count patients added today (assuming patient.date is a date field)
    cursor.execute("SELECT COUNT(*) FROM patient WHERE date = %s", (today,))
    patients_today = cursor.fetchone()['count']

    # Count appointments scheduled today between start and end datetime
    cursor.execute("""
        SELECT COUNT(*) FROM appointment
        WHERE appointment_date >= %s AND appointment_date <= %s
    """, (today_start, today_end))
    appointments_today = cursor.fetchone()['count']

    # Count pending payments for today
    cursor.execute("""
        SELECT COUNT(*) FROM invoice
        WHERE transaction_date::date = %s
        AND NOT EXISTS (
            SELECT 1 FROM unnest(payment) AS p
            WHERE p->>'payment_status' = 'Paid'
        )
    """, (today,))
    pending_payments = cursor.fetchone()['count']

    # Count paid invoices based on payment.date_paid matching today
    cursor.execute("""
        SELECT COUNT(*) FROM invoice
        WHERE EXISTS (
            SELECT 1 FROM unnest(payment) AS p
            WHERE p->>'payment_status' = 'Paid'
            AND (p->>'date_paid')::date = %s
        )
    """, (today,))
    sales_today = cursor.fetchone()['count']

    # Recent appointments before today_start
    cursor.execute("""
        SELECT appointment_id, patient_fname, patient_minitial, patient_lname,
               purpose, appointment_date, status
        FROM appointment
        WHERE appointment_date < %s
        ORDER BY appointment_date DESC
        LIMIT 10
    """, (today_start,))
    recent_appointments = cursor.fetchall()

    # Upcoming appointments from today_start onwards
    cursor.execute("""
        SELECT appointment_id, patient_fname, patient_minitial, patient_lname,
               purpose, appointment_date, status
        FROM appointment
        WHERE appointment_date >= %s
        ORDER BY appointment_date ASC
        LIMIT 10
    """, (today_start,))
    upcoming_appointments = cursor.fetchall()

    print("Recent appointments:", recent_appointments)
    print("Upcoming appointments:", upcoming_appointments)

    # Monthly revenue from invoice table
    cursor.execute("""
        SELECT 
            DATE_TRUNC('month', transaction_date) AS month,
            SUM(CAST(total_price AS numeric)) AS total
        FROM invoice
        GROUP BY month
        ORDER BY month ASC
        LIMIT 12
    """)
    monthly_data = cursor.fetchall()

    month_labels = [row['month'].strftime('%b %Y') for row in monthly_data]
    monthly_totals = [float(row['total']) for row in monthly_data]

    target = 10000
    total_actual = sum(monthly_totals)
    sales_target = target * len(monthly_totals)

    return render_template('index.html',
                           dashboard={
                               'patients': patients_today,
                               'appointments': appointments_today,
                               'pending_payments': pending_payments,
                               'sales': sales_today
                           },
                           recent_appointments=recent_appointments,
                           upcoming_appointments=upcoming_appointments,
                           month_labels=month_labels,
                           monthly_totals=monthly_totals,
                           sales_target=sales_target,
                           sales_actual=total_actual
                           )

@app.template_filter('format_time')
def format_time(value):
    return value.strftime('%I:%M %p') if isinstance(value, datetime) else value


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

@app.route('/update_appointment_status/<int:appointment_id>', methods=['POST'])
def update_appointment_status(appointment_id):
    new_status = request.form.get('status')
    if new_status:
        cursor.execute("UPDATE appointment SET status = %s WHERE appointment_id = %s", (new_status, appointment_id))
        conn.commit()
    return redirect(request.referrer or url_for('appointments'))  # or your appointments route



@app.route('/patients')
def patient_records():
    status = request.args.get('status', 'All')

    # Update number_of_visit for each patient based on count of invoices
    cursor.execute("""
        UPDATE patient SET number_of_visit = sub.invoice_count
        FROM (
            SELECT patient_id, COUNT(*) AS invoice_count
            FROM invoice
            GROUP BY patient_id
        ) AS sub
        WHERE patient.patient_id = sub.patient_id
    """)
    conn.commit()

    # Fetch patients according to filter
    if status == 'All':
        cursor.execute("SELECT * FROM patient")
    else:
        cursor.execute("SELECT * FROM patient WHERE status = %s", (status,))

    patients = cursor.fetchall()
    return render_template("tables.html", patients=patients, status=status)


@app.route('/add_patient', methods=['POST'])
def add_patient():
    # Extract form data
    patient_fname = request.form.get('patient_fname')
    patient_minitial = request.form.get('patient_minitial')
    patient_lname = request.form.get('patient_lname')
    email = request.form.get('email')
    age = request.form.get('age')
    birthday = request.form.get('birthday')  # YYYY-MM-DD format string
    gender = request.form.get('gender')
    contact_details = request.form.get('contact_details')
    province = request.form.get('province')
    city = request.form.get('city')
    barangay = request.form.get('barangay')
    street = request.form.get('street')
    occupation = request.form.get('occupation')
    date = request.form.get('date')  # YYYY-MM-DD format string

    # Validation (optional)
    if not patient_fname or not patient_lname:
        flash('First and last name are required.', 'danger')
        return redirect(url_for('index'))

    cursor.execute("""
        INSERT INTO patient (
            patient_fname, patient_minitial, patient_lname, email, age, birthday,
            gender, contact_details, province, city, barangay, street, occupation, date
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        patient_fname, patient_minitial, patient_lname, email, age, birthday,
        gender, contact_details, province, city, barangay, street, occupation, date
    ))

    # ✅ Commit using the actual connection object
    conn.commit()

    flash('New patient added successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/update_eye_results', methods=['POST'])
def update_eye_results():
    # Get form data
    result_id = request.form.get('eye_results_id')
    medical_history = request.form.get('medical_history')
    old_rx_od = request.form.get('old_rx_od')
    old_rx_os = request.form.get('old_rx_os')
    old_va_od = request.form.get('old_va_od')
    old_va_os = request.form.get('old_va_os')
    old_add_od = request.form.get('old_add_od')
    old_add_os = request.form.get('old_add_os')
    bp = request.form.get('bp')
    ishihara_result = request.form.get('ishihara_result')

    if not result_id:
        flash('Missing result ID. Cannot update.', 'danger')
        return redirect(url_for('patient_records'))  # Or the appropriate route

    try:
        cursor.execute("""
            UPDATE eyeresult
            SET medical_history = %s,
                old_rx_od = %s,
                old_rx_os = %s,
                old_va_od = %s,
                old_va_os = %s,
                old_add_od = %s,
                old_add_os = %s,
                bp = %s,
                ishihara_result = %s
            WHERE eye_results_id = %s
        """, (
            medical_history,
            old_rx_od,
            old_rx_os,
            old_va_od,
            old_va_os,
            old_add_od,
            old_add_os,
            bp,
            ishihara_result,
            result_id
        ))

        conn.commit()
        flash('Eye results updated successfully.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error updating eye results: {str(e)}', 'danger')

    return redirect(url_for('patient_records'))  # Replace 'index' with your view function name


@app.route('/update_prescription', methods=['POST'])
def update_prescription():
    prescription_id = request.form.get('prescription_id')
    prescription_date = request.form.get('prescription_date')
    distance_rx_od = request.form.get('distance_rx_od')
    distance_rx_os = request.form.get('distance_rx_os')
    contact_rx_od = request.form.get('contact_rx_od')
    contact_rx_os = request.form.get('contact_rx_os')
    reading_rx_od = request.form.get('reading_rx_od')
    reading_rx_os = request.form.get('reading_rx_os')
    sph_od = request.form.get('sph_od')
    sph_os = request.form.get('sph_os')
    cyl_od = request.form.get('cyl_od')
    cyl_os = request.form.get('cyl_os')
    axis_od = request.form.get('axis_od')
    axis_os = request.form.get('axis_os')
    va_od = request.form.get('va_od')
    va_os = request.form.get('va_os')
    add_od = request.form.get('add_od')
    add_os = request.form.get('add_os')
    mono_od = request.form.get('mono_od')
    pd_os = request.form.get('pd_os')
    seg_ht_od = request.form.get('seg_ht_od')
    vert_ht_os = request.form.get('vert_ht_os')
    pd = request.form.get('pd')

    if not prescription_id:
        flash('Missing prescription ID. Cannot update.', 'danger')
        return redirect(url_for('patient_records'))  # Adjust this route

    try:
        cursor.execute("""
            UPDATE prescription
            SET prescription_date = %s,
                distance_rx_od = %s,
                distance_rx_os = %s,
                contact_rx_od = %s,
                contact_rx_os = %s,
                reading_rx_od = %s,
                reading_rx_os = %s,
                sph_od = %s,
                sph_os = %s,
                cyl_od = %s,
                cyl_os = %s,
                axis_od = %s,
                axis_os = %s,
                va_od = %s,
                va_os = %s,
                add_od = %s,
                add_os = %s,
                mono_od = %s,
                pd_os = %s,
                seg_ht_od = %s,
                vert_ht_os = %s,
                pd = %s
            WHERE prescription_id = %s
        """, (
            prescription_date,
            distance_rx_od,
            distance_rx_os,
            contact_rx_od,
            contact_rx_os,
            reading_rx_od,
            reading_rx_os,
            sph_od,
            sph_os,
            cyl_od,
            cyl_os,
            axis_od,
            axis_os,
            va_od,
            va_os,
            add_od,
            add_os,
            mono_od,
            pd_os,
            seg_ht_od,
            vert_ht_os,
            pd,
            prescription_id
        ))

        conn.commit()
        flash('Prescription updated successfully.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error updating prescription: {str(e)}', 'danger')

    return redirect(url_for('patient_records'))  # Adjust to your actual route



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

    # Get most frequent patient
    cursor.execute("""
        SELECT * FROM patient
        ORDER BY number_of_visit DESC
        LIMIT 1
    """)
    most_frequent_patient = cursor.fetchone()

    # 🔧 Get all patients (for the dropdown list in the modal)
    cursor.execute("SELECT patient_id, patient_fname, patient_minitial, patient_lname FROM patient")
    all_patients = cursor.fetchall()

    # 🔄 Convert each row to dictionary (in case it's not already)
    all_patients_json = []
    for p in all_patients:
        all_patients_json.append({
            "patient_id": p['patient_id'],
            "patient_fname": p['patient_fname'],
            "patient_minitial": p['patient_minitial'] or "",
            "patient_lname": p['patient_lname']
        })

    return render_template(
        'invoice.html',
        invoices=invoices,
        total_earnings=total_earnings,
        overdue_count=overdue_count,
        most_frequent_patient=most_frequent_patient,
        all_patients=all_patients_json  # ✅ Now available for tojson
    )



@app.route('/update_invoice', methods=['POST'])
def update_invoice():
    invoice_id = request.form['invoice_id']
    invoice_number = request.form['invoice_number']
    transaction_date = request.form['transaction_date']
    claim_date = request.form['claim_date']
    frame_price = request.form['frame_price']
    lens_price = request.form['lens_price']
    additional_price = request.form['additional_price']
    total_price = request.form['total_price']
    deposit_amount = request.form['deposit_amount']
    balance_due = request.form['balance_due']

    try:
        cursor.execute("""
            UPDATE invoice
            SET invoice_number = %s,
                transaction_date = %s,
                claim_date = %s,
                frame_price = %s,
                lens_price = %s,
                additional_price = %s,
                total_price = %s,
                deposit_amount = %s,
                balance_due = %s
            WHERE invoice_id = %s
        """, (
            invoice_number, transaction_date, claim_date,
            frame_price, lens_price, additional_price,
            total_price, deposit_amount, balance_due, invoice_id
        ))
        conn.commit()
        flash('Invoice updated successfully.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error updating invoice: {str(e)}', 'danger')

    return redirect(url_for('patient_records'))


@app.route('/add_payment', methods=['POST'])
def add_payment():
    invoice_id = request.form['invoice_id']
    date_paid = request.form['date_paid']
    amount_paid = request.form['amount_paid']
    payment_method = request.form['payment_method']
    payment_status = request.form['payment_status']

    # Generate 'time_ago'
    today = datetime.today()
    paid_date = datetime.strptime(date_paid, '%Y-%m-%d')
    days_ago = (today - paid_date).days
    time_ago = f"{days_ago} day(s) ago" if days_ago > 0 else "Today"

    # Stringify the payment as a single JSON string to store in TEXT[]
    payment_entry = json.dumps({
        "date_paid": date_paid,
        "amount_paid": amount_paid,
        "payment_method": payment_method,
        "payment_status": payment_status,
        "time_ago": time_ago
    })

    try:
        # Append to PostgreSQL array using array_append
        cursor.execute("""
            UPDATE invoice
            SET payment = array_append(payment, %s)
            WHERE invoice_id = %s
        """, (payment_entry, invoice_id))
        conn.commit()
        flash('Payment added successfully.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error adding payment: {str(e)}', 'danger')

    return redirect(url_for('patient_records'))


@app.route('/add_invoice', methods=['POST'])
def add_invoice():
    try:
        patient_type = request.form.get('patient_type')  # 'new' or 'returning'
        patient_id = request.form.get('patient_id')

        if not patient_id:
            flash('Patient ID is required.', 'danger')
            return redirect(url_for('invoices'))

        if patient_type == 'new':
            patient_fname = request.form['patient_fname']
            patient_minitial = request.form.get('patient_minitial', '')
            patient_lname = request.form['patient_lname']

            cursor.execute("""
                INSERT INTO patient (patient_id, patient_fname, patient_minitial, patient_lname, number_of_visit)
                VALUES (%s, %s, %s, %s, 1)
            """, (patient_id, patient_fname, patient_minitial, patient_lname))
        elif patient_type == 'returning':
            cursor.execute("""
                UPDATE patient SET number_of_visit = number_of_visit + 1 WHERE patient_id = %s
            """, (patient_id,))
        else:
            flash('Invalid patient type.', 'danger')
            return redirect(url_for('invoices'))

        # Extract invoice data
        invoice_number = request.form['invoice_number']
        transaction_date = request.form['transaction_date']
        claim_date = request.form['claim_date']
        frame_price = float(request.form['frame_price'])
        lens_price = float(request.form['lens_price'])
        additional_price = float(request.form['additional_price'])
        total_price = float(request.form['total_price'])
        deposit_amount = float(request.form['deposit_amount'])
        balance_due = float(request.form['balance_due'])

        cursor.execute("""
            INSERT INTO invoice (
                patient_id, invoice_number, transaction_date, claim_date,
                frame_price, lens_price, additional_price, total_price,
                deposit_amount, balance_due, payment,
                patient_fname, patient_minitial, patient_lname
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            patient_id, invoice_number, transaction_date, claim_date,
            frame_price, lens_price, additional_price, total_price,
            deposit_amount, balance_due, [],
            request.form['patient_fname'],
            request.form.get('patient_minitial', ''),
            request.form['patient_lname']
        ))

        conn.commit()
        flash('Invoice added successfully.', 'success')

    except Exception as e:
        conn.rollback()
        flash(f'Error adding invoice: {e}', 'danger')

    return redirect(url_for('invoices'))

@app.route('/delete_invoice/<int:invoice_id>', methods=['POST'])
def delete_invoice(invoice_id):
    try:
        cursor.execute("DELETE FROM invoice WHERE invoice_id = %s", (invoice_id,))
        conn.commit()
        flash('Invoice deleted successfully.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting invoice: {e}', 'danger')
    return redirect(url_for('invoices'))  # or wherever you want to redirect after deletion


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


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        user_type = request.form['user_type']
        first_name = request.form['first_name']
        middle_initial = request.form['middle_initial']
        last_name = request.form['last_name']
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Passwords do not match!', 'danger')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)

        print("Form received:", request.form.to_dict())

        try:
            if user_type == 'admin':
                role = request.form.get('role')
                contact_info = request.form.get('contact_info')

                print("Inserting admin record...")
                cursor.execute("""
                    INSERT INTO admin (
                        admin_fname, admin_minitial, admin_lname,
                        admin_username, email, password, role, contact_info
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    first_name, middle_initial, last_name,
                    username, email, hashed_password, role, contact_info
                ))
            else:
                print("Inserting user record...")
                cursor.execute("""
                    INSERT INTO users (
                        user_fname, user_minitial, user_lname,
                        user_username, email, password
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    first_name, middle_initial, last_name,
                    username, email, hashed_password
                ))

            conn.commit()
            flash('Account created successfully!', 'success')
            return redirect(url_for('index'))

        except psycopg2.Error as e:
            conn.rollback()
            print("Database error:", e.pgerror)
            flash(f"Database error: {e.pgerror}", 'danger')
            return redirect(url_for('register'))

    return render_template('register.html')



if __name__ == '__main__':
    app.run(debug=True)
