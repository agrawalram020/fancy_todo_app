
import os
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, date
from calendar import day_name

try:
    from dateutil.relativedelta import relativedelta # Used for accurate month calculation
except ImportError:
    print("WARNING: 'python-dateutil' not installed. Dashboard month calculation may be inaccurate.")
    # Fallback for systems without dateutil
    def relativedelta(months=0):
        return timedelta(days=months * 30)

app = Flask(__name__)

# --- Configuration ---
basedir = os.path.abspath(os.path.dirname(__file__))
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'todo.db')
app.config['SQLALCHEMY_DATABASE_URI'] = "postgresql://neondb_owner:npg_KoFBmZX87UwN@ep-winter-credit-ai6f8xo0-pooler.c-4.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Models ---
class ToDoTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    taskname = db.Column(db.String(100), nullable=False)
    taskdesc = db.Column(db.String(200))
    frequency = db.Column(db.String(20), nullable=False)  # Once, Daily, Weekly, Monthly
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    created_date = db.Column(db.Date, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

class TaskCompletion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('to_do_task.id'), nullable=False)
    completion_date = db.Column(db.Date, nullable=False)

class ShoppingItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.String(50))
    is_purchased = db.Column(db.Boolean, default=False, nullable=False)

class QuickNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(500), nullable=False)
    created_date = db.Column(db.DateTime, default=datetime.utcnow)

# --- Helper Logic ---
def is_task_due_on_date(task, target_date):
    # 1. Check Date Range
    if not (task.start_date <= target_date <= task.end_date):
        return False

    # 2. Check Frequency
    if task.frequency == 'Daily': return True
    # NOTE: 'Once' tasks are handled in the index route logic directly
    if task.frequency == 'Once': return False

    if task.frequency == 'Weekly':
        # Check if target_date's weekday matches the task's start_date's weekday
        return task.start_date.weekday() == target_date.weekday()
    if task.frequency == 'Monthly':
        # Check if target_date's day of the month matches the task's start_date's day
        return task.start_date.day == target_date.day
    return False

def calculate_tasks_due(start_date, end_date):
    """Calculates total tasks due and completed tasks within a date range.
       Only counts recurring tasks (not 'Once')."""

    # Only consider recurring tasks for due counts (not 'Once' tasks)
    active_tasks = ToDoTask.query.filter_by(is_active=True).filter(ToDoTask.frequency != 'Once').all()

    # Query all completions in the range
    completions = TaskCompletion.query.filter(
        TaskCompletion.completion_date >= start_date,
        TaskCompletion.completion_date <= end_date
    ).all()

    # Filter completions to only count those belonging to recurring tasks
    recurring_task_ids = {t.id for t in active_tasks}
    completed_count = len([c for c in completions if c.task_id in recurring_task_ids])

    total_due_count = 0
    daily_stats = {}

    current_date = start_date
    while current_date <= end_date:
        daily_stats[current_date] = {'due': 0, 'completed': 0, 'not_done': 0}

        # Find recurring completions for the current day
        completed_today = {c.task_id for c in completions if c.completion_date == current_date and c.task_id in recurring_task_ids}

        for task in active_tasks:
            if is_task_due_on_date(task, current_date):
                total_due_count += 1
                daily_stats[current_date]['due'] += 1

                if task.id in completed_today:
                    daily_stats[current_date]['completed'] += 1
                else:
                    daily_stats[current_date]['not_done'] += 1

        current_date += timedelta(days=1)

    not_done_count = total_due_count - completed_count

    return {
        'total_due': total_due_count,
        'completed': completed_count,
        'not_done': not_done_count,
        'daily_stats': daily_stats
    }

def get_date_range_from_period(period_key):
    """Calculates start and end dates based on a period key."""
    end_date = date.today()
    start_date = end_date

    if period_key == '30d': # Last 30 days
        start_date = end_date - timedelta(days=29)
    elif period_key == '1m': # Last Month 
        start_date = end_date - relativedelta(months=1)
    elif period_key == '2m': # Last 2 Months
        start_date = end_date - relativedelta(months=2)
    elif period_key == '3m': # Last 3 Months
        start_date = end_date - relativedelta(months=3)
    else:
        # Default to 30 days if period is unknown
        start_date = end_date - timedelta(days=29)

    return start_date, end_date

