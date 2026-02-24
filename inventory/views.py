from django.shortcuts import render
from django.http import HttpResponse


def home(request):
    return render(request, 'Home.html')

def handle_machine(request):
    if request.method == 'POST':
        # TODO: handle posted machine data
        pass
    return HttpResponse("Handle_machine endpoint not implemented.")


