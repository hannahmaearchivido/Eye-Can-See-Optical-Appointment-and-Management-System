import os
import pickle
import traceback


import cursor
import psycopg2


from flask import Flask, render_template, request, json, jsonify
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from datetime import datetime, date, timedelta, time
from flask import request, redirect, url_for, flash

import pytz
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


@app.route('/update_appointment_status/<appointment_id>', methods=['POST'])
def update_appointment_status(appointment_id):
    new_status = request.form.get('status')
    if new_status:
        cursor.execute("UPDATE appointment SET status = %s WHERE appointment_id = %s", (new_status, appointment_id))
        conn.commit()
    return redirect(request.referrer or url_for('appointments'))  # or your appointments route


@app.route('/optical_product_table')
def optical_product_table(editing_item=None):  # accept argument
    inventory_tables = [
        {'name': 'eyeglassframeinventory', 'id_field': 'eyeglass_frame_id'},
        {'name': 'contactlensinventory', 'id_field': 'contact_lens_id'},
        {'name': 'sunglassinventory', 'id_field': 'sunglass_id'},
        {'name': 'lenscleaninginventory', 'id_field': 'lens_cleaning_id'},
        {'name': 'eyeglasscaseinventory', 'id_field': 'eyeglass_case_id'},
        {'name': 'contactlenscaseinventory', 'id_field': 'contactlens_case_id'},
        {'name': 'contactlenssolutioninventory', 'id_field': 'contactlens_solution_id'},
        {'name': 'repairkitinventory', 'id_field': 'repair_kit_id'},
        {'name': 'cliponlensinventory', 'id_field': 'clipon_lens_id'},
        {'name': 'frameaccessoryinventory', 'id_field': 'accessory_id'},
        {'name': 'antiradiationcoatinginventory', 'id_field': 'antiradiation_coating_id'},
        {'name': 'antireflectivecoatinginventory', 'id_field': 'antireflective_coating_id'},
        {'name': 'photochromicinventory', 'id_field': 'photochromic_id'},
        {'name': 'tintedinventory', 'id_field': 'tinted_id'},
        {'name': 'progressiveinventory', 'id_field': 'progressive_id'}
    ]

    inventory_data = []

    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        for table in inventory_tables:
            query = sql.SQL("SELECT * FROM {}").format(sql.Identifier(table['name']))
            cursor.execute(query)
            rows = cursor.fetchall()

            if not rows:
                continue

            column_names = list(rows[0].keys())

            for row in rows:
                stock = row.get('current_stock', 0)
                max_stock = 25
                stock_percent = (stock / max_stock) * 100 if max_stock else 0

                if stock == 0:
                    bar_color, label, badge, labeltext = 'bg-dark', 'Out of Stock', 'badge-dark', 'text-dark'
                elif stock_percent < 30:
                    bar_color, label, badge, labeltext = 'bg-danger', 'Low', 'badge-danger', 'text-danger'
                elif stock_percent < 70:
                    bar_color, label, badge, labeltext = 'bg-warning', 'Medium', 'badge-warning', 'text-warning'
                else:
                    bar_color, label, badge, labeltext = 'bg-success', 'High', 'badge-success', 'text-success'

                inventory_data.append({
                    'table': table['name'],
                    'item_id': row.get(table['id_field']),
                    'stock': stock,
                    'stock_percent': round(stock_percent, 2),
                    'bar_color': bar_color,
                    'label': label,
                    'badge': badge,
                    'labeltext': labeltext,
                    'item_data': row,
                    'column_names': column_names
                })

    return render_template('inventoryOpticalProduct.html', inventory_data=inventory_data, editing_item=editing_item)

@app.route('/lens_table')
def lens_table(editing_item=None):  # accept argument
    inventory_tables = [
        {'name': 'antiradiationcoatinginventory', 'id_field': 'antiradiation_coating_id'},
        {'name': 'antireflectivecoatinginventory', 'id_field': 'antireflective_coating_id'},
        {'name': 'photochromicinventory', 'id_field': 'photochromic_id'},
        {'name': 'tintedinventory', 'id_field': 'tinted_id'},
        {'name': 'progressiveinventory', 'id_field': 'progressive_id'}
    ]

    inventory_data = []

    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        for table in inventory_tables:
            query = sql.SQL("SELECT * FROM {}").format(sql.Identifier(table['name']))
            cursor.execute(query)
            rows = cursor.fetchall()

            if not rows:
                continue

            column_names = list(rows[0].keys())

            for row in rows:
                stock = row.get('current_stock', 0)
                max_stock = 25
                stock_percent = (stock / max_stock) * 100 if max_stock else 0

                if stock == 0:
                    bar_color, label, badge, labeltext = 'bg-dark', 'Out of Stock', 'badge-dark', 'text-dark'
                elif stock_percent < 30:
                    bar_color, label, badge, labeltext = 'bg-danger', 'Low', 'badge-danger', 'text-danger'
                elif stock_percent < 70:
                    bar_color, label, badge, labeltext = 'bg-warning', 'Medium', 'badge-warning', 'text-warning'
                else:
                    bar_color, label, badge, labeltext = 'bg-success', 'High', 'badge-success', 'text-success'

                inventory_data.append({
                    'table': table['name'],
                    'item_id': row.get(table['id_field']),
                    'stock': stock,
                    'stock_percent': round(stock_percent, 2),
                    'bar_color': bar_color,
                    'label': label,
                    'badge': badge,
                    'labeltext': labeltext,
                    'item_data': row,
                    'column_names': column_names
                })

    return render_template('inventoryLens.html', inventory_data=inventory_data, editing_item=editing_item)

@app.route('/patients')
def patient_records():
    status = request.args.get('status', 'All')

    # ✅ Update number_of_visit safely — no parameters needed here
    cursor.execute("""
        UPDATE patient SET number_of_visit = sub.invoice_count
        FROM (
            SELECT patient_id, COUNT(*) AS invoice_count
            FROM invoice
            GROUP BY patient_id
        ) AS sub
        WHERE patient.patient_id = sub.patient_id::text
    """)
    conn.commit()

    # ✅ Safe parameterized SELECT
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


@app.route("/invoice_eyeexam")
def invoice_eyeexam():
    cursor.execute("SELECT * FROM eyeexam")
    eyeexams = cursor.fetchall()

    cursor.execute("SELECT * FROM contactlensfitting")
    contactlensfittings = cursor.fetchall()

    cursor.execute("SELECT * FROM colorvisiontesting")
    colorvision = cursor.fetchall()

    cursor.execute("SELECT * FROM ocularhealthscreening")
    ocularhealth = cursor.fetchall()

    return render_template("invoiceEyeExam.html",  eyeexams=eyeexams, contactlensfittings=contactlensfittings, colorvision=colorvision, ocularhealth=ocularhealth)


@app.route("/invoice_opticalproduct")
def invoice_opticalproduct():
    cursor.execute("SELECT * FROM eyeglassframe")
    eyeglassframe = cursor.fetchall()

    cursor.execute("SELECT * FROM contactlens")
    contactlense = cursor.fetchall()

    cursor.execute("SELECT * FROM sunglass")
    sunglass = cursor.fetchall()

    cursor.execute("SELECT * FROM lenscleaning")
    lenscleaning = cursor.fetchall()

    cursor.execute("SELECT * FROM eyeglasscase")
    eyeglasscase = cursor.fetchall()

    cursor.execute("SELECT * FROM contactlenscase")
    contactlensecase = cursor.fetchall()

    cursor.execute("SELECT * FROM contactlenssolution")
    contactlenssolution = cursor.fetchall()

    cursor.execute("SELECT * FROM repairkit")
    repairkit = cursor.fetchall()

    cursor.execute("SELECT * FROM cliponlens")
    cliponlens = cursor.fetchall()

    cursor.execute("SELECT * FROM frameaccessory")
    frameaccessory = cursor.fetchall()

    return render_template("invoiceOpticalProduct.html", eyeglassframe=eyeglassframe, contactlense=contactlense, sunglass=sunglass, lenscleaning=lenscleaning, eyeglasscase=eyeglasscase,
        contactlensecase=contactlensecase, contactlenssolution=contactlenssolution, repairkit=repairkit, cliponlens=cliponlens,
        frameaccessory=frameaccessory)

@app.route("/invoice_lens")
def invoice_lens():
    cursor.execute("SELECT * FROM antiradiationcoating")
    antiradiationcoating = cursor.fetchall()

    cursor.execute("SELECT * FROM antireflectivecoating")
    antireflectivecoating = cursor.fetchall()

    cursor.execute("SELECT * FROM photochromic")
    photochromatic = cursor.fetchall()

    cursor.execute("SELECT * FROM tinted")
    tinted = cursor.fetchall()

    cursor.execute("SELECT * FROM progressive")
    progressive = cursor.fetchall()

    return render_template("invoiceLens.html",  antiradiationcoating=antiradiationcoating, antireflectivecoating=antireflectivecoating,
        photochromatic=photochromatic, tinted=tinted, progressive=progressive)


