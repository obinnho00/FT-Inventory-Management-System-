from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.core.files.base import ContentFile
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.urls import reverse
import io
import re
from PIL import Image
import qrcode
from zoneinfo import ZoneInfo
from .models import Building, Department, UserRequirement, Machine, MachinePart, VendorPart, Part, DepartmentAuthorizedUser, ManagerAccount, AdminSetupKey, Station, WorkOrderRequest
from functools import wraps


def require_any_login(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if (
            request.session.get("inventory_user")
            or request.session.get("inventory_manager_account_id")
            or request.user.is_superuser
            or request.session.get("inventory_admin_manager_setup_unlocked")
        ):
            return view_func(request, *args, **kwargs)
        messages.error(request, "Please login first.")
        return redirect("inventory_login")
    return _wrapped


def _safe_part_image_url(part):
    if not part.image:
        return ""
    try:
        if part.image.storage.exists(part.image.name):
            return part.image.url
    except Exception:
        return ""
    return ""

def _get_inventory_session_user(request):
    # This helper reads the logged-in inventory user from session.
    # We store first name, last name, and department to tie every stock action to a person.
    return request.session.get("inventory_user")

def _build_shared_template_context(request):
    inventory_user = _get_inventory_session_user(request)
    department_names = (inventory_user or {}).get("department_names") or []
    manager_account = _get_manager_session_account(request)
    manager_department_names = []
    if manager_account:
        manager_department_names = list(manager_account.departments.order_by("name").values_list("name", flat=True))
    allowed_department_ids = sorted(_get_allowed_department_ids(request))
    can_access_work_station = bool(allowed_department_ids)
    inventory_dashboard_url = reverse("inventory")
    reporting_manager_name = "-"
    reporting_manager_email = "-"

    if inventory_user and allowed_department_ids:
        user_email = (inventory_user.get("email") or "").strip().lower()
        allowed_department_id_set = set(allowed_department_ids)
        reporting_manager = None
        best_score = -1

        manager_candidates = (
            ManagerAccount.objects.filter(is_active=True, departments__id__in=allowed_department_ids)
            .prefetch_related("departments")
            .order_by("first_name", "last_name", "email")
            .distinct()
        )

        for candidate in manager_candidates:
            candidate_email = (candidate.email or "").strip().lower()
            if user_email and candidate_email == user_email:
                continue

            candidate_department_ids = {department.id for department in candidate.departments.all()}
            overlap_score = len(candidate_department_ids.intersection(allowed_department_id_set))

            if overlap_score > best_score:
                reporting_manager = candidate
                best_score = overlap_score

        if reporting_manager:
            reporting_manager_name = f"{reporting_manager.first_name} {reporting_manager.last_name}".strip() or "-"
            reporting_manager_email = reporting_manager.email or "-"

    if allowed_department_ids:
        inventory_dashboard_url = f"{reverse('inventory')}?department={allowed_department_ids[0]}"

    return {
        "inventory_user": inventory_user,
        "inventory_user_departments_text": ", ".join(department_names),
        "manager_account": manager_account,
        "show_public_dashboard_search": False,
        "manager_departments_text": ", ".join(manager_department_names),
        "admin_unlocked": bool(request.session.get("inventory_admin_manager_setup_unlocked", False)),
        "can_access_work_station": can_access_work_station,
        "inventory_dashboard_url": inventory_dashboard_url,
        "reporting_manager_name": reporting_manager_name,
        "reporting_manager_email": reporting_manager_email,
    }

def _render_template(request, template_name, context=None):
    shared_context = _build_shared_template_context(request)
    if context:
        shared_context.update(context)
    return render(request, template_name, shared_context)

def _set_machine_part_last_action(machine_part, request, action_type, action_quantity=None):
    # This helper stamps WHO performed the latest inventory action.
    # It writes first/last name + action type + timestamp on the exact machine-part row.
    user = _get_inventory_session_user(request)
    if not user:
        return

    machine_part.last_used_quantity = action_quantity if action_type == "USED" else None
    machine_part.last_action_by_first_name = user.get("first_name", "")
    machine_part.last_action_by_last_name = user.get("last_name", "")
    machine_part.last_action_type = action_type
    machine_part.last_action_at = timezone.now()

def inventory_login_view(request):
    # Login page for inventory operations.
    # User must provide email + target department + manager access code for that department.
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        department_id = request.POST.get("department_id", "").strip()
        access_code = request.POST.get("access_code", "").strip()

        # Validate basic input first.
        if not email or not department_id or not access_code:
            messages.error(request, "Email, department, and access code are required.")
            return redirect("inventory_login")

        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "Please enter a valid email address.")
            return redirect("inventory_login")

        try:
            department_id_int = int(department_id)
        except (TypeError, ValueError):
            messages.error(request, "Please select a valid department.")
            return redirect("inventory_login")

        # Manager emails must use manager login path only.
        if ManagerAccount.objects.filter(email__iexact=email, is_active=True).exists():
            messages.error(request, "Manager accounts must login from Manager login.")
            return redirect("manager_login")

        authorized_user = (
            DepartmentAuthorizedUser.objects.select_related("department")
            .filter(
                email__iexact=email,
                department_id=department_id_int,
                is_active=True,
            )
            .first()
        )
        if not authorized_user:
            messages.error(request, "Access not granted for this email in the selected department.")
            return redirect("inventory_login")

        # Department login code must match an active manager account that owns this department.
        manager_accounts = ManagerAccount.objects.filter(
            is_active=True,
            departments__id=department_id_int,
        ).distinct()
        if not manager_accounts.exists():
            messages.error(request, "No manager access code is configured for this department.")
            return redirect("inventory_login")

        code_is_valid = any(manager.check_access_code(access_code) for manager in manager_accounts)
        if not code_is_valid:
            messages.error(request, "Invalid department access code.")
            return redirect("inventory_login")

        department_ids = [department_id_int]
        department_names = [authorized_user.department.name]

        # Save user identity in session for audit tracking on inventory updates.
        request.session["inventory_user"] = {
            "first_name": authorized_user.first_name,
            "last_name": authorized_user.last_name,
            "email": email,
            "department_ids": department_ids,
            "department_names": department_names,
        }
        request.session.set_expiry(60 * 30)

        messages.success(request, f"Logged in as {authorized_user.first_name} {authorized_user.last_name}. Department: {authorized_user.department.name}.")
        return redirect("inventory_manage")

    context = {
        "departments": Department.objects.select_related("building").all().order_by("name"),
    }
    return _render_template(request, "login.html", context)

def inventory_logout_view(request):
    # Remove all app-level login sessions (inventory user, manager login, and admin unlock session).
    request.session.pop("inventory_user", None)
    request.session.pop("inventory_manager_account_id", None)
    request.session.pop("inventory_admin_manager_setup_unlocked", None)
    messages.success(request, "You have been logged out.")
    return redirect("inventory_login")



# function for the home page of the inventory system
def Home(request):
    #load the data based when the web interface comes in
    load_departments = Department.objects.all().order_by('name')
    search_results = []
    search_query = ""
    
    # Handle search if form is submitted
    if request.method == 'POST':
        search_query = request.POST.get('search_value', '').strip()
        if search_query:
            if search_query.isdigit():
                # Search by MachinePart ID
                search_results = MachinePart.objects.filter(id=int(search_query))
            else:
                # Search by part name
                search_results = MachinePart.objects.filter(part__part_name__icontains=search_query)
    
    context = {
        'departments': load_departments,
        'search_results': search_results,
        'search_query': search_query,
    }
    return _render_template(request, 'Home.html', context)

def handle_requirement_submission(request):
    if request.method == 'GET':
        return redirect('home')

    if request.method == 'POST':
        name = request.POST.get('name')
        department_id = request.POST.get('department')
        message = request.POST.get('message')

        try:
            department = Department.objects.get(id=department_id)

            UserRequirement.objects.create(
                department=department,
                name_of_requester=name,
                requirement_description=message
            )

            messages.success(request, 'Thank you! Your requirement has been submitted successfully.')
            return redirect('home')

        except Department.DoesNotExist:
            messages.error(request, 'Invalid department selected.')
            return redirect('home')

    messages.error(request, 'Request method is not supported for this action.')
    return redirect('home')

def upload_part_image_popup(request):
    if request.method != "POST":
        messages.error(request, "Request method is not supported for this action.")
        return redirect("inventory")

    user = _get_inventory_session_user(request)
    if not user:
        messages.error(request, "Please login first to upload part images.")
        return redirect("inventory_login")

    user_department_ids = user.get("department_ids") or []
    if not user_department_ids and user.get("department_id"):
        user_department_ids = [user.get("department_id")]

    department_id = request.POST.get("department_id", "").strip()
    if not department_id:
        messages.error(request, "Please select a department first before uploading an image.")
        return redirect("inventory")

    try:
        department_id_int = int(department_id)
    except ValueError:
        messages.error(request, "Invalid department selection.")
        return redirect("inventory")

    if department_id_int not in user_department_ids:
        messages.error(request, "You are not allowed to upload images for this department.")
        return redirect("inventory")

    model_number = request.POST.get("model_number", "").strip()
    selected_model = request.POST.get("part_model", "").strip()
    image_file = request.FILES.get("part_image")

    target_model = selected_model or model_number

    if not target_model:
        messages.error(request, "Please choose an existing part first.")
        return redirect("inventory")

    if not image_file:
        messages.error(request, "Please select an image file to upload.")
        return redirect("inventory")

    try:
        part = Part.objects.get(model_number=target_model)
    except Part.DoesNotExist:
        messages.error(request, "Selected part was not found.")
        return redirect(f"{reverse('inventory')}?department={department_id_int}")

    part_belongs_to_department = MachinePart.objects.filter(
        part=part,
        machine__department_id=department_id_int,
    ).exists()
    if not part_belongs_to_department:
        messages.error(request, "You can only upload images for parts used in your selected department.")
        return redirect(f"{reverse('inventory')}?department={department_id_int}")

    replacing_existing = bool(part.image)
    part.image = image_file
    part.save(update_fields=["image"])

    if replacing_existing:
        messages.success(request, f"Image replaced for {part.name} ({part.model_number}).")
    else:
        messages.success(request, f"Image added for {part.name} ({part.model_number}).")

    return redirect(f"{reverse('inventory')}?department={department_id_int}")