# --- Routes ---
@app.route('/', methods=['GET', 'POST'])
def index():
    # 1. Determine the date to view
    target_date_str = request.args.get('target_date')
    if target_date_str:
        try:
            today = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        except ValueError:
            today = date.today()
    else:
        today = date.today()

    # 2. Filter active tasks and completions for today
    all_tasks = ToDoTask.query.filter_by(is_active=True).all()
    todays_completions = TaskCompletion.query.filter_by(completion_date=today).all()
    completed_task_ids = {c.task_id for c in todays_completions}

    pending_list = []
    completed_list = []
    future_once_tasks = [] 

    for task in all_tasks:
        is_due_today = False

        if task.frequency == 'Once':
            if task.end_date <= today: 
                is_due_today = True
            else:
                due_in_days = (task.end_date - today).days
                future_once_tasks.append({
                    'id': task.id,
                    'taskname': task.taskname,
                    'taskdesc': task.taskdesc,
                    'frequency': task.frequency,
                    'start_date': task.start_date,
                    'end_date': task.end_date,
                    'due_since': due_in_days
                })
                continue 

        elif is_task_due_on_date(task, today):
            is_due_today = True

        if is_due_today:
            if task.id in completed_task_ids:
                completed_list.append(task)
            else:
                pending_list.append(task)

    # 3. Sort lists
    future_once_tasks.sort(key=lambda x: x['end_date'])

    # 4. Fetch Shopping Items (sorted by purchased status then ID)
    all_shopping_items = ShoppingItem.query.order_by(ShoppingItem.is_purchased, ShoppingItem.id).all()

    # 5. Fetch Notes (Most recent first)
    all_notes = QuickNote.query.order_by(QuickNote.created_date.desc()).all()

    return render_template('index.html', 
                           pending=pending_list, 
                           completed=completed_list, 
                           future_once=future_once_tasks, 
                           today=today,
                           shopping_items=all_shopping_items,
                           notes=all_notes)


@app.route('/dashboard')
def dashboard():
    # 1. Determine the date range
    period_key = request.args.get('period', '30d')
    start_date_param = request.args.get('start_date')
    end_date_param = request.args.get('end_date')

    end_date = date.today()
    start_date = end_date - timedelta(days=29)

    if start_date_param and end_date_param:
        try:
            custom_start = datetime.strptime(start_date_param, '%Y-%m-%d').date()
            custom_end = datetime.strptime(end_date_param, '%Y-%m-%d').date()

            if custom_start <= custom_end:
                start_date = custom_start
                end_date = custom_end
                period_key = None
        except ValueError:
            pass 
    elif period_key:
        start_date, end_date = get_date_range_from_period(period_key)

    # 2. Calculate Recurring Task stats
    stats = calculate_tasks_due(start_date, end_date)

    # 3. Calculate Global Stats
    total_active_tasks = ToDoTask.query.filter_by(is_active=True).count()
    unpurchased_items = ShoppingItem.query.filter_by(is_purchased=False).count()

    # 4. Prepare data for template
    start_date_str = start_date.strftime('%d %b %Y')
    end_date_str = end_date.strftime('%d %b %Y')

    progress_data = {
        'labels': [d.strftime('%b %d') for d in stats['daily_stats'].keys()],
        'completed': [s['completed'] for s in stats['daily_stats'].values()],
        'not_done': [s['not_done'] for s in stats['daily_stats'].values()],
        'total_due': [s['due'] for s in stats['daily_stats'].values()],
    }

    efficiency = (stats['completed'] / stats['total_due'] * 100) if stats['total_due'] else 0

    return render_template('dashboard.html', 
                           stats=stats, 
                           efficiency=efficiency, 
                           progress_data=progress_data,
                           start_date_str=start_date_str, 
                           end_date_str=end_date_str,
                           start_date_obj=start_date.strftime('%Y-%m-%d'),
                           end_date_obj=end_date.strftime('%Y-%m-%d'),
                           current_period=period_key,
                           total_active_tasks=total_active_tasks,
                           unpurchased_items=unpurchased_items)


@app.route('/add_task', methods=['POST'])
def add_task():
    try:
        t_name = request.form['taskname']
        t_desc = request.form['taskdesc']
        t_freq = request.form['frequency']
        t_start = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
        t_end = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()

        new_task = ToDoTask(
            taskname=t_name, taskdesc=t_desc, frequency=t_freq,
            start_date=t_start, end_date=t_end
        )
        db.session.add(new_task)
        db.session.commit()
    except Exception:
        pass

    return redirect(url_for('index'))

@app.route('/edit_task/<int:task_id>', methods=['POST'])
def edit_task(task_id):
    task = ToDoTask.query.get_or_404(task_id)

    if 'action' in request.form:
        if request.form['action'] == 'delete':
            db.session.delete(task)
        elif request.form['action'] == 'inactivate':
            task.is_active = False
        db.session.commit()
        return redirect(url_for('index'))

    task.taskname = request.form['taskname']
    task.taskdesc = request.form['taskdesc']
    task.frequency = request.form['frequency']
    task.start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
    task.end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()

    db.session.commit()
    return redirect(url_for('index'))

@app.route('/complete_task', methods=['POST'])
def complete_task():
    data = request.json
    task_id = data.get('task_id')
    completion_date_str = data.get('completion_date', date.today().strftime('%Y-%m-%d'))
    completion_date = datetime.strptime(completion_date_str, '%Y-%m-%d').date()

    exists = TaskCompletion.query.filter_by(task_id=task_id, completion_date=completion_date).first()
    if not exists:
        new_completion = TaskCompletion(task_id=task_id, completion_date=completion_date)
        db.session.add(new_completion)
        db.session.commit()
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error', 'message': 'Already completed'})

