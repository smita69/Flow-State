from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, jsonify
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from functools import wraps
from pathlib import Path
import mysql.connector, os, re

load_dotenv()
csrf = CSRFProtect()

def get_db():
    return mysql.connector.connect(host=os.getenv('DB_HOST','127.0.0.1'), port=int(os.getenv('DB_PORT','3306')), user=os.getenv('DB_USER','root'), password=os.getenv('DB_PASSWORD',''), database=os.getenv('DB_NAME','flowstate_db'), autocommit=False)

def query(sql, params=(), one=False, commit=False):
    conn=get_db(); cur=conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        result=cur.fetchone() if one else cur.fetchall() if cur.with_rows else None
        if commit: conn.commit()
        return result
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close(); conn.close()

def execute(sql, params=()):
    conn=get_db(); cur=conn.cursor()
    try:
        cur.execute(sql, params); conn.commit(); return cur.lastrowid
    except Exception:
        conn.rollback(); raise
    finally: cur.close(); conn.close()

def create_app():
    app=Flask(__name__, template_folder='app/templates', static_folder='app/static')
    app.config.update(SECRET_KEY=os.getenv('SECRET_KEY','dev-only-change-me'), WTF_CSRF_TIME_LIMIT=None, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('SESSION_COOKIE_SECURE','0') == '1', MAX_CONTENT_LENGTH=2*1024*1024)
    csrf.init_app(app)
    @app.context_processor
    def context(): return {'current_user': session.get('user'), 'app_name': os.getenv('APP_NAME','FlowState'), 'csrf_token': __import__('flask_wtf.csrf',fromlist=['generate_csrf']).generate_csrf}
    @app.get('/')
    def home():
        if session.get('user'): return redirect(url_for('dashboard'))
        return render_template('landing.html')
    @app.route('/register', methods=['GET','POST'])
    def register():
        if request.method=='POST':
            name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
            if len(name)<2 or len(name)>100 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email) or len(password)<8:
                flash('Enter a valid name and email. Password must be at least 8 characters.','error')
            else:
                try:
                    execute('INSERT INTO users(name,email,password_hash,role) VALUES(%s,%s,%s,%s)',(name,email,generate_password_hash(password),'MEMBER'))
                    flash('Account created. You can sign in now.','success'); return redirect(url_for('login'))
                except mysql.connector.IntegrityError: flash('Unable to create account. Check the details or use another email.','error')
                except mysql.connector.Error: flash('Database unavailable. Check your local MySQL configuration.','error')
        return render_template('register.html')
    @app.route('/login', methods=['GET','POST'])
    def login():
        if request.method=='POST':
            email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
            try: user=query('SELECT id,name,email,password_hash,role FROM users WHERE email=%s AND active=1',(email,),one=True)
            except mysql.connector.Error: user=None; flash('Database unavailable. Check setup instructions.','error')
            if user and check_password_hash(user['password_hash'],password):
                session.clear(); session['user']={k:user[k] for k in ('id','name','email','role')}; return redirect(url_for('dashboard'))
            flash('Sign-in failed. Check your details and try again.','error')
        return render_template('login.html')
    @app.post('/logout')
    def logout(): session.clear(); flash('You have signed out.','success'); return redirect(url_for('home'))
    @app.get('/dashboard')
    @login_required
    def dashboard(): return dashboard_view(app)
    @app.get('/health')
    def health(): return jsonify(status='ok', app=os.getenv('APP_NAME','FlowState'))
    @app.errorhandler(403)
    def forbidden(e): return render_template('error.html', code=403, message='You do not have permission to do that.'),403
    @app.errorhandler(404)
    def missing(e): return render_template('error.html', code=404, message='We could not find that page.'),404
    @app.errorhandler(413)
    def too_large(e): return render_template('error.html', code=413, message='The submitted request is too large.'),413
    @app.errorhandler(500)
    def server_error(e): return render_template('error.html', code=500, message='Something went wrong. Check the server log and configuration.'),500
    register_domain_routes(app)
    return app