# this is the main inventory view that shows the inventory table with dynamic columns and filters, and also allows clicking into each row to see more details about the part, machine, and vendors. It also supports department filtering on top.
# this is the main inventory view that shows the inventory table with dynamic columns and filters, and also allows clicking into each row to see more details about the part, machine, and vendors. It also supports department filtering on top.
# this table shoes all machine-part relationships across the factory, so you can see which parts are used by which machines, and how many are left in inventory. You can filter by department to narrow down to specific areas of the factory. Each row is clickable to show more details about the part, the machine it belongs to, and the vendors that supply that part.
def inventory_view(request):

    selected_department = request.GET.get("department")
    selected_station = request.GET.get("station", "").strip()

    inventory_user = _get_inventory_session_user(request)
    manager_account = _get_manager_session_account(request)
    is_logged_in_inventory_scope = bool(inventory_user or manager_account)
    user_department_ids = (inventory_user or {}).get("department_ids") or []
    if not user_department_ids and (inventory_user or {}).get("department_id"):
        user_department_ids = [(inventory_user or {}).get("department_id")]

    allowed_department_ids = _get_allowed_department_ids(request)

    if is_logged_in_inventory_scope:
        if allowed_department_ids:
            departments = Department.objects.select_related("building").filter(id__in=allowed_department_ids).order_by("name")
        else:
            departments = Department.objects.none()
    else:
        departments = Department.objects.select_related("building").all()

    if selected_department and selected_department.isdigit():
        selected_department_int = int(selected_department)
        if is_logged_in_inventory_scope and allowed_department_ids and selected_department_int not in allowed_department_ids:
            selected_department = ""

    stations = Station.objects.select_related("department").all()
    if selected_department and selected_department.isdigit():
        stations = stations.filter(department_id=int(selected_department))
    elif is_logged_in_inventory_scope and allowed_department_ids:
        stations = stations.filter(department_id__in=allowed_department_ids)
    stations = stations.order_by("name")

    if selected_station and not stations.filter(id=selected_station).exists():
        selected_station = ""

    can_upload_part_image = False
    upload_department_id = ""
    if selected_department and selected_department.isdigit():
        selected_department_id = int(selected_department)
        if selected_department_id in user_department_ids:
            can_upload_part_image = True
            upload_department_id = str(selected_department_id)

    parts = MachinePart.objects.select_related(
        "machine",
        "machine__department",
        "machine__department__building",
        "part"
    ).prefetch_related(
        "part__vendorpart_set__vendor",
        "part__vendorpart_set__manufacturer"
    )

    if selected_department:
        parts = parts.filter(machine__department__id=selected_department)
    if selected_station:
        parts = parts.filter(machine__station_id=selected_station)

    table_columns = []

    for field in MachinePart._meta.get_fields():

        # Skip reverse relations
        if field.auto_created and not field.concrete:
            continue

        field_name = field.name

        # ---- HANDLE FOREIGN KEYS DYNAMICALLY ----
        if field.many_to_one:

            related_model = field.related_model

            # Machine FK
            if related_model.__name__ == "Machine":
                table_columns.extend([
                    {
                        "header": "Building",
                        "path": "machine.department.building.name",
                        "type": "text"
                    },
                    {
                        "header": "Department",
                        "path": "machine.department.name",
                        "type": "text"
                    },
                    {
                        "header": "Machine",
                        "path": "machine.name",
                        "type": "text"
                    }
                ])

            # Part FK
            elif related_model.__name__ == "Part":
                table_columns.extend([
                    {
                        "header": "Part Name",
                        "path": "part.name",
                        "type": "text"
                    },
                    {
                        "header": "Model Number",
                        "path": "part.model_number",
                        "type": "text"
                    }
                ])

        # ---- HANDLE REGULAR FIELDS ----
        # this section section to display the table header and of last used information, it will dynamically add the header based on the field name, and also specify the type of the column for better rendering in the frontend. for example, if the field name contains "quantity", it will be marked as a quantity type for potential special formatting (like highlighting low stock).
        else:
            if field_name not in ["id", "machine", "part"]:
                header_overrides = {
                    "last_action_by_first_name": "First Name",
                    "last_action_by_last_name": "Last Name",
                    "last_action_type": "Action Type",
                    "last_used_quantity": "Qty Used",
                    "last_action_at": "Time Used",
                }
                header = header_overrides.get(field_name, field_name.replace("_", " ").title())

                field_type = "text" if field_name == "last_used_quantity" else (
                    "quantity" if "quantity" in field_name.lower() else "text"
                )

                table_columns.append({
                    "header": header,
                    "path": field_name,
                    "type": field_type
                })

    # ---- ADD VENDORS DYNAMICALLY ----
    table_columns.append({
        "header": "Vendors",
        "path": "part.vendorpart_set.all",
        "type": "vendors"
    })

    data_rows = []
    row_details = []

    for item in parts:
        row = []

        for col in table_columns:
            value = item

            try:
                for attr in col["path"].split("."):
                    if attr == "all":
                        value = value.all()
                        break
                    value = getattr(value, attr, None)
                    if value is None:
                        break

                if value is None:
                    row.append({"value": "-", "type": "text"})

                elif col["type"] == "vendors":
                    vendors = []
                    for link in value:
                        text = link.vendor.name if link.vendor else ""
                        if link.manufacturer:
                            text += f" ({link.manufacturer.name})"
                        vendors.append(text)

                    row.append({
                        "value": vendors if vendors else ["No Vendor"],
                        "type": "vendors"
                    })

                elif col["type"] == "quantity":
                    row.append({
                        "value": value,
                        "type": "quantity",
                        "is_low": value <= 2 if isinstance(value, (int, float)) else False
                    })

                else:
                    row.append({"value": str(value), "type": "text"})

            except Exception:
                row.append({"value": "-", "type": "text"})

        data_rows.append(row)

        vendor_details = []
        for link in item.part.vendorpart_set.all():
            vendor_details.append({
                "vendor": link.vendor.name if link.vendor else "-",
                "manufacturer": link.manufacturer.name if link.manufacturer else "-",
                "website": link.vendor.website if link.vendor and link.vendor.website else "",
                "phone": link.vendor.phone if link.vendor and link.vendor.phone else "",
            })

        row_details.append({
            "part": item.part.name,
            "model": item.part.model_number,
            "machine": item.machine.name,
            "machine_location": item.machine.location,
            "department": item.machine.department.name,
            "building": item.machine.department.building.name,
            "quantity": item.quantity_left,
            "location": item.placement_location,
            "description": item.part.description,
            "compatibility_notes": item.compatibility_notes,
            "last_used_quantity": item.last_used_quantity,
            "image_url": _safe_part_image_url(item.part),
            "vendors": vendor_details,
        })

    has_logged_session = bool(inventory_user or manager_account or request.user.is_superuser or request.session.get("inventory_admin_manager_setup_unlocked"))

    context = {
        "departments": departments,
        "stations": stations,
        "selected_department": selected_department,
        "selected_station": selected_station,
        "table_columns": table_columns,
        "data_rows": data_rows,
        "row_details": row_details,
        "can_upload_part_image": can_upload_part_image,
        "upload_department_id": upload_department_id,
        "show_inventory_filters": is_logged_in_inventory_scope,
        "show_public_dashboard_search": not has_logged_session,
    }

    return _render_template(request, "dashboard.html", context)



# this function handle the seach filed which accept the seach by part name, model number or vendor name. it will return the result in the same table format as the main inventory page, but only show the matched results based on the search query. it also supports partial match and case-insensitive search for better usability.
# the search results page will also show the same dynamic columns and details view as the main inventory page, so you can click into each row to see more information about the part, machine, and vendors. this allows users to quickly find specific parts or machines in the inventory by searching with keywords, and then drill down into the details from the search results.

def inventory_search(request):
    query = request.GET.get("q", "").strip()

    results = MachinePart.objects.select_related(
        "machine",
        "machine__department",
        "machine__department__building",
        "part"
    ).prefetch_related(
        "part__vendorpart_set__vendor",
        "part__vendorpart_set__manufacturer"
    )

    if query:
        results = results.filter(
            Q(part__model_number__icontains=query) |
            Q(part__name__icontains=query) |
            Q(part__vendorpart__vendor__name__icontains=query)
        ).distinct()

    # ===============================
    # Dynamic Columns
    # ===============================

    table_columns = []

    if results.exists():
        sample = results.first()

        table_columns = [
            {"header": "Building"},
            {"header": "Department"},
            {"header": "Machine"},
            {"header": "Part Name"},
            {"header": "Model"},
            {"header": "Quantity Left"},
            {"header": "Location"},
        ]

    data_rows = []
    row_details = []

    for item in results:
        row = [
            {"value": item.machine.department.building.name},
            {"value": item.machine.department.name},
            {"value": item.machine.name},
            {"value": item.part.name},
            {"value": item.part.model_number},
            {
                "value": item.quantity_left,
                "type": "quantity",
                "is_low": item.quantity_left <= 5
            },
            {"value": item.placement_location}
        ]
        data_rows.append(row)

        vendor_details = []
        for link in item.part.vendorpart_set.all():
            vendor_details.append({
                "vendor": link.vendor.name if link.vendor else "-",
                "manufacturer": link.manufacturer.name if link.manufacturer else "-",
                "website": link.vendor.website if link.vendor and link.vendor.website else "",
                "phone": link.vendor.phone if link.vendor and link.vendor.phone else "",
            })

        row_details.append({
            "part": item.part.name,
            "model": item.part.model_number,
            "machine": item.machine.name,
            "machine_location": item.machine.location,
            "department": item.machine.department.name,
            "building": item.machine.department.building.name,
            "quantity": item.quantity_left,
            "location": item.placement_location,
            "description": item.part.description,
            "compatibility_notes": item.compatibility_notes,
            "last_used_quantity": item.last_used_quantity,
            "image_url": _safe_part_image_url(item.part),
            "vendors": vendor_details,
        })

    has_logged_session = bool(
        _get_inventory_session_user(request)
        or _get_manager_session_account(request)
        or request.user.is_superuser
        or request.session.get("inventory_admin_manager_setup_unlocked")
    )

    context = {
        "table_columns": table_columns,
        "data_rows": data_rows,
        "row_details": row_details,
        "departments": Department.objects.all(),
        "stations": Station.objects.none(),
        "selected_department": None,
        "selected_station": "",
        "search_query": query,
        "can_upload_part_image": False,
        "upload_department_id": "",
        "show_inventory_filters": False,
        "show_public_dashboard_search": not has_logged_session,
    }

    return _render_template(request, "dashboard.html", context)


# this is the Update inventory page where you can add new inventory or use existing inventory. the left side of the page is for adding new inventory, where you can select the department, machine, and part (or create a new part on the fly), and specify the quantity, location, and usage notes. when you submit the form, it will update the inventory quantity for that machine-part combination, and also record who made the change and when for audit tracking.
# this function allows acces to the inventory management page where users can add new inventory or record used inventory. The left side of the page is for adding inventory, where users can select the department, machine, and part (or create a new part), and specify quantity, location, and usage notes. When submitted, it updates the inventory quantity for that machine-part combination and records who made the change and when for audit tracking. The right side of the page is for recording used inventory, where users can select the department, machine, and specific inventory item, and specify how many units were used. This will auto-reduce the quantity in the database and also track who used the inventory and when. This page ensures that all inventory changes are tied to a named user for accountability.

