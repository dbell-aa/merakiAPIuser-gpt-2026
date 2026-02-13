from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import meraki
import threading
import time
import uuid
import sys

app = Flask(__name__)
app.secret_key = "replace-this-with-a-random-secret"

# In-memory job store
jobs = {}


def log(job_id, message, category="info"):
    jobs[job_id]["logs"].append({
        "message": message,
        "category": category
    })

def run_job(job_id, api_key, email, name, action, org_ids):
    dashboard = meraki.DashboardAPI(api_key, suppress_logging=True)
    total = len(org_ids)
    completed = 0

    for org_id in org_ids:
        org_name = jobs[job_id]["org_map"].get(org_id, org_id)

        # Create initial log entry
        log_entry = {
            "message": f"{action.capitalize()} {email} in {org_name} ... ",
            "category": "info"
        }
        jobs[job_id]["logs"].append(log_entry)
        log_index = len(jobs[job_id]["logs"]) - 1

        try:
            if action in ["add_selected", "mass_add"]:
                admins = dashboard.organizations.getOrganizationAdmins(org_id)

                if any(a["email"].lower() == email.lower() for a in admins):
                    result = "Skipped: already exists"
                else:
                    dashboard.organizations.createOrganizationAdmin(
                        org_id,
                        email=email,
                        name=name,
                        orgAccess="full"
                    )
                    result = "Done"

            elif action in ["delete_selected", "mass_delete"]:
                admins = dashboard.organizations.getOrganizationAdmins(org_id)
                target = next(
                    (a for a in admins if a["email"].lower() == email.lower()),
                    None
                )

                if not target:
                    result = "Skipped: not found"
                else:
                    dashboard.organizations.deleteOrganizationAdmin(
                        org_id,
                        target["id"]
                    )
                    result = "Done"

            jobs[job_id]["logs"][log_index]["message"] += result

        except Exception as e:
            jobs[job_id]["logs"][log_index]["message"] += f"Failed: {str(e)}"
            jobs[job_id]["logs"][log_index]["category"] = "error"

        completed += 1
        jobs[job_id]["progress"] = int((completed / total) * 100)

    jobs[job_id]["status"] = "complete"

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        api_key = request.form["api_key"]
        session["api_key"] = api_key

        dashboard = meraki.DashboardAPI(api_key, suppress_logging=True)
        orgs = dashboard.organizations.getOrganizations()

        session["org_data"] = {org["id"]: org["name"] for org in orgs}
        return redirect(url_for("manage"))

    return render_template("index.html")


@app.route("/manage", methods=["GET"])
def manage():
    org_data = session.get("org_data", {})
    return render_template("manage.html", org_data=org_data)


@app.route("/start_job", methods=["POST"])
def start_job():
    api_key = session.get("api_key")
    org_data = session.get("org_data", {})

    email = request.form["email"]
    name = request.form.get("name", "")
    action = request.form["action"]

    if action.startswith("mass_"):
        org_ids = list(org_data.keys())
    else:
        org_ids = request.form.getlist("orgs")

    job_id = str(uuid.uuid4())

    jobs[job_id] = {
        "status": "running",
        "progress": 0,
        "logs": [],
        "org_map": org_data
    }

    thread = threading.Thread(
        target=run_job,
        args=(job_id, api_key, email, name, action, org_ids)
    )
    thread.start()

    return redirect(url_for("job_status", job_id=job_id))


@app.route("/job/<job_id>")
def job_status(job_id):
    return render_template("job.html", job_id=job_id)


@app.route("/job_status/<job_id>")
def job_status_api(job_id):
    return jsonify(jobs.get(job_id, {}))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    import threading
import webbrowser
import tkinter as tk
import sys

def start_flask():
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)

def open_browser():
    webbrowser.open("http://127.0.0.1:5000")

def quit_app(root):
    root.destroy()
    sys.exit(0)

if __name__ == "__main__":
    # Windows launcher mode (no GUI inside app.py)
    if "--no-gui" in sys.argv:
        start_flask()
    else:
        # macOS normal mode (Tkinter window)
        flask_thread = threading.Thread(target=start_flask, daemon=True)
        flask_thread.start()

        # Open browser after short delay
        threading.Timer(1.5, open_browser).start()

        # Create simple control window
        root = tk.Tk()
        root.title("Meraki Admin Tool")
        root.geometry("300x120")

        label = tk.Label(root, text="Meraki Admin Tool is running.", pady=10)
        label.pack()

        quit_button = tk.Button(root, text="Quit", command=lambda: quit_app(root))
        quit_button.pack(pady=10)

        root.mainloop()

