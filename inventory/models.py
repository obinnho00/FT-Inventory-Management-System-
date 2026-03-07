from django.db import models
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password


# ==========================================
# LOCATION STRUCTURE
# ==========================================

class Building(models.Model):
    """Table for physical buildings where departments and machines exist."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = "inventory_building"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Department(models.Model):
    """Table for functional departments (linked to one building)."""

    name = models.CharField(max_length=100, unique=True)

    building = models.ForeignKey(
        Building,
        on_delete=models.CASCADE,
        related_name="departments"
    )

    class Meta:
        db_table = "inventory_department"
        ordering = ["name"]

    def __str__(self):
        return self.name


class DepartmentAccessCode(models.Model):
    """Table for department-specific login/access codes used on inventory operations."""

    department = models.OneToOneField(
        Department,
        on_delete=models.CASCADE,
        related_name="access_code"
    )

    code = models.CharField(max_length=50)

    class Meta:
        db_table = "inventory_department_access_code"

    def __str__(self):
        return f"{self.department.name} Access Code"


class DepartmentAuthorizedUser(models.Model):
    """Individuals granted inventory access by manager for a specific department."""

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="authorized_users"
    )

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(max_length=254)
    is_active = models.BooleanField(default=True)
    email_verified = models.BooleanField(default=False)
    email_verification_token = models.CharField(max_length=128, blank=True, db_index=True)
    email_verification_sent_at = models.DateTimeField(null=True, blank=True)
    email_verification_expires_at = models.DateTimeField(null=True, blank=True)
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inventory_department_authorized_user"
        unique_together = ("department", "email")
        ordering = ["department__name", "first_name", "last_name", "email"]

    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        verify_status = "Verified" if self.email_verified else "Pending Verification"
        return f"{self.first_name} {self.last_name} <{self.email}> - {self.department.name} ({status}, {verify_status})"


class ManagerAccount(models.Model):
    """Manager account that controls one or more departments."""

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(max_length=254, unique=True)
    access_code_hash = models.CharField(max_length=128)
    departments = models.ManyToManyField(
        Department,
        related_name="manager_accounts",
        blank=True,
    )
    is_active = models.BooleanField(default=True)
    email_verified = models.BooleanField(default=False)
    email_verification_token = models.CharField(max_length=128, blank=True, db_index=True)
    email_verification_sent_at = models.DateTimeField(null=True, blank=True)
    email_verification_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inventory_manager_account"
        ordering = ["first_name", "last_name", "email"]

    def set_access_code(self, raw_code):
        self.access_code_hash = make_password(raw_code)

    def check_access_code(self, raw_code):
        return check_password(raw_code, self.access_code_hash)

    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        verify_status = "Verified" if self.email_verified else "Pending Verification"
        return f"{self.first_name} {self.last_name} <{self.email}> ({status}, {verify_status})"


class AdminSetupKey(models.Model):
    """Database-backed key used to unlock the admin manager-setup page."""

    key_hash = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inventory_admin_setup_key"
        ordering = ["-updated_at"]

    def set_key(self, raw_key):
        self.key_hash = make_password(raw_key)

    def check_key(self, raw_key):
        return check_password(raw_key, self.key_hash)

    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        return f"Admin Setup Key ({status})"


# ==========================================
# MACHINE STRUCTURE
# ==========================================

class Station(models.Model):
    """Stations that belong to a department and can host one or more machines."""

    name = models.CharField(max_length=100)

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="stations"
    )

    qr_payload = models.TextField(blank=True)
    qr_image_url = models.URLField(blank=True)
    qr_png = models.FileField(upload_to="station_qr_images/", null=True, blank=True)
    qr_pdf = models.FileField(upload_to="station_qr_pdfs/", null=True, blank=True)

    class Meta:
        db_table = "inventory_station"
        ordering = ["department__name", "name"]
        unique_together = ("department", "name")

    def __str__(self):
        return f"{self.name} ({self.department.name})"

class Machine(models.Model):
    """Table for machines/robots that consume parts and belong to a department."""

    STATUS_CHOICES = [
        ("Running", "Running"),
        ("Idle", "Idle"),
        ("Maintenance", "Maintenance"),
        ("Down", "Down"),
    ]

    name = models.CharField(max_length=100, unique=True)
    type = models.CharField(max_length=100)

    location = models.CharField(
        max_length=100,
        help_text="Internal location inside department"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Idle"
    )

    last_updated = models.DateTimeField(default=timezone.now)
    uptime = models.FloatField(default=0)

    image = models.ImageField(
        upload_to="machine_images/",
        blank=True,
        null=True
    )

    station = models.ForeignKey(
        Station,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="machines"
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="machines"
    )

    class Meta:
        db_table = "inventory_machine"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.department.name})"


# ==========================================
# PART STRUCTURE
# ==========================================

class Part(models.Model):
    """Master table for parts/spares identified by a unique model number."""

    model_number = models.CharField(
        max_length=100,
        unique=True,
        db_index=True
    )

    name = models.CharField(max_length=100)

    description = models.TextField(
        blank=True,
        help_text="Technical description or specifications"
    )

    image = models.ImageField(
        upload_to="part_images/",
        blank=True,
        null=True
    )

    class Meta:
        db_table = "inventory_part"
        ordering = ["model_number"]

    def __str__(self):
        return f"{self.name} ({self.model_number})"


# ==========================================
# MACHINE ↔ PART RELATIONSHIP
# ==========================================

class MachinePart(models.Model):
    """
    Inventory junction table between Machine and Part.

    Stores live quantity, placement, usage notes, and last user action tracking.
    """

    machine = models.ForeignKey(
        Machine,
        on_delete=models.CASCADE
    )

    part = models.ForeignKey(
        Part,
        on_delete=models.CASCADE
    )

    quantity_left = models.PositiveIntegerField(default=0)

    placement_location = models.CharField(
        max_length=200,
        blank=True
    )

    compatibility_notes = models.TextField(blank=True)

    # Tracks the last person who changed this inventory row (use/replace action).
    last_action_by_first_name = models.CharField(max_length=100, blank=True)
    last_action_by_last_name = models.CharField(max_length=100, blank=True)

    # Stores what the last operation was (for example: USED, REPLACED).
    last_action_type = models.CharField(max_length=30, blank=True)

    # Stores how many units were used in the latest USED action.
    last_used_quantity = models.PositiveIntegerField(null=True, blank=True)

    # Timestamp for the most recent inventory action on this machine-part row.
    last_action_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "inventory_machine_part"
        unique_together = ("machine", "part")

    def __str__(self):
        return f"{self.machine.name} - {self.part.name}"


# ==========================================
# MAINTENANCE RECORDS
# ==========================================

class MaintenanceRecord(models.Model):
    """Table for maintenance incidents and optional consumed/replaced parts."""

    machine = models.ForeignKey(
        Machine,
        on_delete=models.CASCADE,
        related_name="maintenance_records"
    )

    issue_description = models.TextField(blank=True)

    date_reported = models.DateTimeField(auto_now_add=True)
    date_fixed = models.DateTimeField(null=True, blank=True)

    time_to_fix = models.DurationField(null=True, blank=True)

    part_replaced = models.ForeignKey(
        Part,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    part_consumed = models.BooleanField(default=False)

    class Meta:
        db_table = "inventory_maintenance_record"
        ordering = ["-date_reported"]

    def __str__(self):
        return f"{self.machine.name} - {self.date_reported.date()}"


# ==========================================
# SUPPLY CHAIN
# ==========================================

class Vendor(models.Model):
    """Vendor/supplier master table (contact and website info)."""

    name = models.CharField(max_length=120, unique=True)
    phone = models.CharField(max_length=30, blank=True)
    website = models.URLField(blank=True)

    class Meta:
        db_table = "inventory_vendor"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Manufacturer(models.Model):
    """Manufacturer master table used by vendor-part mappings."""

    name = models.CharField(max_length=120, unique=True)
    phone = models.CharField(max_length=30, blank=True)

    class Meta:
        db_table = "inventory_manufacturer"
        ordering = ["name"]

    def __str__(self):
        return self.name


class VendorPart(models.Model):
    """Mapping table for which vendors supply which part models."""

    part = models.ForeignKey(Part, on_delete=models.CASCADE)
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE)

    manufacturer = models.ForeignKey(
        Manufacturer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    last_purchase_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "inventory_vendor_part"
        unique_together = ("part", "vendor")

    def __str__(self):
        return f"{self.part.model_number} - {self.vendor.name}"

# ==========================================
# Engineering Work Order Notification Screen
# ==========================================
class WorkOrderNotification(models.Model):
    """Table for work order notifications"""

    machine = models.ForeignKey(
        Machine,
        on_delete=models.CASCADE,
        related_name="work_order_notifications"
    )

    notification_message = models.TextField(blank=True)

    date_reported = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inventory_work_order_notification"
        ordering = ["-date_reported"]

    def __str__(self):
        return f"{self.machine.name} - {self.date_reported.date()}"


class WorkOrderRequest(models.Model):
    """Work order created from station QR scan and tracked through response lifecycle."""

    STATUS_NEW = "NEW"
    STATUS_COMING = "COMING"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES = [
        (STATUS_NEW, "New"),
        (STATUS_COMING, "Coming"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    PRIORITY_HIGH = 1
    PRIORITY_MEDIUM = 2
    PRIORITY_LOW = 3

    PRIORITY_CHOICES = [
        (PRIORITY_HIGH, "High"),
        (PRIORITY_MEDIUM, "Medium"),
        (PRIORITY_LOW, "Low"),
    ]

    station = models.ForeignKey(
        Station,
        on_delete=models.CASCADE,
        related_name="work_orders",
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="work_orders",
    )

    machine = models.ForeignKey(
        Machine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_orders",
    )

    message = models.TextField(blank=True)
    priority = models.PositiveSmallIntegerField(choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW)

    technician_first_name = models.CharField(max_length=100, blank=True)
    technician_last_name = models.CharField(max_length=100, blank=True)
    technician_email = models.EmailField(blank=True)

    completed_by_first_name = models.CharField(max_length=100, blank=True)
    completed_by_last_name = models.CharField(max_length=100, blank=True)
    completed_by_email = models.EmailField(blank=True)

    scanned_at = models.DateTimeField(auto_now_add=True)
    downtime_started_at = models.DateTimeField(null=True, blank=True)
    accessed_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "inventory_work_order_request"
        ordering = ["scanned_at"]

    def __str__(self):
        machine_name = self.machine.name if self.machine else "No Machine"
        return f"{self.department.name} | {self.station.name} | {machine_name} | {self.get_status_display()}"


# ==========================================
# USER REQUIREMENTS
# ==========================================

class UserRequirement(models.Model):
    """Table for user-submitted requirements/requests by department."""

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE
    )

    requirement_description = models.TextField(blank=True)
    name_of_requester = models.CharField(max_length=100, blank=True)
    date_reported = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inventory_user_requirement"
        ordering = ["-date_reported"]

    def __str__(self):
        return f"{self.department.name} Requirement"


class UserEmail(models.Model):
    """Table of unique email addresses used for reminder notifications."""

    email = models.EmailField(unique=True)

    class Meta:
        db_table = "inventory_user_email"

    def __str__(self):
        return self.email


class InventoryReminder(models.Model):
    """Department-scoped inventory threshold reminder configured by authorized users."""

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="inventory_reminders",
    )

    machine_part = models.ForeignKey(
        MachinePart,
        on_delete=models.CASCADE,
        related_name="inventory_reminders",
    )

    alert_quantity = models.PositiveIntegerField(default=1)
    notify_email = models.EmailField(max_length=254)

    created_by_first_name = models.CharField(max_length=100, blank=True)
    created_by_last_name = models.CharField(max_length=100, blank=True)
    created_by_email = models.EmailField(blank=True)

    is_active = models.BooleanField(default=True)
    alert_sent = models.BooleanField(default=False)
    last_alert_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inventory_inventory_reminder"
        ordering = ["department__name", "machine_part__machine__name", "machine_part__part__model_number"]
        unique_together = ("department", "machine_part", "notify_email")

    def __str__(self):
        return f"{self.department.name} | {self.machine_part.machine.name} | {self.machine_part.part.model_number} <= {self.alert_quantity}"