@require_any_login
def inventory_manage_view(request):
    # Enforce login: inventory add/use actions must be tied to a named person.
    user = _get_inventory_session_user(request)
    if not user:
        messages.error(request, "Please login first.")
        return redirect("inventory_login")

    user_department_ids = user.get("department_ids") or []
    if not user_department_ids and user.get("department_id"):
        user_department_ids = [user.get("department_id")]

    if not user_department_ids:
        messages.error(request, "No authorized departments found for this login.")
        return redirect("inventory_login")

    if request.method == "POST":
        action = request.POST.get("action", "").strip()

        if action == "add_inventory":
            department_id = request.POST.get("department_id", "").strip()
            machine_id = request.POST.get("machine_id", "").strip()
            part_mode = request.POST.get("part_mode", "existing").strip().lower()
            part_id = request.POST.get("part_id", "").strip()
            new_part_name = request.POST.get("new_part_name", "").strip()
            new_model_number = request.POST.get("new_model_number", "").strip()
            new_description = request.POST.get("new_description", "").strip()
            add_quantity = request.POST.get("add_quantity", "").strip()
            placement_location = request.POST.get("placement_location", "").strip()
            usage_notes = request.POST.get("usage_notes", "").strip()

            if not department_id or not machine_id or not add_quantity:
                messages.error(request, "Department, machine, and quantity are required to add inventory.")
                return redirect("inventory_manage")

            # Department lock: user can only manage inventory for the department they logged into.
            if int(department_id) not in user_department_ids:
                messages.error(request, "You can only add inventory for your authorized departments.")
                return redirect("inventory_manage")

            try:
                quantity_value = int(add_quantity)
                if quantity_value <= 0:
                    raise ValueError()
            except ValueError:
                messages.error(request, "Add quantity must be a valid number greater than 0.")
                return redirect("inventory_manage")

            try:
                machine = Machine.objects.select_related("department").get(id=machine_id)
            except Machine.DoesNotExist:
                messages.error(request, "Selected machine does not exist.")
                return redirect("inventory_manage")

            if str(machine.department_id) != department_id:
                messages.error(request, "Selected machine does not belong to the selected department.")
                return redirect("inventory_manage")

            if part_mode == "new":
                if not new_part_name or not new_model_number:
                    messages.error(request, "New part name and model number are required.")
                    return redirect("inventory_manage")

                part, created_part = Part.objects.get_or_create(
                    model_number=new_model_number,
                    defaults={
                        "name": new_part_name,
                        "description": new_description,
                    },
                )

                if created_part:
                    messages.success(request, f"New part created: {part.name} ({part.model_number}).")
                else:
                    part.name = new_part_name
                    if new_description:
                        part.description = new_description
                    part.save(update_fields=["name", "description"])
                    messages.success(request, f"Part model {part.model_number} already existed and was updated.")
            else:
                if not part_id:
                    messages.error(request, "Please select an existing part.")
                    return redirect("inventory_manage")

                try:
                    part = Part.objects.get(id=part_id)
                except Part.DoesNotExist:
                    messages.error(request, "Selected part does not exist.")
                    return redirect("inventory_manage")

            machine_part, created = MachinePart.objects.get_or_create(
                machine=machine,
                part=part,
                defaults={
                    "quantity_left": 0,
                    "placement_location": placement_location,
                    "compatibility_notes": usage_notes,
                },
            )

            machine_part.quantity_left += quantity_value

            if placement_location:
                machine_part.placement_location = placement_location

            if usage_notes:
                machine_part.compatibility_notes = usage_notes

            machine_part.save()

            # Record the last inventory action with accurate action labels.
            add_action_type = "ADDED" if created else "INCREASED"
            _set_machine_part_last_action(machine_part, request, add_action_type, quantity_value)
            machine_part.save(update_fields=[
                "quantity_left",
                "placement_location",
                "compatibility_notes",
                "last_action_by_first_name",
                "last_action_by_last_name",
                "last_action_type",
                "last_used_quantity",
                "last_action_at",
            ])

            if created:
                messages.success(
                    request,
                    f"Inventory record created. Added {quantity_value} units. Current quantity: {machine_part.quantity_left}.",
                )
            else:
                messages.success(
                    request,
                    f"Inventory quantity increased by {quantity_value} units. Current quantity: {machine_part.quantity_left}.",
                )

            return redirect("inventory_manage")

        if action == "use_inventory":
            department_id = request.POST.get("department_id", "").strip()
            machine_id = request.POST.get("machine_id", "").strip()
            machine_part_id = request.POST.get("machine_part_id", "").strip()
            used_quantity = request.POST.get("used_quantity", "").strip()

            if not department_id or not machine_id or not machine_part_id or not used_quantity:
                messages.error(request, "Department, machine, inventory item, and used quantity are required.")
                return redirect("inventory_manage")

            # Department lock: user can only consume inventory from their own department.
            if int(department_id) not in user_department_ids:
                messages.error(request, "You can only use inventory for your authorized departments.")
                return redirect("inventory_manage")

            try:
                used_value = int(used_quantity)
                if used_value <= 0:
                    raise ValueError()
            except ValueError:
                messages.error(request, "Used quantity must be a valid number greater than 0.")
                return redirect("inventory_manage")

            try:
                machine_part = MachinePart.objects.select_related("machine", "part").get(id=machine_part_id)
            except MachinePart.DoesNotExist:
                messages.error(request, "Selected inventory item does not exist.")
                return redirect("inventory_manage")

            if str(machine_part.machine.department_id) != department_id:
                messages.error(request, "Selected inventory item does not match selected department.")
                return redirect("inventory_manage")

            if str(machine_part.machine_id) != machine_id:
                messages.error(request, "Selected inventory item does not match selected machine.")
                return redirect("inventory_manage")

            if used_value > machine_part.quantity_left:
                messages.error(request, f"Cannot use {used_value}. Available quantity is {machine_part.quantity_left}.")
                return redirect("inventory_manage")

            machine_part.quantity_left -= used_value

            # Record who last used this inventory item.
            _set_machine_part_last_action(machine_part, request, "USED", used_value)
            machine_part.save(update_fields=[
                "quantity_left",
                "last_action_by_first_name",
                "last_action_by_last_name",
                "last_action_type",
                "last_used_quantity",
                "last_action_at",
            ])

            messages.success(
                request,
                f"Used {used_value} from {machine_part.part.name} on {machine_part.machine.name}. Remaining: {machine_part.quantity_left}.",
            )
            return redirect("inventory_manage")

        messages.error(request, "Invalid action.")
        return redirect("inventory_manage")


    # Restrict all dropdown data to the logged-in department.
    departments = Department.objects.select_related("building").filter(id__in=user_department_ids).order_by("name")
    machines = Machine.objects.select_related("department").filter(department_id__in=user_department_ids).order_by("department__name", "name")
    parts = Part.objects.all().order_by("model_number")
    machine_parts = MachinePart.objects.select_related(
        "machine", "machine__department", "part"
    ).filter(machine__department_id__in=user_department_ids).order_by("machine__department__name", "machine__name", "part__model_number")

    context = {
        "departments": departments,
        "machines": machines,
        "parts": parts,
        "machine_parts": machine_parts,
        "inventory_user": user,
    }

    return _render_template(request, "addpart.html", context)



def _get_manager_session_account(request):
    manager_account_id = request.session.get("inventory_manager_account_id")
    if not manager_account_id:
        return None
    return ManagerAccount.objects.filter(id=manager_account_id, is_active=True).first()

