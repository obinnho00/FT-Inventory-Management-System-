"""
URL configuration for abb_inventory_system project.
"""

from django.contrib import admin
from django.urls import path
from inventory import views
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('admin/', admin.site.urls),

    path('', views.Home, name='home'),

    path('submit-requirement/', views.handle_requirement_submission, name='submit_requirement'),

    path('inventory/upload-part-image/', views.upload_part_image_popup, name='upload_part_image_popup'),

    path("inventory/search/", views.inventory_search, name="inventory_search"),

    # MAIN INVENTORY PAGE
    path('inventory/', views.inventory_view, name='inventory'),
]


# Serve media files (persistent disk setup)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)