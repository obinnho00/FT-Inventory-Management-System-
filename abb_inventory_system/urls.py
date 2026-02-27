"""
URL configuration for lineWatch project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from inventory import views


from django.contrib import admin
from django.urls import path
from inventory import views
from django.conf.urls.static import static
from django.conf import settings

urlpatterns = [
    path('admin/', admin.site.urls),

    path('', views.Home, name='home'),

    path('submit-requirement/', views.handle_requirement_submission, name='submit_requirement'),
    path('inventory/upload-part-image/', views.upload_part_image_popup, name='upload_part_image_popup'),
    path("inventory/search/", views.inventory_search, name="inventory_search"),

    # MAIN INVENTORY PAGE (handles search + department filter)
    path('inventory/', views.inventory_view, name='inventory'),
]

if settings.DEBUG and settings.MEDIA_URL and settings.MEDIA_ROOT:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


