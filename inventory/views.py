from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib import messages
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


def Handle_requirement_submission(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        department_id = request.POST.get('department')
        message = request.POST.get('message')
        
        try:
            department = Department.objects.get(id=department_id)
            UserRequirement.objects.create(
                department=department,
                requirement_description=f"From: {name}\n\n{message}"
            )
            messages.success(request, 'Thank you! Your requirement has been submitted successfully.')
            return redirect('home')
        except Department.DoesNotExist:
            messages.error(request, 'Invalid department selected.')
            return redirect('home')
    
    return HttpResponse("Invalid request method.", status=405)


#  this function will handle  the finding the machine part based on the user entry if numeric entry is there then it will search based on the id and if text entry is there then it will search based on the name of the machine part

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

    # Base queryset (LOAD EVERYTHING)
    parts = MachinePart.objects.select_related(
        "machine",
        "machine__department",
        "machine__department__building",
        "part"
    ).prefetch_related(
        "part__vendor_links__vendor",
        "part__vendor_links__manufacturer"
    )

    # FILTER IF DEPARTMENT SELECTED
    if selected_department:
        parts = parts.filter(
            machine__department__id=selected_department
        )

    # DYNAMICALLY GET ALL FIELDS FROM MachinePart MODEL
    table_columns = []
    
    # Get all fields from the MachinePart model
    for field in MachinePart._meta.get_fields():
        field_name = field.name
        field_type = field.__class__.__name__
        
        # Skip reverse relations and internal fields
        if field_type in ['ManyToOneRel', 'ManyToManyRel']:
            continue
            
        # Handle different field types dynamically
        if field_type == 'ForeignKey':
            if field_name == 'machine':
                # Add machine-related columns
                table_columns.append({
                    'header': 'Building',
                    'path': 'machine.department.building.name',
                    'type': 'text'
                })
                table_columns.append({
                    'header': 'Department',
                    'path': 'machine.department.name',
                    'type': 'text'
                })
                table_columns.append({
                    'header': 'Machine',
                    'path': 'machine.machine_name',
                    'type': 'text'
                })
            elif field_name == 'part':
                # Add part-related columns
                table_columns.append({
                    'header': 'Part Name',
                    'path': 'part.part_name',
                    'type': 'text'
                })
                table_columns.append({
                    'header': 'Model Number',
                    'path': 'part.model_number',
                    'type': 'text'
                })
        else:
            # Add regular fields from MachinePart
            if field_name not in ['id', 'machine', 'part']:
                # Convert field name to readable header
                header = field_name.replace('_', ' ').title()
                table_columns.append({
                    'header': header,
                    'path': field_name,
                    'type': 'quantity' if 'quantity' in field_name.lower() else 'text'
                })
    
    # Add vendors column (special handling for many-to-many through Part)
    table_columns.append({
        'header': 'Vendors',
        'path': 'part.vendor_links.all',
        'type': 'vendors'
    })
    
    # Prepare data rows dynamically
    data_rows = []
    for item in parts:
        row = []
        for col in table_columns:
            path = col['path']
            cell_type = col['type']
            
            # Navigate through the path dynamically
            value = item
            try:
                for attr in path.split('.'):
                    if attr == 'all':
                        value = value.all()
                        break
                    value = getattr(value, attr, None)
                    if value is None:
                        break
                        
                # Format the value based on type
                if value is None:
                    row.append({'value': '-', 'type': 'text'})
                elif cell_type == 'vendors':
                    vendors_list = []
                    for link in value:
                        vendor_text = link.vendor.name if link.vendor else ''
                        if link.manufacturer:
                            vendor_text += f' ({link.manufacturer.name})'
                        vendors_list.append(vendor_text)
                    row.append({
                        'value': vendors_list if vendors_list else ['No Vendor'],
                        'type': 'vendors'
                    })
                elif cell_type == 'quantity':
                    row.append({
                        'value': value,
                        'type': 'quantity',
                        'is_low': value <= 2 if isinstance(value, (int, float)) else False
                    })
                else:
                    row.append({'value': str(value), 'type': 'text'})
            except Exception:
                row.append({'value': '-', 'type': 'text'})
                
        data_rows.append(row)

    context = {
        "departments": departments,
        "parts": parts,
        "selected_department": selected_department,
        "table_columns": table_columns,
        "data_rows": data_rows,
    }

    return render(request, "dashboard.html", context)
