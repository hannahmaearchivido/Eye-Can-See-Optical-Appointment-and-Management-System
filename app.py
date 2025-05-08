from flask import Flask, render_template, request  # <-- this 'request' is what you need
import pymongo
from pymongo import MongoClient
from datetime import datetime, date

app = Flask(__name__)
client = MongoClient("mongodb+srv://archiannah:EyEcansEEoptical@eyecanseeoptical.aevclbc.mongodb.net/?retryWrites=true&w=majority&appName=EyeCanSeeOptical")
db = client["EyeCanSeeOptical"]

appointments_collection = db["appointment"]
invoices_collection = db['invoice']  # Your MongoDB collection


@app.route('/')
def index():
    today_str = datetime.today().strftime('%Y-%m-%d')

    # Count patients added today
    patients_today = db.patient.count_documents({'Date': today_str})

    # Count appointments scheduled for today
    appointments_today = db.appointment.count_documents({'Appointment_Date': today_str})

    # Count pending payments in today's invoices
    pending_payments = db.invoice.count_documents({
        'Date': today_str,
        'Payment_Status': 'Pending'
    })

    # Count sales (you can define this as any invoice with full payment)
    sales_today = db.invoice.count_documents({
        'Date': today_str,
        'Payment_Status': 'Paid'
    })

    return render_template('index.html', dashboard={
        'patients': patients_today,
        'appointments': appointments_today,
        'pending_payments': pending_payments,
        'sales': sales_today
    })

@app.route('/appointments/<status>')
def appointments_by_status(status):
    appointments = db.appointments.find({'status': status})
    return render_template('appointments.html', appointments=appointments, status=status)

@app.route('/filter_appointments')
def filter_appointments():
    status = request.args.get('status')
    date = request.args.get('date')  # Expecting format: YYYY-MM-DD

    query = {}
    if status and status != "All":
        query['status'] = status
    if date:
        query['appointment_date'] = date  # Ensure date format matches DB

    appointments = db.appointments.find(query)
    return render_template('partials/_cards.html', appointments=appointments)

@app.route("/appointments")
def appointments():
    appointments = list(appointments_collection.find())
    return render_template("appointment.html", appointments=appointments)

@app.route('/patients')
def patient_records():
    status = request.args.get('status', 'All')
    if status == 'All':
        patients = list(db.patient.find())
    else:
        patients = list(db.patient.find({'Status': status}))
    return render_template('tables.html', patients=patients, status=status)


@app.route('/invoices')
def invoices():
    # Fetch all invoices from MongoDB and convert to a list for reuse
    invoice_list = list(invoices_collection.find())

    # Calculate total earnings
    total_earnings = sum(inv.get('Total_Amount', 0) for inv in invoice_list)

    # Calculate overdue count
    overdue_count = sum(
        1 for inv in invoice_list
        if inv.get('Claim_Date') and datetime.strptime(inv['Claim_Date'], '%Y-%m-%d').date() < datetime.today().date()
    )

    # Get most frequent patient by counting invoice occurrences
    patient_counts = invoices_collection.aggregate([
        {"$group": {"_id": "$Patient_ID", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 1}
    ])

    most_frequent_patient = None
    try:
        most_frequent_data = next(patient_counts)
        most_frequent_patient_id = most_frequent_data['_id']
        most_frequent_patient = db.patients.find_one({"Patient_ID": most_frequent_patient_id})
    except StopIteration:
        most_frequent_patient = None

    return render_template('invoice.html',
                           invoices=invoice_list,
                           total_earnings=total_earnings,
                           overdue_count=overdue_count,
                           patient=most_frequent_patient)



if __name__ == '__main__':
    app.run(debug=True)
