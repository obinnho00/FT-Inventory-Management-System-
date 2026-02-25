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

    context = {
        "departments": departments,
        "parts": parts,
        "selected_department": selected_department
    }

    return render(request, "Dashboard.html", context)
