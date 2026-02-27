from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib import messages
from django.db.models import Q
from .models import Department, UserRequirement, Machine, MachinePart




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

    return HttpResponse("Invalid request method.", status=405)


from django.shortcuts import render
from django.db.models import Prefetch
from .models import (
    Department,
    MachinePart,
    VendorPart
)



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
        else:
            if field_name not in ["id", "machine", "part"]:
                header = field_name.replace("_", " ").title()

                table_columns.append({
                    "header": header,
                    "path": field_name,
                    "type": "quantity" if "quantity" in field_name.lower() else "text"
                })

    # ---- ADD VENDORS DYNAMICALLY ----
    table_columns.append({
        "header": "Vendors",
        "path": "part.vendorpart_set.all",
        "type": "vendors"
    })

    data_rows = []

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

    context = {
        "departments": departments,
        "selected_department": selected_department,
        "table_columns": table_columns,
        "data_rows": data_rows,
    }

    return render(request, "dashboard.html", context)


def inventory_search(request):
    query = request.GET.get("q", "").strip()

    results = MachinePart.objects.select_related(
        "machine",
        "machine__department",
        "machine__department__building",
        "part"
    ).prefetch_related(
        "part__vendorpart_set__vendor"
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

    context = {
        "table_columns": table_columns,
        "data_rows": data_rows,
        "departments": Department.objects.all(),
        "selected_department": None,
        "search_query": query
    }

    return render(request, "dashboard.html", context)