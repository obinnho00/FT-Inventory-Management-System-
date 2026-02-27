from django.db import models
from django.utils import timezone


# ==========================================
# LOCATION STRUCTURE
# ==========================================

class Building(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = "inventory_building"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Department(models.Model):
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


# ==========================================
# MACHINE STRUCTURE
# ==========================================

class Machine(models.Model):

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

    class Meta:
        db_table = "inventory_machine_part"
        unique_together = ("machine", "part")

    def __str__(self):
        return f"{self.machine.name} - {self.part.name}"


# ==========================================
# MAINTENANCE RECORDS
# ==========================================

class MaintenanceRecord(models.Model):

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
    name = models.CharField(max_length=120, unique=True)
    phone = models.CharField(max_length=30, blank=True)
    website = models.URLField(blank=True)

    class Meta:
        db_table = "inventory_vendor"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Manufacturer(models.Model):
    name = models.CharField(max_length=120, unique=True)
    phone = models.CharField(max_length=30, blank=True)

    class Meta:
        db_table = "inventory_manufacturer"
        ordering = ["name"]

    def __str__(self):
        return self.name


class VendorPart(models.Model):

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
# USER REQUIREMENTS
# ==========================================

class UserRequirement(models.Model):
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
    email = models.EmailField(unique=True)

    class Meta:
        db_table = "inventory_user_email"

    def __str__(self):
        return self.email