def manager_login_view(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        manager_code = request.POST.get("manager_code", "").strip()

        if not email or not manager_code:
            messages.error(request, "Manager email and manager access code are required.")
            return redirect("manager_login")

        manager = ManagerAccount.objects.filter(email__iexact=email, is_active=True).first()
        if not manager or not manager.check_access_code(manager_code):
            messages.error(request, "Invalid manager email or access code.")
            return redirect("manager_login")

        request.session["inventory_manager_account_id"] = manager.id
        request.session.set_expiry(60 * 30)
        messages.success(request, "Manager access unlocked.")
        return redirect("manager_access")

    return _render_template(request, "manager_login.html")



def admin_manager_accounts_view(request):
    admin_session_key = "inventory_admin_manager_setup_unlocked"
    is_admin_unlocked = bool(request.session.get(admin_session_key, False))

    if request.method == "POST":
        action = request.POST.get("action", "").strip()

        if action == "admin_unlock":
            admin_code = request.POST.get("admin_code", "").strip()

            admin_key = AdminSetupKey.objects.filter(is_active=True).order_by("-updated_at").first()
            if not admin_key:
                messages.error(request, "No active admin setup key in database. Run: python manage.py set_admin_key --key YOUR_KEY")
                return redirect("manager_admin")

            if admin_key.check_key(admin_code):
                request.session[admin_session_key] = True
                request.session.set_expiry(60 * 30)
                messages.success(request, "Admin manager setup unlocked.")
            else:
                messages.error(request, "Invalid admin setup code.")
            return redirect("manager_admin")

        if action == "admin_logout":
            request.session.pop(admin_session_key, None)
            messages.success(request, "Admin manager setup locked.")
            return redirect("manager_admin")

        if not is_admin_unlocked:
            messages.error(request, "Unlock admin manager setup first.")
            return redirect("manager_admin")

        if action == "manager_create_account":
            first_name = request.POST.get("first_name", "").strip()
            last_name = request.POST.get("last_name", "").strip()
            email = request.POST.get("email", "").strip().lower()
            access_code = request.POST.get("access_code", "").strip()
            department_ids = request.POST.getlist("department_ids")

            if not first_name or not last_name or not email or not access_code:
                messages.error(request, "First name, last name, email, and manager access code are required.")
                return redirect("manager_admin")

            try:
                validate_email(email)
            except ValidationError:
                messages.error(request, "Please provide a valid manager email address.")
                return redirect("manager_admin")

            if len(access_code) < 6:
                messages.error(request, "Manager access code must be at least 6 characters.")
                return redirect("manager_admin")

            if not department_ids:
                messages.error(request, "Select at least one department for this manager account.")
                return redirect("manager_admin")

            if ManagerAccount.objects.filter(email__iexact=email).exists():
                messages.error(request, "A manager account with this email already exists.")
                return redirect("manager_admin")

            manager = ManagerAccount(
                first_name=first_name.title(),
                last_name=last_name.title(),
                email=email,
                is_active=True,
            )
            manager.set_access_code(access_code)
            manager.save()

            departments = Department.objects.filter(id__in=department_ids)
            manager.departments.set(departments)

            messages.success(request, f"Manager account created for {manager.first_name} {manager.last_name}.")
            return redirect("manager_admin")

        if action == "admin_update_manager_access":
            manager_id = request.POST.get("manager_id", "").strip()
            update_department_ids = request.POST.getlist("update_department_ids")

            if not manager_id:
                messages.error(request, "Select a manager account to update.")
                return redirect("manager_admin")

            try:
                manager = ManagerAccount.objects.get(id=manager_id)
            except ManagerAccount.DoesNotExist:
                messages.error(request, "Selected manager account was not found.")
                return redirect("manager_admin")

            valid_department_ids = []
            for department_id in update_department_ids:
                try:
                    valid_department_ids.append(int(department_id))
                except (TypeError, ValueError):
                    continue

            departments = Department.objects.filter(id__in=valid_department_ids)
            manager.departments.set(departments)

            department_names = list(departments.order_by("name").values_list("name", flat=True))
            department_text = ", ".join(department_names) if department_names else "No departments assigned"

            messages.success(request, f"Updated manager {manager.first_name} {manager.last_name}: Departments: {department_text}.")
            return redirect("manager_admin")

        if action == "admin_delete_manager":
            manager_id = request.POST.get("manager_id", "").strip()

            if not manager_id:
                messages.error(request, "Select a manager account to delete.")
                return redirect("manager_admin")

            try:
                manager = ManagerAccount.objects.get(id=manager_id)
            except ManagerAccount.DoesNotExist:
                messages.error(request, "Selected manager account was not found.")
                return redirect("manager_admin")

            deleted_name = f"{manager.first_name} {manager.last_name}"
            deleted_email = manager.email
            manager.delete()

            if request.session.get("inventory_manager_account_id") == int(manager_id):
                request.session.pop("inventory_manager_account_id", None)

            messages.success(request, f"Manager account deleted: {deleted_name} ({deleted_email}).")
            return redirect("manager_admin")

        if action == "admin_create_department":
            department_name = request.POST.get("department_name", "").strip()
            building_id = request.POST.get("building_id", "").strip()

            if not department_name or not building_id:
                messages.error(request, "Department name and building are required.")
                return redirect("manager_admin")

            try:
                building = Building.objects.get(id=building_id)
            except Building.DoesNotExist:
                messages.error(request, "Selected building was not found.")
                return redirect("manager_admin")

            if Department.objects.filter(name__iexact=department_name).exists():
                messages.error(request, "A department with this name already exists.")
                return redirect("manager_admin")

            department = Department.objects.create(name=department_name, building=building)
            messages.success(request, f"Department created: {department.name} ({building.name}).")
            return redirect("manager_admin")

        if action == "admin_move_machine_department":
            machine_id = request.POST.get("machine_id", "").strip()
            target_department_id = request.POST.get("target_department_id", "").strip()
            target_station_name = request.POST.get("target_station_name", "").strip()

            if not machine_id or not target_department_id:
                messages.error(request, "Machine and target department are required.")
                return redirect("manager_admin")

            try:
                machine = Machine.objects.select_related("department", "station").get(id=machine_id)
            except Machine.DoesNotExist:
                messages.error(request, "Selected machine was not found.")
                return redirect("manager_admin")

            try:
                target_department = Department.objects.get(id=target_department_id)
            except Department.DoesNotExist:
                messages.error(request, "Target department was not found.")
                return redirect("manager_admin")

            target_station = None
            if target_station_name:
                target_station, _ = Station.objects.get_or_create(
                    department=target_department,
                    name=target_station_name,
                )

            machine.department = target_department
            if target_station:
                machine.station = target_station
            elif machine.station and machine.station.department_id != target_department.id:
                machine.station = None
            machine.save(update_fields=["department", "station"])

            messages.success(request, f"Machine {machine.name} moved to {target_department.name}.")
            return redirect("manager_admin")

        if action == "admin_create_machine":
            target_department_id = request.POST.get("target_department_id", "").strip()
            machine_name = request.POST.get("machine_name", "").strip()
            machine_type = request.POST.get("machine_type", "").strip()
            machine_location = request.POST.get("machine_location", "").strip()
            machine_status = request.POST.get("machine_status", "Idle").strip()
            station_name = request.POST.get("station_name", "").strip()

            if not target_department_id or not machine_name or not machine_type or not machine_location:
                messages.error(request, "Department, machine name, type, and location are required.")
                return redirect("manager_admin")

            try:
                target_department = Department.objects.get(id=target_department_id)
            except Department.DoesNotExist:
                messages.error(request, "Target department was not found.")
                return redirect("manager_admin")

            if Machine.objects.filter(name__iexact=machine_name).exists():
                messages.error(request, "A machine with this name already exists.")
                return redirect("manager_admin")

            station = None
            if station_name:
                station, _ = Station.objects.get_or_create(
                    department=target_department,
                    name=station_name,
                )

            machine = Machine.objects.create(
                name=machine_name,
                type=machine_type,
                location=machine_location,
                status=machine_status if machine_status in {"Running", "Idle", "Maintenance", "Down"} else "Idle",
                department=target_department,
                station=station,
            )

            messages.success(request, f"Machine created: {machine.name} in {target_department.name}.")
            return redirect("manager_admin")

        if action == "admin_delete_department":
            delete_department_id = request.POST.get("delete_department_id", "").strip()
            transfer_department_id = request.POST.get("transfer_department_id", "").strip()

            if not delete_department_id or not transfer_department_id:
                messages.error(request, "Select the department to delete and the transfer department.")
                return redirect("manager_admin")

            if delete_department_id == transfer_department_id:
                messages.error(request, "Transfer department must be different from the department you are deleting.")
                return redirect("manager_admin")

            try:
                delete_department = Department.objects.get(id=delete_department_id)
            except Department.DoesNotExist:
                messages.error(request, "Department to delete was not found.")
                return redirect("manager_admin")

            try:
                transfer_department = Department.objects.get(id=transfer_department_id)
            except Department.DoesNotExist:
                messages.error(request, "Transfer department was not found.")
                return redirect("manager_admin")

            old_station_to_new_station = {}
            for station in Station.objects.filter(department=delete_department):
                target_station, _ = Station.objects.get_or_create(
                    department=transfer_department,
                    name=station.name,
                )
                old_station_to_new_station[station.id] = target_station

            machines_to_move = Machine.objects.filter(department=delete_department).select_related("station")
            for machine in machines_to_move:
                machine.department = transfer_department
                if machine.station_id in old_station_to_new_station:
                    machine.station = old_station_to_new_station[machine.station_id]
                elif machine.station and machine.station.department_id != transfer_department.id:
                    machine.station = None
                machine.save(update_fields=["department", "station"])

            deleted_department_name = delete_department.name
            transfer_department_name = transfer_department.name
            delete_department.delete()

            messages.success(
                request,
                f"Department {deleted_department_name} deleted. Machines and stations moved to {transfer_department_name}.",
            )
            return redirect("manager_admin")

        messages.error(request, "Invalid admin action.")
        return redirect("manager_admin")

    all_buildings = Building.objects.all().order_by("name")
    all_departments = Department.objects.select_related("building").all().order_by("name")
    all_machines = Machine.objects.select_related("department", "station").all().order_by("name")
    manager_accounts = ManagerAccount.objects.prefetch_related("departments").order_by("first_name", "last_name")

    context = {
        "admin_unlocked": is_admin_unlocked,
        "all_buildings": all_buildings,
        "all_departments": all_departments,
        "all_machines": all_machines,
        "manager_accounts": manager_accounts,
    }
    return _render_template(request, "admin_manager_accounts.html", context)


@require_any_login
def grant_access_view(request):
    manager_account = _get_manager_session_account(request)
    if not manager_account:
        messages.error(request, "Please login as manager first.")
        return redirect("manager_login")

    if request.method == "POST":
        action = request.POST.get("action", "").strip()

        if action == "manager_logout":
            request.session.pop("inventory_manager_account_id", None)
            messages.success(request, "Manager signed out.")
            return redirect("manager_login")

        if action == "grant_user_access":
            department_ids = request.POST.getlist("department_ids")
            first_name = request.POST.get("first_name", "").strip()
            last_name = request.POST.get("last_name", "").strip()
            email = request.POST.get("email", "").strip().lower()
            is_active = True

            if not department_ids or not first_name or not last_name or not email:
                messages.error(request, "Select at least one department, and provide first name, last name, and email.")
                return redirect("manager_access")

            try:
                validate_email(email)
            except ValidationError:
                messages.error(request, "Please provide a valid email address.")
                return redirect("manager_access")

            manager_department_ids = set(manager_account.departments.values_list("id", flat=True))

            valid_department_ids = []
            for department_id in department_ids:
                try:
                    department_id_int = int(department_id)
                except (TypeError, ValueError):
                    continue

                if department_id_int in manager_department_ids:
                    valid_department_ids.append(department_id_int)

            if not valid_department_ids:
                messages.error(request, "Select departments assigned to your manager account.")
                return redirect("manager_access")

            department_map = Department.objects.in_bulk(valid_department_ids)
            updated_department_names = []

            for department_id_int in valid_department_ids:
                department = department_map.get(department_id_int)
                if not department:
                    continue

                granted_user, created = DepartmentAuthorizedUser.objects.get_or_create(
                    department=department,
                    email=email,
                    defaults={
                        "first_name": first_name.title(),
                        "last_name": last_name.title(),
                        "is_active": is_active,
                    },
                )

                if not created:
                    granted_user.first_name = first_name.title()
                    granted_user.last_name = last_name.title()
                    granted_user.is_active = is_active
                    granted_user.save(update_fields=["first_name", "last_name", "is_active"])

                updated_department_names.append(department.name)

            if not updated_department_names:
                messages.error(request, "No valid departments were updated.")
                return redirect("manager_access")

            department_list_text = ", ".join(sorted(updated_department_names))
            messages.success(request, f"Access granted for {first_name.title()} {last_name.title()} ({email}) in: {department_list_text}.")
            return redirect("manager_access")

        if action == "update_existing_user_access":
            authorized_user_id = request.POST.get("authorized_user_id", "").strip()
            access_action = request.POST.get("access_action", "").strip().lower()

            if not authorized_user_id or access_action not in ["grant", "deny"]:
                messages.error(request, "Select an existing user and choose Grant or Deny.")
                return redirect("manager_access")

            try:
                authorized_user = DepartmentAuthorizedUser.objects.select_related("department").get(id=authorized_user_id)
            except DepartmentAuthorizedUser.DoesNotExist:
                messages.error(request, "Selected authorized user was not found.")
                return redirect("manager_access")

            manager_department_ids = set(manager_account.departments.values_list("id", flat=True))
            if authorized_user.department_id not in manager_department_ids:
                messages.error(request, "You can only update users in your assigned departments.")
                return redirect("manager_access")

            new_status = access_action == "grant"
            authorized_user.is_active = new_status
            authorized_user.save(update_fields=["is_active"])

            action_word = "granted" if new_status else "denied"
            messages.success(
                request,
                f"Access {action_word} for {authorized_user.first_name} {authorized_user.last_name} ({authorized_user.email}) in {authorized_user.department.name}.",
            )
            return redirect("manager_access")

        if action == "remove_existing_user":
            authorized_user_id = request.POST.get("authorized_user_id", "").strip()

            if not authorized_user_id:
                messages.error(request, "Select an existing user to remove.")
                return redirect("manager_access")

            try:
                authorized_user = DepartmentAuthorizedUser.objects.select_related("department").get(id=authorized_user_id)
            except DepartmentAuthorizedUser.DoesNotExist:
                messages.error(request, "Selected authorized user was not found.")
                return redirect("manager_access")

            manager_department_ids = set(manager_account.departments.values_list("id", flat=True))
            if authorized_user.department_id not in manager_department_ids:
                messages.error(request, "You can only remove users in your assigned departments.")
                return redirect("manager_access")

            deleted_name = f"{authorized_user.first_name} {authorized_user.last_name}"
            deleted_email = authorized_user.email
            deleted_department = authorized_user.department.name
            authorized_user.delete()

            messages.success(
                request,
                f"Removed team member {deleted_name} ({deleted_email}) from {deleted_department}.",
            )
            return redirect("manager_access")

        messages.error(request, "Invalid manager action.")
        return redirect("manager_access")

    all_departments = Department.objects.select_related("building").all().order_by("name")
    manager_departments = all_departments.filter(id__in=manager_account.departments.values_list("id", flat=True))

    authorized_users = DepartmentAuthorizedUser.objects.select_related("department", "department__building").filter(
        department__in=manager_departments
    )

    context = {
        "manager_unlocked": True,
        "departments": manager_departments,
        "all_departments": all_departments,
        "manager_account": manager_account,
        "authorized_users": authorized_users,
    }
    return _render_template(request, "manager_access.html", context)




def _save_station_qr_assets(station, qr_payload):
    station.qr_payload = qr_payload

    try:
        qr_obj = qrcode.QRCode(box_size=10, border=4)
        qr_obj.add_data(qr_payload)
        qr_obj.make(fit=True)
        qr_image = qr_obj.make_image(fill_color="black", back_color="white").convert("RGB")

        png_buffer = io.BytesIO()
        qr_image.save(png_buffer, format="PNG")
        png_buffer.seek(0)

        pdf_buffer = io.BytesIO()
        qr_image.save(pdf_buffer, format="PDF")
        pdf_buffer.seek(0)

        if station.qr_png:
            station.qr_png.delete(save=False)
        if station.qr_pdf:
            station.qr_pdf.delete(save=False)

        safe_station_name = slugify(station.name) or f"station-{station.id}"
        png_name = f"station_qr_{station.department_id}_{station.id}_{safe_station_name}.png"
        pdf_name = f"station_qr_{station.department_id}_{station.id}_{safe_station_name}.pdf"

        station.qr_png.save(png_name, ContentFile(png_buffer.read()), save=False)
        station.qr_pdf.save(pdf_name, ContentFile(pdf_buffer.read()), save=False)
        station.save()

        station.qr_image_url = station.qr_png.url if station.qr_png else ""
        station.save(update_fields=["qr_payload", "qr_image_url", "qr_png", "qr_pdf"])
    except Exception:
        station.save(update_fields=["qr_payload"])


@require_any_login
def create_qrcode(request):
    """Create/get a station and return QR data instantly for that station."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "POST request required."}, status=405)

    station_name = request.POST.get("station_name", "").strip() or request.POST.get("station_location", "").strip()
    station_department_id = request.POST.get("station_department_id", "").strip() or request.POST.get("department_id", "").strip()

    if not station_name or not station_department_id:
        return JsonResponse(
            {"ok": False, "message": "station_name and station_department_id are required."},
            status=400,
        )

    try:
        department = Department.objects.get(id=station_department_id)
    except Department.DoesNotExist:
        return JsonResponse({"ok": False, "message": "Department not found."}, status=404)

    station, created = Station.objects.get_or_create(
        department=department,
        name=station_name,
    )

    qr_data = _build_station_qr_data(request, station)
    _save_station_qr_assets(station, qr_data["qr_payload"])
    qr_data = _build_station_qr_data(request, station)

    return JsonResponse(
        {
            "ok": True,
            "created": created,
            "station": {
                "id": station.id,
                "name": station.name,
                "department_id": department.id,
                "department_name": department.name,
            },
            "qr_payload": qr_data["qr_payload"],
            "qr_image_url": qr_data["qr_image_url"],
            "qr_pdf_url": qr_data["qr_pdf_url"],
        }
    )


def _build_station_qr_data(request, station):
    station_page_url = request.build_absolute_uri(f"{reverse('work_station')}?station_id={station.id}&scan=1")
    qr_payload = station_page_url
    qr_image_url = station.qr_image_url or (station.qr_png.url if station.qr_png else "")
    return {
        "station_id": station.id,
        "station_name": station.name,
        "department_id": station.department_id,
        "department_name": station.department.name,
        "qr_payload": qr_payload,
        "qr_image_url": qr_image_url,
        "qr_pdf_url": station.qr_pdf.url if station.qr_pdf else "",
    }


def _get_actor_identity(request):
    inventory_user = _get_inventory_session_user(request)
    if inventory_user:
        return {
            "first_name": inventory_user.get("first_name", ""),
            "last_name": inventory_user.get("last_name", ""),
            "email": inventory_user.get("email", ""),
        }

    manager_account = _get_manager_session_account(request)
    if manager_account:
        return {
            "first_name": manager_account.first_name,
            "last_name": manager_account.last_name,
            "email": manager_account.email,
        }

    return {"first_name": "", "last_name": "", "email": ""}


def _get_allowed_department_ids(request):
    allowed_department_ids = set()

    inventory_user = _get_inventory_session_user(request) or {}
    inventory_department_ids = inventory_user.get("department_ids") or []
    for department_id in inventory_department_ids:
        try:
            allowed_department_ids.add(int(department_id))
        except (TypeError, ValueError):
            continue

    manager_account = _get_manager_session_account(request)
    if manager_account:
        manager_department_ids = manager_account.departments.values_list("id", flat=True)
        for department_id in manager_department_ids:
            try:
                allowed_department_ids.add(int(department_id))
            except (TypeError, ValueError):
                continue

    return allowed_department_ids


NC_TIMEZONE = ZoneInfo("America/New_York")


def _format_nc_time(value):
    if not value:
        return "-"
    return timezone.localtime(value, NC_TIMEZONE).strftime("%Y-%m-%d %I:%M:%S %p ET")


def _resolve_station_machine(station):
    if not station:
        return None
    return Machine.objects.filter(station=station).order_by("name").first()


def _resolve_station_machine_name(station):
    linked_machine = _resolve_station_machine(station)
    return linked_machine.name if linked_machine else "-"


def _serialize_work_order(item):
    technician_name = f"{(item.technician_first_name or '').strip()} {(item.technician_last_name or '').strip()}".strip()
    resolved_machine = item.machine if item.machine else _resolve_station_machine(item.station)
    machine_name = resolved_machine.name if resolved_machine else "-"
    return {
        "id": item.id,
        "department_id": item.department_id,
        "priority": item.priority,
        "priority_label": item.get_priority_display(),
        "status": item.status,
        "status_label": item.get_status_display(),
        "department_name": item.department.name,
        "location_name": item.department.building.name,
        "station_name": item.station.name,
        "station_id": item.station_id,
        "machine_id": resolved_machine.id if resolved_machine else "",
        "machine_name": machine_name,
        "message": item.message or "-",
        "technician_name": technician_name or "Engineering Team",
        "technician_email": item.technician_email or "",
        "scanned_at": _format_nc_time(item.scanned_at),
        "accepted_at": _format_nc_time(item.accepted_at),
        "completed_at": _format_nc_time(item.completed_at),
    }


def _is_ajax_request(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def work_station_view(request):
    station_id = request.GET.get("station_id", "").strip()
    department_id = request.GET.get("department_id", "").strip()
    scan_flag = request.GET.get("scan", "").strip().lower() in {"1", "true", "yes"}
    completed_flag = request.GET.get("done", "").strip().lower() in {"1", "true", "yes"}
    is_logged_in = bool(request.session.get("inventory_user") or request.session.get("inventory_manager_account_id"))
    is_inventory_user = bool(request.session.get("inventory_user"))

    selected_station = None
    selected_department = None
    machine_options = Machine.objects.none()
    station_latest_request = None
    station_default_machine_name = "-"
    just_completed = completed_flag
    allowed_department_ids = _get_allowed_department_ids(request)

    if not is_logged_in and not (scan_flag and station_id):
        messages.error(request, "Please login first.")
        return redirect("inventory_login")

    if not allowed_department_ids and not scan_flag:
        messages.error(request, "No department access assigned. Ask your manager for access.")
        context = {
            "departments": Department.objects.none(),
            "stations": Station.objects.none(),
            "machine_options": Machine.objects.none(),
            "selected_station": None,
            "selected_department": None,
            "work_orders": WorkOrderRequest.objects.none(),
            "station_latest_request": None,
            "active_alerts": [],
            "just_completed": False,
            "is_scanner_view": False,
        }
        return _render_template(request, "Work_station.html", context)

    if station_id:
        station_queryset = Station.objects.select_related("department", "department__building").filter(id=station_id)
        if is_logged_in and not scan_flag:
            station_queryset = station_queryset.filter(department_id__in=allowed_department_ids)
        selected_station = station_queryset.first()
        if selected_station:
            selected_department = selected_station.department
            machine_options = Machine.objects.filter(department=selected_department).order_by("name")
            linked_machine = (
                Machine.objects.filter(station=selected_station, department=selected_department)
                .order_by("name")
                .first()
            )
            if linked_machine:
                station_default_machine_name = linked_machine.name
            department_id = str(selected_department.id)
        else:
            if is_logged_in:
                messages.error(request, "You are not allowed to access this station.")
            else:
                messages.error(request, "Station QR code is invalid.")

    if not scan_flag:
        if not selected_department and department_id:
            selected_department = (
                Department.objects.select_related("building")
                .filter(id=department_id, id__in=allowed_department_ids)
                .first()
            )
            if selected_department:
                machine_options = Machine.objects.filter(department=selected_department).order_by("name")
            else:
                messages.error(request, "You are not allowed to view this department queue.")

        if not selected_department:
            selected_department = (
                Department.objects.select_related("building")
                .filter(id__in=allowed_department_ids)
                .order_by("name")
                .first()
            )
            if selected_department:
                machine_options = Machine.objects.filter(department=selected_department).order_by("name")
                department_id = str(selected_department.id)

        departments = Department.objects.select_related("building").filter(id__in=allowed_department_ids).order_by("name")

        stations = Station.objects.select_related("department", "department__building").filter(
            department_id__in=allowed_department_ids
        )
        if selected_department:
            stations = stations.filter(department=selected_department)
        stations = stations.order_by("department__name", "name")

        work_orders = WorkOrderRequest.objects.select_related("department", "station", "machine").filter(
            department_id__in=allowed_department_ids
        )
        if selected_department:
            work_orders = work_orders.filter(department=selected_department)
        if selected_station:
            work_orders = work_orders.filter(station=selected_station)
        work_orders = work_orders.order_by("-scanned_at")
    else:
        departments = Department.objects.none()
        stations = Station.objects.none()
        work_orders = WorkOrderRequest.objects.none()

    if selected_station and not station_latest_request:
        station_latest_request = (
            WorkOrderRequest.objects.filter(
                station=selected_station,
                status__in=[WorkOrderRequest.STATUS_NEW, WorkOrderRequest.STATUS_COMING],
            )
            .select_related("department", "station", "machine")
            .order_by("-scanned_at")
            .first()
        )

    if not scan_flag:
        active_alerts = WorkOrderRequest.objects.select_related("department", "station", "machine").filter(
            status__in=[WorkOrderRequest.STATUS_NEW, WorkOrderRequest.STATUS_COMING],
            department_id__in=allowed_department_ids,
        )
        if selected_department:
            active_alerts = active_alerts.filter(department=selected_department)
        if selected_station:
            active_alerts = active_alerts.filter(station=selected_station)
        active_alerts = list(active_alerts.order_by("-scanned_at"))
    else:
        active_alerts = []

    is_scanner_view = bool(scan_flag)

    context = {
        "departments": departments,
        "stations": stations,
        "machine_options": machine_options,
        "selected_station": selected_station,
        "selected_department": selected_department,
        "work_orders": work_orders,
        "station_latest_request": station_latest_request,
        "active_alerts": active_alerts,
        "just_completed": just_completed,
        "is_scanner_view": is_scanner_view,
        "station_default_machine_name": station_default_machine_name,
        "current_nc_time": timezone.localtime(timezone.now(), NC_TIMEZONE).strftime("%Y-%m-%d %I:%M:%S %p ET"),
    }
    template_name = "scanner_station.html" if is_scanner_view else "Work_station.html"
    return _render_template(request, template_name, context)


def work_station_live_status(request):
    station_id = request.GET.get("station_id", "").strip()
    department_id = request.GET.get("department_id", "").strip()
    filter_station_id = request.GET.get("filter_station_id", "").strip()

    if station_id:
        station = Station.objects.select_related("department", "department__building").filter(id=station_id).first()
        if not station:
            return JsonResponse({"ok": False, "message": "Station not found."}, status=404)

        linked_machine = (
            Machine.objects.filter(station=station, department=station.department)
            .order_by("name")
            .first()
        )

        latest = (
            WorkOrderRequest.objects.select_related("department", "station", "machine")
            .filter(station=station, status__in=[WorkOrderRequest.STATUS_NEW, WorkOrderRequest.STATUS_COMING])
            .order_by("-scanned_at")
            .first()
        )

        return JsonResponse(
            {
                "ok": True,
                "now": timezone.localtime(timezone.now(), NC_TIMEZONE).strftime("%Y-%m-%d %I:%M:%S %p ET"),
                "station": {
                    "id": station.id,
                    "name": station.name,
                    "department_name": station.department.name,
                    "location_name": station.department.building.name,
                    "default_machine_name": linked_machine.name if linked_machine else "-",
                },
                "latest": _serialize_work_order(latest) if latest else None,
            }
        )

    allowed_department_ids = _get_allowed_department_ids(request)
    if not allowed_department_ids:
        return JsonResponse({"ok": False, "message": "Login required."}, status=403)

    if department_id:
        try:
            requested_department_id = int(department_id)
        except ValueError:
            return JsonResponse({"ok": False, "message": "Invalid department filter."}, status=400)
        if requested_department_id not in allowed_department_ids:
            return JsonResponse({"ok": False, "message": "Not allowed for this department."}, status=403)

    work_orders = WorkOrderRequest.objects.select_related("department", "station", "machine").filter(
        department_id__in=allowed_department_ids
    )
    if department_id:
        work_orders = work_orders.filter(department_id=department_id)
    if filter_station_id:
        work_orders = work_orders.filter(station_id=filter_station_id)
    work_orders = work_orders.order_by("-scanned_at")[:120]

    active_alerts = (
        WorkOrderRequest.objects.select_related("department", "station", "machine")
        .filter(status__in=[WorkOrderRequest.STATUS_NEW, WorkOrderRequest.STATUS_COMING], department_id__in=allowed_department_ids)
        .order_by("-scanned_at")
    )
    if department_id:
        active_alerts = active_alerts.filter(department_id=department_id)
    if filter_station_id:
        active_alerts = active_alerts.filter(station_id=filter_station_id)
    active_alerts = active_alerts[:50]

    return JsonResponse(
        {
            "ok": True,
            "now": timezone.localtime(timezone.now(), NC_TIMEZONE).strftime("%Y-%m-%d %I:%M:%S %p ET"),
            "alerts": [_serialize_work_order(item) for item in active_alerts],
            "work_orders": [_serialize_work_order(item) for item in work_orders],
        }
    )


@require_any_login
def work_station_machine_parts(request):
    if not request.session.get("inventory_user"):
        return JsonResponse({"ok": False, "message": "Only authorized department users can access machine parts."}, status=403)

    work_order_id = request.GET.get("work_order_id", "").strip()
    if not work_order_id:
        return JsonResponse({"ok": False, "message": "Work order ID is required."}, status=400)

    work_order = WorkOrderRequest.objects.select_related("department", "station", "machine").filter(id=work_order_id).first()
    if not work_order:
        return JsonResponse({"ok": False, "message": "Work order not found."}, status=404)

    allowed_department_ids = _get_allowed_department_ids(request)
    if work_order.department_id not in allowed_department_ids:
        return JsonResponse({"ok": False, "message": "You are not allowed to access this department."}, status=403)

    target_machine = work_order.machine or _resolve_station_machine(work_order.station)
    if not target_machine:
        return JsonResponse({"ok": False, "message": "No machine is linked to this station/request.", "parts": []}, status=200)

    machine_parts = MachinePart.objects.select_related("part", "machine", "machine__department").filter(machine=target_machine).order_by("part__name")

    return JsonResponse(
        {
            "ok": True,
            "machine": {
                "id": target_machine.id,
                "name": target_machine.name,
                "department_id": target_machine.department_id,
                "department_name": target_machine.department.name,
            },
            "parts": [
                {
                    "machine_part_id": row.id,
                    "part_name": row.part.name,
                    "model_number": row.part.model_number,
                    "quantity_left": row.quantity_left,
                }
                for row in machine_parts
            ],
        }
    )


@require_any_login
def work_station_record_part_usage(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "POST required."}, status=405)

    if not request.session.get("inventory_user"):
        return JsonResponse({"ok": False, "message": "Only authorized department users can use inventory."}, status=403)

    work_order_id = request.POST.get("work_order_id", "").strip()
    machine_part_id = request.POST.get("machine_part_id", "").strip()
    used_quantity = request.POST.get("used_quantity", "").strip()

    if not work_order_id or not machine_part_id or not used_quantity:
        return JsonResponse({"ok": False, "message": "Work order, part, and used quantity are required."}, status=400)

    try:
        used_value = int(used_quantity)
        if used_value <= 0:
            raise ValueError()
    except ValueError:
        return JsonResponse({"ok": False, "message": "Used quantity must be greater than 0."}, status=400)

    work_order = WorkOrderRequest.objects.select_related("department", "station", "machine").filter(id=work_order_id).first()
    if not work_order:
        return JsonResponse({"ok": False, "message": "Work order not found."}, status=404)

    allowed_department_ids = _get_allowed_department_ids(request)
    if work_order.department_id not in allowed_department_ids:
        return JsonResponse({"ok": False, "message": "You are not allowed to use inventory for this department."}, status=403)

    target_machine = work_order.machine or _resolve_station_machine(work_order.station)
    if not target_machine:
        return JsonResponse({"ok": False, "message": "No machine is linked to this station/request."}, status=400)

    machine_part = MachinePart.objects.select_related("machine", "part").filter(id=machine_part_id).first()
    if not machine_part:
        return JsonResponse({"ok": False, "message": "Selected machine part was not found."}, status=404)

    if machine_part.machine_id != target_machine.id:
        return JsonResponse({"ok": False, "message": "Selected part does not belong to this machine."}, status=400)

    if machine_part.machine.department_id != work_order.department_id:
        return JsonResponse({"ok": False, "message": "Department mismatch for selected part."}, status=400)

    if used_value > machine_part.quantity_left:
        return JsonResponse(
            {
                "ok": False,
                "message": f"Cannot use {used_value}. Available quantity is {machine_part.quantity_left}.",
            },
            status=400,
        )

    machine_part.quantity_left -= used_value
    _set_machine_part_last_action(machine_part, request, "USED", used_value)
    machine_part.save(
        update_fields=[
            "quantity_left",
            "last_action_by_first_name",
            "last_action_by_last_name",
            "last_action_type",
            "last_used_quantity",
            "last_action_at",
        ]
    )

    return JsonResponse(
        {
            "ok": True,
            "message": f"Used {used_value} from {machine_part.part.name} on {machine_part.machine.name}. Remaining: {machine_part.quantity_left}.",
        }
    )


@require_any_login
def work_station_submit_request(request):
    if request.method != "POST":
        return redirect("work_station")

    if not request.session.get("inventory_user"):
        messages.error(request, "Only authorized department users can submit workstation requests.")
        return redirect("inventory_login")

    station_id = request.POST.get("station_id", "").strip()
    machine_id = request.POST.get("machine_id", "").strip()
    message = request.POST.get("message", "").strip()
    priority_value = request.POST.get("priority", "2").strip()

    if not station_id:
        messages.error(request, "Station is required for work order request.")
        return redirect("work_station")

    allowed_department_ids = _get_allowed_department_ids(request)
    if not allowed_department_ids:
        messages.error(request, "No department access assigned. Ask your manager for access.")
        return redirect("work_station")

    try:
        station = Station.objects.select_related("department").get(id=station_id, department_id__in=allowed_department_ids)
    except Station.DoesNotExist:
        messages.error(request, "Selected station was not found or access is not allowed.")
        return redirect("work_station")

    machine = None
    if machine_id:
        machine = Machine.objects.filter(id=machine_id, department=station.department).first()
        if not machine:
            messages.error(request, "Selected machine is not in the station department.")
            return redirect(f"{reverse('work_station')}?station_id={station.id}")

    try:
        priority = int(priority_value)
    except ValueError:
        priority = WorkOrderRequest.PRIORITY_MEDIUM
    if priority not in {WorkOrderRequest.PRIORITY_HIGH, WorkOrderRequest.PRIORITY_MEDIUM, WorkOrderRequest.PRIORITY_LOW}:
        priority = WorkOrderRequest.PRIORITY_MEDIUM

    existing_active_request = WorkOrderRequest.objects.filter(
        station=station,
        status__in=[WorkOrderRequest.STATUS_NEW, WorkOrderRequest.STATUS_COMING],
    ).order_by("-scanned_at").first()
    if existing_active_request:
        messages.info(request, f"An active request already exists for {station.name}.")
        return redirect(f"{reverse('work_station')}?station_id={station.id}")

    work_order = WorkOrderRequest.objects.create(
        station=station,
        department=station.department,
        machine=machine,
        message=message,
        priority=priority,
        status=WorkOrderRequest.STATUS_NEW,
    )

    messages.success(request, f"Request created for {station.name}. Ticket #{work_order.id} submitted.")
    return redirect(f"{reverse('work_station')}?station_id={station.id}")


@require_any_login
def work_station_accept_request(request):
    if request.method != "POST":
        return redirect("work_station")

    if not request.session.get("inventory_user"):
        messages.error(request, "Only authorized department users can accept workstation requests.")
        return redirect("inventory_login")

    work_order_id = request.POST.get("work_order_id", "").strip()
    station_id = request.POST.get("station_id", "").strip()
    department_id = request.POST.get("department_id", "").strip()
    if not work_order_id:
        messages.error(request, "Work order ID is required.")
        return redirect("work_station")

    work_order = WorkOrderRequest.objects.select_related("department").filter(id=work_order_id).first()
    if not work_order:
        if _is_ajax_request(request):
            return JsonResponse({"ok": False, "message": "Work order not found."}, status=404)
        messages.error(request, "Work order not found.")
        return redirect("work_station")

    allowed_department_ids = _get_allowed_department_ids(request)
    if work_order.department_id not in allowed_department_ids:
        if _is_ajax_request(request):
            return JsonResponse({"ok": False, "message": "Not allowed."}, status=403)
        messages.error(request, "You are not allowed to access this department request.")
        return redirect("work_station")

    if work_order.status != WorkOrderRequest.STATUS_NEW:
        if _is_ajax_request(request):
            return JsonResponse({"ok": False, "message": "Only NEW requests can be accepted."}, status=400)
        messages.info(request, "Only NEW requests can be accepted.")
        if department_id:
            return redirect(f"{reverse('work_station')}?department_id={department_id}")
        return redirect("work_station")

    actor = _get_actor_identity(request)

    now = timezone.now()
    if not work_order.accessed_at:
        work_order.accessed_at = now
    if not work_order.responded_at:
        work_order.responded_at = now
    work_order.accepted_at = now
    work_order.status = WorkOrderRequest.STATUS_COMING
    work_order.technician_first_name = actor["first_name"]
    work_order.technician_last_name = actor["last_name"]
    work_order.technician_email = actor["email"]
    work_order.save(update_fields=[
        "accessed_at",
        "responded_at",
        "accepted_at",
        "status",
        "technician_first_name",
        "technician_last_name",
        "technician_email",
    ])

    if _is_ajax_request(request):
        return JsonResponse({"ok": True, "message": "Status set to COMING."})

    messages.success(request, f"Work order #{work_order.id} accepted. Status set to COMING.")
    if department_id:
        return redirect(f"{reverse('work_station')}?department_id={department_id}")
    if station_id:
        return redirect(f"{reverse('work_station')}?station_id={station_id}")
    return redirect(f"{reverse('work_station')}?department_id={work_order.department_id}")


@require_any_login
def work_station_complete_request(request):
    if request.method != "POST":
        return redirect("work_station")

    if not request.session.get("inventory_user"):
        if _is_ajax_request(request):
            return JsonResponse({"ok": False, "message": "Login required."}, status=403)
        messages.error(request, "Only authorized department users can complete workstation requests.")
        return redirect("inventory_login")

    work_order_id = request.POST.get("work_order_id", "").strip()
    department_id = request.POST.get("department_id", "").strip()
    inventory_used_answer = request.POST.get("inventory_used_answer", "").strip().lower()

    if inventory_used_answer not in {"yes", "no"}:
        if _is_ajax_request(request):
            return JsonResponse({"ok": False, "message": "Please answer inventory usage before completion."}, status=400)
        messages.error(request, "Please answer inventory usage before completion.")
        return redirect("work_station")

    work_order = WorkOrderRequest.objects.select_related("department").filter(id=work_order_id).first()
    if not work_order:
        if _is_ajax_request(request):
            return JsonResponse({"ok": False, "message": "Work order not found."}, status=404)
        messages.error(request, "Work order not found.")
        return redirect("work_station")

    allowed_department_ids = _get_allowed_department_ids(request)
    if work_order.department_id not in allowed_department_ids:
        if _is_ajax_request(request):
            return JsonResponse({"ok": False, "message": "Not allowed."}, status=403)
        messages.error(request, "You are not allowed to complete this request.")
        return redirect("work_station")

    if work_order.status != WorkOrderRequest.STATUS_COMING:
        if _is_ajax_request(request):
            return JsonResponse({"ok": False, "message": "Only COMING requests can be completed."}, status=400)
        messages.info(request, "Only COMING requests can be completed.")
        return redirect("work_station")

    actor = _get_actor_identity(request)
    now = timezone.now()
    work_order.status = WorkOrderRequest.STATUS_COMPLETED
    work_order.completed_at = now
    work_order.completed_by_first_name = actor["first_name"]
    work_order.completed_by_last_name = actor["last_name"]
    work_order.completed_by_email = actor["email"]
    work_order.save(
        update_fields=[
            "status",
            "completed_at",
            "completed_by_first_name",
            "completed_by_last_name",
            "completed_by_email",
        ]
    )

    if _is_ajax_request(request):
        return JsonResponse({"ok": True, "message": "Work marked completed."})

    if department_id:
        return redirect(f"{reverse('work_station')}?department_id={department_id}")
    return redirect("work_station")


@require_any_login
def work_station_cancel_request(request):
    if request.method != "POST":
        return redirect("work_station")

    if not request.session.get("inventory_user"):
        messages.error(request, "Only authorized department users can cancel workstation requests.")
        return redirect("inventory_login")

    station_id = request.POST.get("station_id", "").strip()
    if not station_id:
        messages.error(request, "Station is required to cancel call.")
        return redirect("work_station")

    allowed_department_ids = _get_allowed_department_ids(request)
    station = (
        Station.objects.select_related("department")
        .filter(id=station_id, department_id__in=allowed_department_ids)
        .first()
    )
    if not station:
        messages.error(request, "You are not allowed to cancel this station call.")
        return redirect("work_station")

    work_order = (
        WorkOrderRequest.objects.filter(
            station=station,
            status=WorkOrderRequest.STATUS_NEW,
        )
        .order_by("-scanned_at")
        .first()
    )

    if not work_order:
        messages.info(request, "No pending NEW call found to cancel.")
        return redirect(f"{reverse('work_station')}?station_id={station_id}")

    station_name = work_order.station.name
    work_order.delete()
    messages.success(request, f"Call cancelled for station {station_name}. Unaccepted request removed.")
    return redirect(f"{reverse('work_station')}?station_id={station_id}")


def work_station_scan_call(request):
    if request.method != "POST":
        return redirect("work_station")

    station_id = request.POST.get("station_id", "").strip()
    if not station_id:
        messages.error(request, "Station is required.")
        return redirect("work_station")

    station = Station.objects.select_related("department").filter(id=station_id).first()
    if not station:
        messages.error(request, "Station was not found.")
        return redirect("work_station")

    existing_active_request = WorkOrderRequest.objects.filter(
        station=station,
        status__in=[WorkOrderRequest.STATUS_NEW, WorkOrderRequest.STATUS_COMING],
    ).order_by("-scanned_at").first()
    if existing_active_request:
        if not existing_active_request.machine_id:
            fallback_machine = Machine.objects.filter(station=station).order_by("name").first()
            if fallback_machine:
                existing_active_request.machine = fallback_machine
                existing_active_request.save(update_fields=["machine"])
        if _is_ajax_request(request):
            return JsonResponse({"ok": False, "message": "Call already active for this station."}, status=400)
        messages.info(request, "Call already active for this station.")
        return redirect(f"{reverse('work_station')}?station_id={station.id}&scan=1")

    linked_machine = (
        Machine.objects.filter(station=station)
        .order_by("name")
        .first()
    )

    WorkOrderRequest.objects.create(
        station=station,
        department=station.department,
        machine=linked_machine,
        message="Station needs help.",
        priority=WorkOrderRequest.PRIORITY_MEDIUM,
        status=WorkOrderRequest.STATUS_NEW,
    )

    if _is_ajax_request(request):
        return JsonResponse({"ok": True, "message": "Call sent."})

    messages.success(request, f"Call sent from {station.name}.")
    return redirect(f"{reverse('work_station')}?station_id={station.id}&scan=1")


def work_station_scan_cancel(request):
    if request.method != "POST":
        return redirect("work_station")

    station_id = request.POST.get("station_id", "").strip()
    if not station_id:
        messages.error(request, "Station is required.")
        return redirect("work_station")

    work_order = (
        WorkOrderRequest.objects.filter(
            station_id=station_id,
            status=WorkOrderRequest.STATUS_NEW,
        )
        .order_by("-scanned_at")
        .first()
    )
    if not work_order:
        if _is_ajax_request(request):
            return JsonResponse({"ok": False, "message": "No pending NEW call found to cancel."}, status=400)
        messages.info(request, "No pending NEW call found to cancel.")
        return redirect(f"{reverse('work_station')}?station_id={station_id}&scan=1")

    station_name = work_order.station.name
    work_order.delete()

    if _is_ajax_request(request):
        return JsonResponse({"ok": True, "message": "Call cancelled.", "state": "CANCELLED"})

    messages.success(request, f"Call cancelled for station {station_name}. Unaccepted request removed.")
    return redirect(f"{reverse('work_station')}?station_id={station_id}&scan=1")


def work_station_scan_machine_parts(request):
    station_id = request.GET.get("station_id", "").strip()
    if not station_id:
        return JsonResponse({"ok": False, "message": "Station is required."}, status=400)

    station = Station.objects.select_related("department").filter(id=station_id).first()
    if not station:
        return JsonResponse({"ok": False, "message": "Station was not found."}, status=404)

    work_order = (
        WorkOrderRequest.objects.select_related("station", "department", "machine")
        .filter(station=station, status__in=[WorkOrderRequest.STATUS_NEW, WorkOrderRequest.STATUS_COMING])
        .order_by("-scanned_at")
        .first()
    )

    target_machine = (work_order.machine if work_order and work_order.machine else _resolve_station_machine(station))
    if not target_machine:
        return JsonResponse({"ok": False, "message": "No machine is linked to this station.", "parts": []}, status=200)

    machine_parts = MachinePart.objects.select_related("part").filter(machine=target_machine).order_by("part__name")

    return JsonResponse(
        {
            "ok": True,
            "machine": {"id": target_machine.id, "name": target_machine.name},
            "parts": [
                {
                    "machine_part_id": row.id,
                    "part_name": row.part.name,
                    "model_number": row.part.model_number,
                    "quantity_left": row.quantity_left,
                }
                for row in machine_parts
            ],
        }
    )


def work_station_scan_record_usage(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "POST required."}, status=405)

    station_id = request.POST.get("station_id", "").strip()
    machine_part_id = request.POST.get("machine_part_id", "").strip()
    used_quantity = request.POST.get("used_quantity", "").strip()

    if not station_id or not machine_part_id or not used_quantity:
        return JsonResponse({"ok": False, "message": "Station, part, and used quantity are required."}, status=400)

    try:
        used_value = int(used_quantity)
        if used_value <= 0:
            raise ValueError()
    except ValueError:
        return JsonResponse({"ok": False, "message": "Used quantity must be greater than 0."}, status=400)

    station = Station.objects.select_related("department").filter(id=station_id).first()
    if not station:
        return JsonResponse({"ok": False, "message": "Station was not found."}, status=404)

    work_order = (
        WorkOrderRequest.objects.select_related("station", "department", "machine")
        .filter(station=station, status__in=[WorkOrderRequest.STATUS_NEW, WorkOrderRequest.STATUS_COMING])
        .order_by("-scanned_at")
        .first()
    )
    if not work_order:
        return JsonResponse({"ok": False, "message": "No active request found for this station."}, status=400)

    target_machine = work_order.machine or _resolve_station_machine(station)
    if not target_machine:
        return JsonResponse({"ok": False, "message": "No machine is linked to this station/request."}, status=400)

    machine_part = MachinePart.objects.select_related("machine", "part").filter(id=machine_part_id).first()
    if not machine_part:
        return JsonResponse({"ok": False, "message": "Selected machine part was not found."}, status=404)

    if machine_part.machine_id != target_machine.id:
        return JsonResponse({"ok": False, "message": "Selected part does not belong to this machine."}, status=400)

    if used_value > machine_part.quantity_left:
        return JsonResponse({"ok": False, "message": f"Cannot use {used_value}. Available quantity is {machine_part.quantity_left}."}, status=400)

    machine_part.quantity_left -= used_value
    machine_part.last_action_by_first_name = "Operator"
    machine_part.last_action_by_last_name = "Scanner"
    machine_part.last_action_type = "USED"
    machine_part.last_used_quantity = used_value
    machine_part.last_action_at = timezone.now()
    machine_part.save(
        update_fields=[
            "quantity_left",
            "last_action_by_first_name",
            "last_action_by_last_name",
            "last_action_type",
            "last_used_quantity",
            "last_action_at",
        ]
    )

    if not work_order.machine_id:
        work_order.machine = target_machine
        work_order.save(update_fields=["machine"])

    return JsonResponse({"ok": True, "message": f"Used {used_value} from {machine_part.part.name} on {machine_part.machine.name}. Remaining: {machine_part.quantity_left}."})


def work_station_scan_complete(request):
    if request.method != "POST":
        return redirect("work_station")

    station_id = request.POST.get("station_id", "").strip()
    if not station_id:
        if _is_ajax_request(request):
            return JsonResponse({"ok": False, "message": "Station is required."}, status=400)
        messages.error(request, "Station is required.")
        return redirect("work_station")

    work_order = (
        WorkOrderRequest.objects.filter(
            station_id=station_id,
            status__in=[WorkOrderRequest.STATUS_NEW, WorkOrderRequest.STATUS_COMING],
        )
        .order_by("-scanned_at")
        .first()
    )
    if not work_order:
        if _is_ajax_request(request):
            return JsonResponse({"ok": False, "message": "No active request found to complete."}, status=400)
        messages.info(request, "No active request found to complete.")
        return redirect(f"{reverse('work_station')}?station_id={station_id}&scan=1")

    actor = _get_actor_identity(request)
    now = timezone.now()
    work_order.status = WorkOrderRequest.STATUS_COMPLETED
    work_order.completed_at = now
    work_order.completed_by_first_name = actor["first_name"] or "Operator"
    work_order.completed_by_last_name = actor["last_name"] or "Scanner"
    work_order.completed_by_email = actor["email"]
    work_order.save(
        update_fields=[
            "status",
            "completed_at",
            "completed_by_first_name",
            "completed_by_last_name",
            "completed_by_email",
        ]
    )

    if _is_ajax_request(request):
        return JsonResponse({"ok": True, "message": "Work completed recorded.", "state": "COMPLETED"})

    return redirect("work_station_scanner_expired")


def work_station_scanner_expired(request):
    return _render_template(request, "scanner_expired.html")



# this function is for adding and managingind dp
@require_any_login
def manage_department(request):
    is_admin_mode = bool(request.user.is_superuser or request.session.get("inventory_admin_manager_setup_unlocked", False))
    manager_account = _get_manager_session_account(request)
    if not manager_account and not is_admin_mode:
        messages.error(request, "Please login as manager first.")
        return redirect("manager_login")

    if is_admin_mode:
        manager_department_ids = set(Department.objects.values_list("id", flat=True))
    else:
        manager_department_ids = set(manager_account.departments.values_list("id", flat=True))

    if request.method == "POST":
        action = request.POST.get("action", "").strip()

        if action == "add_department":
            building_id = request.POST.get("building_id", "").strip()
            new_building_name = request.POST.get("new_building_name", "").strip()
            department_name = request.POST.get("department_name", "").strip()

            if not department_name:
                messages.error(request, "Department name is required.")
                return redirect("manage_department")

            if not building_id and not new_building_name:
                messages.error(request, "Select a building or enter a new building name.")
                return redirect("manage_department")

            if new_building_name:
                building = Building.objects.filter(name__iexact=new_building_name).first()
                if not building:
                    building = Building.objects.create(name=new_building_name)
            else:
                try:
                    building = Building.objects.get(id=building_id)
                except Building.DoesNotExist:
                    messages.error(request, "Selected building was not found.")
                    return redirect("manage_department")

            if Department.objects.filter(name__iexact=department_name).exists():
                messages.error(request, "A department with this name already exists.")
                return redirect("manage_department")

            department = Department.objects.create(name=department_name, building=building)
            if manager_account:
                manager_account.departments.add(department)
            messages.success(request, f"Department '{department.name}' added to building '{building.name}'.")
            return redirect("manage_department")

        if action == "move_machine_department":
            machine_id = request.POST.get("machine_id", "").strip()
            target_department_id = request.POST.get("target_department_id", "").strip()
            target_station_name = request.POST.get("target_station_name", "").strip()

            if not machine_id or not target_department_id:
                messages.error(request, "Machine and target department are required.")
                return redirect("manage_department")

            try:
                machine = Machine.objects.select_related("department", "station").get(id=machine_id)
            except Machine.DoesNotExist:
                messages.error(request, "Selected machine was not found.")
                return redirect("manage_department")

            try:
                target_department = Department.objects.get(id=target_department_id)
            except Department.DoesNotExist:
                messages.error(request, "Target department was not found.")
                return redirect("manage_department")

            if machine.department_id not in manager_department_ids or target_department.id not in manager_department_ids:
                messages.error(request, "You can only move machines between your assigned departments.")
                return redirect("manage_department")

            target_station = None
            if target_station_name:
                target_station, _ = Station.objects.get_or_create(
                    department=target_department,
                    name=target_station_name,
                )

            machine.department = target_department
            if target_station:
                machine.station = target_station
            elif machine.station and machine.station.department_id != target_department.id:
                machine.station = None
            machine.save(update_fields=["department", "station"])

            messages.success(request, f"Machine {machine.name} moved to {target_department.name}.")
            return redirect("manage_department")

        if action == "create_machine":
            target_department_id = request.POST.get("target_department_id", "").strip()
            machine_name = request.POST.get("machine_name", "").strip()
            machine_type = request.POST.get("machine_type", "").strip()
            machine_location = request.POST.get("machine_location", "").strip()
            machine_status = request.POST.get("machine_status", "Idle").strip()
            station_id = request.POST.get("station_id", "").strip()
            station_name = request.POST.get("station_name", "").strip()

            if not target_department_id or not machine_name or not machine_type or not machine_location:
                messages.error(request, "Department, machine name, type, and location are required.")
                return redirect("manage_department")

            try:
                target_department = Department.objects.get(id=target_department_id)
            except Department.DoesNotExist:
                messages.error(request, "Target department was not found.")
                return redirect("manage_department")

            if target_department.id not in manager_department_ids:
                messages.error(request, "You can only create machines in your assigned departments.")
                return redirect("manage_department")

            if Machine.objects.filter(name__iexact=machine_name).exists():
                messages.error(request, "A machine with this name already exists.")
                return redirect("manage_department")

            station = None
            station_created = False
            if station_id:
                try:
                    station = Station.objects.get(id=station_id, department=target_department)
                except Station.DoesNotExist:
                    messages.error(request, "Selected station was not found in the selected department.")
                    return redirect("manage_department")
            elif station_name:
                station, station_created = Station.objects.get_or_create(
                    department=target_department,
                    name=station_name,
                )

            machine = Machine.objects.create(
                name=machine_name,
                type=machine_type,
                location=machine_location,
                status=machine_status if machine_status in {"Running", "Idle", "Maintenance", "Down"} else "Idle",
                department=target_department,
                station=station,
            )

            if station and station_created:
                qr_data = _build_station_qr_data(request, station)
                _save_station_qr_assets(station, qr_data["qr_payload"])
                request.session["manage_department_station_qr_results"] = [_build_station_qr_data(request, station)]

            messages.success(request, f"Machine created: {machine.name} in {target_department.name}.")
            return redirect("manage_department")

        if action == "assign_machine_station":
            machine_id = request.POST.get("machine_id", "").strip()
            station_id = request.POST.get("assign_station_id", "").strip()
            station_name = request.POST.get("assign_station_name", "").strip()

            if not machine_id:
                messages.error(request, "Please select a machine.")
                return redirect("manage_department")

            try:
                machine = Machine.objects.select_related("department").get(id=machine_id)
            except Machine.DoesNotExist:
                messages.error(request, "Selected machine was not found.")
                return redirect("manage_department")

            if machine.department_id not in manager_department_ids:
                messages.error(request, "You can only manage machines in your assigned departments.")
                return redirect("manage_department")

            if not station_id and not station_name:
                messages.error(request, "Select an existing station or enter a new station name.")
                return redirect("manage_department")

            station = None
            station_created = False
            if station_id:
                try:
                    station = Station.objects.get(id=station_id)
                except Station.DoesNotExist:
                    messages.error(request, "Selected station was not found.")
                    return redirect("manage_department")

                if station.department_id != machine.department_id:
                    messages.error(request, "Machine can only be linked to a station in the same department.")
                    return redirect("manage_department")
            else:
                station, station_created = Station.objects.get_or_create(
                    department=machine.department,
                    name=station_name,
                )

            machine.station = station
            machine.save(update_fields=["station"])

            if station_created:
                qr_data = _build_station_qr_data(request, station)
                _save_station_qr_assets(station, qr_data["qr_payload"])
                request.session["manage_department_station_qr_results"] = [_build_station_qr_data(request, station)]

            messages.success(request, f"Machine {machine.name} linked to station {station.name}.")
            return redirect("manage_department")

        if action == "add_stations_bulk":
            station_department_id = request.POST.get("station_department_id", "").strip()
            station_names_raw = request.POST.get("station_names", "")

            if not station_department_id or not station_names_raw.strip():
                messages.error(request, "Department and station names are required.")
                return redirect("manage_department")

            try:
                department = Department.objects.get(id=station_department_id)
            except Department.DoesNotExist:
                messages.error(request, "Selected department was not found.")
                return redirect("manage_department")

            if department.id not in manager_department_ids:
                messages.error(request, "You can only add stations to your assigned departments.")
                return redirect("manage_department")

            parsed_names = [name.strip() for name in re.split(r"[\n,;]+", station_names_raw) if name.strip()]
            if not parsed_names:
                messages.error(request, "Provide at least one valid station name.")
                return redirect("manage_department")

            unique_names = []
            seen_lower = set()
            for name in parsed_names:
                lowered = name.lower()
                if lowered in seen_lower:
                    continue
                seen_lower.add(lowered)
                unique_names.append(name)

            qr_results = []
            created_count = 0
            existing_count = 0

            for station_name in unique_names:
                station, created = Station.objects.get_or_create(
                    department=department,
                    name=station_name,
                )
                if created:
                    created_count += 1
                else:
                    existing_count += 1
                qr_data = _build_station_qr_data(request, station)
                _save_station_qr_assets(station, qr_data["qr_payload"])
                qr_results.append(_build_station_qr_data(request, station))

            request.session["manage_department_station_qr_results"] = qr_results
            messages.success(
                request,
                f"Stations processed for {department.name}. Created: {created_count}. Existing: {existing_count}. QR codes are ready below.",
            )
            return redirect("manage_department")

        if action == "delete_station":
            station_id = request.POST.get("station_id", "").strip()
            if not station_id:
                messages.error(request, "Select a station to delete.")
                return redirect("manage_department")

            try:
                station = Station.objects.select_related("department").get(id=station_id)
            except Station.DoesNotExist:
                messages.error(request, "Selected station was not found.")
                return redirect("manage_department")

            if station.department_id not in manager_department_ids:
                messages.error(request, "You can only delete stations in your assigned departments.")
                return redirect("manage_department")

            linked_machine_count = Machine.objects.filter(station=station).count()
            station_name = station.name
            station_department = station.department.name

            if station.qr_pdf:
                station.qr_pdf.delete(save=False)

            station.delete()

            messages.success(
                request,
                f"Station '{station_name}' deleted from {station_department}. Removed stored QR PDF. Machines unlinked: {linked_machine_count}.",
            )
            return redirect("manage_department")

        if action == "delete_department":
            delete_department_id = request.POST.get("delete_department_id", "").strip()
            transfer_department_id = request.POST.get("transfer_department_id", "").strip()

            if not delete_department_id or not transfer_department_id:
                messages.error(request, "Select the department to delete and the transfer department.")
                return redirect("manage_department")

            if delete_department_id == transfer_department_id:
                messages.error(request, "Transfer department must be different.")
                return redirect("manage_department")

            try:
                delete_department = Department.objects.get(id=delete_department_id)
                transfer_department = Department.objects.get(id=transfer_department_id)
            except Department.DoesNotExist:
                messages.error(request, "Department selection is invalid.")
                return redirect("manage_department")

            if delete_department.id not in manager_department_ids or transfer_department.id not in manager_department_ids:
                messages.error(request, "You can only delete/transfer between your assigned departments.")
                return redirect("manage_department")

            old_station_to_new_station = {}
            for station in Station.objects.filter(department=delete_department):
                target_station, _ = Station.objects.get_or_create(
                    department=transfer_department,
                    name=station.name,
                )
                old_station_to_new_station[station.id] = target_station

            machines_to_move = Machine.objects.filter(department=delete_department).select_related("station")
            for machine in machines_to_move:
                machine.department = transfer_department
                if machine.station_id in old_station_to_new_station:
                    machine.station = old_station_to_new_station[machine.station_id]
                elif machine.station and machine.station.department_id != transfer_department.id:
                    machine.station = None
                machine.save(update_fields=["department", "station"])

            deleted_name = delete_department.name
            delete_department.delete()
            if manager_account:
                manager_account.departments.remove(delete_department)

            messages.success(
                request,
                f"Department '{deleted_name}' deleted. Machines/stations moved to '{transfer_department.name}'.",
            )
            return redirect("manage_department")

        messages.error(request, "Invalid action.")
        return redirect("manage_department")

    buildings = Building.objects.all().order_by("name")
    departments = Department.objects.select_related("building").filter(id__in=manager_department_ids).order_by("name")
    machines = Machine.objects.select_related("department", "station").filter(department_id__in=manager_department_ids).order_by("name")
    stations = Station.objects.select_related("department", "department__building").filter(department_id__in=manager_department_ids).order_by("department__name", "name")
    qr_department_id = request.GET.get("qr_department_id", "").strip()
    qr_library_stations = stations

    if qr_department_id:
        try:
            qr_department_id_int = int(qr_department_id)
        except ValueError:
            qr_department_id_int = None

        if qr_department_id_int and qr_department_id_int in manager_department_ids:
            qr_library_stations = qr_library_stations.filter(department_id=qr_department_id_int)
        else:
            messages.error(request, "Invalid department selected for QR library.")
            qr_department_id = ""

    qr_library = []
    for station in qr_library_stations:
        if not station.qr_png or not station.qr_pdf or not station.qr_payload:
            qr_data = _build_station_qr_data(request, station)
            _save_station_qr_assets(station, qr_data["qr_payload"])
            station.refresh_from_db(fields=["qr_payload", "qr_image_url", "qr_png", "qr_pdf"])

        qr_data = _build_station_qr_data(request, station)
        qr_library.append(
            {
                "station_id": station.id,
                "station_name": station.name,
                "department_name": station.department.name,
                "building_name": station.department.building.name,
                "qr_image_url": qr_data["qr_image_url"],
                "qr_payload": qr_data["qr_payload"],
                "qr_png_url": station.qr_png.url if station.qr_png else "",
                "qr_pdf_url": station.qr_pdf.url if station.qr_pdf else "",
            }
        )

    station_qr_results = request.session.pop("manage_department_station_qr_results", [])
    context = {
        "buildings": buildings,
        "departments": departments,
        "machines": machines,
        "stations": stations,
        "manager_account": manager_account,
        "station_qr_results": station_qr_results,
        "qr_library": qr_library,
        "selected_qr_department_id": qr_department_id,
    }
    return _render_template(request, "add_department.html", context)