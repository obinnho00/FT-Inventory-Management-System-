from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from .models import Department, UserRequirement, Machine, MachinePart, VendorPart, Part, DepartmentAuthorizedUser, ManagerAccount, AdminSetupKey


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
    # User must provide first/last name + email.
    # Authorization is granted when the email exists in manager-approved allowed users.
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip().lower()

        # Validate basic input first.
        if not first_name or not last_name or not email:
            messages.error(request, "First name, last name, and email are required.")
            return redirect("inventory_login")

        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "Please enter a valid email address.")
            return redirect("inventory_login")

        # User is allowed if their email is active in manager-approved allowed list.
        authorized_users = DepartmentAuthorizedUser.objects.filter(
            email__iexact=email,
            is_active=True,
        ).select_related("department")

        if not authorized_users.exists():
            messages.error(request, "Access not granted for this email. Ask manager to grant your email access.")
            return redirect("inventory_login")

        department_ids = list(authorized_users.values_list("department_id", flat=True).distinct())
        department_names = list(
            Department.objects.filter(id__in=department_ids).order_by("name").values_list("name", flat=True)
        )

        # Save user identity in session for audit tracking on inventory updates.
        request.session["inventory_user"] = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "department_ids": department_ids,
            "department_names": department_names,
        }

        messages.success(request, f"Logged in as {first_name} {last_name}. Authorized by email: {email}.")
        return redirect("inventory_manage")

    return render(request, "login.html")


def inventory_logout_view(request):
    # Remove inventory session identity.
    # This ensures the next stock action cannot be tied to the previous user accidentally.
    request.session.pop("inventory_user", None)
    messages.success(request, "You have been logged out from inventory access.")
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
    return render(request, 'Home.html', context)


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
        return redirect("inventory")

    replacing_existing = bool(part.image)
    part.image = image_file
    part.save(update_fields=["image"])

    if replacing_existing:
        messages.success(request, f"Image replaced for {part.name} ({part.model_number}).")
    else:
        messages.success(request, f"Image added for {part.name} ({part.model_number}).")

    return redirect("inventory")


from django.shortcuts import render
from django.db.models import Prefetch
from .models import (
    Department,
    MachinePart,
    VendorPart
)


# this is the main inventory view that shows the inventory table with dynamic columns and filters, and also allows clicking into each row to see more details about the part, machine, and vendors. It also supports department filtering on top.
# this is the main inventory view that shows the inventory table with dynamic columns and filters, and also allows clicking into each row to see more details about the part, machine, and vendors. It also supports department filtering on top.
# this table shoes all machine-part relationships across the factory, so you can see which parts are used by which machines, and how many are left in inventory. You can filter by department to narrow down to specific areas of the factory. Each row is clickable to show more details about the part, the machine it belongs to, and the vendors that supply that part.
def inventory_view(request):

    selected_department = request.GET.get("department")

    departments = Department.objects.select_related("building").all()

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

    context = {
        "departments": departments,
        "selected_department": selected_department,
        "table_columns": table_columns,
        "data_rows": data_rows,
        "row_details": row_details,
    }

    return render(request, "dashboard.html", context)



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

    context = {
        "table_columns": table_columns,
        "data_rows": data_rows,
        "row_details": row_details,
        "departments": Department.objects.all(),
        "selected_department": None,
        "search_query": query
    }

    return render(request, "dashboard.html", context)


# this is the Update inventory page where you can add new inventory or use existing inventory. the left side of the page is for adding new inventory, where you can select the department, machine, and part (or create a new part on the fly), and specify the quantity, location, and usage notes. when you submit the form, it will update the inventory quantity for that machine-part combination, and also record who made the change and when for audit tracking.
# this function allows acces to the inventory management page where users can add new inventory or record used inventory. The left side of the page is for adding inventory, where users can select the department, machine, and part (or create a new part), and specify quantity, location, and usage notes. When submitted, it updates the inventory quantity for that machine-part combination and records who made the change and when for audit tracking. The right side of the page is for recording used inventory, where users can select the department, machine, and specific inventory item, and specify how many units were used. This will auto-reduce the quantity in the database and also track who used the inventory and when. This page ensures that all inventory changes are tied to a named user for accountability.

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

            # Record who last replaced/updated this inventory item.
            
            _set_machine_part_last_action(machine_part, request, "REPLACED", quantity_value)
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
                messages.success(request, f"Inventory link created and {quantity_value} units added.")
            else:
                messages.success(request, f"Added {quantity_value} units. New quantity: {machine_part.quantity_left}.")

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

    return render(request, "addpart.html", context)




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
        messages.success(request, "Manager access unlocked.")
        return redirect("manager_access")

    return render(request, "manager_login.html")


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

        messages.error(request, "Invalid admin action.")
        return redirect("manager_admin")

    all_departments = Department.objects.select_related("building").all().order_by("name")
    manager_accounts = ManagerAccount.objects.prefetch_related("departments").order_by("first_name", "last_name")

    context = {
        "admin_unlocked": is_admin_unlocked,
        "all_departments": all_departments,
        "manager_accounts": manager_accounts,
    }
    return render(request, "admin_manager_accounts.html", context)


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
    return render(request, "manager_access.html", context)


