import meraki
import json
import re
import time
import os
from flask import Flask, request, render_template, redirect, url_for, session, flash

# --- Flask App Setup ---
app = Flask(__name__)
# IMPORTANT: Change this to a long, random secret key in a real application
# You can generate one using: python -c 'import os; print(os.urandom(24))'
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'your-default-secret-key') # Use environment variable or a default

# Delay between Meraki API calls (seconds). Adjust via env MERAKI_CALL_DELAY if needed.
CALL_DELAY_SECONDS = float(os.environ.get('MERAKI_CALL_DELAY', '1.2'))

# --- Helper Functions (Adapted from your original code) ---

def validate_email(email):
    email_pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return re.match(email_pattern, email) is not None

def log_message(message, category='info'):
    """Helper to store messages (with category) for later display and console output."""
    if 'results_log' not in session or not isinstance(session['results_log'], list):
        session['results_log'] = []

    entry = {
        "category": category,
        "message": f"[{category.upper()}] {message}"
    }

    # Prepend to show newest first
    session['results_log'].insert(0, entry)
    session.modified = True  # Important when modifying mutable session objects like lists

    # Also print to console for debugging
    print(entry["message"])


def normalize_results_log():
    """
    Normalize results_log entries to dicts with category/message for template consumption.
    Converts legacy string entries to info messages.
    """
    raw_entries = session.get('results_log', [])
    normalized = []

    for entry in raw_entries:
        if isinstance(entry, dict) and 'message' in entry and 'category' in entry:
            normalized.append(entry)
        elif isinstance(entry, str):
            normalized.append({"category": "info", "message": entry})

    session['results_log'] = normalized
    session.modified = True
    return normalized


def apply_rate_limit_delay():
    """Pause between sequential API calls to avoid hitting rate limits."""
    if CALL_DELAY_SECONDS > 0:
        log_message(f"Waiting {CALL_DELAY_SECONDS} seconds before next call...", 'debug')
        time.sleep(CALL_DELAY_SECONDS)


def delete_admin(dashboard, organization_id, admin_id, org_name=""):
    """Deletes an admin. Uses passed dashboard object."""
    org_identifier = f"{org_name} ({organization_id})" if org_name else organization_id
    if not admin_id:
        log_message(f"Admin ID not provided. Skipping deletion for org {org_identifier}.", 'warning')
        return False
    try:
        dashboard.organizations.deleteOrganizationAdmin(organization_id, admin_id)
        log_message(f"Successfully deleted admin ID {admin_id} from organization {org_identifier}.", 'success')
        return True
    except meraki.APIError as e:
        log_message(f"Failed to delete admin ID {admin_id} from organization {org_identifier}: {e}", 'danger')
        return False
    except Exception as e:
        log_message(f"Unexpected error during deletion in {org_identifier}: {e}", 'danger')
        return False

def add_admin(dashboard, organization_id, email, name, org_name=""):
    """Adds an admin. Uses passed dashboard object."""
    org_identifier = f"{org_name} ({organization_id})" if org_name else organization_id
    log_message(f"Starting add_admin for {email} in {org_identifier}", 'debug')
    
    admin_id = check_for_email_in_admins(dashboard, organization_id, email, org_name, suppress_found_msg=True) # Check first
    if admin_id:
        log_message(f"Admin with email {email} already exists (ID: {admin_id}) in organization {org_identifier}. Skipping addition.", 'info')
        return None # Indicate skipped

    log_message(f"Attempting to create admin {email} in {org_identifier}", 'debug')
    try:
        response = dashboard.organizations.createOrganizationAdmin(
            organization_id, email, name, orgAccess="full" # Changed 'full' to 'orgAccess="full"' based on potential library changes
        )
        log_message(f"API response when creating admin: {response}", 'debug')
        log_message(f"Successfully added admin {name} ({email}) to organization {org_identifier}. Response: {response.get('id', 'N/A')}", 'success')
        return response # Return the response which might contain the new admin ID
    except meraki.APIError as e:
        log_message(f"Failed to add admin {email} to organization {org_identifier}: {e}", 'danger')
        return False
    except Exception as e:
        log_message(f"Unexpected error during addition to {org_identifier}: {e}", 'danger')
        return False

