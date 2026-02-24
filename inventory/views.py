from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib import messages
from .models import Department, User_Requirement, Machine, MachinePart




# function for the home page of the inventory system
def Home(request):
    #load the data based when the web interface comes in
    load_departments = Department.objects.all().order_by('name')
    context = {
        'departments': load_departments
    }
    return render(request, 'Home.html', context)


def Handle_requirement_submission(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        department_id = request.POST.get('department')
        message = request.POST.get('message')
        
        try:
            department = Department.objects.get(id=department_id)
            User_Requirement.objects.create(
                department=department,
                requirement_description=f"From: {name}\n\n{message}"
            )
            messages.success(request, 'Thank you! Your requirement has been submitted successfully.')
            return redirect('home')
        except Department.DoesNotExist:
            messages.error(request, 'Invalid department selected.')
            return redirect('home')
    
    return HttpResponse("Invalid request method.", status=405)
