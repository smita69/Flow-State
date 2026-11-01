# FlowState

Team task, workload and focus management.

Make meaningful work feel manageable.

## Features

- Responsive HTML/CSS/vanilla JavaScript interface with an app-specific color theme.
- Flask server-rendered pages, session authentication, role checks, CSRF protection, and parameterized MySQL queries.
- Password hashes using Werkzeug; no plaintext passwords or committed `.env` secrets.
- Persistent notifications and database-backed overview counts.
- Search/filter views, empty states, inline feedback, and a keyboard-friendly reduced-motion-aware design.
- SQL schema, administrator bootstrap script, and lightweight unit tests.

### Application workflows

- Administrators create and assign tasks; members view tasks they are assigned to or created. Status and assignment changes are recorded in task activity. Focus sessions use server-side start/end timestamps, prevent a second active session, and summarize completed focus time.
- Task statuses: Backlog, To Do, In Progress, In Review, Done, and Blocked. Overdue tasks are calculated from due dates.

## Requirements

- Windows 10/11, PowerShell, Python 3.11+ (3.12 recommended), MySQL Server 8.0+, and optionally VS Code / MySQL Workbench.
- Check Python: `python --version`
- Check MySQL is running and remember your MySQL username/password.

## Setup (Windows PowerShell)

1. Extract this ZIP and open the `FlowState` folder in VS Code.
2. Create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal only, then activate again. Or use `.venv\Scripts\python.exe` directly without activation.

3. Install dependencies:

   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Create the database. In MySQL Workbench, connect to your local server, open a SQL tab and run:

   ```sql
   CREATE DATABASE flowstate_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```

   Then open `app/database.sql`, execute its full contents while connected to `flowstate_db`. Or use the MySQL CLI: `mysql -u your_mysql_username -p flowstate_db < app/database.sql`.

5. Copy `.env.example` to `.env`, then edit `DB_USER`, `DB_PASSWORD`, and `SECRET_KEY`. Use a long random secret key; never share the `.env` file. Keep `DB_NAME=flowstate_db`.

6. Create the first administrator securely (the password is entered without being echoed):

   ```powershell
   python scripts/create_admin.py
   ```

   The registration form creates a normal member/citizen account only; it cannot create administrators. For CivicPulse, additional staff roles can be granted through a trusted local database operation.

7. Run the app:

   ```powershell
   python run.py
   ```

   Open **http://127.0.0.1:5000**. `/health` is a lightweight process health endpoint.

## Demo data

No fake records are inserted automatically. Register a normal account and add your own records through the UI. For CivicPulse staff demonstrations, create a normal account and assign the `STAFF` role using MySQL Workbench after reviewing the role field.

## Tests

Run unit tests with `python -m unittest discover -s tests -v`. These tests cover password-hash behavior and a basic password-policy assertion. They do **not** replace end-to-end integration tests against a live MySQL server. Before a presentation, test registration, login/logout, role restrictions, CSRF rejection, record workflows, notifications, and refresh persistence against your own MySQL instance.

## Backup and restore

From PowerShell with MySQL client tools installed:

```powershell
mysqldump -u your_mysql_username -p flowstate_db > backup.sql
mysql -u your_mysql_username -p flowstate_db < backup.sql
```

## Troubleshooting

- **Can’t connect to MySQL:** check the MySQL service, host/port, database name, and credentials in `.env`.
- **Unknown database:** create `flowstate_db` and execute `app/database.sql`.
- **Missing module:** activate the virtual environment and run `pip install -r requirements.txt`.
- **CSRF error:** use the form pages in the running app; state-changing forms include CSRF tokens. Do not disable CSRF.
- **Port already in use:** stop the other local process or change the port in `run.py`.

## Security and limitations

- Set a strong `SECRET_KEY`, use HTTPS and `SESSION_COOKIE_SECURE=1` behind a correctly configured HTTPS deployment before production use. The included run command is for local demonstration, not production hosting.
- No paid services, email provider, external API, or Node.js are required. Notifications are in-app. File uploads are not included in this implementation.
- The UI is responsive and uses actual database-backed records, but run your own browser/device and live-MySQL acceptance checks before claiming full production readiness. The current automated tests are deliberately described by what they actually cover.