def login_required(fn):
    @wraps(fn)
    def wrapped(*a,**kw):
        if not session.get('user'): return redirect(url_for('login',next=request.path))
        return fn(*a,**kw)
    return wrapped

def roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapped(*a,**kw):
            if not session.get('user'): return redirect(url_for('login'))
            if session['user']['role'] not in allowed: abort(403)
            return fn(*a,**kw)
        return wrapped
    return deco

def dashboard_view(app):
    uid=session['user']['id']; role=session['user']['role']; where='1=1' if role=='ADMIN' else 'assignee_id=%s'; params=() if role=='ADMIN' else (uid,); total=query('SELECT COUNT(*) n FROM tasks WHERE '+where,params,one=True)['n']; open_n=query("SELECT COUNT(*) n FROM tasks WHERE "+where+" AND status='In Progress'",params,one=True)['n']; overdue=query('SELECT COUNT(*) n FROM tasks WHERE '+where+" AND due_date<CURDATE() AND status!='Done'",params,one=True)['n']; done=query('SELECT COUNT(*) n FROM tasks WHERE '+where+" AND status='Done'",params,one=True)['n']; recent=query('SELECT t.*,u.name assignee FROM tasks t LEFT JOIN users u ON u.id=t.assignee_id WHERE '+('1=1' if role=='ADMIN' else 't.assignee_id=%s')+' ORDER BY t.updated_at DESC LIMIT 6',params); focus=query("SELECT COALESCE(SUM(TIMESTAMPDIFF(MINUTE,started_at,ended_at)),0) mins FROM focus_sessions WHERE user_id=%s AND ended_at IS NOT NULL AND started_at>=DATE_SUB(NOW(),INTERVAL 7 DAY)",(uid,),one=True)['mins']; return render_template('dashboard.html',total=total,open_n=open_n,high=overdue,resolved=done,recent=recent,distribution=[],focus_minutes=focus,domain_label='Tasks')

