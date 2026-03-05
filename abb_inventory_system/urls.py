"""
URL configuration for abb_inventory_system project.
"""

from django.contrib import admin
from django.urls import path
from inventory import views
from django.conf import settings
from django.conf.urls.static import static
from django.urls import re_path
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),

    path('home/', views.Home, name='home'),

    path('inventory/login/', views.inventory_login_view, name='inventory_login'),
    path('inventory/logout/', views.inventory_logout_view, name='inventory_logout'),
    path('inventory/manager-login/', views.manager_login_view, name='manager_login'),
    path('inventory/admin-manager/', views.admin_manager_accounts_view, name='manager_admin'),
    path('inventory/manager-access/', views.grant_access_view, name='manager_access'),
    path('inventory/add-department/', views.manage_department, name='manage_department'),

    path('submit-requirement/', views.handle_requirement_submission, name='submit_requirement'),

    path('inventory/upload-part-image/', views.upload_part_image_popup, name='upload_part_image_popup'),
    path('inventory/manage/', views.inventory_manage_view, name='inventory_manage'),
    path('inventory/stations/create-qr/', views.create_qrcode, name='create_station_qrcode'),
    path('inventory/work-station/', views.work_station_view, name='work_station'),
    path('inventory/work-station/live-status/', views.work_station_live_status, name='work_station_live_status'),
    path('inventory/work-station/scanner-expired/', views.work_station_scanner_expired, name='work_station_scanner_expired'),
    path('inventory/work-station/scan/call/', views.work_station_scan_call, name='work_station_scan_call'),
    path('inventory/work-station/scan/cancel/', views.work_station_scan_cancel, name='work_station_scan_cancel'),
    path('inventory/work-station/scan/complete/', views.work_station_scan_complete, name='work_station_scan_complete'),
    path('inventory/work-station/submit/', views.work_station_submit_request, name='work_station_submit'),
    path('inventory/work-station/accept/', views.work_station_accept_request, name='work_station_accept'),
    path('inventory/work-station/complete/', views.work_station_complete_request, name='work_station_complete'),
    path('inventory/work-station/cancel/', views.work_station_cancel_request, name='work_station_cancel'),
    path('inventory/work-station/machine-parts/', views.work_station_machine_parts, name='work_station_machine_parts'),
    path('inventory/work-station/record-part-usage/', views.work_station_record_part_usage, name='work_station_record_part_usage'),

    path("inventory/search/", views.inventory_search, name="inventory_search"),

    # MAIN INVENTORY PAGE
    path('', views.inventory_view, name='inventory'),
]


if settings.MEDIA_URL:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {
            'document_root': settings.MEDIA_ROOT,
        }),
    ]