@app.route('/uncomplete_task', methods=['POST'])
def uncomplete_task():
    data = request.json
    task_id = data.get('task_id')
    completion_date = datetime.strptime(data.get('completion_date'), '%Y-%m-%d').date()

    completion_entry = TaskCompletion.query.filter_by(
        task_id=task_id, 
        completion_date=completion_date
    ).first()

    if completion_entry:
        db.session.delete(completion_entry)
        db.session.commit()
        return jsonify({'status': 'success'})

    return jsonify({'status': 'error', 'message': 'Completion record not found'})

# --- SHOPPING LIST ROUTES ---
@app.route('/add_item', methods=['POST'])
def add_item():
    try:
        name = request.form['item_name']
        quantity = request.form.get('item_quantity', '')
        new_item = ShoppingItem(name=name, quantity=quantity)
        db.session.add(new_item)
        db.session.commit()
    except Exception:
        pass
    return redirect(url_for('index'))

@app.route('/delete_item/<int:item_id>', methods=['POST'])
def delete_item(item_id):
    item = ShoppingItem.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/toggle_item/<int:item_id>', methods=['POST'])
def toggle_item(item_id):
    item = ShoppingItem.query.get_or_404(item_id)
    item.is_purchased = not item.is_purchased
    db.session.commit()
    return jsonify({'status': 'success', 'is_purchased': item.is_purchased})

# --- NOTE ROUTES ---
@app.route('/add_note', methods=['POST'])
def add_note():
    try:
        content = request.form['note_content']
        new_note = QuickNote(content=content)
        db.session.add(new_note)
        db.session.commit()
    except Exception:
        pass
    return redirect(url_for('index'))

@app.route('/delete_note/<int:note_id>', methods=['POST'])
def delete_note(note_id):
    note = QuickNote.query.get_or_404(note_id)
    db.session.delete(note)
    db.session.commit()
    return redirect(url_for('index'))


@app.route('/reset_db')
def reset_db():
    with app.app_context():
        db.drop_all()
        db.create_all()

        today = date.today()

        # 1. Daily task (Recurring)
        t1 = ToDoTask(taskname='Daily Code Review', taskdesc='Check all pull requests', frequency='Daily', start_date=today - timedelta(days=1), end_date=today + timedelta(days=30), is_active=True)

        # 2. Weekly task (Recurring)
        t2 = ToDoTask(taskname='Grocery Shopping', taskdesc='Buy fresh produce', frequency='Weekly', start_date=today, end_date=today + timedelta(days=90), is_active=True)

        # 3. One-time task DUE TODAY
        t3 = ToDoTask(taskname='Pay Electricity Bill (Once)', taskdesc='Monthly utility payment', frequency='Once', start_date=today - timedelta(days=5), end_date=today, is_active=True)

        # 4. One-time task OVERDUE
        t4 = ToDoTask(taskname='Send Birthday Gift (Overdue)', taskdesc='Shipping deadline passed', frequency='Once', start_date=today - timedelta(days=30), end_date=today - timedelta(days=3), is_active=True)

        # 5. One-time task DUE IN FUTURE (Nearest)
        t5 = ToDoTask(taskname='Future Project Deadline (Nearest)', taskdesc='Phase 1 completion for client', frequency='Once', start_date=today, end_date=today + timedelta(days=5), is_active=True)

        # 6. One-time task DUE IN FUTURE (Farthest)
        t6 = ToDoTask(taskname='Book Flight Tickets (Farthest)', taskdesc='Summer holiday travel plans', frequency='Once', start_date=today, end_date=today + timedelta(days=60), is_active=True)

        # Dummy completion
        yesterday = today - timedelta(days=1)
        c1 = TaskCompletion(task_id=1, completion_date=yesterday)

        # DEMO SHOPPING ITEMS
        s1 = ShoppingItem(name='Milk', quantity='1 Gallon', is_purchased=False)
        s2 = ShoppingItem(name='Eggs', quantity='1 Dozen', is_purchased=False)
        s3 = ShoppingItem(name='Bread', quantity='1 Loaf', is_purchased=True)

        # DEMO NOTES
        n1 = QuickNote(content='Remember to backup the local repository this weekend.')
        n2 = QuickNote(content='Call the mechanic about the car next Tuesday.')


        db.session.add_all([t1, t2, t3, t4, t5, t6, c1, s1, s2, s3, n1, n2])
        db.session.commit()

    return redirect(url_for('index'))

if __name__ == '__main__':
    current_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(current_dir)

    if not os.path.exists('todo.db'):
        with app.app_context(): db.create_all()

    app.run(debug=True, host='0.0.0.0') # <-- Host set for network access