def check_for_email_in_admins(dashboard, organization_id, email, org_name="", suppress_found_msg=False):
    """Checks for admin email. Uses passed dashboard object."""
    org_identifier = f"{org_name} ({organization_id})" if org_name else organization_id
    log_message(f"Checking for email {email} in {org_identifier}", 'debug')
    try:
        admins = dashboard.organizations.getOrganizationAdmins(organization_id)
        log_message(f"Found {len(admins)} admins in {org_identifier}", 'debug')
        for admin in admins:
            if admin['email'].lower() == email.lower():
                if not suppress_found_msg:
                    log_message(f"Found admin: {admin['name']} (Email: {admin['email']}, ID: {admin['id']}) in org {org_identifier}", 'info')
                log_message(f"Email {email} matched admin ID {admin['id']}", 'debug')
                return admin['id'] # Return the admin ID if found

        log_message(f"Email {email} not found in {org_identifier}", 'debug')
        if not suppress_found_msg:
            log_message(f"No admin with email {email} found in organization {org_identifier}.", 'info')
        return None # Return None if not found

    except meraki.APIError as e:
        log_message(f"API Error checking admins in {org_identifier}: {e}", 'danger')
        return None
    except Exception as e:
        log_message(f"Unexpected Error checking admins in {org_identifier}: {e}", 'danger')
        return None

def mass_delete_admin(dashboard, organizations, email):
    """Mass deletes an admin. Uses passed dashboard object and org dict."""
    log_message(f"--- Starting Mass Delete for {email} ---", 'info')
    deleted_count = 0
    checked_count = 0
    no_email_found_orgs = []

    for org_id, org_name in organizations.items():
        checked_count += 1
        log_message(f"Checking organization: {org_name} (ID: {org_id})", 'info')
        admin_id = check_for_email_in_admins(dashboard, org_id, email, org_name)

        if admin_id:
            if delete_admin(dashboard, org_id, admin_id, org_name):
                deleted_count += 1
        else:
            # Logged already by check_for_email_in_admins
            no_email_found_orgs.append(org_name)

        apply_rate_limit_delay()

    log_message(f"--- Mass Delete for {email} Complete ---", 'info')
    log_message(f"Checked {checked_count} organizations.", 'info')
    log_message(f"Successfully deleted admin from {deleted_count} organizations.", 'success')
    if no_email_found_orgs:
        log_message(f"Admin not found in: {', '.join(no_email_found_orgs)}", 'info')


def mass_add_admin(dashboard, organizations, email, name):
    """Mass adds an admin. Uses passed dashboard object and org dict."""
    log_message(f"Starting Mass Add for {name} ({email}) across {len(organizations)} organizations", 'debug')
    log_message(f"--- Starting Mass Add for {name} ({email}) ---", 'info')
    added_count = 0
    skipped_count = 0
    failed_count = 0
    checked_count = 0

    for org_id, org_name in organizations.items():
        checked_count += 1
        log_message(f"Processing org {checked_count}/{len(organizations)}: {org_name} (ID: {org_id})", 'debug')
        log_message(f"Processing organization: {org_name} (ID: {org_id})", 'info')
        
        result = add_admin(dashboard, org_id, email, name, org_name)
        
        if result is None: # Indicates skipped because already exists
            skipped_count += 1
            log_message(f"SKIPPED - Admin already exists in {org_name}", 'debug')
        elif result: # Indicates success (got a response object)
            added_count += 1
            log_message(f"SUCCESS - Added admin to {org_name}", 'debug')
        else: # Indicates failure
            failed_count += 1
            log_message(f"FAILED - Could not add admin to {org_name}", 'debug')

        apply_rate_limit_delay()

    log_message("Mass Add Complete", 'debug')
    log_message(f"Summary: {added_count} added, {skipped_count} skipped, {failed_count} failed", 'debug')
    log_message(f"--- Mass Add for {email} Complete ---", 'info')
    log_message(f"Checked {checked_count} organizations.", 'info')
    log_message(f"Successfully added admin to {added_count} organizations.", 'success')
    log_message(f"Skipped {skipped_count} organizations (admin likely already existed).", 'info')
    if failed_count > 0:
        log_message(f"Failed to add admin to {failed_count} organizations.", 'warning')