def register_domain_routes(app):

    @app.before_request
    def load_unread():
        if session.get('user'):
            try: from flask import g; g.unread=query('SELECT COUNT(*) n FROM notifications WHERE user_id=%s AND is_read=0',(session['user']['id'],),one=True)['n']
            except Exception: pass
    @app.context_processor
    def flow_context():
        from flask import g
        return {'domain_label':'Tasks','unread_count':getattr(g,'unread',0),'tagline':os.getenv('TAGLINE','')}
    @app.get('/tasks')
    @login_required
    def records():
        u=session['user']; q=request.args.get('q','').strip(); status=request.args.get('status',''); where=[]; params=[]
        if u['role']!='ADMIN': where.append('t.assignee_id=%s'); params.append(u['id'])
        if q: where.append('(t.title LIKE %s OR t.description LIKE %s)'); params += [f'%{q}%',f'%{q}%']
        if status: where.append('t.status=%s'); params.append(status)
        items=query('SELECT t.*,u.name assignee FROM tasks t LEFT JOIN users u ON u.id=t.assignee_id'+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY FIELD(t.priority,"Urgent","High","Medium","Low"),t.due_date IS NULL,t.due_date LIMIT 100',tuple(params)); return render_template('records.html',items=items,q=q,status=status,domain_label='Tasks',statuses=['Backlog','To Do','In Progress','In Review','Done','Blocked'])
    @app.route('/tasks/new',methods=['GET','POST'])
    @roles('ADMIN')
    def record_new():
        members=query("SELECT id,name FROM users WHERE active=1 AND role IN ('MEMBER','ADMIN') ORDER BY name")
        if request.method=='POST':
            title=request.form.get('title','').strip(); desc=request.form.get('description','').strip(); priority=request.form.get('priority','Medium'); status=request.form.get('status','To Do'); assignee=request.form.get('assignee_id',type=int); due=request.form.get('due_date') or None; effort=request.form.get('estimated_hours',type=float) or 1
            if not title or len(title)>180 or priority not in ['Low','Medium','High','Urgent'] or status not in ['Backlog','To Do','In Progress','In Review','Done','Blocked'] or effort<0 or effort>1000 or (assignee and not any(m['id']==assignee for m in members)):
                flash('Check the task title, priority, status, assignee and effort.','error')
            else:
                tid=execute('INSERT INTO tasks(title,description,creator_id,assignee_id,priority,status,estimated_hours,due_date,completed_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,IF(%s="Done",NOW(),NULL))',(title,desc,session['user']['id'],assignee,priority,status,effort,due,status)); execute('INSERT INTO task_activity(task_id,actor_id,event,details) VALUES(%s,%s,%s,%s)',(tid,session['user']['id'],'Created','Task created')); 
                if assignee: execute('INSERT INTO notifications(user_id,title,message,entity_id) VALUES(%s,%s,%s,%s)',(assignee,'Task assigned',f'You were assigned: {title}.',tid))
                flash('Task created.','success'); return redirect(url_for('record_detail',rid=tid))
        return render_template('record_form.html',item=None,members=members,domain_label='Tasks')
    @app.get('/tasks/<int:rid>')
    @login_required
    def record_detail(rid):
        item=query('SELECT t.*,u.name assignee,c.name creator FROM tasks t LEFT JOIN users u ON u.id=t.assignee_id JOIN users c ON c.id=t.creator_id WHERE t.id=%s',(rid,),one=True)
        if not item: abort(404)
        u=session['user']
        if u['role']!='ADMIN' and item['assignee_id']!=u['id'] and item['creator_id']!=u['id']: abort(403)
        history=query('SELECT a.*,u.name actor FROM task_activity a LEFT JOIN users u ON u.id=a.actor_id WHERE a.task_id=%s ORDER BY a.created_at DESC',(rid,)); members=query("SELECT id,name FROM users WHERE active=1 AND role IN ('MEMBER','ADMIN') ORDER BY name") if u['role']=='ADMIN' else []
        sessions=query('SELECT * FROM focus_sessions WHERE task_id=%s AND user_id=%s ORDER BY started_at DESC LIMIT 10',(rid,u['id'])); return render_template('record_detail.html',item=item,history=history,comments=[],staff=members,statuses=['Backlog','To Do','In Progress','In Review','Done','Blocked'],domain_label='Tasks',focus_sessions=sessions)
    @app.post('/tasks/<int:rid>/update')
    @login_required
    def record_status(rid):
        item=query('SELECT * FROM tasks WHERE id=%s',(rid,),one=True); u=session['user']
        if not item: abort(404)
        if u['role']!='ADMIN' and item['assignee_id']!=u['id']: abort(403)
        status=request.form.get('status'); priority=request.form.get('priority',item['priority']); allowed_status=['Backlog','To Do','In Progress','In Review','Done','Blocked']; allowed_priority=['Low','Medium','High','Urgent']
        if status not in allowed_status or priority not in allowed_priority: abort(400)
        if u['role']!='ADMIN': priority=item['priority']
        event='Status changed' if status!=item['status'] else 'Task updated'; execute('UPDATE tasks SET status=%s,priority=%s,completed_at=IF(%s="Done",COALESCE(completed_at,NOW()),NULL),updated_at=CURRENT_TIMESTAMP WHERE id=%s',(status,priority,status,rid)); execute('INSERT INTO task_activity(task_id,actor_id,event,details) VALUES(%s,%s,%s,%s)',(rid,u['id'],event,f'{item["status"]} → {status}; priority {item["priority"]} → {priority}'))
        if item['assignee_id'] and item['assignee_id']!=u['id']: execute('INSERT INTO notifications(user_id,title,message,entity_id) VALUES(%s,%s,%s,%s)',(item['assignee_id'],'Task updated',f'{item["title"]} is now {status}.',rid))
        flash('Task updated and activity recorded.','success'); return redirect(url_for('record_detail',rid=rid))
    @app.post('/tasks/<int:rid>/assign')
    @roles('ADMIN')
    def record_assign(rid):
        item=query('SELECT * FROM tasks WHERE id=%s',(rid,),one=True); aid=request.form.get('assignee_id',type=int); member=query('SELECT id FROM users WHERE id=%s AND active=1',(aid,),one=True) if aid else None
        if not item: abort(404)
        if aid and not member: flash('Select an active member.','error'); return redirect(url_for('record_detail',rid=rid))
        execute('UPDATE tasks SET assignee_id=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s',(aid,rid)); execute('INSERT INTO task_activity(task_id,actor_id,event,details) VALUES(%s,%s,%s,%s)',(rid,session['user']['id'],'Assignment changed',f'Assigned to user #{aid}' if aid else 'Task unassigned'))
        if aid: execute('INSERT INTO notifications(user_id,title,message,entity_id) VALUES(%s,%s,%s,%s)',(aid,'Task assigned',f'You were assigned: {item["title"]}.',rid))
        flash('Assignment updated.','success'); return redirect(url_for('record_detail',rid=rid))
    @app.route('/focus',methods=['GET','POST'])
    @login_required
    def focus():
        u=session['user']
        if request.method=='POST':
            action=request.form.get('action'); sid=request.form.get('session_id',type=int); tid=request.form.get('task_id',type=int) or None
            if action=='start':
                if tid:
                    t=query('SELECT id FROM tasks WHERE id=%s AND (assignee_id=%s OR creator_id=%s)',(tid,u['id'],u['id']),one=True)
                    if not t: abort(403)
                active=query('SELECT id FROM focus_sessions WHERE user_id=%s AND ended_at IS NULL',(u['id'],),one=True)
                if active: flash('Finish your active focus session before starting another.','error')
                else: execute('INSERT INTO focus_sessions(user_id,task_id,started_at) VALUES(%s,%s,NOW())',(u['id'],tid)); flash('Focus session started.','success')
            elif action=='stop':
                s=query('SELECT * FROM focus_sessions WHERE id=%s AND user_id=%s AND ended_at IS NULL',(sid,u['id']),one=True)
                if not s: abort(403)
                execute('UPDATE focus_sessions SET ended_at=NOW() WHERE id=%s AND user_id=%s AND ended_at IS NULL',(sid,u['id'])); flash('Focus session completed.','success')
            return redirect(url_for('focus'))
        sessions=query('SELECT f.*,t.title task_title,TIMESTAMPDIFF(MINUTE,f.started_at,COALESCE(f.ended_at,NOW())) minutes FROM focus_sessions f LEFT JOIN tasks t ON t.id=f.task_id WHERE f.user_id=%s ORDER BY f.started_at DESC LIMIT 30',(u['id'],)); tasks=query('SELECT id,title FROM tasks WHERE assignee_id=%s AND status!="Done" ORDER BY due_date LIMIT 100',(u['id'],)); active=next((s for s in sessions if s['ended_at'] is None),None); total=query('SELECT COALESCE(SUM(TIMESTAMPDIFF(MINUTE,started_at,ended_at)),0) mins FROM focus_sessions WHERE user_id=%s AND ended_at IS NOT NULL AND started_at>=DATE_SUB(NOW(),INTERVAL 7 DAY)',(u['id'],),one=True)['mins']; return render_template('focus.html',sessions=sessions,tasks=tasks,active=active,total=total,domain_label='Focus sessions')
    @app.get('/notifications')
    @login_required
    def notifications(): return render_template('notifications.html',notifications=query('SELECT * FROM notifications WHERE user_id=%s ORDER BY created_at DESC LIMIT 100',(session['user']['id'],)))
    @app.post('/notifications/<int:nid>/read')
    @login_required
    def notification_read(nid): execute('UPDATE notifications SET is_read=1 WHERE id=%s AND user_id=%s',(nid,session['user']['id'])); return redirect(url_for('notifications'))
    @app.get('/admin/users')
    @roles('ADMIN')
    def admin_users(): return render_template('admin.html',users=query('SELECT id,name,email,role,active FROM users ORDER BY created_at DESC LIMIT 200'))
    @app.post('/admin/users/<int:uid>/toggle')
    @roles('ADMIN')
    def admin_toggle_user(uid):
        if uid==session['user']['id']: flash('You cannot deactivate your own account.','error')
        else: execute('UPDATE users SET active=IF(active=1,0,1) WHERE id=%s',(uid,)); flash('Account status changed.','success')
        return redirect(url_for('admin_users'))