@app.route("/add_new_record_form")
def add_new_record_form():
    # Get all patients (for the dropdown list in the modal)
    cursor.execute("SELECT patient_id, patient_fname, patient_minitial, patient_lname, age, gender FROM patient")
    all_patients = cursor.fetchall()

    # Convert each row to dictionary (in case it's not already)
    all_patients_json = []
    for p in all_patients:
        all_patients_json.append({
            "patient_id": p['patient_id'],
            "patient_fname": p['patient_fname'],
            "patient_minitial": p['patient_minitial'] or "",
            "patient_lname": p['patient_lname'],
            "age": p['age'],
            "gender": p['gender']
        })

    return render_template("invoiceAddNew.html", all_patients=all_patients_json)


@app.route("/invoice_billing")
def invoice_billing():
    cursor.execute("SELECT * FROM invoices")
    invoices = cursor.fetchall()

    cursor.execute("SELECT * FROM payment_receipt")
    payment_receipts = cursor.fetchall()

    return render_template("invoiceBilling.html",  invoices=invoices, payment_receipts=payment_receipts)


@app.route('/invoices')
def invoices():
    cursor.execute("SELECT * FROM invoices")
    invoices = cursor.fetchall()

    cursor.execute("SELECT * FROM payment_receipt")
    payment_receipts = cursor.fetchall()

    total_earnings = 0
    overdue_count = 0

    for inv in invoices:
        total_earnings += inv['total_price'] or 0

        payments = inv.get('payment') or []
        if payments:
            # ✅ No need for json.loads — already a dict
            latest_payment = payments[-1]
            inv['payment_method'] = latest_payment.get('payment_method')
            inv['payment_status'] = latest_payment.get('payment_status')
        else:
            inv['payment_method'] = None
            inv['payment_status'] = None

        if inv.get('payment_status') == 'Partial':
            overdue_count += 1

    # Monthly revenue from invoice table
    cursor.execute("""            SELECT 
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


    return render_template(
        'invoice.html', invoices=invoices, payment_receipts=payment_receipts,  total_earnings=total_earnings,
        overdue_count=overdue_count, month_labels=month_labels, monthly_totals=monthly_totals, sales_target=sales_target,
        sales_actual=total_actual
    )


@app.route('/add_exam', methods=['POST'])
def add_exam():
    service_type = request.form.get('service_type')

    field_map = {
        "eyeexam": {
            "table": "eyeexam",
            "prefix": "EYEEXAM",
            "id_field": "eye_exam_id",
            "success_msg": "Eye Exam added successfully."
        },
        "contactlensfitting": {
            "table": "contactlensfitting",
            "prefix": "LENSFITTING",
            "id_field": "contact_lens_fitting_id",
            "success_msg": "Contact Lens Fitting added successfully."
        },
        "colorvisiontesting": {
            "table": "colorvisiontesting",
            "prefix": "COLORVISION",
            "id_field": "color_vision_testing_id",
            "success_msg": "Color Vision Testing added successfully."
        },
        "ocularhealthscreening": {
            "table": "ocularhealthscreening",
            "prefix": "OCUHEALTH",
            "id_field": "ocular_health_screening_id",
            "success_msg": "Ocular Health Screening added successfully."
        }
    }

    if service_type not in field_map:
        flash("Invalid service type.", "danger")
        return redirect(url_for("invoices"))

    mapping = field_map[service_type]

    # Debug print all incoming form data
    print("== FORM DATA ==")
    print(request.form)

    # Collect form values
    patient_id = request.form.get('patient_id')
    patient_fname = request.form.get('patient_fname')
    patient_minitial = request.form.get('patient_minitial')
    patient_lname = request.form.get('patient_lname')
    age = request.form.get('age')
    gender = request.form.get('gender')
    date_val = request.form.get('date')
    amount = request.form.get('amount')

    try:
        # Generate next unique ID
        query = sql.SQL("SELECT {id_field} FROM {table}").format(
            id_field=sql.Identifier(mapping['id_field']),
            table=sql.Identifier(mapping['table'])
        )
        cursor.execute(query)
        existing_ids = cursor.fetchall()

        max_num = 0
        for row in existing_ids:
            unique_id = row[mapping['id_field']]
            if unique_id and unique_id.startswith(mapping["prefix"]):
                try:
                    num = int(unique_id.split("-")[1])
                    max_num = max(max_num, num)
                except ValueError:
                    continue

        new_id = f"{mapping['prefix']}-{max_num + 1}"

        # Insert record
        insert_query = sql.SQL("""
            INSERT INTO {table} (
                {id_field}, patient_id, patient_fname, patient_minitial,
                patient_lname, age, gender, date, amount
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """).format(
            table=sql.Identifier(mapping['table']),
            id_field=sql.Identifier(mapping['id_field'])
        )
        cursor.execute(insert_query, (
            new_id, patient_id, patient_fname, patient_minitial,
            patient_lname, int(age) if age else None,
            gender, date_val, float(amount) if amount else None
        ))
        conn.commit()
        flash(mapping["success_msg"], "success")

    except Exception as e:
        conn.rollback()
        print("=== ERROR OCCURRED ===")
        traceback.print_exc()  # Logs full error to terminal
        flash(f"Error adding service: {str(e)}", "danger")

    return redirect(url_for("invoice_eyeexam"))

# Sample data — in real app, you’d query from a database
sunglass_models = {
    'Ray-Ban': ['RB-2132', 'RB-3025', 'RB-3447'], 'Oakley': ['OX-8046', 'OX-3217', 'OX-5141'], 'Gucci': ['GG-0061O', 'GG-0449S', 'GG-0036O'],
    'Prada': ['PD-2132', 'PD-3025', 'PD-3447'], 'Tom Ford': ['TF-8046', 'TF-3217', 'TF-5141'], 'Versace': ['VS-0061O', 'VS-0449S', 'VS-0036O'],
    'Burberry': ['BB-0061O', 'BB-0449S', 'BB-0036O'], 'Dolce & Gabbana': ['DG-2132', 'DG-3025', 'DG-3447'], 'Persol': ['PS-8046', 'PS-3217', 'PS-5141'],
    'Cartier': ['CT-0061O', 'CT-0449S', 'CT-0036O'], 'Armani Exchange': ['AE-2132', 'AE-3025', 'AE-3447'], 'Fossil': ['FS-8046', 'FS-3217', 'FS-5141'],
    'Michael Kors': ['MK-0061O', 'MK-0449S', 'MK-0036O'], 'Coach': ['CC-8046', 'CC-3217', 'CC-5141'], 'Guess': ['GS-0061O', 'GS-0449S', 'GS-0036O'],
    'Levi': ['LV-2132', 'LV-3025', 'LV-3447'], 'Nike': ['NK-0061O', 'NK-0449S', 'NK-0036O'], 'Adidas': ['AD-8046', 'AD-3217', 'AD-5141'],
    'Hugo Boss': ['HB-0061O', 'HB-0449S', 'HB-0036O'], 'EyeBuyDirect': ['EB-2132', 'EB-3025', 'EB-3447'], 'Zenni Optical': ['ZO-0061O', 'ZO-0449S', 'ZO-0036O'],
    'Warby Parker': ['WP-8046', 'WP-3217', 'WP-5141'], 'Vogue Eyewear': ['VE-0061O', 'VE-0449S', 'VE-0036O'], 'Titan': ['TT-2132', 'TT-3025', 'TT-3447'],
    'Lenskart': ['LK-0061O', 'LK-0449S', 'LK-0036O'], 'Generic': ['GR-8046', 'GR-3217', 'GR-5141'], 'OEM': ['OE-0061O', 'OE-0449S', 'OE-0036O'],
    'Ideal Vision': ['IV-2132', 'IV-3025', 'IV-3447'], 'Executive Optical': ['EO-0061O', 'EO-0449S', 'EO-0036O'], 'Owndays': ['OD-8046', 'OD-3217', 'OD-5141'],
    'George Optical': ['GO-0061O', 'GO-0449S', 'GO-0036O'], 'Vision Express': ['VE-2132', 'VE-3025', 'VE-3447']
}

contactLensModels = {
    'Acuvue': ['Oasys', 'Oasys 1-Day', 'Moist for Astigmatism', 'Vita'], 'Air Optix': ['Plus HydraGlyde', 'Colors', 'Night & Day Aqua'],
    'Dailies': ['AquaComfort Plus', 'Total1', 'Total1 Multifocal'], 'Biofinity': ['Biofinity', 'Biofinity Toric', 'Biofinity Multifocal'],
    'FreshLook': ['ColorBlends', 'One-Day Colors'], 'Bausch + Lomb': ['ULTRA', 'ULTRA for Presbyopia', 'PureVision2'],
    'Clariti': ['Clariti 1 Day', 'Clariti 1 Day Multifocal'], 'Miacare': ['Confidence', 'Delight'],
    'Hydron': ['Hydron Aqua', 'Hydron Flex'], 'Geo Medical': ['Geo Nudy', 'Geo Angel'],
    'Alcon': ['Dailies Total1', 'Air Optix Night & Day'], 'SEED': ['1dayPure Moisture', 'MonthlyFine']
}

lenscleaningModels = {
    'Zeiss': ['Zeiss Lens Cleaning Spray 60ml', 'Zeiss Lens Wipes (Pre-moistened)'], 'Peeps': ['Peeps CarbonKlean Lens Cleaner'],
    'Koala': ['Koala Kleaner Natural Lens Spray', 'Koala Kleaner 2oz Spray with Cloth'], 'Calyptus': ['Calyptus Natural Eyeglass Lens Cleaner'],
    'MagicFiber': ['MagicFiber Lens Cleaner Spray with Cloth'], 'Optix 55': ['Optix 55 Streak-Free Lens Cleaner'], 'Specsavers': ['Specsavers Anti-Fog & Cleaning Spray'],
    'Hilco Vision': ['Hilco Cleaning Spray Pro Series'], 'Bausch': ['Sight Savers Lens Cleaning Spray'], 'iCloth': ['iCloth Small Lens Wipes'],
    'Eye Mo': ['Eye Mo Lens & Screen Cleaner Spray'], 'Sereese': ['Sereese Eyewear Cleaning Spray', 'Sereese Premium Anti-Fog Lens Cleaner'],
    'Lensguard PH': ['Lensguard Premium Lens Cleaning Spray', 'Lensguard Pocket Spray'], 'Voptica': ['Voptica Vision Lens Cleaner'], 'ClearView': ['ClearView Anti-Reflective Lens Spray'],
    'Aqua Lens Care': ['Aqua Lens Multi-purpose Lens Solution'], 'Bright Vision': ['Bright Vision Lens Kit Spray'], 'VisionMate': ['VisionMate Fog-Free & Clean Spray']
}

contactLensCaseModels = {
    'Acuvue': ['Oasys', 'Oasys 1-Day', 'Moist for Astigmatism', 'Vita'], 'Bausch': ['ULTRA', 'ULTRA for Presbyopia', 'PureVision2', 'Biotrue ONEday'],
    'Alcon': ['Dailies Total1', 'Air Optix Plus HydraGlyde', 'Air Optix Night & Day Aqua', 'Precision1', 'Dailies AquaComfort Plus'],
    'Clear Care': ['Clear Care Cleaning & Disinfecting Solution (used with Barrel Case)'], 'Renu': ['Renu Advanced Formula Multi-Purpose Solution (with Flat Case)'],
    'Boston': ['Boston Advance Comfort Formula (for RGP lenses)'], 'Solo Care': ['Solo Care Aqua (Multi-Purpose Solution with Case)'],
    'Equate': ['Equate Saline Solution (with Standard Case)']
}

contactSolutionModels = {
    'Renu': ['Renu Advanced Formula Multi-Purpose Solution', 'Renu Fresh Multi-Purpose Solution'],
    'Opti-Free': ['Opti-Free PureMoist Multi-Purpose Disinfecting Solution', 'Opti-Free Replenish Multi-Purpose Solution', 'Opti-Free Express Lasting Comfort Formula'],
    'Biotrue': ['Biotrue Multi-Purpose Solution', 'Biotrue Hydration Boost Contact Lens Solution'], 'AOSept Plus': ['AOSept Plus with HydraGlyde'],
    'Clear Care': ['Clear Care Cleaning & Disinfecting Solution', 'Clear Care Plus with HydraGlyde'], 'Complete': ['Complete Multi-Purpose Solution Easy Rub Formula'],
    'RevitaLens': ['RevitaLens OcuTec Disinfecting Solution'], 'Equate': ['Equate Saline Solution', 'Equate Multi-Purpose Solution for Soft Contact Lenses'],
    'Solocare Aqua': ['Solo Care Aqua Multi-Purpose Solution'], 'Sensitive Eyes': ['Sensitive Eyes Saline Solution'], 'Blink': ['Blink Revitalens Multi-Purpose Disinfecting Solution']
}

repairKitModels = {
    'Zacro': ['Zacro Eyeglass Repair Kit with Screws, Nose Pads, Screwdrivers & Tweezers', 'Zacro Mini Eyeglass Repair Kit with 1100 Pieces'],
    'Kingsdun': ['Kingsdun Eyeglass Repair Kit with Magnetic Screwdriver Set', 'Kingsdun Precision Screwdriver Eyeglass Tool Kit with Nose Pads and Screws'],
    'Bayite': ['Bayite Eyeglass Repair Kit with Stainless Steel Screws and Tools'], 'Pilotfish': ['Pilotfish Mini Eyeglass Repair Kit with Double-Ended Screwdriver and Screw Assortment'],
    'Eyekepper': ['Eyekepper Eyeglass Repair Kit with Nose Pads, Screws and Tool Set'], 'HQMaster': ['HQMaster Eyeglass Repair Kit with Precision Screwdrivers and Screw Set'],
    'HDE': ['HDE Eyeglass Repair Kit with Assorted Screws and Nose Pads'], 'Xool': ['Xool Eyeglass Repair Kit with 1000 Screws and Tools for Glasses and Sunglasses'],
    'LaMi': ['LaMi Eyeglass Repair Kit with Case, Screws, and Screwdrivers'], 'ProCase': ['ProCase Eyeglass Repair Kit with Stainless Steel Tools and Travel Case']
}

frameAccessoryModels = {
    'Croakies': ['Croakies Original Eyewear Retainer - Adjustable Neoprene Strap', 'Croakies Terra Spec Cord - Lightweight Nylon Eyewear Retainer'],
    'Chums': ['Chums Classic Cotton Eyewear Retainer', 'Chums Adjustable Orbiter Eyewear Strap with Metal Ends'],
    'Cocoons': ['Cocoons Adjustable Eyewear Retainer Strap for Over-Rx Sunglasses', 'Cocoons Slip Fit Eyewear Cord with Rubber Loop Ends'],
    'Peepers': ['Peepers Beaded Glasses Chain - Vintage Style', 'Peepers Eyewear Cord with Silicone Grips'],
    'Eyewear Chain Co.': ['Eyewear Chain Co. Pearl Chain for Glasses', 'Eyewear Chain Co. Gold Plated Chain with Lobster Clasp Ends'],
    'La Loop': ['La Loop Leather Eyeglass Necklace with Loop Holder', 'La Loop Sterling Silver Chain with Loop Ring for Glasses'],
    'Quay Australia': ['Quay Link Up Chain Eyewear Accessory', 'Quay Luxe Gold Chain for Sunglasses'],
    'Dior': ['Dior Oblique Chain Eyewear Accessory with Logo Charm', 'Dior Sunglass Chain in Gold-Finish Metal'],
    'Ray-Ban': ['Ray-Ban Eyewear Chain in Black Leather', 'Ray-Ban Logo-Branded Nylon Cord with Adjustable Ends'],
    'Prada': ['Prada Polished Metal Glasses Chain with Logo Engraving', 'Prada Eyewear Neck Strap in Saffiano Leather'],
    'Urban Outfitters': ['Urban Outfitters Retro Beaded Glasses Chain', 'Urban Outfitters Chunky Chain Eyeglass Holder'],
    'Vogue Eyewear': ['Vogue Eyewear Gold Tone Chain with Adjustable Ends', 'Vogue Decorative Link Glasses Chain with Branding Detail']
}

antiRadiationCoatingModels = {
  'Crizal': ['Crizal Prevencia', 'Crizal Sapphire HR', 'Crizal Easy Pro', 'Crizal Rock'],
  'Zeiss': ['DuraVision BlueProtect', 'DuraVision Platinum', 'DuraVision Silver', 'DuraVision Chrome'],
  'Hoya': ['BlueControl', 'Hi-Vision LongLife BlueControl', 'Recharge EX3', 'Diamond Finish Blue'],
  'Nikon': ['SeeCoat Blue', 'SeeCoat Bright', 'SeeCoat Plus UV', 'SeeCoat Next Blue'],
  'Transitions': ['Transitions XTRActive Polarized', 'Transitions Signature GEN 8', 'Transitions XTRActive New Generation'],
  'Essilor': ['Eyezen Coating', 'Prevencia', 'Smart Blue Filter'],
  'Kodak': ['Clean&Clear Blue', 'UVBlue', 'Total Blue Lens Coating'],
  'Seiko': ['SuperResistantBlue', 'SRB UV Plus', 'SuperResistant Coating'],
  'Rodenstock': ['Solitaire Protect Balance 2', 'Solitaire Protect Plus 2', 'Solitaire 2 Blue']
}

antiReflectiveCoatingModels = {
  'Crizal': ['Sapphire HR', 'Rock', 'EasyPro', 'Prevencia', 'Forte UV'],
  'Hoya': ['Hi-Vision LongLife', 'Recharge', 'Diamond Finish', 'Hi-Vision Aqua', 'BlueControl'],
  'ZEISS': ['DuraVision Platinum', 'DuraVision BlueProtect', 'LotuTec', 'DuraVision Silver'],
  'Nikon': ['SeeCoat Blue', 'SeeCoat Bright', 'SeeCoat Plus UV', 'SeeCoat Drive'],
  'Kodak': ['Clean&Clear', 'Clean&Clear UVBlue', 'Easy Lens AR'],
  'Rodenstock': ['Solitaire Protect Plus 2', 'Solitaire Red Sun 2', 'Solitaire Protect Balance 2'],
  'Seiko': ['SuperResistantCoat', 'SRB UV', 'P-UV Coating'],
  'Essilor': ['Crizal Sapphire HR', 'Crizal Prevencia', 'Crizal Rock'],
  'Tokai': ['Lutina', 'Blue Light Cut Coat', 'UV420 Plus'],
  'Younger Optics': ['NuPolar AR', 'Transitions AR']
}

photochromicModels = {
    'Transitions': ['Signature GEN 8', 'XTRActive New Generation', 'XTRActive Polarized', 'Vantage','Drivewear'],
    'Essilor': ['Transitions Signature', 'Transitions XTRActive', 'Transitions Vantage', 'Transitions Drivewear'],
    'Hoya': ['Sensity','Sensity 2', 'Sensity Dark', 'Sensity Shine'],
    'Zeiss': ['PhotoFusion X', 'PhotoFusion', 'AdaptiveSun', 'Skylet'],
    'Nikon': ['Transitions GEN 8', 'Transitions XTRActive', 'SeeCoat Photochromic', 'Presio Transitions'],
    'Rodenstock': ['ColorMatic IQ 2', 'ColorMatic 3', 'ColorMatic Sport', 'Impression ColorMatic'],
    'Seiko': ['Photochromic Plus', 'Photochromic Blue', 'Transitions Signature GEN 8']
}
tintedModels = {
    'FreshLook': ['ColorBlends', 'Dimensions', 'One-Day Colors'],
    'Air Optix': ['Colors'],
    'Acuvue': ['Define Radiant Charm', 'Define Accent Style', 'Define Natural Shine'],
    'Solotica': ['Hidrocor', 'Hidrocor Rio', 'Natural Colors', 'Aquarella'],
    'Desio': ['Attitude Collection', 'Two Shades of Grey', 'Sensual Beauty Lenses'],
    'Bella': ['Elite Collection', 'Glow Collection', 'Diamond Collection', 'Natural Collection'],
    'Hydrocore': ['Hidrocor Mel', 'Hidrocor Ocre', 'Hidrocor Quartzo'],
    'Adore': ['Bi-tone', 'Tri-tone', 'Dare', 'Extra'],
    'Geo Medical': ['Geo Nudy', 'Geo Bella', 'Geo Angel', 'Geo Tri Color'],
    'Colorvue': ['Big Eyes', 'TruBlends', 'Fusion', 'Glamour'],
    'Eye FreshGO': ['Pony Series', 'Candy Series', 'Jelly Series'],
    'Anesthesia': ['Addict', 'Dream', 'USA', 'Once'],
    'TTDEye': ['Queen Series', 'Polar Lights Series', 'Icy Blue Series'],
    'Sweety Plus': ['Sweety K Crazy', 'Sweety Ocean', 'Sweety Spatax'],
    'Olens': ['Scandi', 'Russian Velvet', 'Spanish Real', 'Ocean Velvet']
}

progressiveModels = {
  'Essilor': ['Varilux Comfort Max', 'Varilux X Series', 'Varilux Physio', 'Varilux Liberty 3.0'],
  'Zeiss': ['Precision Pure', 'Precision Superb', 'Individual 2', 'SmartLife Progressive'],
  'Hoya': ['Hoyalux iD MyStyle V+', 'Hoyalux iD LifeStyle 3', 'Hoyalux Dynamic Premium', 'Hoyalux TACT'],
  'Nikon': ['Presio Power', 'Presio i', 'SeeMax Infinite', 'Lite AS Progressive'],
  'Rodenstock': ['Impression FreeSign 3', 'Multigressiv MyView 2', 'Progressiv Ergo', 'Progressiv PureLife 2'],
  'Kodak': ['Unique HD Progressive', 'Precise PB', 'Kodak SoftWear Lenses', 'Kodak DSII'],
  'Younger Optics': ['Image Progressive', 'Camber Steady Plus Progressive', 'Trilogy Progressive', 'Transitions Drivewear Progressive'],
  'Seiko': ['Prime Xceed', 'Surmount WS', 'Supercede II', 'Emblem Smart Zoom'],
  'Shamir': ['Autograph Intelligence', 'Autograph III', 'Spectrum+', 'Genesis II'],
  'Transitions': ['Signature GEN 8 Progressive', 'XTRActive New Generation Progressive', 'Transitions Drivewear Progressive']
}


@app.route('/get_models')
def get_models():
    brand = request.args.get('brand')
    type_ = request.args.get('type')  # 'frame' or 'contactlens'

    if type_ == 'eyeglasscase' or type_ == 'sunglass' or type_ == 'frame' or type_ == 'cliponlens':
        models = sunglass_models.get(brand, [])
    elif type_ == 'contactlens':
        models = contactLensModels.get(brand, [])
    elif type_ == 'lenscleaning':
        models = lenscleaningModels.get(brand, [])
    elif type_ == 'contactlenscase':
        models = contactLensCaseModels.get(brand, [])
    elif type_ == 'contactsolution':
        models = contactSolutionModels.get(brand, [])
    elif type_ == 'repairkit':
        models = repairKitModels.get(brand, [])
    elif type_ == 'frameaccessory':
        models = frameAccessoryModels.get(brand, [])
    elif type_ == 'antiradiationcoating':
        models = antiRadiationCoatingModels.get(brand, [])
    elif type_ == 'antireflectivecoating':
        models = antiReflectiveCoatingModels.get(brand, [])
    elif type_ == 'photochromic':
        models = photochromicModels.get(brand, [])
    elif type_ == 'tinted':
        models = tintedModels.get(brand, [])
    elif type_ == 'progressive':
        models = progressiveModels.get(brand, [])
    else:
        models = []

    return jsonify(models)


@app.route("/add_new_product_form")
def add_new_product_form():
    return render_template("inventoryAddNew.html")


@app.route("/inventory")
def inventory():
    return render_template("inventory.html")


@app.route('/add_new_product', methods=['POST'])
def add_new_product():
    product_type = request.form.get('product_type')

    product_map = {
        "eyeglassframe": {
            "table": "eyeglassframeinventory",
            "prefix": "EYEGLSSFRM",
            "id_field": "eyeglass_frame_id",
            "stock_field": "current_stock",
            "success_msg": "Eyeglass Frame record added successfully."
        },
        "contactlens": {
            "table": "contactlensinventory",
            "prefix": "CNTCTLNS",
            "id_field": "contact_lens_id",
            "stock_field": "current_stock_contactlens",
            "success_msg": "Contact Lens record added successfully."
        },
        "sunglass": {
            "table": "sunglassinventory",
            "prefix": "SNGLSS",
            "id_field": "sunglass_id",
            "stock_field": "current_stock_sunglass",
            "success_msg": "Sunglass record added successfully."
        },
        "lenscleaning": {
            "table": "lenscleaninginventory",
            "prefix": "LNSCLNNG",
            "id_field": "lens_cleaning_id",
            "stock_field": "current_stock_lenscleaning",
            "success_msg": "Lens Cleaning or Spray record added successfully."
        },
        "eyeglasscase": {
            "table": "eyeglasscaseinventory",
            "prefix": "EYEGLSSCS",
            "id_field": "eyeglass_case_id",
            "stock_field": "current_stock_eyeglasscase",
            "success_msg": "Eyeglass Case record added successfully."
        },
        "contactlenscase": {
            "table": "contactlenscaseinventory",
            "prefix": "CNTCTLNSCS",
            "id_field": "contactlens_case_id",
            "stock_field": "current_stock_contactlenscase",
            "success_msg": "Contactlens Case record added successfully."
        },
        "contactlenssolution": {
            "table": "contactlenssolutioninventory",
            "prefix": "LNSSLTN",
            "id_field": "contactlens_solution_id",
            "stock_field": "current_stock_contactlenssolution",
            "success_msg": "Contactlens Solution record added successfully."
        },
        "repairkit": {
            "table": "repairkitinventory",
            "prefix": "RPRKT",
            "id_field": "repair_kit_id",
            "stock_field": "current_stock_repairkit",
            "success_msg": "Repair Kits record added successfully."
        },
        "cliponlens": {
            "table": "cliponlensinventory",
            "prefix": "CLPNLNS",
            "id_field": "clipon_lens_id",
            "stock_field": "current_stock_clipon",
            "success_msg": "Clip-on Lens record added successfully."
        },
        "frameaccessory": {
            "table": "frameaccessoryinventory",
            "prefix": "ACCSSRY",
            "id_field": "accessory_id",
            "stock_field": "current_stock_frameaccessory",
            "success_msg": "Frame Accessory record added successfully."
        }
    }

    if product_type not in product_map:
        flash("Invalid product type.", "danger")
        return redirect(url_for("invoices"))

    mapping = product_map[product_type]

    # Debug incoming form
    print("== FORM DATA ==")
    print(request.form)


    try:
        # Generate next unique ID
        cursor.execute(f"SELECT {mapping['id_field']} FROM {mapping['table']}")
        existing_ids = cursor.fetchall()

        max_num = 0
        for row in existing_ids:
            unique_id = row[mapping['id_field']]
            if unique_id and unique_id.startswith(mapping['prefix']):
                try:
                    num = int(unique_id.split("-")[1])
                    max_num = max(max_num, num)
                except ValueError:
                    continue

        new_id = f"{mapping['prefix']}-{max_num + 1}"

        # Prepare insert query and values
        if product_type == "eyeglassframe":
            table_columns = (
                f"{mapping['id_field']}, frame_brand, model_number, frame_type, "
                "frame_color, frame_shape, added_date, price, supplier, current_stock"
            )
            values = (
                new_id,
                request.form.get("frame_brand"),
                request.form.get("model_number"),
                request.form.get("frame_type"),
                request.form.get("frame_color"),
                request.form.get("frame_shape"),
                request.form.get("added_date"),
                float(request.form.get("price")) if request.form.get("price") else None,
                request.form.get("supplier"),
                request.form.get("current_stock")
            )

        elif product_type == "contactlens":
            table_columns = (
                f"{mapping['id_field']}, brand, model_name, color, material, "
                "modality, lens_type, water_content, box_content, "
                "price_per_box, added_date, expiry_date, supplier, current_stock"
            )
            values = (
                new_id,
                request.form.get("brand"),
                request.form.get("model_name"),
                request.form.get("color"),
                request.form.get("material"),
                request.form.get("modality"),
                request.form.get("lens_type"),
                request.form.get("water_content"),
                request.form.get("box_content"),
                float(request.form.get("price_per_box")) if request.form.get("price_per_box") else None,
                request.form.get("added_date_contactlens"),
                request.form.get("expiry_date_contactlens"),
                request.form.get("supplier_contactlens"),
                request.form.get("current_stock_contactlens")
            )

        elif product_type == "sunglass":
            table_columns = (
                f"{mapping['id_field']}, brand, model_name, frame_type, "
                "frame_material, frame_color, frame_shape, lens_color, lens_material, "
                "lens_type, price, added_date, supplier, current_stock"
            )
            values = (
                new_id,
                request.form.get("brand_sunglass"),
                request.form.get("model_name_sunglass"),
                request.form.get("frame_type_sunglass"),
                request.form.get("frame_material"),
                request.form.get("frame_color_sunglass"),
                request.form.get("frame_shape_sunglass"),
                request.form.get("lens_color"),
                request.form.get("lens_material"),
                request.form.get("lens_type_sunglass"),
                float(request.form.get("price_sunglass")) if request.form.get("price_sunglass") else None,
                request.form.get("added_date_sunglass"),
                request.form.get("supplier_sunglass"),
                request.form.get("current_stock_sunglass")
            )

        elif product_type == "lenscleaning":
            table_columns = (
                f"{mapping['id_field']}, brand, product_name, volume_ml, spray_type, "
                "package_includes, price, added_date, expiration_date, supplier, current_stock"
            )
            values = (
                new_id,
                request.form.get("brand_lenscleaning"),
                request.form.get("product_name"),
                request.form.get("volume_ml"),
                request.form.get("spray_type"),
                request.form.get("package_includes"),
                float(request.form.get("price_lenscleaning")) if request.form.get("price") else None,
                request.form.get("added_date_lenscleaning"),
                request.form.get("expiration_date"),
                request.form.get("supplier_lenscleaning"),
                request.form.get("current_stock_lenscleaning")
            )

        elif product_type == "eyeglasscase":
            table_columns = (
                f"{mapping['id_field']}, brand, model_name, material, color, "
                "type, compatible_frame_sizes, closure_type, price, added_date, "
                "supplier, current_stock"
            )
            values = (
                new_id,
                request.form.get("brand_eyeglasscase"),
                request.form.get("model_name_eyeglasscase"),
                request.form.get("material_eyeglasscase"),
                request.form.get("color_eyeglasscase"),
                request.form.get("type"),
                request.form.get("compatible_frame_sizes"),
                request.form.get("closure_type"),
                float(request.form.get("price_eyeglasscase")) if request.form.get("price_eyeglasscase") else None,
                request.form.get("added_date_eyeglasscase"),
                request.form.get("supplier_eyeglasscase"),
                request.form.get("current_stock_eyeglasscase")
            )

        elif product_type == "contactlenscase":
            table_columns = (
                f"{mapping['id_field']}, brand, model_name, case_type, material, color, "
                "capacity, compatible_lens_types, price, added_date, supplier, current_stock"
            )
            values = (
                new_id,
                request.form.get("brand_contactlenscase"),
                request.form.get("model_name_contactlenscase"),
                request.form.get("case_type"),
                request.form.get("material_contactlenscase"),
                request.form.get("color_contactlenscase"),
                request.form.get("capacity"),
                request.form.get("compatible_lens_types"),
                float(request.form.get("price_contactlenscase")) if request.form.get("price_contactlenscase") else None,
                request.form.get("added_date_contactlenscase"),
                request.form.get("supplier_contactlenscase"),
            )

        elif product_type == "contactlenssolution":
            table_columns = (
                f"{mapping['id_field']}, brand, model_name, type, volume_ml, bottle_count, "
                "suitable_for, preservative_free, suitable_for, preservative_free, price, "
                "added_date, supplier, current_stock"
            )
            values = (
                new_id,
                request.form.get("brand_contactlenssolution"),
                request.form.get("model_name_contactlenssolution"),
                request.form.get("type_contactlenssolution"),
                request.form.get("volume_ml_contactlenssolution"),
                request.form.get("bottle_count"),
                request.form.get("suitable_for"),
                request.form.get("preservative_free"),
                float(request.form.get("price_contactlenssolution")) if request.form.get("price_contactlenssolution") else None,
                request.form.get("added_date_contactlenssolution"),
                request.form.get("supplier_contactlenssolution"),
                request.form.get("current_stock_contactlenssolution")
            )

        elif product_type == "repairkit":
            table_columns = (
                f"{mapping['id_field']}, brand, product_name, included_items, screwdriver_type, "
                "screw_sizes, compatible_frame_types, case_included, price, added_date, supplier, current_stock"
            )
            values = (
                new_id,
                request.form.get("brand_repairkit"),
                request.form.get("product_name_repairkit"),
                request.form.get("included_items"),
                request.form.get("screwdriver_type"),
                request.form.get("screw_sizes"),
                request.form.get("compatible_frame_types"),
                request.form.get("case_included"),
                float(request.form.get("price_repairkit")) if request.form.get("price_repairkit") else None,
                request.form.get("added_date_repairkit"),
                request.form.get("supplier_repairkit"),
                request.form.get("current_stock_repairkit")
            )

        elif product_type == "cliponlens":
            table_columns = (
                f"{mapping['id_field']}, brand, model_name, lens_type, lens_color, lens_shape, "
                "material, price, lens_shape, added_date, supplier, current_stock"
            )
            values = (
                new_id,
                request.form.get("brand_clipon"),
                request.form.get("model_name_clipon"),
                request.form.get("lens_type_clipon"),
                request.form.get("lens_color_clipon"),
                request.form.get("lens_shape"),
                request.form.get("material_clipon"),
                float(request.form.get("price_clipon")) if request.form.get("price_clipon") else None,
                request.form.get("added_date_clipon"),
                request.form.get("supplier_clipon"),
                request.form.get("current_stock_clipon")
            )

        elif product_type == "frameaccessory":
            table_columns = (
                f"{mapping['id_field']}, accessory_type, brand, product_name, material, color, "
                "price, added_date, supplier, current_stock"
            )
            values = (
                new_id,
                request.form.get("accessory_type"),
                request.form.get("brand_frameaccessory"),
                request.form.get("product_name_frameaccessory"),
                request.form.get("material_frameaccessory"),
                request.form.get("color_frameaccessory"),
                float(request.form.get("price_frameaccessory")) if request.form.get("price_frameaccessory") else None,
                request.form.get("added_date_frameaccessory"),
                request.form.get("supplier_frameaccessory"),
                request.form.get("current_stock_frameaccessory")
            )

        else:
            flash("Unsupported product type.", "danger")
            return redirect(url_for("inventory"))

        # Execute insert
        cursor.execute(
            f"INSERT INTO {mapping['table']} ({table_columns}) VALUES ({','.join(['%s'] * len(values))})",
            values
        )

        conn.commit()
        flash(mapping['success_msg'], "success")

    except Exception as e:
        conn.rollback()
        print("=== ERROR OCCURRED ===")
        traceback.print_exc()
        flash(f"Error adding product: {str(e)}", "danger")

    # --- Automatically update status based on stock ---
    try:
        stock_val = request.form.get(mapping['stock_field'])
        if stock_val is not None and stock_val.isdigit():
            stock_val = int(stock_val)
            if stock_val > 10:
                status = "In Stock"
            elif 1 <= stock_val <= 10:
                status = "Low Stock"
            else:
                status = "Out of Stock"
        else:
            status = "Unknown"

        cursor.execute(
            f"UPDATE {mapping['table']} SET status=%s WHERE {mapping['id_field']}=%s",
            (status, new_id)
        )
        conn.commit()

    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        flash(f"Error updating status: {str(e)}", "danger")

    return redirect(url_for("optical_product_table"))


@app.route('/add_new_lens', methods=['POST'])
def add_new_lens():
    lensaddon_type = request.form.get('lensaddon_type')

    lensaddon_map = {
        "antiradiationcoating": {
            "table": "antiradiationcoatinginventory",
            "prefix": "RDTN",
            "id_field": "antiradiation_coating_id",
            "stock_field": "current_stock_antirad",
            "success_msg": "Anti-Radiation Coating record added successfully."
        },
        "antireflectivecoating": {
            "table": "antireflectivecoatinginventory",
            "prefix": "RFLCTV",
            "id_field": "antireflective_coating_id",
            "stock_field": "current_stock_antiref",
            "success_msg": "Anti-reflective Coating record added successfully."
        },
        "photochromic": {
            "table": "photochromicinventory",
            "prefix": "PHTCHRMC",
            "id_field": "photochromic_id",
            "stock_field": "current_stock_photo",
            "success_msg": "Photochromic record added successfully."
        },
        "tinted": {
            "table": "tintedinventory",
            "prefix": "TNTD",
            "id_field": "tinted_id",
            "stock_field": "current_stock_tinted",
            "success_msg": "Tinted / Colored Lens record added successfully."
        },
        "progressive": {
            "table": "progressiveinventory",
            "prefix": "PRGRSSV",
            "id_field": "progressive_id",
            "stock_field": "current_stock_pro",
            "success_msg": "Progressive Lens record added successfully."
        }
    }

    if lensaddon_type not in lensaddon_map:
        flash("Invalid lensaddon type.", "danger")
        return redirect(url_for("add_new_product_form"))

    mapping = lensaddon_map[lensaddon_type]

    # Debug incoming form
    print("== FORM DATA ==")
    print(request.form)

    try:
        # Generate next unique ID
        cursor.execute(f"SELECT {mapping['id_field']} FROM {mapping['table']}")
        existing_ids = cursor.fetchall()

        max_num = 0
        for row in existing_ids:
            unique_id = row[mapping['id_field']]
            if unique_id and unique_id.startswith(mapping['prefix']):
                try:
                    num = int(unique_id.split("-")[1])
                    max_num = max(max_num, num)
                except ValueError:
                    continue

        new_id = f"{mapping['prefix']}-{max_num + 1}"

        # Prepare insert query and values
        if lensaddon_type == "antiradiationcoating":
            table_columns = (
                f"{mapping['id_field']}, brand, model_name, color_tint, warranty_period,"
                "applicable_lens_types, protection_type, transmittance_rate, price, added_date,"
                "supplier, current_stock"
            )
            values = (
                new_id,
                request.form.get("brand_antirad"),
                request.form.get("model_name_antirad"),
                request.form.get("color_tint"),
                request.form.get("warranty_period"),
                request.form.get("applicable_lens_types"),
                request.form.get("protection_type"),
                request.form.get("transmittance_rate"),
                float(request.form.get("price_antirad")) if request.form.get("price_antirad") else None,
                request.form.get("added_date_antirad"),
                request.form.get("supplier_antirad"),
                request.form.get("current_stock_antirad")
            )

        elif lensaddon_type == "antireflectivecoating":
            table_columns = (
                f"{mapping['id_field']}, brand, model_name, color_tint, reflectance_level"
                "compatible_lens_types, warranty_period, price, added_date, supplier, current_stock"
            )
            values = (
                new_id,
                request.form.get("brand_antiref"),
                request.form.get("model_name_antiref"),
                request.form.get("color_tint_antiref"),
                request.form.get("reflectance_level"),
                request.form.get("compatible_lens_types_antiref"),
                request.form.get("warranty_period_antiref"),
                float(request.form.get("price_antiref")) if request.form.get("price_antiref") else None,
                request.form.get("added_date_antiref"),
                request.form.get("supplier_antiref"),
                request.form.get("current_stock_antiref"),
            )
        elif lensaddon_type == "photochromic":
            table_columns = (
                f"{mapping['id_field']}, brand, product_name, index_of_refraction, "
                "color_tint, activation_method, indoor_transparency, outdoor_darkness,"
                "available_prescription_range, price, added_date, supplier, current_stock"
            )
            values = (
                new_id,
                request.form.get("brand_photo"),
                request.form.get("product_name_photo"),
                request.form.get("material_photo"),
                request.form.get("index_of_refraction"),
                request.form.get("uv_protection"),
                request.form.get("color_tint_photo"),
                request.form.get("activation_method"),
                request.form.get("indoor_transparency"),
                request.form.get("outdoor_darkness"),
                request.form.get("available_prescription_range"),
                float(request.form.get("price_photo")) if request.form.get("price_photo") else None,
                request.form.get("added_date_photo"),
                request.form.get("supplier_photo"),
                request.form.get("current_stock_photo"),
            )
        elif lensaddon_type == "tinted":
            table_columns = (
                f"{mapping['id_field']}, brand, model_name, lens_type, color_tinted, "
                "lens_count, tint_type, color_intensity, uv_blocking, price_per_box, "
                "added_date, supplier, current_stock"
            )
            values = (
                new_id,
                request.form.get("brand_tinted"),
                request.form.get("model_name_tinted"),
                request.form.get("lens_type_tinted"),
                request.form.get("color_tinted"),
                request.form.get("lens_count"),
                request.form.get("tint_type"),
                request.form.get("color_intensity"),
                request.form.get("uv_blocking"),
                float(request.form.get("price_per_box_tinted")) if request.form.get("price_per_box_tinted") else None,
                request.form.get("added_date_tinted"),
                request.form.get("supplier_tinted"),
                request.form.get("current_stock_tinted")
            )
        elif lensaddon_type == "progressive":
            table_columns = (
                f"{mapping['id_field']}, brand, model_name, material, coating, "
                "uv_protection, blue_light_filter, color_tint, warranty_period, "
                "photochromic, frame_compatibility, price_per_pair, added_date, "
                "supplier, current_stock"
            )
            values = (
                new_id,
                request.form.get("brand_pro"),
                request.form.get("model_name_pro"),
                request.form.get("material_pro"),
                request.form.get("coating"),
                request.form.get("uv_protection_pro"),
                request.form.get("blue_light_filter"),
                request.form.get("color_tint_pro"),
                request.form.get("warranty_period_pro"),
                request.form.get("photochromic_pro"),
                request.form.get("frame_compatibility"),
                float(request.form.get("price_per_pair")) if request.form.get("price_per_pair") else None,
                request.form.get("added_date_pro"),
                request.form.get("supplier_pro"),
                request.form.get("current_stock_pro"),
            )
        else:
            flash("Unsupported lens type.", "danger")
            return redirect(url_for("add_new_product_form"))

        # Execute insert
        cursor.execute(
            f"INSERT INTO {mapping['table']} ({table_columns}) VALUES ({','.join(['%s'] * len(values))})",
            values
        )

        conn.commit()
        flash(mapping['success_msg'], "success")

    except Exception as e:
        conn.rollback()
        print("=== ERROR OCCURRED ===")
        traceback.print_exc()
        flash(f"Error adding product: {str(e)}", "danger")

    # --- Automatically update status based on stock ---
    try:
        stock_val = request.form.get(mapping['stock_field'])
        if stock_val is not None and stock_val.isdigit():
            stock_val = int(stock_val)
            if stock_val > 10:
                status = "In Stock"
            elif 1 <= stock_val <= 10:
                status = "Low Stock"
            else:
                status = "Out of Stock"
        else:
            status = "Unknown"

        cursor.execute(
            f"UPDATE {mapping['table']} SET status=%s WHERE {mapping['id_field']}=%s",
            (status, new_id)
        )
        conn.commit()

    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        flash(f"Error updating status: {str(e)}", "danger")

    return redirect(url_for("lens_table"))



@app.route('/add_optical_product', methods=['POST'])
def add_optical_product():
    product_type = request.form.get('product_type')

    product_map = {
        "eyeglassframe": {
            "table": "eyeglassframe",
            "prefix": "EYEGLSSFRM",
            "id_field": "eyeglass_frame_id",
            "success_msg": "Eyeglass Frame record added successfully."
        },
        "contactlens": {
            "table": "contactlens",
            "prefix": "CNTCTLNS",
            "id_field": "contact_lens_id",
            "success_msg": "Contact Lens record added successfully."
        },
        "sunglass": {
            "table": "sunglass",
            "prefix": "SNGLSS",
            "id_field": "sunglass_id",
            "success_msg": "Sunglass record added successfully."
        },
        "lenscleaning": {
            "table": "lenscleaning",
            "prefix": "LNSCLNNG",
            "id_field": "lens_cleaning_id",
            "success_msg": "Lens Cleaning or Spray record added successfully."
        },
        "eyeglasscase": {
            "table": "eyeglasscase",
            "prefix": "EYEGLSSCS",
            "id_field": "eyeglass_case_id",
            "success_msg": "Eyeglass Case record added successfully."
        },
        "contactlenscase": {
            "table": "contactlenscase",
            "prefix": "CNTCTLNSCS",
            "id_field": "contactlens_case_id",
            "success_msg": "Contactlens Case record added successfully."
        },
        "contactlenssolution": {
            "table": "contactlenssolution",
            "prefix": "LNSSLTN",
            "id_field": "contactlens_solution_id",
            "success_msg": "Contactlens Solution record added successfully."
        },
        "repairkit": {
            "table": "repairkit",
            "prefix": "RPRKT",
            "id_field": "repair_kit_id",
            "success_msg": "Repair Kits record added successfully."
        },
        "cliponlens": {
            "table": "cliponlens",
            "prefix": "CLPNLNS",
            "id_field": "clipon_lens_id",
            "success_msg": "Clip-on Lens record added successfully."
        },
        "frameaccessory": {
            "table": "frameaccessory",
            "prefix": "ACCSSRY",
            "id_field": "accessory_id",
            "success_msg": "Frame Accessory record added successfully."
        }
    }

    if product_type not in product_map:
        flash("Invalid product type.", "danger")
        return redirect(url_for("invoices"))

    mapping = product_map[product_type]

    # Debug incoming form
    print("== FORM DATA ==")
    print(request.form)

    # Common fields
    patient_id = request.form.get('patient_id')
    patient_fname = request.form.get('patient_fname')
    patient_minitial = request.form.get('patient_minitial')
    patient_lname = request.form.get('patient_lname')
    age = request.form.get('age')
    gender = request.form.get('gender')

    try:
        # Generate next unique ID
        cursor.execute(f"SELECT {mapping['id_field']} FROM {mapping['table']}")
        existing_ids = cursor.fetchall()

        max_num = 0
        for row in existing_ids:
            unique_id = row[mapping['id_field']]
            if unique_id and unique_id.startswith(mapping['prefix']):
                try:
                    num = int(unique_id.split("-")[1])
                    max_num = max(max_num, num)
                except ValueError:
                    continue

        new_id = f"{mapping['prefix']}-{max_num + 1}"

        # Prepare insert query and values
        if product_type == "eyeglassframe":
            table_columns = (
                f"{mapping['id_field']}, patient_id, patient_fname, patient_minitial, "
                "patient_lname, age, gender, frame_brand, frame_type,"
                "frame_color, frame_shape, model_number, price, date"
            )
            values = (
                new_id, patient_id, patient_fname, patient_minitial,
                patient_lname, int(age) if age else None,
                gender,
                request.form.get("frame_brand"),
                request.form.get("frame_type"),
                request.form.get("frame_color"),
                request.form.get("frame_shape"),
                request.form.get("frame_model"),
                float(request.form.get("price")) if request.form.get("price") else None,
                request.form.get("date")
            )

        elif product_type == "contactlens":
            table_columns = (
                f"{mapping['id_field']}, patient_id, patient_fname, patient_minitial, "
                "patient_lname, age, gender, brand, price_per_box, color, "
                "material, modality, lens_type, model_name, box_content, expiry_date, purchased_date "
            )
            values = (
                new_id, patient_id, patient_fname, patient_minitial,
                patient_lname, int(age) if age else None,
                gender,
                request.form.get("contactlens_brand"),
                float(request.form.get("price_per_box")) if request.form.get("price_per_box") else None,
                request.form.get("contactlens_color"),
                request.form.get("contactlens_material"),
                request.form.get("contactlens_modality"),
                request.form.get("contactlens_lenstype"),
                request.form.get("contactlens_modelname"),
                request.form.get("box_content"),
                request.form.get("expiry_date"),
                request.form.get("date")
            )
        elif product_type == "sunglass":
            table_columns = (
                f"{mapping['id_field']}, patient_id, patient_fname, patient_minitial, "
                "patient_lname, age, gender, brand, price, frame_color, "
                "frame_material, frame_type, frame_shape, model_name, date "
            )
            values = (
                new_id, patient_id, patient_fname, patient_minitial,
                patient_lname, int(age) if age else None,
                gender,
                request.form.get("sunglass_brand"),
                float(request.form.get("price")) if request.form.get("price") else None,
                request.form.get("sunglass_color"),
                request.form.get("sunglass_material"),
                request.form.get("sunglass_type"),
                request.form.get("sunglass_shape"),
                request.form.get("sunglass_modelname"),
                request.form.get("date")
            )
        elif product_type == "lenscleaning":
            table_columns = (
                f"{mapping['id_field']}, patient_id, patient_fname, patient_minitial, "
                "patient_lname, age, gender, brand, price, spray_type, "
                "product_name, expiration_date, package_includes, date "
            )
            values = (
                new_id, patient_id, patient_fname, patient_minitial,
                patient_lname, int(age) if age else None,
                gender,
                request.form.get("lenscleaning_brand"),
                float(request.form.get("price")) if request.form.get("price") else None,
                request.form.get("lenscleaning_spray"),
                request.form.get("lenscleaning_modelname"),
                request.form.get("expiration_date"),
                request.form.get("lenscleaning_package"),
                request.form.get("date")
            )
        elif product_type == "eyeglasscase":
            table_columns = (
                f"{mapping['id_field']}, patient_id, patient_fname, patient_minitial, "
                "patient_lname, age, gender, brand, price, color, "
                "model_name, type, material, compatible_frame_sizes, date "
            )
            values = (
                new_id, patient_id, patient_fname, patient_minitial,
                patient_lname, int(age) if age else None,
                gender,
                request.form.get("eyeglasscase_brand"),
                float(request.form.get("price")) if request.form.get("price") else None,
                request.form.get("eyeglasscase_color"),
                request.form.get("eyeglasscase_modelname"),
                request.form.get("eyeglasscase_type"),
                request.form.get("eyeglasscase_material"),
                request.form.get("eyeglasscase_size"),
                request.form.get("date")
            )
        elif product_type == "contactlenscase":
            table_columns = (
                f"{mapping['id_field']}, patient_id, patient_fname, patient_minitial, "
                "patient_lname, age, gender, brand, price, color, model_name, "
                "case_type, material, capacity, compatible_lens_types, date "
            )
            values = (
                new_id, patient_id, patient_fname, patient_minitial,
                patient_lname, int(age) if age else None,
                gender,
                request.form.get("contactlenscase_brand"),
                float(request.form.get("price")) if request.form.get("price") else None,
                request.form.get("contactlenscasecase_color"),
                request.form.get("contactlenscase_modelname"),
                request.form.get("contactlenscasecase_type"),
                request.form.get("contactlenscasecase_material"),
                request.form.get("contactlenscasecase_capacity"),
                request.form.get("contactlenscasecase_compatible"),
                request.form.get("date")
            )
        elif product_type == "contactlenssolution":
            table_columns = (
                f"{mapping['id_field']}, patient_id, patient_fname, patient_minitial, "
                "patient_lname, age, gender, brand, price, type, product_name, "
                "expiry_date, bottle_count, suitable_for, preservative_free, date "
            )
            values = (
                new_id, patient_id, patient_fname, patient_minitial,
                patient_lname, int(age) if age else None,
                gender,
                request.form.get("contactsolution_brand"),
                float(request.form.get("price")) if request.form.get("price") else None,
                request.form.get("contactsolution_type"),
                request.form.get("contactsolution_modelname"),
                request.form.get("expiry_date"),
                request.form.get("bottle_count"),
                request.form.get("contactsolution_suitable"),
                request.form.get("contactsolution_preservative"),
                request.form.get("date")
            )
        elif product_type == "repairkit":
            table_columns = (
                f"{mapping['id_field']}, patient_id, patient_fname, patient_minitial, "
                "patient_lname, age, gender, brand, price, screw_sizes, product_name, "
                "case_included, included_items, screwdriver_type, compatible_frame_types, date "
            )
            values = (
                new_id, patient_id, patient_fname, patient_minitial,
                patient_lname, int(age) if age else None,
                gender,
                request.form.get("repairkit_brand"),
                float(request.form.get("price")) if request.form.get("price") else None,
                request.form.get("repairkit_screw"),
                request.form.get("repairkit_modelname"),
                request.form.get("repairkit_case"),
                request.form.get("repairkit_included"),
                request.form.get("repairkit_type"),
                request.form.get("repairkit_compatible"),
                request.form.get("date")
            )
        elif product_type == "cliponlens":
            table_columns = (
                f"{mapping['id_field']}, patient_id, patient_fname, patient_minitial, "
                "patient_lname, age, gender, brand, price, material, model_name, "
                "lens_type, lens_color, lens_shape, date "
            )
            values = (
                new_id, patient_id, patient_fname, patient_minitial,
                patient_lname, int(age) if age else None,
                gender,
                request.form.get("cliponlens_brand"),
                float(request.form.get("price")) if request.form.get("price") else None,
                request.form.get("cliponlens_material"),
                request.form.get("cliponlens_modelname"),
                request.form.get("cliponlens_type"),
                request.form.get("cliponlens_color"),
                request.form.get("cliponlens_shape"),

                request.form.get("date")
            )
        elif product_type == "frameaccessory":
            table_columns = (
                f"{mapping['id_field']}, patient_id, patient_fname, patient_minitial, "
                "patient_lname, age, gender, brand, price, material, product_name, "
                "color, accessory_type, date "
            )
            values = (
                new_id, patient_id, patient_fname, patient_minitial,
                patient_lname, int(age) if age else None,
                gender,
                request.form.get("frameaccessory_brand"),
                float(request.form.get("price")) if request.form.get("price") else None,
                request.form.get("frameaccessory_material"),
                request.form.get("frameaccessory_modelname"),
                request.form.get("frameaccessory_color"),
                request.form.get("frameaccessory_type"),
                request.form.get("date")
            )

        else:
            flash("Unsupported product type.", "danger")
            return redirect(url_for("invoices"))

        # Execute insert
        cursor.execute(
            f"INSERT INTO {mapping['table']} ({table_columns}) VALUES ({','.join(['%s'] * len(values))})",
            values
        )

        conn.commit()
        flash(mapping['success_msg'], "success")

    except Exception as e:
        conn.rollback()
        print("=== ERROR OCCURRED ===")
        traceback.print_exc()
        flash(f"Error adding product: {str(e)}", "danger")

    return redirect(url_for("invoice_opticalproduct"))


@app.route('/add_lensaddon', methods=['POST'])
def add_lensaddon():
    lensaddon_type = request.form.get('lensaddon_type')

    lensaddon_map = {
        "antiradiationcoating": {
            "table": "antiradiationcoating",
            "prefix": "RDTN",
            "id_field": "antiradiation_coating_id",
            "success_msg": "Anti-Radiation Coating record added successfully."
        },
        "antireflectivecoating": {
            "table": "antireflectivecoating",
            "prefix": "RFLCTV",
            "id_field": "antireflective_coating_id",
            "success_msg": "Anti-reflective Coating record added successfully."
        },
        "photochromic": {
            "table": "photochromic",
            "prefix": "PHTCHRMC",
            "id_field": "photochromic_id",
            "success_msg": "Photochromic record added successfully."
        },
        "tinted": {
            "table": "tinted",
            "prefix": "TNTD",
            "id_field": "tinted_id",
            "success_msg": "Tinted / Colored Lens record added successfully."
        },
        "progressive": {
            "table": "progressive",
            "prefix": "PRGRSSV",
            "id_field": "progressive_id",
            "success_msg": "Progressive Lens record added successfully."
        }
    }

    if lensaddon_type not in lensaddon_map:
        flash("Invalid lens type.", "danger")
        return redirect(url_for("invoices"))

    mapping = lensaddon_map[lensaddon_type]

    # Debug incoming form
    print("== FORM DATA ==")
    print(request.form)

    # Common fields
    patient_id = request.form.get('patient_id')
    patient_fname = request.form.get('patient_fname')
    patient_minitial = request.form.get('patient_minitial')
    patient_lname = request.form.get('patient_lname')
    age = request.form.get('age')
    gender = request.form.get('gender')

    try:
        # Generate next unique ID
        cursor.execute(f"SELECT {mapping['id_field']} FROM {mapping['table']}")
        existing_ids = cursor.fetchall()

        max_num = 0
        for row in existing_ids:
            unique_id = row[mapping['id_field']]
            if unique_id and unique_id.startswith(mapping['prefix']):
                try:
                    num = int(unique_id.split("-")[1])
                    max_num = max(max_num, num)
                except ValueError:
                    continue

        new_id = f"{mapping['prefix']}-{max_num + 1}"

        # Prepare insert query and values
        if lensaddon_type == "antiradiationcoating":
            table_columns = (
                f"{mapping['id_field']}, patient_id, patient_fname, patient_minitial, "
                "patient_lname, age, gender, brand, model_name,"
                "color_tint, warranty_period, applicable_lens_types, price, date"
            )
            values = (
                new_id, patient_id, patient_fname, patient_minitial,
                patient_lname, int(age) if age else None,
                gender,
                request.form.get("antiradiationcoating_brand"),
                request.form.get("antiradiationcoating_model"),
                request.form.get("antiradiationcoating_color"),
                request.form.get("antiradiationcoating_warranty"),
                request.form.get("antiradiationcoating_applicable"),
                float(request.form.get("price")) if request.form.get("price") else None,
                request.form.get("date")
            )

        elif lensaddon_type == "antireflectivecoating":
            table_columns = (
                f"{mapping['id_field']}, patient_id, patient_fname, patient_minitial, "
                "patient_lname, age, gender, brand, price, product_name, "
                "color_tint, warranty_period, compatible_lens_types, date "
            )
            values = (
                new_id, patient_id, patient_fname, patient_minitial,
                patient_lname, int(age) if age else None,
                gender,
                request.form.get("antireflectivecoating_brand"),
                float(request.form.get("price")) if request.form.get("price") else None,
                request.form.get("antireflectivecoating_model"),
                request.form.get("antireflectivecoating_color"),
                request.form.get("antireflectivecoating_warranty"),
                request.form.get("antireflectivecoating_compatible"),
                request.form.get("date")
            )
        elif lensaddon_type == "photochromic":
            table_columns = (
                f"{mapping['id_field']}, patient_id, patient_fname, patient_minitial, "
                "patient_lname, age, gender, brand, price, product_name, "
                "color_tint, material, date "
            )
            values = (
                new_id, patient_id, patient_fname, patient_minitial,
                patient_lname, int(age) if age else None,
                gender,
                request.form.get("photochromic_brand"),
                float(request.form.get("price")) if request.form.get("price") else None,
                request.form.get("photochromic_model"),
                request.form.get("photochromic_color"),
                request.form.get("photochromic_material"),
                request.form.get("date")
            )
        elif lensaddon_type == "tinted":
            table_columns = (
                f"{mapping['id_field']}, patient_id, patient_fname, patient_minitial, "
                "patient_lname, age, gender, brand, price_per_box, model_name, "
                "lens_type, color, lens_count, date "
            )
            values = (
                new_id, patient_id, patient_fname, patient_minitial,
                patient_lname, int(age) if age else None,
                gender,
                request.form.get("tinted_brand"),
                float(request.form.get("price_per_box")) if request.form.get("price_per_box") else None,
                request.form.get("tinted_model"),
                request.form.get("tinted_type"),
                request.form.get("tinted_color"),
                request.form.get("lens_count"),
                request.form.get("date")
            )
        elif lensaddon_type == "progressive":
            table_columns = (
                f"{mapping['id_field']}, patient_id, patient_fname, patient_minitial, "
                "patient_lname, age, gender, brand, price_per_pair, model_name, "
                "coating, material, color_tint, blue_light_filter, date "
            )
            values = (
                new_id, patient_id, patient_fname, patient_minitial,
                patient_lname, int(age) if age else None,
                gender,
                request.form.get("progressive_brand"),
                float(request.form.get("price_per_pair")) if request.form.get("price_per_pair") else None,
                request.form.get("progressive_model"),
                request.form.get("progressive_coating"),
                request.form.get("progressive_material"),
                request.form.get("progressive_color"),
                request.form.get("progressive_blue"),
                request.form.get("date")
            )
        else:
            flash("Unsupported lens type.", "danger")
            return redirect(url_for("invoices"))

        # Execute insert
        cursor.execute(
            f"INSERT INTO {mapping['table']} ({table_columns}) VALUES ({','.join(['%s'] * len(values))})",
            values
        )

        conn.commit()
        flash(mapping['success_msg'], "success")

    except Exception as e:
        conn.rollback()
        print("=== ERROR OCCURRED ===")
        traceback.print_exc()
        flash(f"Error adding lens: {str(e)}", "danger")

    return redirect(url_for("invoice_lens"))



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

@app.route('/delete_invoice/<invoice_id>', methods=['POST'])
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

    return render_template("patient details.html",  patient=patient)


@app.route('/patient/<patient_id>/history')
def patient_history(patient_id):
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

    cursor.execute("SELECT * FROM appointment WHERE patient_id = %s", (patient_id,))
    appointments = cursor.fetchall()

    presc_lookup = {
        p['prescription_date']: {
            'eyeresult': p.get('old_va_od', 'N/A'),
            'prescription': f"{p.get('sph_od', '')}/{p.get('sph_os', '')}"
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
            'prescription': presc_lookup.get(appt.get('appointment_date'), None)
        })


    return render_template("patient history.html",
                           patient=patient,
                           eye_results=eye_results,
                           prescriptions=prescriptions,
                           invoices=invoices, history_data=history_data)


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