# --- Flask Routes ---

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        api_key = request.form.get('api_key')
        if not api_key:
            flash('API key cannot be empty.', 'danger')
            return render_template('index.html')

        # Clear previous session data
        session.clear()
        # Reset log for new session
        session['results_log'] = []

        try:
            # Suppress console output from meraki library during init/fetch if desired
            log_message("Initializing Meraki Dashboard API...", 'debug')
            dashboard = meraki.DashboardAPI(api_key, suppress_logging=True)
            log_message("Getting organizations...", 'debug')
            organizations = dashboard.organizations.getOrganizations()
            log_message(f"Found {len(organizations)} organizations", 'debug')

            if not organizations:
                log_message("No organizations found for this API key.", 'warning')
                flash('API key is valid, but no organizations were found or accessible.', 'warning')
                return render_template('index.html')

            # Store essential info in session
            session['api_key'] = api_key
            session['org_data'] = {org['id']: org['name'] for org in organizations}
            log_message("Successfully loaded organizations.", 'success')
            session.modified = True # Mark session as modified
            
            log_message(f"Organizations loaded into session: {', '.join(session['org_data'].values())}", 'debug')

            flash('API Key accepted and organizations loaded.', 'success')
            return redirect(url_for('manage'))

        except meraki.APIError as e:
            flash(f'Meraki API Error: Failed to validate API key or fetch organizations. Please check the key and permissions. Error: {e}', 'danger')
            return render_template('index.html')
        except Exception as e:
            flash(f'An unexpected error occurred: {e}', 'danger')
            return render_template('index.html')

    # GET request or failed POST validation
    return render_template('index.html')


@app.route('/manage', methods=['GET'])
def manage():
    if 'api_key' not in session or 'org_data' not in session:
        flash('Please enter your API key first.', 'info')
        return redirect(url_for('index'))

    # Pass org data and results log to the template
    org_data = session.get('org_data', {})
    results_log = normalize_results_log()
    return render_template('manage.html', org_data=org_data, results=results_log)

@app.route('/manage-admin', methods=['POST'])
def manage_admin():
    if 'api_key' not in session:
        flash('Session expired or invalid. Please enter API key again.', 'warning')
        return redirect(url_for('index'))

    api_key = session['api_key']
    org_data = session.get('org_data', {})
    normalize_results_log() # Ensure results_log entries are in dict format for consistent logging

    # Get form data
    email = request.form.get('email')
    name = request.form.get('name')
    action = request.form.get('action')
    organization_id = request.form.get('organization_id') # Might be empty for mass actions

    # --- Basic Input Validation ---
    if not email or not validate_email(email):
        flash('Invalid or missing email address.', 'danger')
        return redirect(url_for('manage'))

    if not action:
        flash('No action selected.', 'danger')
        return redirect(url_for('manage'))

    if action in ['add', 'mass_add'] and not name:
        flash('Admin name is required for add actions.', 'danger')
        return redirect(url_for('manage'))

    if action in ['add', 'delete', 'check'] and not organization_id:
        flash('Please select a target organization for this action.', 'danger')
        return redirect(url_for('manage'))

    # --- Perform Action ---
    try:
        # Initialize Dashboard API for this request
        # suppress_logging=True prevents the library from printing to *console*
        dashboard = meraki.DashboardAPI(api_key, suppress_logging=True)

        org_name = org_data.get(organization_id, organization_id) # Get name if available

        log_message(f"--- Action Requested: {action.replace('_', ' ').title()} for {email} ---", "info")

        if action == 'add':
            add_admin(dashboard, organization_id, email, name, org_name)
        elif action == 'delete':
            admin_id = check_for_email_in_admins(dashboard, organization_id, email, org_name)
            if admin_id:
                delete_admin(dashboard, organization_id, admin_id, org_name)
            # No else needed, check_for_email_in_admins already logs if not found
        elif action == 'mass_add':
            log_message(f"Starting mass_add action for {email}", 'debug')
            log_message(f"Organization data contains {len(org_data)} organizations", 'debug')
            mass_add_admin(dashboard, org_data, email, name)
        elif action == 'mass_delete':
            mass_delete_admin(dashboard, org_data, email)
        elif action == 'check':
            check_for_email_in_admins(dashboard, organization_id, email, org_name) # This function already logs results
        else:
            log_message(f"Unknown action '{action}'.", 'danger')

    except meraki.APIError as e:
        log_message(f"Meraki API Error during action '{action}': {e}", 'danger')
    except Exception as e:
        log_message(f"An unexpected error occurred during action '{action}': {e}", 'danger')

    # No flash message here as logs are displayed directly.
    # Redirect back to the manage page to show updated logs
    return redirect(url_for('manage'))


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# --- Run the App ---
if __name__ == '__main__':
    # Use debug=True only for development! Remove or set to False for production.
    # Consider using a proper WSGI server like Gunicorn or Waitress for production.
    app.run(debug=True, host='0.0.0.0', port=5003) # Run on port 5003 to avoid conflicts